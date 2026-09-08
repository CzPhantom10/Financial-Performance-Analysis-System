-- ===========================================================================
--  Financial Performance & Profitability Analytics - relational schema
-- ---------------------------------------------------------------------------
--  A star schema: one transaction-grain fact table surrounded by conformed
--  dimensions, plus four finance fact tables at month grain.
--
--  Portability note: the fact table carries pre-computed `year_month` (TEXT)
--  and `month_start` (DATE) columns rather than relying on date functions.
--  SQLite's STRFTIME, PostgreSQL's DATE_TRUNC and MySQL's DATE_FORMAT are all
--  mutually incompatible, so materialising the grain keys at load time keeps
--  every query in sql/ standard SQL that runs unchanged on all three engines.
-- ===========================================================================

DROP VIEW  IF EXISTS v_monthly_pnl;
DROP VIEW  IF EXISTS v_monthly_revenue;
DROP VIEW  IF EXISTS v_customer_summary;
DROP VIEW  IF EXISTS v_product_summary;

DROP TABLE IF EXISTS fact_transactions;
DROP TABLE IF EXISTS fact_operating_expenses;
DROP TABLE IF EXISTS fact_marketing_spend;
DROP TABLE IF EXISTS fact_employee_costs;
DROP TABLE IF EXISTS fact_budget;
DROP TABLE IF EXISTS fact_accounts_receivable;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_date;

-- ---------------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key        DATE        NOT NULL PRIMARY KEY,
    year            INTEGER     NOT NULL,
    quarter         INTEGER     NOT NULL,
    year_quarter    VARCHAR(8)  NOT NULL,
    month           INTEGER     NOT NULL,
    year_month      VARCHAR(7)  NOT NULL,
    month_start     DATE        NOT NULL,
    month_name      VARCHAR(12) NOT NULL,
    day_of_week     VARCHAR(12) NOT NULL,
    is_weekend      INTEGER     NOT NULL
);

CREATE TABLE dim_customer (
    customer_id       VARCHAR(16) NOT NULL PRIMARY KEY,
    customer_segment  VARCHAR(24) NOT NULL,
    region            VARCHAR(24) NOT NULL,
    signup_date       DATE,
    churn_date        DATE
);

CREATE TABLE dim_product (
    product_id        VARCHAR(16) NOT NULL PRIMARY KEY,
    product_name      VARCHAR(64) NOT NULL,
    product_category  VARCHAR(32) NOT NULL,
    list_price        DECIMAL(12,2) NOT NULL,
    base_unit_cost    DECIMAL(12,2) NOT NULL,
    launch_date       DATE
);

-- ---------------------------------------------------------------------------
-- Transaction-grain fact
-- ---------------------------------------------------------------------------
CREATE TABLE fact_transactions (
    transaction_id          VARCHAR(16)   NOT NULL PRIMARY KEY,
    transaction_date        DATE          NOT NULL,
    year                    INTEGER       NOT NULL,
    quarter                 INTEGER       NOT NULL,
    year_quarter            VARCHAR(8)    NOT NULL,
    month                   INTEGER       NOT NULL,
    year_month              VARCHAR(7)    NOT NULL,
    month_start             DATE          NOT NULL,
    day_of_week             VARCHAR(12)   NOT NULL,
    is_weekend              INTEGER       NOT NULL,
    customer_id             VARCHAR(16)   NOT NULL,
    is_customer_attributed  INTEGER       NOT NULL,
    customer_segment        VARCHAR(24)   NOT NULL,
    region                  VARCHAR(24)   NOT NULL,
    product_id              VARCHAR(16)   NOT NULL,
    product_category        VARCHAR(32)   NOT NULL,
    payment_type            VARCHAR(24)   NOT NULL,
    quantity                INTEGER       NOT NULL,
    unit_price              DECIMAL(12,4) NOT NULL,
    unit_cost               DECIMAL(12,4) NOT NULL,
    discount                DECIMAL(6,4)  NOT NULL,
    gross_revenue           DECIMAL(14,2) NOT NULL,
    discount_amount         DECIMAL(14,2) NOT NULL,
    revenue                 DECIMAL(14,2) NOT NULL,
    cost                    DECIMAL(14,2) NOT NULL,
    profit                  DECIMAL(14,2) NOT NULL,
    profit_margin_pct       DECIMAL(10,4),
    unit_margin             DECIMAL(12,4),
    cost_to_revenue_ratio   DECIMAL(10,4),
    is_loss_making          INTEGER       NOT NULL,
    had_reconciliation_error INTEGER      NOT NULL
);

-- ---------------------------------------------------------------------------
-- Month-grain finance facts
-- ---------------------------------------------------------------------------
CREATE TABLE fact_operating_expenses (
    month             DATE          NOT NULL,
    expense_category  VARCHAR(32)   NOT NULL,
    amount            DECIMAL(14,2) NOT NULL,
    PRIMARY KEY (month, expense_category)
);

CREATE TABLE fact_marketing_spend (
    month    DATE          NOT NULL,
    region   VARCHAR(24)   NOT NULL,
    channel  VARCHAR(32)   NOT NULL,
    spend    DECIMAL(14,2) NOT NULL,
    PRIMARY KEY (month, region, channel)
);

CREATE TABLE fact_employee_costs (
    month       DATE          NOT NULL,
    department  VARCHAR(32)   NOT NULL,
    headcount   INTEGER       NOT NULL,
    total_cost  DECIMAL(14,2) NOT NULL,
    PRIMARY KEY (month, department)
);

CREATE TABLE fact_budget (
    month           DATE          NOT NULL,
    region          VARCHAR(24)   NOT NULL,
    revenue_target  DECIMAL(14,2) NOT NULL,
    profit_target   DECIMAL(14,2) NOT NULL,
    PRIMARY KEY (month, region)
);

CREATE TABLE fact_accounts_receivable (
    invoice_id      VARCHAR(16)   NOT NULL PRIMARY KEY,
    transaction_id  VARCHAR(16)   NOT NULL,
    customer_id     VARCHAR(16)   NOT NULL,
    invoice_date    DATE          NOT NULL,
    due_date        DATE          NOT NULL,
    paid_date       DATE,
    invoice_amount  DECIMAL(14,2) NOT NULL,
    -- Materialised at load time: SQLite (JULIANDAY), PostgreSQL (date minus
    -- date) and MySQL (DATEDIFF) express date arithmetic incompatibly, so the
    -- day counts are computed once rather than in every query.
    days_to_pay     INTEGER,
    days_overdue    INTEGER,
    is_open         INTEGER NOT NULL,
    payment_status  VARCHAR(20) NOT NULL,
    aging_bucket    VARCHAR(20) NOT NULL
);
