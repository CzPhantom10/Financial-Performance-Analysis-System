"""Reproducible data-cleaning pipeline for the raw transaction ledger.

The pipeline is a sequence of named, auditable steps.  Every step records what
it changed into a ``CleaningLog``; the log is written to
``data/processed/cleaning_report.json`` so the cleaning is reviewable rather
than a black box.

Design decisions worth stating explicitly:

* **Reject vs. repair.**  Rows that fail a *hard* business rule (unparseable
  or impossible date, non-positive quantity or price, out-of-range discount)
  are quarantined to ``transactions_rejected.csv`` with a reason - they are
  not silently dropped and not guessed at.  Rows with *soft* problems
  (missing region, missing category) are repaired from the reference
  dimensions, which is a lookup, not an imputation.
* **Components are authoritative.**  ``revenue``/``cost``/``profit`` arriving
  in the extract are treated as untrusted.  They are recomputed from
  quantity, price, cost and discount, and the discrepancy is measured and
  reported rather than assumed away.
* **Standardise before deduplicating.**  Casing and whitespace variants must
  collapse first, or duplicate detection misses re-keyed rows.

Run with:  python -m src.clean_pipeline
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src import config

# Business calendar the ledger is allowed to cover. Anything outside is a
# data-entry error, not a real transaction.
VALID_START = date(2023, 1, 1)
VALID_END = date(2025, 12, 31)

CANONICAL_REGIONS = ["North America", "Europe", "APAC", "LATAM", "Middle East"]
CANONICAL_CATEGORIES = [
    "Enterprise Software", "Hardware", "Networking", "Peripherals",
    "Cloud Services", "Professional Services", "Support Contracts",
]
CANONICAL_PAYMENTS = ["Credit Card", "Bank Transfer", "Net 30 Invoice",
                      "Digital Wallet", "Cash"]
CANONICAL_SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Retail"]

# Alias -> canonical.  Keys are matched after aggressive normalisation
# (lowercased, non-alphanumerics stripped), so "N. America", "n_america" and
# "NORTH AMERICA" all reduce to the same lookup key.
REGION_ALIASES = {
    "northamerica": "North America", "namerica": "North America", "na": "North America",
    "europe": "Europe", "emea": "Europe",
    "apac": "APAC", "asiapacific": "APAC",
    "latam": "LATAM", "latinamerica": "LATAM",
    "middleeast": "Middle East", "meast": "Middle East",
}
PAYMENT_ALIASES = {
    "creditcard": "Credit Card", "cc": "Credit Card",
    "banktransfer": "Bank Transfer", "wire": "Bank Transfer", "wiretransfer": "Bank Transfer",
    "net30": "Net 30 Invoice", "net30invoice": "Net 30 Invoice", "invoice": "Net 30 Invoice",
    "digitalwallet": "Digital Wallet", "ewallet": "Digital Wallet", "wallet": "Digital Wallet",
    "cash": "Cash",
}

# Date formats seen in the extract, tried in order of decreasing specificity.
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%Y.%m.%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------
@dataclass
class CleaningLog:
    steps: list[dict] = field(default_factory=list)

    def record(self, step: str, detail: str, affected: int, **extra) -> None:
        entry = {"step": step, "detail": detail, "rows_affected": int(affected)}
        entry.update(extra)
        self.steps.append(entry)
        print(f"  [{step:<22}] {detail:<52} {affected:>7,}")

    def to_dict(self, **summary) -> dict:
        return {"summary": summary, "steps": self.steps}


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def _norm_key(value) -> str:
    """Aggressively normalise a categorical value for alias lookup.

    Nulls must short-circuit *before* stringification: ``str(pd.NA)`` is
    ``'<NA>'``, which normalises to ``'na'`` - a real alias for North America.
    Without this guard every missing region would be silently booked to the
    largest region in the business.
    """
    if value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value)):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def parse_numeric(series: pd.Series) -> pd.Series:
    """Coerce a column that may contain '$1,234.50', '12.5%' or plain floats.

    Percent-suffixed values are divided by 100, which is what the source system
    means by them - dropping the sign would silently inflate a discount by 100x.
    """
    s = series.astype(str).str.strip()
    is_pct = s.str.endswith("%")
    s = (s.str.replace(r"[$,\s]", "", regex=True)
          .str.replace("%", "", regex=False)
          .replace({"": None, "nan": None, "None": None, "N/A": None, "-": None}))
    out = pd.to_numeric(s, errors="coerce")
    out = out.where(~is_pct, out / 100.0)
    return out


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a column holding several date formats at once.

    Each format is applied to whatever is still unparsed, most specific first.
    ``%d/%m/%Y`` before ``%m/%d/%Y`` reflects the source system's European
    locale; the ambiguity is real, so the choice is documented rather than
    left to pandas' inference.
    """
    raw = series.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        pending = out.isna()
        if not pending.any():
            break
        attempt = pd.to_datetime(raw[pending], format=fmt, errors="coerce")
        out.loc[pending] = attempt
    return out


