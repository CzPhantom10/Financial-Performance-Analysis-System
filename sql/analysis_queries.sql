-- ===========================================================================
--  Analytical query library
-- ---------------------------------------------------------------------------
--  Each query is delimited by a `-- name:` marker and loaded by
--  src/sql_analysis.py, which runs them and writes the results to
--  reports/sql_results/.  The same names are importable from Python:
--
--      from src.sql_analysis import run_named
--      run_named("top_customers")
--
--  Everything here is standard SQL (CTEs + window functions) and runs
--  unchanged on SQLite 3.25+, PostgreSQL 11+ and MySQL 8+.
-- ===========================================================================


-- name: monthly_revenue_trend
-- description: Monthly revenue, profit and margin with month-on-month growth,
--              a 3-month moving average and a cumulative running total.
WITH m AS (
    SELECT month_start, year_month, revenue, profit, cost, transactions,
           active_customers, avg_transaction_value, profit_margin_pct,
           discount_rate_pct
    FROM v_monthly_revenue
)
SELECT
    month_start,
    year_month,
    ROUND(revenue, 2)                                   AS revenue,
    ROUND(profit, 2)                                    AS profit,
    ROUND(profit_margin_pct, 2)                         AS profit_margin_pct,
    transactions,
    active_customers,
    ROUND(avg_transaction_value, 2)                     AS avg_transaction_value,
    ROUND(discount_rate_pct, 2)                         AS discount_rate_pct,
    ROUND(LAG(revenue) OVER w, 2)                       AS prev_month_revenue,
    ROUND((revenue - LAG(revenue) OVER w) * 100.0
          / NULLIF(LAG(revenue) OVER w, 0), 2)          AS mom_growth_pct,
    ROUND(AVG(revenue) OVER (ORDER BY month_start
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS revenue_3mo_ma,
    ROUND(AVG(profit_margin_pct) OVER (ORDER BY month_start
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS margin_3mo_ma,
    ROUND(SUM(revenue) OVER (ORDER BY month_start
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2) AS cumulative_revenue
FROM m
WINDOW w AS (ORDER BY month_start)
ORDER BY month_start;


-- name: yoy_growth_by_month
-- description: Year-over-year revenue and profit growth, comparing each month
--              with the same month twelve periods earlier (LAG 12).
WITH m AS (
    SELECT month_start, year_month, revenue, profit, profit_margin_pct
    FROM v_monthly_revenue
)
SELECT
    month_start,
    year_month,
    ROUND(revenue, 2)                          AS revenue,
    ROUND(LAG(revenue, 12) OVER w, 2)          AS revenue_ly,
    ROUND((revenue - LAG(revenue, 12) OVER w) * 100.0
          / NULLIF(LAG(revenue, 12) OVER w, 0), 2) AS revenue_yoy_pct,
    ROUND(profit, 2)                           AS profit,
    ROUND(LAG(profit, 12) OVER w, 2)           AS profit_ly,
    ROUND((profit - LAG(profit, 12) OVER w) * 100.0
          / NULLIF(LAG(profit, 12) OVER w, 0), 2)  AS profit_yoy_pct,
    ROUND(profit_margin_pct, 2)                AS profit_margin_pct,
    ROUND(profit_margin_pct - LAG(profit_margin_pct, 12) OVER w, 2)
                                               AS margin_change_pp
FROM m
WINDOW w AS (ORDER BY month_start)
ORDER BY month_start;


-- name: annual_summary
-- description: Headline P&L by financial year with growth rates.
WITH y AS (
    SELECT year,
           SUM(revenue)        AS revenue,
           SUM(cost)           AS cost,
           SUM(profit)         AS profit,
           SUM(discount_amount) AS discount_amount,
           COUNT(*)            AS transactions,
           COUNT(DISTINCT customer_id) AS customers
    FROM fact_transactions
    GROUP BY year
)
SELECT
    year,
    ROUND(revenue, 2)   AS revenue,
    ROUND(cost, 2)      AS cost,
    ROUND(profit, 2)    AS profit,
    ROUND(profit * 100.0 / NULLIF(revenue, 0), 2)      AS gross_margin_pct,
    ROUND(cost * 100.0 / NULLIF(revenue, 0), 2)        AS cost_to_revenue_pct,
    ROUND(discount_amount * 100.0
          / NULLIF(revenue + discount_amount, 0), 2)   AS discount_rate_pct,
    transactions,
    customers,
    ROUND(revenue * 1.0 / NULLIF(transactions, 0), 2)  AS avg_order_value,
    ROUND(revenue * 1.0 / NULLIF(customers, 0), 2)     AS revenue_per_customer,
    ROUND((revenue - LAG(revenue) OVER w) * 100.0
          / NULLIF(LAG(revenue) OVER w, 0), 2)         AS revenue_growth_pct,
    ROUND((profit - LAG(profit) OVER w) * 100.0
          / NULLIF(LAG(profit) OVER w, 0), 2)          AS profit_growth_pct,
    ROUND((cost - LAG(cost) OVER w) * 100.0
          / NULLIF(LAG(cost) OVER w, 0), 2)            AS cost_growth_pct
FROM y
WINDOW w AS (ORDER BY year)
ORDER BY year;


-- name: quarterly_performance
-- description: Quarterly revenue and margin with quarter-on-quarter movement.
WITH q AS (
    SELECT year_quarter, year, quarter,
           SUM(revenue) AS revenue, SUM(profit) AS profit, COUNT(*) AS transactions
    FROM fact_transactions
    GROUP BY year_quarter, year, quarter
)
SELECT
    year_quarter,
    ROUND(revenue, 2) AS revenue,
    ROUND(profit, 2)  AS profit,
    ROUND(profit * 100.0 / NULLIF(revenue, 0), 2) AS profit_margin_pct,
    transactions,
    ROUND((revenue - LAG(revenue) OVER w) * 100.0
          / NULLIF(LAG(revenue) OVER w, 0), 2)    AS qoq_growth_pct,
    ROUND((revenue - LAG(revenue, 4) OVER w) * 100.0
          / NULLIF(LAG(revenue, 4) OVER w, 0), 2) AS yoy_growth_pct
FROM q
WINDOW w AS (ORDER BY year, quarter)
ORDER BY year, quarter;


-- name: revenue_by_region
-- description: Regional contribution to revenue and profit, ranked, with each
--              region's share of the total computed by a windowed aggregate.
SELECT
    region,
    COUNT(*)                                   AS transactions,
    COUNT(DISTINCT customer_id)                AS customers,
    ROUND(SUM(revenue), 2)                     AS revenue,
    ROUND(SUM(cost), 2)                        AS cost,
    ROUND(SUM(profit), 2)                      AS profit,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2) AS profit_margin_pct,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(SUM(profit)  * 100.0 / SUM(SUM(profit))  OVER (), 2) AS pct_of_profit,
    ROUND(SUM(revenue) * 1.0 / NULLIF(COUNT(*), 0), 2)         AS avg_order_value,
    ROUND(SUM(discount_amount) * 100.0
          / NULLIF(SUM(gross_revenue), 0), 2)  AS discount_rate_pct,
    RANK() OVER (ORDER BY SUM(revenue) DESC)   AS revenue_rank,
    RANK() OVER (ORDER BY SUM(profit) DESC)    AS profit_rank
FROM fact_transactions
GROUP BY region
ORDER BY revenue DESC;


-- name: region_monthly_trend
-- description: Region x month revenue with each region's own MoM growth -
--              the input to the regional trend charts.
WITH rm AS (
    SELECT region, month_start, year_month,
           SUM(revenue) AS revenue, SUM(profit) AS profit
    FROM fact_transactions
    GROUP BY region, month_start, year_month
)
SELECT
    region,
    month_start,
    year_month,
    ROUND(revenue, 2) AS revenue,
    ROUND(profit, 2)  AS profit,
    ROUND(profit * 100.0 / NULLIF(revenue, 0), 2) AS profit_margin_pct,
    ROUND((revenue - LAG(revenue) OVER w) * 100.0
          / NULLIF(LAG(revenue) OVER w, 0), 2)    AS mom_growth_pct,
    ROUND(AVG(revenue) OVER (PARTITION BY region ORDER BY month_start
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS revenue_3mo_ma
FROM rm
WINDOW w AS (PARTITION BY region ORDER BY month_start)
ORDER BY region, month_start;


-- name: margin_by_category
-- description: Profit margin, discount intensity and contribution by product
--              category - which lines actually carry the business.
SELECT
    product_category,
    COUNT(*)                                   AS transactions,
    SUM(quantity)                              AS units_sold,
    ROUND(SUM(gross_revenue), 2)               AS gross_revenue,
    ROUND(SUM(discount_amount), 2)             AS discount_given,
    ROUND(SUM(revenue), 2)                     AS revenue,
    ROUND(SUM(cost), 2)                        AS cost,
    ROUND(SUM(profit), 2)                      AS profit,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2)  AS profit_margin_pct,
    ROUND(SUM(discount_amount) * 100.0
          / NULLIF(SUM(gross_revenue), 0), 2)  AS discount_rate_pct,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(SUM(profit)  * 100.0 / SUM(SUM(profit))  OVER (), 2) AS pct_of_profit,
    RANK() OVER (ORDER BY SUM(profit) * 1.0 / NULLIF(SUM(revenue), 0) DESC)
                                               AS margin_rank
FROM fact_transactions
GROUP BY product_category
ORDER BY profit DESC;


-- name: profit_by_product
-- description: Every product ranked by profit, with its rank inside its own
--              category and its share of category profit.
SELECT
    product_id,
    product_name,
    product_category,
    transactions,
    units_sold,
    ROUND(revenue, 2)            AS revenue,
    ROUND(cost, 2)               AS cost,
    ROUND(profit, 2)             AS profit,
    ROUND(profit_margin_pct, 2)  AS profit_margin_pct,
    ROUND(discount_rate_pct, 2)  AS discount_rate_pct,
    ROUND(avg_realised_price, 2) AS avg_realised_price,
    RANK() OVER (ORDER BY profit DESC)                       AS profit_rank_overall,
    RANK() OVER (PARTITION BY product_category
                 ORDER BY profit DESC)                       AS profit_rank_in_category,
    ROUND(profit * 100.0
          / NULLIF(SUM(profit) OVER (PARTITION BY product_category), 0), 2)
                                                             AS pct_of_category_profit
FROM v_product_summary
ORDER BY profit DESC;


-- name: high_revenue_low_margin_products
-- description: The management investigation list - products in the top half of
--              the revenue distribution whose margin sits in the bottom
--              quartile.  High volume plus thin margin is where a small pricing
--              correction moves the most money.
WITH ranked AS (
    SELECT
        product_id, product_name, product_category, units_sold,
        revenue, profit, profit_margin_pct, discount_rate_pct,
        PERCENT_RANK() OVER (ORDER BY revenue)           AS revenue_pctile,
        PERCENT_RANK() OVER (ORDER BY profit_margin_pct) AS margin_pctile
    FROM v_product_summary
)
SELECT
    product_id,
    product_name,
    product_category,
    units_sold,
    ROUND(revenue, 2)                 AS revenue,
    ROUND(profit, 2)                  AS profit,
    ROUND(profit_margin_pct, 2)       AS profit_margin_pct,
    ROUND(discount_rate_pct, 2)       AS discount_rate_pct,
    ROUND(revenue_pctile * 100, 1)    AS revenue_percentile,
    ROUND(margin_pctile * 100, 1)     AS margin_percentile,
    -- What one point of extra margin would be worth on current volume
    ROUND(revenue * 0.01, 2)          AS profit_uplift_per_margin_point
FROM ranked
WHERE revenue_pctile >= 0.50
  AND margin_pctile  <= 0.25
ORDER BY revenue DESC;


-- name: discount_heavy_products
-- description: Products giving away the most discount, and what that discount
--              is costing in absolute profit terms.
SELECT
    product_id,
    product_name,
    product_category,
    units_sold,
    ROUND(gross_revenue, 2)      AS gross_revenue,
    ROUND(gross_revenue - revenue, 2) AS discount_given,
    ROUND(revenue, 2)            AS revenue,
    ROUND(profit, 2)             AS profit,
    ROUND(discount_rate_pct, 2)  AS discount_rate_pct,
    ROUND(profit_margin_pct, 2)  AS profit_margin_pct,
    RANK() OVER (ORDER BY discount_rate_pct DESC) AS discount_rank
FROM v_product_summary
WHERE units_sold > 100
ORDER BY discount_rate_pct DESC
LIMIT 25;


-- name: top_customers
-- description: Top 30 customers by revenue with a running cumulative share -
--              the direct answer to "what fraction of revenue sits with our
--              largest accounts?"
WITH ranked AS (
    SELECT
        customer_id, customer_segment, region, transactions, active_months,
        revenue, profit, profit_margin_pct, avg_order_value, discount_rate_pct,
        ROW_NUMBER() OVER (ORDER BY revenue DESC) AS revenue_rank,
        SUM(revenue) OVER (ORDER BY revenue DESC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                                                  AS cumulative_revenue,
        SUM(revenue) OVER ()                      AS total_revenue
    FROM v_customer_summary
)
SELECT
    revenue_rank,
    customer_id,
    customer_segment,
    region,
    transactions,
    active_months,
    ROUND(revenue, 2)            AS revenue,
    ROUND(profit, 2)             AS profit,
    ROUND(profit_margin_pct, 2)  AS profit_margin_pct,
    ROUND(avg_order_value, 2)    AS avg_order_value,
    ROUND(discount_rate_pct, 2)  AS discount_rate_pct,
    ROUND(revenue * 100.0 / total_revenue, 3)            AS pct_of_revenue,
    ROUND(cumulative_revenue * 100.0 / total_revenue, 2) AS cumulative_pct_of_revenue
FROM ranked
WHERE revenue_rank <= 30
ORDER BY revenue_rank;


-- name: customer_concentration
-- description: Pareto test.  Customers are split into revenue deciles and each
--              decile's share reported, so "80/20" can be checked rather than
--              assumed.
WITH deciled AS (
    SELECT customer_id, revenue, profit,
           NTILE(10) OVER (ORDER BY revenue DESC) AS revenue_decile
    FROM v_customer_summary
)
SELECT
    revenue_decile,
    COUNT(*)                  AS customers,
    ROUND(SUM(revenue), 2)    AS revenue,
    ROUND(SUM(profit), 2)     AS profit,
    ROUND(AVG(revenue), 2)    AS avg_revenue_per_customer,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(SUM(SUM(revenue)) OVER (ORDER BY revenue_decile
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0
          / SUM(SUM(revenue)) OVER (), 2)                      AS cumulative_pct_of_revenue
FROM deciled
GROUP BY revenue_decile
ORDER BY revenue_decile;


-- name: customer_segment_performance
-- description: Revenue, margin, order value and discount intensity by segment.
SELECT
    customer_segment,
    COUNT(DISTINCT customer_id)  AS customers,
    COUNT(*)                     AS transactions,
    ROUND(SUM(revenue), 2)       AS revenue,
    ROUND(SUM(profit), 2)        AS profit,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2)  AS profit_margin_pct,
    ROUND(SUM(revenue) * 1.0 / NULLIF(COUNT(*), 0), 2)       AS avg_order_value,
    ROUND(SUM(revenue) * 1.0
          / NULLIF(COUNT(DISTINCT customer_id), 0), 2)       AS revenue_per_customer,
    ROUND(SUM(discount_amount) * 100.0
          / NULLIF(SUM(gross_revenue), 0), 2)                AS discount_rate_pct,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue
FROM fact_transactions
WHERE is_customer_attributed = 1
GROUP BY customer_segment
ORDER BY revenue DESC;


-- name: repeat_purchase_behaviour
-- description: How many customers come back, and what repeat buyers are worth
--              relative to one-time buyers.
WITH per_customer AS (
    SELECT customer_id, customer_segment,
           COUNT(*) AS orders, COUNT(DISTINCT year_month) AS active_months,
           SUM(revenue) AS revenue
    FROM fact_transactions
    WHERE is_customer_attributed = 1
    GROUP BY customer_id, customer_segment
),
bucketed AS (
    SELECT *,
           CASE WHEN orders = 1 THEN '1 order'
                WHEN orders BETWEEN 2 AND 5   THEN '2-5 orders'
                WHEN orders BETWEEN 6 AND 20  THEN '6-20 orders'
                WHEN orders BETWEEN 21 AND 50 THEN '21-50 orders'
                ELSE '50+ orders' END AS order_band
    FROM per_customer
)
SELECT
    order_band,
    COUNT(*)                   AS customers,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)         AS pct_of_customers,
    ROUND(SUM(revenue), 2)     AS revenue,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue,
    ROUND(AVG(revenue), 2)     AS avg_lifetime_revenue,
    ROUND(AVG(orders), 1)      AS avg_orders,
    ROUND(AVG(active_months), 1) AS avg_active_months
FROM bucketed
GROUP BY order_band
ORDER BY avg_orders;


-- name: customer_cohort_retention
-- description: Monthly acquisition cohorts tracked forward.  The month offset
--              is computed with integer arithmetic on the year_month key so
--              the query needs no engine-specific date functions.
WITH first_purchase AS (
    SELECT customer_id, MIN(year_month) AS cohort_month
    FROM fact_transactions
    WHERE is_customer_attributed = 1
    GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT f.customer_id, fp.cohort_month, f.year_month
    FROM fact_transactions f
    JOIN first_purchase fp ON fp.customer_id = f.customer_id
    WHERE f.is_customer_attributed = 1
),
offsets AS (
    SELECT
        cohort_month,
        customer_id,
        (CAST(SUBSTR(year_month, 1, 4) AS INTEGER) * 12
             + CAST(SUBSTR(year_month, 6, 2) AS INTEGER))
        - (CAST(SUBSTR(cohort_month, 1, 4) AS INTEGER) * 12
             + CAST(SUBSTR(cohort_month, 6, 2) AS INTEGER)) AS month_offset
    FROM activity
),
cohort_size AS (
    SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_customers
    FROM offsets WHERE month_offset = 0
    GROUP BY cohort_month
)
SELECT
    o.cohort_month,
    cs.cohort_customers,
    o.month_offset,
    COUNT(DISTINCT o.customer_id) AS active_customers,
    ROUND(COUNT(DISTINCT o.customer_id) * 100.0
          / NULLIF(cs.cohort_customers, 0), 2) AS retention_pct
FROM offsets o
JOIN cohort_size cs ON cs.cohort_month = o.cohort_month
GROUP BY o.cohort_month, cs.cohort_customers, o.month_offset
ORDER BY o.cohort_month, o.month_offset;


-- name: avg_transaction_value
-- description: Average order value by segment and region, with the segment
--              average alongside so the regional deviation is visible.
SELECT
    customer_segment,
    region,
    COUNT(*)                 AS transactions,
    ROUND(AVG(revenue), 2)   AS avg_transaction_value,
    ROUND(MIN(revenue), 2)   AS min_transaction_value,
    ROUND(MAX(revenue), 2)   AS max_transaction_value,
    ROUND(SUM(revenue), 2)   AS revenue,
    ROUND(AVG(AVG(revenue)) OVER (PARTITION BY customer_segment), 2)
                             AS segment_avg_transaction_value,
    ROUND(AVG(revenue)
          - AVG(AVG(revenue)) OVER (PARTITION BY customer_segment), 2)
                             AS deviation_from_segment_avg
FROM fact_transactions
WHERE is_customer_attributed = 1
GROUP BY customer_segment, region
ORDER BY customer_segment, avg_transaction_value DESC;


-- name: discount_impact
-- description: Transactions bucketed by discount depth against realised margin.
--              This is the descriptive half of the discount question; the
--              inferential half lives in src/stats_analysis.py.
WITH banded AS (
    SELECT
        CASE WHEN discount = 0            THEN 'A. 0%'
             WHEN discount <= 0.05        THEN 'B. 0-5%'
             WHEN discount <= 0.10        THEN 'C. 5-10%'
             WHEN discount <= 0.15        THEN 'D. 10-15%'
             WHEN discount <= 0.25        THEN 'E. 15-25%'
             WHEN discount <= 0.40        THEN 'F. 25-40%'
             ELSE                              'G. 40%+' END AS discount_band,
        revenue, gross_revenue, discount_amount, profit, quantity, is_loss_making
    FROM fact_transactions
)
SELECT
    discount_band,
    COUNT(*)                        AS transactions,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)  AS pct_of_transactions,
    ROUND(AVG(quantity), 1)         AS avg_quantity,
    ROUND(SUM(gross_revenue), 2)    AS gross_revenue,
    ROUND(SUM(discount_amount), 2)  AS discount_given,
    ROUND(SUM(revenue), 2)          AS revenue,
    ROUND(SUM(profit), 2)           AS profit,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2) AS profit_margin_pct,
    ROUND(AVG(revenue), 2)          AS avg_order_value,
    SUM(is_loss_making)             AS loss_making_transactions,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue
FROM banded
GROUP BY discount_band
ORDER BY discount_band;


-- name: cost_trend
-- description: Are costs growing faster than revenue?  Monthly COGS against
--              revenue with both YoY growth rates and the cost-to-revenue
--              ratio trend.
WITH m AS (
    SELECT month_start, year_month,
           SUM(revenue) AS revenue, SUM(cost) AS cost, SUM(profit) AS profit,
           SUM(quantity) AS units
    FROM fact_transactions
    GROUP BY month_start, year_month
)
SELECT
    month_start,
    year_month,
    ROUND(revenue, 2)  AS revenue,
    ROUND(cost, 2)     AS cost,
    ROUND(cost * 100.0 / NULLIF(revenue, 0), 2)   AS cost_to_revenue_pct,
    ROUND(cost * 1.0 / NULLIF(units, 0), 2)       AS cost_per_unit,
    ROUND((revenue - LAG(revenue, 12) OVER w) * 100.0
          / NULLIF(LAG(revenue, 12) OVER w, 0), 2) AS revenue_yoy_pct,
    ROUND((cost - LAG(cost, 12) OVER w) * 100.0
          / NULLIF(LAG(cost, 12) OVER w, 0), 2)    AS cost_yoy_pct,
    ROUND(((cost - LAG(cost, 12) OVER w) * 100.0 / NULLIF(LAG(cost, 12) OVER w, 0))
          - ((revenue - LAG(revenue, 12) OVER w) * 100.0
             / NULLIF(LAG(revenue, 12) OVER w, 0)), 2) AS cost_minus_revenue_growth_pp,
    ROUND(AVG(cost * 100.0 / NULLIF(revenue, 0)) OVER (ORDER BY month_start
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS cost_ratio_3mo_ma
FROM m
WINDOW w AS (ORDER BY month_start)
ORDER BY month_start;


-- name: operating_cost_structure
-- description: The full cost stack month by month - COGS, opex, payroll and
--              marketing - and what each consumes as a share of revenue.
SELECT
    month_start,
    ROUND(revenue, 2)             AS revenue,
    ROUND(cogs, 2)                AS cogs,
    ROUND(gross_profit, 2)        AS gross_profit,
    ROUND(gross_margin_pct, 2)    AS gross_margin_pct,
    ROUND(operating_expenses, 2)  AS operating_expenses,
    ROUND(payroll_cost, 2)        AS payroll_cost,
    ROUND(marketing_spend, 2)     AS marketing_spend,
    headcount,
    ROUND(operating_profit, 2)    AS operating_profit,
    ROUND(operating_margin_pct, 2) AS operating_margin_pct,
    ROUND(payroll_cost * 100.0 / NULLIF(revenue, 0), 2)      AS payroll_pct_of_revenue,
    ROUND(marketing_spend * 100.0 / NULLIF(revenue, 0), 2)   AS marketing_pct_of_revenue,
    ROUND(operating_expenses * 100.0 / NULLIF(revenue, 0), 2) AS opex_pct_of_revenue,
    ROUND(revenue * 1.0 / NULLIF(headcount, 0), 2)           AS revenue_per_head
FROM v_monthly_pnl
ORDER BY month_start;


-- name: opex_by_category_trend
-- description: Operating expense lines over time, each with its own YoY growth,
--              so a step change in one line is not hidden by the total.
WITH e AS (
    SELECT month, expense_category, SUM(amount) AS amount
    FROM fact_operating_expenses
    GROUP BY month, expense_category
)
SELECT
    month,
    expense_category,
    ROUND(amount, 2) AS amount,
    ROUND(LAG(amount, 12) OVER w, 2) AS amount_ly,
    ROUND((amount - LAG(amount, 12) OVER w) * 100.0
          / NULLIF(LAG(amount, 12) OVER w, 0), 2) AS yoy_growth_pct,
    ROUND(amount * 100.0
          / SUM(amount) OVER (PARTITION BY month), 2) AS pct_of_month_opex
FROM e
WINDOW w AS (PARTITION BY expense_category ORDER BY month)
ORDER BY expense_category, month;


-- name: marketing_efficiency
-- description: Marketing spend against the revenue booked in the same month
--              and the next month, by region.  Descriptive only - this shows
--              association, and the report says so.
WITH spend AS (
    SELECT month, region, SUM(spend) AS marketing_spend
    FROM fact_marketing_spend GROUP BY month, region
),
rev AS (
    SELECT month_start AS month, region, SUM(revenue) AS revenue
    FROM fact_transactions GROUP BY month_start, region
)
SELECT
    s.month,
    s.region,
    ROUND(s.marketing_spend, 2) AS marketing_spend,
    ROUND(r.revenue, 2)         AS revenue,
    ROUND(LEAD(r.revenue) OVER w, 2) AS next_month_revenue,
    ROUND(r.revenue / NULLIF(s.marketing_spend, 0), 2)  AS revenue_per_marketing_dollar,
    ROUND(s.marketing_spend * 100.0 / NULLIF(r.revenue, 0), 2) AS marketing_pct_of_revenue,
    ROUND((s.marketing_spend - LAG(s.marketing_spend) OVER w) * 100.0
          / NULLIF(LAG(s.marketing_spend) OVER w, 0), 2) AS spend_mom_pct,
    ROUND((r.revenue - LAG(r.revenue) OVER w) * 100.0
          / NULLIF(LAG(r.revenue) OVER w, 0), 2)         AS revenue_mom_pct
FROM spend s
JOIN rev r ON r.month = s.month AND r.region = s.region
WINDOW w AS (PARTITION BY s.region ORDER BY s.month)
ORDER BY s.region, s.month;


-- name: budget_variance
-- description: Actual against target by month and region, in absolute and
--              percentage terms, with a plain-language attainment label.
WITH actual AS (
    SELECT month_start AS month, region,
           SUM(revenue) AS revenue, SUM(profit) AS profit
    FROM fact_transactions
    GROUP BY month_start, region
)
SELECT
    b.month,
    b.region,
    ROUND(a.revenue, 2)          AS actual_revenue,
    ROUND(b.revenue_target, 2)   AS target_revenue,
    ROUND(a.revenue - b.revenue_target, 2) AS revenue_variance,
    ROUND((a.revenue - b.revenue_target) * 100.0
          / NULLIF(b.revenue_target, 0), 2) AS revenue_variance_pct,
    ROUND(a.profit, 2)           AS actual_profit,
    ROUND(b.profit_target, 2)    AS target_profit,
    ROUND((a.profit - b.profit_target) * 100.0
          / NULLIF(b.profit_target, 0), 2)  AS profit_variance_pct,
    CASE WHEN a.revenue >= b.revenue_target * 1.05 THEN 'Beat'
         WHEN a.revenue >= b.revenue_target        THEN 'Met'
         WHEN a.revenue >= b.revenue_target * 0.90 THEN 'Near miss'
         ELSE 'Missed' END       AS attainment
FROM fact_budget b
JOIN actual a ON a.month = b.month AND a.region = b.region
ORDER BY b.month, b.region;


-- name: largest_monthly_declines
-- description: The ten sharpest month-on-month revenue falls - the direct
--              answer to "which month had the largest revenue decline?"
WITH m AS (
    SELECT month_start, year_month, SUM(revenue) AS revenue, SUM(profit) AS profit
    FROM fact_transactions
    GROUP BY month_start, year_month
),
delta AS (
    SELECT
        month_start, year_month, revenue, profit,
        LAG(revenue) OVER (ORDER BY month_start) AS prev_revenue,
        revenue - LAG(revenue) OVER (ORDER BY month_start) AS revenue_change
    FROM m
)
SELECT
    year_month,
    ROUND(prev_revenue, 2)   AS previous_month_revenue,
    ROUND(revenue, 2)        AS revenue,
    ROUND(revenue_change, 2) AS revenue_change,
    ROUND(revenue_change * 100.0 / NULLIF(prev_revenue, 0), 2) AS change_pct
FROM delta
WHERE revenue_change IS NOT NULL
ORDER BY revenue_change ASC
LIMIT 10;


-- name: loss_making_transactions
-- description: Where the business sold below cost, grouped by category and
--              month, so a pricing fault shows up as a cluster rather than
--              a scatter of one-offs.
SELECT
    year_month,
    product_category,
    COUNT(*)                    AS loss_making_transactions,
    ROUND(SUM(revenue), 2)      AS revenue_at_a_loss,
    ROUND(SUM(profit), 2)       AS profit_impact,
    ROUND(AVG(profit_margin_pct), 2) AS avg_margin_pct,
    ROUND(AVG(discount) * 100, 2)    AS avg_discount_pct
FROM fact_transactions
WHERE is_loss_making = 1
GROUP BY year_month, product_category
HAVING COUNT(*) >= 5
ORDER BY profit_impact ASC
LIMIT 25;


-- name: payment_type_mix
-- description: Revenue and margin by payment method, including the 'Unknown'
--              bucket the cleaner created rather than guessing.
SELECT
    payment_type,
    COUNT(*)                 AS transactions,
    ROUND(SUM(revenue), 2)   AS revenue,
    ROUND(SUM(profit), 2)    AS profit,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2) AS profit_margin_pct,
    ROUND(AVG(revenue), 2)   AS avg_order_value,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 2) AS pct_of_revenue
FROM fact_transactions
GROUP BY payment_type
ORDER BY revenue DESC;


-- name: receivables_aging
-- description: Open receivables by age bucket plus the settled comparison,
--              with each bucket's share of the outstanding balance.
SELECT
    aging_bucket,
    COUNT(*)                        AS invoices,
    ROUND(SUM(invoice_amount), 2)   AS balance,
    ROUND(AVG(invoice_amount), 2)   AS avg_invoice,
    ROUND(AVG(days_overdue), 1)     AS avg_days_overdue,
    ROUND(SUM(invoice_amount) * 100.0
          / SUM(SUM(invoice_amount)) OVER (), 2) AS pct_of_total
FROM fact_accounts_receivable
GROUP BY aging_bucket
ORDER BY aging_bucket;


-- name: collections_performance
-- description: Days-to-pay by customer segment and month - a collections
--              trend, and whether the biggest accounts are the slowest payers.
WITH paid AS (
    SELECT ar.invoice_id, ar.invoice_amount, ar.days_to_pay,
           ar.payment_status, c.customer_segment,
           SUBSTR(ar.invoice_date, 1, 7) AS invoice_month
    FROM fact_accounts_receivable ar
    JOIN dim_customer c ON c.customer_id = ar.customer_id
    WHERE ar.days_to_pay IS NOT NULL
)
SELECT
    customer_segment,
    COUNT(*)                     AS invoices_settled,
    ROUND(AVG(days_to_pay), 1)   AS avg_days_to_pay,
    ROUND(SUM(invoice_amount), 2) AS settled_value,
    SUM(CASE WHEN payment_status = 'Paid late' THEN 1 ELSE 0 END) AS paid_late,
    ROUND(SUM(CASE WHEN payment_status = 'Paid late' THEN 1 ELSE 0 END) * 100.0
          / COUNT(*), 2)         AS late_payment_rate_pct
FROM paid
GROUP BY customer_segment
ORDER BY avg_days_to_pay DESC;


-- name: monthly_kpi_scorecard
-- description: One row per month carrying every headline KPI, with the prior
--              month and prior year alongside.  This is the query the
--              executive dashboard page is built on.
WITH base AS (
    SELECT
        f.month_start,
        f.year_month,
        SUM(f.revenue)                  AS revenue,
        SUM(f.cost)                     AS cost,
        SUM(f.profit)                   AS gross_profit,
        SUM(f.gross_revenue)            AS gross_revenue,
        SUM(f.discount_amount)          AS discount_amount,
        COUNT(*)                        AS transactions,
        COUNT(DISTINCT f.customer_id)   AS active_customers,
        SUM(f.quantity)                 AS units_sold
    FROM fact_transactions f
    GROUP BY f.month_start, f.year_month
)
SELECT
    b.month_start,
    b.year_month,
    ROUND(b.revenue, 2)      AS revenue,
    ROUND(b.cost, 2)         AS cost,
    ROUND(b.gross_profit, 2) AS gross_profit,
    ROUND(b.gross_profit * 100.0 / NULLIF(b.revenue, 0), 2)      AS gross_margin_pct,
    ROUND(b.cost * 100.0 / NULLIF(b.revenue, 0), 2)              AS cost_to_revenue_pct,
    ROUND(b.discount_amount * 100.0 / NULLIF(b.gross_revenue, 0), 2) AS discount_rate_pct,
    b.transactions,
    b.active_customers,
    b.units_sold,
    ROUND(b.revenue * 1.0 / NULLIF(b.transactions, 0), 2)        AS avg_order_value,
    ROUND(b.revenue * 1.0 / NULLIF(b.active_customers, 0), 2)    AS revenue_per_customer,
    ROUND((b.revenue - LAG(b.revenue) OVER w) * 100.0
          / NULLIF(LAG(b.revenue) OVER w, 0), 2)                 AS revenue_mom_pct,
    ROUND((b.revenue - LAG(b.revenue, 12) OVER w) * 100.0
          / NULLIF(LAG(b.revenue, 12) OVER w, 0), 2)             AS revenue_yoy_pct,
    ROUND((b.gross_profit - LAG(b.gross_profit, 12) OVER w) * 100.0
          / NULLIF(LAG(b.gross_profit, 12) OVER w, 0), 2)        AS profit_yoy_pct,
    ROUND(AVG(b.revenue) OVER (ORDER BY b.month_start
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)      AS revenue_3mo_ma,
    ROUND(p.operating_profit, 2)     AS operating_profit,
    ROUND(p.operating_margin_pct, 2) AS operating_margin_pct,
    ROUND(p.marketing_spend, 2)      AS marketing_spend,
    p.headcount
FROM base b
LEFT JOIN v_monthly_pnl p ON p.month_start = b.month_start
WINDOW w AS (ORDER BY b.month_start)
ORDER BY b.month_start;


-- name: data_quality_summary
-- description: How much of the loaded ledger carried a reconciliation defect
--              in the source extract - a standing check that the cleaning
--              pipeline's findings survive into the warehouse.
SELECT
    year,
    COUNT(*)                              AS transactions,
    SUM(had_reconciliation_error)         AS rows_with_reconciliation_error,
    ROUND(SUM(had_reconciliation_error) * 100.0 / COUNT(*), 2) AS pct_with_error,
    SUM(CASE WHEN is_customer_attributed = 0 THEN 1 ELSE 0 END) AS unattributed_rows,
    SUM(is_loss_making)                   AS loss_making_rows,
    ROUND(SUM(CASE WHEN is_customer_attributed = 0 THEN revenue ELSE 0 END), 2)
                                          AS unattributed_revenue
FROM fact_transactions
GROUP BY year
ORDER BY year;
