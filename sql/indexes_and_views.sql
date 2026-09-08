-- ===========================================================================
--  Indexes and reusable analytical views
--  Applied after the bulk load so the load itself is not slowed by index
--  maintenance.
-- ===========================================================================

CREATE INDEX idx_txn_date        ON fact_transactions (transaction_date);
CREATE INDEX idx_txn_month       ON fact_transactions (year_month);
CREATE INDEX idx_txn_customer    ON fact_transactions (customer_id);
CREATE INDEX idx_txn_product     ON fact_transactions (product_id);
CREATE INDEX idx_txn_region      ON fact_transactions (region);
CREATE INDEX idx_txn_category    ON fact_transactions (product_category);
CREATE INDEX idx_txn_segment     ON fact_transactions (customer_segment);
CREATE INDEX idx_ar_customer     ON fact_accounts_receivable (customer_id);
CREATE INDEX idx_ar_invoice_date ON fact_accounts_receivable (invoice_date);

-- ---------------------------------------------------------------------------
-- Monthly revenue spine: the base every time-series query builds on.
-- ---------------------------------------------------------------------------
CREATE VIEW v_monthly_revenue AS
SELECT
    month_start,
    year_month,
    year,
    quarter,
    COUNT(*)                        AS transactions,
    COUNT(DISTINCT customer_id)     AS active_customers,
    SUM(quantity)                   AS units_sold,
    SUM(gross_revenue)              AS gross_revenue,
    SUM(discount_amount)            AS discount_amount,
    SUM(revenue)                    AS revenue,
    SUM(cost)                       AS cost,
    SUM(profit)                     AS profit,
    SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0)          AS profit_margin_pct,
    SUM(discount_amount) * 100.0 / NULLIF(SUM(gross_revenue), 0) AS discount_rate_pct,
    SUM(revenue) * 1.0 / NULLIF(COUNT(*), 0)               AS avg_transaction_value
FROM fact_transactions
GROUP BY month_start, year_month, year, quarter;

-- ---------------------------------------------------------------------------
-- Full monthly P&L: gross profit from the ledger, then the cost stack from
-- the three operating-cost fact tables.  Salaries live in fact_employee_costs
-- AND in fact_operating_expenses' "Salaries & Wages" line, so opex here
-- deliberately excludes that category to avoid double counting.
-- ---------------------------------------------------------------------------
CREATE VIEW v_monthly_pnl AS
WITH sales AS (
    SELECT month_start, SUM(revenue) AS revenue, SUM(cost) AS cogs,
           SUM(profit) AS gross_profit
    FROM fact_transactions
    GROUP BY month_start
),
opex AS (
    SELECT month AS month_start, SUM(amount) AS operating_expenses
    FROM fact_operating_expenses
    WHERE expense_category <> 'Salaries & Wages'
    GROUP BY month
),
payroll AS (
    SELECT month AS month_start, SUM(total_cost) AS payroll_cost,
           SUM(headcount) AS headcount
    FROM fact_employee_costs
    GROUP BY month
),
mkt AS (
    SELECT month AS month_start, SUM(spend) AS marketing_spend
    FROM fact_marketing_spend
    GROUP BY month
)
SELECT
    s.month_start,
    s.revenue,
    s.cogs,
    s.gross_profit,
    s.gross_profit * 100.0 / NULLIF(s.revenue, 0) AS gross_margin_pct,
    COALESCE(o.operating_expenses, 0)             AS operating_expenses,
    COALESCE(p.payroll_cost, 0)                   AS payroll_cost,
    COALESCE(m.marketing_spend, 0)                AS marketing_spend,
    COALESCE(p.headcount, 0)                      AS headcount,
    s.gross_profit
        - COALESCE(o.operating_expenses, 0)
        - COALESCE(p.payroll_cost, 0)
        - COALESCE(m.marketing_spend, 0)          AS operating_profit,
    (s.gross_profit
        - COALESCE(o.operating_expenses, 0)
        - COALESCE(p.payroll_cost, 0)
        - COALESCE(m.marketing_spend, 0)) * 100.0 / NULLIF(s.revenue, 0)
                                                  AS operating_margin_pct
FROM sales s
LEFT JOIN opex    o ON o.month_start = s.month_start
LEFT JOIN payroll p ON p.month_start = s.month_start
LEFT JOIN mkt     m ON m.month_start = s.month_start;

-- ---------------------------------------------------------------------------
-- Customer and product roll-ups used by several downstream queries.
-- ---------------------------------------------------------------------------
CREATE VIEW v_customer_summary AS
SELECT
    f.customer_id,
    c.customer_segment,
    c.region,
    COUNT(*)                    AS transactions,
    MIN(f.transaction_date)     AS first_purchase,
    MAX(f.transaction_date)     AS last_purchase,
    COUNT(DISTINCT f.year_month) AS active_months,
    SUM(f.revenue)              AS revenue,
    SUM(f.cost)                 AS cost,
    SUM(f.profit)               AS profit,
    SUM(f.profit) * 100.0 / NULLIF(SUM(f.revenue), 0) AS profit_margin_pct,
    SUM(f.revenue) * 1.0 / NULLIF(COUNT(*), 0)        AS avg_order_value,
    SUM(f.discount_amount) * 100.0 / NULLIF(SUM(f.gross_revenue), 0) AS discount_rate_pct
FROM fact_transactions f
JOIN dim_customer c ON c.customer_id = f.customer_id
WHERE f.is_customer_attributed = 1
GROUP BY f.customer_id, c.customer_segment, c.region;

CREATE VIEW v_product_summary AS
SELECT
    f.product_id,
    p.product_name,
    f.product_category,
    COUNT(*)                    AS transactions,
    SUM(f.quantity)             AS units_sold,
    SUM(f.gross_revenue)        AS gross_revenue,
    SUM(f.revenue)              AS revenue,
    SUM(f.cost)                 AS cost,
    SUM(f.profit)               AS profit,
    SUM(f.profit) * 100.0 / NULLIF(SUM(f.revenue), 0)  AS profit_margin_pct,
    SUM(f.discount_amount) * 100.0 / NULLIF(SUM(f.gross_revenue), 0) AS discount_rate_pct,
    SUM(f.revenue) * 1.0 / NULLIF(SUM(f.quantity), 0)  AS avg_realised_price
FROM fact_transactions f
JOIN dim_product p ON p.product_id = f.product_id
GROUP BY f.product_id, p.product_name, f.product_category;