def canonicalise(series: pd.Series, aliases: dict[str, str],
                 canonical: list[str]) -> pd.Series:
    """Map free-text categorical values onto the controlled vocabulary."""
    lookup = {_norm_key(c): c for c in canonical}
    lookup.update(aliases)
    keys = series.map(_norm_key)
    return keys.map(lookup)


def normalise_customer_id(series: pd.Series) -> pd.Series:
    """Reduce CUST-00012 / cust00012 / C12 / CUST_00012 to one canonical form."""
    digits = series.astype(str).str.extract(r"(\d+)", expand=False)
    out = "CUST-" + digits.astype(float).astype("Int64").astype(str).str.zfill(5)
    return out.where(digits.notna())


# --------------------------------------------------------------------------
# Pipeline steps
# --------------------------------------------------------------------------
def load_raw() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read everything as text so the pipeline, not pandas, controls parsing."""
    txns = pd.read_csv(config.RAW_TRANSACTIONS, dtype=str, keep_default_na=False,
                       na_values=["", "nan", "NaN", "None", "NULL"])
    products = pd.read_csv(config.RAW_PRODUCTS)
    customers = pd.read_csv(config.RAW_CUSTOMERS, keep_default_na=False,
                            na_values=["", "nan"])
    return txns, products, customers


def standardise(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Steps 8 & 9: controlled vocabularies and consistent identifiers."""
    df = df.copy()

    # Trim stray whitespace everywhere before anything else looks at values.
    obj_cols = [c for c in df.columns if df[c].dtype == object or
                str(df[c].dtype).startswith("str")]
    trimmed = 0
    for c in obj_cols:
        before = df[c]
        after = before.astype("string").str.strip()
        trimmed += int((before.astype("string") != after).fillna(False).sum())
        df[c] = after
    log.record("standardise", "whitespace trimmed from text fields", trimmed)

    for col, aliases, canon in [
        ("region", REGION_ALIASES, CANONICAL_REGIONS),
        ("product_category", {}, CANONICAL_CATEGORIES),
        ("payment_type", PAYMENT_ALIASES, CANONICAL_PAYMENTS),
        ("customer_segment", {}, CANONICAL_SEGMENTS),
    ]:
        before = df[col].copy()
        df[col] = canonicalise(df[col], aliases, canon)
        changed = int((before.fillna("~") != df[col].fillna("~")).sum())
        unmapped = int(df[col].isna().sum() - before.isna().sum())
        log.record("standardise", f"{col}: values mapped to canonical vocabulary",
                   changed, newly_unmapped=unmapped)

    before = df["customer_id"].copy()
    df["customer_id"] = normalise_customer_id(df["customer_id"])
    log.record("standardise", "customer_id normalised to CUST-#####",
               int((before.fillna("~") != df["customer_id"].fillna("~")).sum()))

    df["product_id"] = df["product_id"].astype("string").str.upper()
    return df


def parse_types(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Steps 3 & 4: dates and numerics become real types, or become NaN."""
    df = df.copy()
    df["transaction_date"] = parse_dates(df["transaction_date"])
    log.record("parse", "dates that could not be parsed in any known format",
               int(df["transaction_date"].isna().sum()))

    for col in ["quantity", "unit_price", "unit_cost", "discount",
                "revenue", "cost", "profit"]:
        df[col] = parse_numeric(df[col])
    df["quantity"] = df["quantity"].astype("Float64")
    log.record("parse", "numeric columns coerced from mixed text/number", len(df))
    return df


def deduplicate(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Step 1, run after standardisation so re-keyed rows still collapse."""
    n0 = len(df)

    df = df.drop_duplicates()
    log.record("deduplicate", "exact duplicate rows removed", n0 - len(df))

    n1 = len(df)
    df = df.drop_duplicates(subset=["transaction_id"], keep="first")
    log.record("deduplicate", "repeated transaction_id (kept first)", n1 - len(df))

    # A re-keyed duplicate: identical economics on the same day for the same
    # customer and product, but a fresh transaction_id.
    n2 = len(df)
    business_key = ["transaction_date", "customer_id", "product_id",
                    "quantity", "unit_price", "discount"]
    df = df.drop_duplicates(subset=business_key, keep="first")
    log.record("deduplicate", "re-keyed near-duplicates on business key", n2 - len(df))
    return df.reset_index(drop=True)


def validate(df: pd.DataFrame, log: CleaningLog) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Steps 3-5: quarantine rows that violate a hard business rule."""
    df = df.copy()
    reasons = pd.Series([""] * len(df), index=df.index, dtype=object)

    def flag(mask: pd.Series, reason: str) -> None:
        mask = mask.fillna(False).to_numpy()
        reasons[mask & (reasons == "")] = reason
        log.record("validate", reason, int(mask.sum()))

    d = df["transaction_date"]
    flag(d.isna(), "unparseable_transaction_date")
    flag(d.notna() & (d < pd.Timestamp(VALID_START)), "date_before_business_start")
    flag(d.notna() & (d > pd.Timestamp(VALID_END)), "date_in_the_future")

    q = df["quantity"]
    flag(q.notna() & (q <= 0), "non_positive_quantity")
    flag(q.notna() & (q > config.MAX_PLAUSIBLE_QUANTITY), "implausible_quantity")

    p = df["unit_price"]
    flag(p.notna() & (p <= 0), "non_positive_unit_price")
    flag(p.notna() & (p > config.MAX_PLAUSIBLE_UNIT_PRICE), "implausible_unit_price")

    disc = df["discount"]
    flag(disc.notna() & ((disc < 0) | (disc > 1)), "discount_outside_0_1")

    flag(df["product_id"].isna(), "missing_product_id")

    rejected = df[reasons != ""].copy()
    rejected["rejection_reason"] = reasons[reasons != ""]
    clean = df[reasons == ""].copy().reset_index(drop=True)
    log.record("validate", "TOTAL rows quarantined", len(rejected))
    return clean, rejected


def repair_missing(df: pd.DataFrame, products: pd.DataFrame,
                   customers: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Step 2. Repair from reference data where possible; impute only where a
    defensible statistical fallback exists; label the rest explicitly."""
    df = df.copy()

    # -- Dimension lookups: this is recovery of a known value, not imputation.
    cat_by_product = products.set_index("product_id")["product_category"]
    miss = df["product_category"].isna()
    df.loc[miss, "product_category"] = df.loc[miss, "product_id"].map(cat_by_product)
    log.record("repair", "product_category recovered from product master", int(miss.sum()))

    cust = customers.set_index("customer_id")
    for col in ["region", "customer_segment"]:
        miss = df[col].isna() & df["customer_id"].notna()
        df.loc[miss, col] = df.loc[miss, "customer_id"].map(cust[col])
        log.record("repair", f"{col} recovered from customer master", int(miss.sum()))

    # -- Derived-from-siblings: unit_price and cost are recoverable by algebra
    #    when the other components survived.
    miss = df["unit_price"].isna() & df["revenue"].notna() & df["quantity"].gt(0)
    denom = df.loc[miss, "quantity"] * (1 - df.loc[miss, "discount"].fillna(0))
    df.loc[miss, "unit_price"] = (df.loc[miss, "revenue"] / denom).where(denom > 0)
    log.record("repair", "unit_price back-solved from revenue", int(miss.sum()))

    miss = df["unit_cost"].isna() & df["cost"].notna() & df["quantity"].gt(0)
    df.loc[miss, "unit_cost"] = df.loc[miss, "cost"] / df.loc[miss, "quantity"]
    log.record("repair", "unit_cost back-solved from cost", int(miss.sum()))

    miss = df["cost"].isna() & df["unit_cost"].notna()
    df.loc[miss, "cost"] = df.loc[miss, "unit_cost"] * df.loc[miss, "quantity"]
    log.record("repair", "cost recomputed from unit_cost x quantity", int(miss.sum()))

    # -- Statistical fallback: product-level median, which respects the fact
    #    that price and cost vary far more between products than within one.
    for col, src in [("unit_price", "list_price"), ("unit_cost", "base_unit_cost")]:
        miss = df[col].isna()
        if miss.any():
            med = df.groupby("product_id")[col].median()
            df.loc[miss, col] = df.loc[miss, "product_id"].map(med)
            still = df[col].isna()
            if still.any():  # product never seen with a valid value
                df.loc[still, col] = df.loc[still, "product_id"].map(
                    products.set_index("product_id")[src])
            log.record("repair", f"{col} imputed from product median / list", int(miss.sum()))

    miss = df["cost"].isna()
    df.loc[miss, "cost"] = df.loc[miss, "unit_cost"] * df.loc[miss, "quantity"]
    log.record("repair", "cost filled after unit_cost imputation", int(miss.sum()))

    # -- Discount: median by segment, the strongest observed driver of discount.
    miss = df["discount"].isna()
    seg_median = df.groupby("customer_segment")["discount"].median()
    df.loc[miss, "discount"] = df.loc[miss, "customer_segment"].map(seg_median)
    df["discount"] = df["discount"].fillna(df["discount"].median())
    log.record("repair", "discount imputed from segment median", int(miss.sum()))

    # -- No defensible way to invent these: label them and let the analysis
    #    decide whether to include them.
    n_unknown_pay = int(df["payment_type"].isna().sum())
    df["payment_type"] = df["payment_type"].fillna("Unknown")
    log.record("repair", "payment_type labelled 'Unknown'", n_unknown_pay)

    df["is_customer_attributed"] = df["customer_id"].notna()
    n_unattr = int((~df["is_customer_attributed"]).sum())
    df["customer_id"] = df["customer_id"].fillna("UNATTRIBUTED")
    log.record("repair", "customer_id missing -> 'UNATTRIBUTED' (kept for revenue, "
                         "excluded from customer analysis)", n_unattr)

    for col in ["region", "customer_segment"]:
        n = int(df[col].isna().sum())
        df[col] = df[col].fillna("Unknown")
        log.record("repair", f"{col} still missing -> 'Unknown'", n)

    return df


def reconcile_and_derive(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Steps 6, 7 & 10: recompute the money, measure the discrepancy, then
    build the derived financial metrics the rest of the project reads."""
    df = df.copy()
    tol = config.RECONCILIATION_TOLERANCE

    # Validation has already guaranteed quantity is a positive whole number,
    # so it can drop the nullable float that parsing required.
    df["quantity"] = df["quantity"].astype("int64")

    df["gross_revenue"] = (df["quantity"] * df["unit_price"]).round(2)
    df["discount_amount"] = (df["gross_revenue"] * df["discount"]).round(2)
    recomputed_revenue = (df["gross_revenue"] - df["discount_amount"]).round(2)
    recomputed_cost = (df["quantity"] * df["unit_cost"]).round(2)
    recomputed_profit = (recomputed_revenue - recomputed_cost).round(2)

    rev_bad = (df["revenue"] - recomputed_revenue).abs() > tol
    cost_bad = (df["cost"] - recomputed_cost).abs() > tol
    prof_bad = (df["profit"] - recomputed_profit).abs() > tol

    log.record("reconcile", "revenue disagreed with quantity x price x (1-discount)",
               int(rev_bad.fillna(True).sum()))
    log.record("reconcile", "cost disagreed with quantity x unit_cost",
               int(cost_bad.fillna(True).sum()))
    log.record("reconcile", "profit disagreed with revenue - cost",
               int(prof_bad.fillna(True).sum()))

    df["reported_revenue"] = df["revenue"]
    df["revenue_variance"] = (df["revenue"] - recomputed_revenue).round(2)
    df["had_reconciliation_error"] = (rev_bad | cost_bad | prof_bad).fillna(True)

    # Components win. Everything downstream reads these three columns.
    df["revenue"] = recomputed_revenue
    df["cost"] = recomputed_cost
    df["profit"] = recomputed_profit

    df["profit_margin_pct"] = np.where(df["revenue"] > 0,
                                       df["profit"] / df["revenue"] * 100, np.nan).round(4)
    df["unit_margin"] = (df["unit_price"] * (1 - df["discount"]) - df["unit_cost"]).round(4)
    df["cost_to_revenue_ratio"] = np.where(df["revenue"] > 0,
                                           df["cost"] / df["revenue"], np.nan).round(4)
    df["is_loss_making"] = df["profit"] < 0

    d = df["transaction_date"]
    df["year"] = d.dt.year
    df["quarter"] = d.dt.quarter
    df["year_quarter"] = d.dt.year.astype(str) + "-Q" + d.dt.quarter.astype(str)
    df["month"] = d.dt.month
    df["month_start"] = d.dt.to_period("M").dt.to_timestamp()
    df["year_month"] = d.dt.strftime("%Y-%m")
    df["day_of_week"] = d.dt.day_name()
    df["is_weekend"] = d.dt.weekday >= 5

    log.record("derive", "financial and calendar metrics created", len(df))
    return df


def order_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "transaction_id", "transaction_date", "year", "quarter", "year_quarter",
        "month", "year_month", "month_start", "day_of_week", "is_weekend",
        "customer_id", "is_customer_attributed", "customer_segment", "region",
        "product_id", "product_category", "payment_type",
        "quantity", "unit_price", "unit_cost", "discount",
        "gross_revenue", "discount_amount", "revenue", "cost", "profit",
        "profit_margin_pct", "unit_margin", "cost_to_revenue_ratio",
        "is_loss_making", "reported_revenue", "revenue_variance",
        "had_reconciliation_error",
    ]
    return df[[c for c in cols if c in df.columns]]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run(verbose: bool = True) -> pd.DataFrame:
    log = CleaningLog()
    if verbose:
        print("Loading raw extracts ...")
    raw, products, customers = load_raw()
    n_raw = len(raw)
    if verbose:
        print(f"Raw rows: {n_raw:,}\n")

    df = standardise(raw, log)
    df = parse_types(df, log)
    df = deduplicate(df, log)
    df, rejected = validate(df, log)
    df = repair_missing(df, products, customers, log)
    df = reconcile_and_derive(df, log)
    df = order_columns(df)

    df.to_csv(config.CLEAN_TRANSACTIONS, index=False)
    rejected.to_csv(config.REJECTED_TRANSACTIONS, index=False)

    summary = {
        "raw_rows": n_raw,
        "clean_rows": len(df),
        "rejected_rows": len(rejected),
        "rows_removed_as_duplicates": int(
            sum(s["rows_affected"] for s in log.steps if s["step"] == "deduplicate")),
        "retention_rate_pct": round(len(df) / n_raw * 100, 2),
        "rows_with_reconciliation_error": int(df["had_reconciliation_error"].sum()),
        "date_range": [str(df["transaction_date"].min().date()),
                       str(df["transaction_date"].max().date())],
        "total_revenue": round(float(df["revenue"].sum()), 2),
        "total_cost": round(float(df["cost"].sum()), 2),
        "total_profit": round(float(df["profit"].sum()), 2),
        "gross_margin_pct": round(float(df["profit"].sum() / df["revenue"].sum() * 100), 2),
        "rejection_reasons": (rejected["rejection_reason"].value_counts().to_dict()
                              if len(rejected) else {}),
    }
    config.CLEANING_REPORT.write_text(json.dumps(log.to_dict(**summary), indent=2))

    if verbose:
        print("\n" + "=" * 74)
        print(f"Raw {n_raw:,} -> clean {len(df):,} "
              f"({summary['retention_rate_pct']}% retained), "
              f"{len(rejected):,} quarantined")
        print(f"Revenue {summary['total_revenue']:,.0f} | "
              f"Profit {summary['total_profit']:,.0f} | "
              f"Margin {summary['gross_margin_pct']}%")
        print(f"Written: {config.CLEAN_TRANSACTIONS.name}, "
              f"{config.REJECTED_TRANSACTIONS.name}, {config.CLEANING_REPORT.name}")
    return df


def load_clean() -> pd.DataFrame:
    """Convenience reader used by the notebooks, dashboard and analysis modules."""
    df = pd.read_csv(config.CLEAN_TRANSACTIONS,
                     parse_dates=["transaction_date", "month_start"])
    return df


if __name__ == "__main__":
    run()
