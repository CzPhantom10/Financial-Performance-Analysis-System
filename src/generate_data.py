"""Generate the raw financial dataset for the analytics platform.

Produces a realistic three-year transactional ledger for a mid-size B2B
technology reseller, plus the supporting finance extracts (opex, marketing,
payroll, budgets, receivables).

Two things make the output useful as a *data science* exercise rather than a
toy CSV:

1. **Injected business events** - cost spikes, a revenue collapse, a rogue
   discounting campaign, marketing overspend.  Each event is written to
   ``_injected_events.json`` so the anomaly module can be scored against
   ground truth instead of hand-waving.
2. **Injected data-quality defects** - duplicates, mixed date formats,
   currency strings in numeric columns, inconsistent identifiers and
   categoricals, impossible values, and stale revenue/profit fields that no
   longer reconcile with their components.  The cleaning pipeline has to earn
   its keep.

Run with:  python -m src.generate_data
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src import config

SEED = 42
START_DATE = date(2023, 1, 1)
END_DATE = date(2025, 12, 31)

N_CUSTOMERS = 1_200
BASE_TXNS_PER_DAY = 58.0
ANNUAL_REVENUE_GROWTH = 0.18   # underlying demand trend
ANNUAL_PRICE_INFLATION = 0.035
ANNUAL_COST_INFLATION = 0.052  # cost outrunning price -> structural margin squeeze

# --------------------------------------------------------------------------
# Reference dimensions
# --------------------------------------------------------------------------
# margin is the *designed* gross margin before discounts; price is the base
# list-price range in USD.
CATEGORIES = {
    "Enterprise Software": dict(margin=0.72, price=(800, 5200), share=0.11, n_products=9),
    "Hardware":            dict(margin=0.26, price=(150, 3400), share=0.24, n_products=12),
    "Networking":          dict(margin=0.34, price=(200, 2600), share=0.13, n_products=9),
    "Peripherals":         dict(margin=0.41, price=(18, 420),   share=0.22, n_products=11),
    "Cloud Services":      dict(margin=0.63, price=(90, 1300),  share=0.12, n_products=8),
    "Professional Services": dict(margin=0.47, price=(450, 8000), share=0.08, n_products=6),
    "Support Contracts":   dict(margin=0.57, price=(280, 4100), share=0.10, n_products=7),
}

REGIONS = ["North America", "Europe", "APAC", "LATAM", "Middle East"]
REGION_WEIGHTS = [0.38, 0.27, 0.19, 0.10, 0.06]

SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Retail"]
SEGMENT_WEIGHTS = [0.09, 0.24, 0.41, 0.26]
SEGMENT_PROFILE = {
    # order_mu/sigma parameterise a lognormal for line quantity
    "Enterprise": dict(order_mu=2.30, order_sigma=0.75, base_discount=0.125, activity=6.0),
    "Mid-Market": dict(order_mu=1.55, order_sigma=0.70, base_discount=0.085, activity=3.0),
    "SMB":        dict(order_mu=0.95, order_sigma=0.65, base_discount=0.050, activity=1.4),
    "Retail":     dict(order_mu=0.35, order_sigma=0.55, base_discount=0.025, activity=0.8),
}

PAYMENT_TYPES = ["Credit Card", "Bank Transfer", "Net 30 Invoice", "Digital Wallet", "Cash"]
PAYMENT_BY_SEGMENT = {
    "Enterprise": [0.10, 0.34, 0.52, 0.03, 0.01],
    "Mid-Market": [0.24, 0.31, 0.34, 0.10, 0.01],
    "SMB":        [0.46, 0.20, 0.14, 0.18, 0.02],
    "Retail":     [0.58, 0.06, 0.02, 0.28, 0.06],
}

# Month-of-year demand index: B2B tech, quarter-end pushes and a December
# budget flush, summer trough.
MONTH_INDEX = {
    1: 0.82, 2: 0.86, 3: 1.13, 4: 0.88, 5: 0.95, 6: 1.16,
    7: 0.83, 8: 0.76, 9: 1.11, 10: 0.97, 11: 1.07, 12: 1.26,
}
# Monday..Sunday
DOW_INDEX = [1.12, 1.15, 1.14, 1.10, 1.02, 0.36, 0.24]

OPEX_CATEGORIES = {
    "Salaries & Wages":  dict(base=1_480_000, growth=0.16, noise=0.03),
    "Rent & Facilities": dict(base=210_000,   growth=0.05, noise=0.02),
    "Utilities":         dict(base=48_000,    growth=0.07, noise=0.09),
    "Software & Tools":  dict(base=132_000,   growth=0.22, noise=0.05),
    "Logistics & Freight": dict(base=0,       growth=0.00, noise=0.08),  # volume-driven
    "Travel & Entertainment": dict(base=86_000, growth=0.11, noise=0.18),
    "Professional Fees": dict(base=64_000,    growth=0.09, noise=0.15),
    "Depreciation":      dict(base=95_000,    growth=0.06, noise=0.01),
}

DEPARTMENTS = ["Sales", "Engineering", "Support", "Operations", "Finance & Admin", "Marketing"]
MARKETING_CHANNELS = ["Digital Ads", "Events & Trade Shows", "Content & SEO", "Partner Co-Marketing"]


# --------------------------------------------------------------------------
# Injected business events (ground truth for the anomaly module)
# --------------------------------------------------------------------------
INJECTED_EVENTS = [
    dict(
        event_id="EV-01", kind="cost_spike",
        start="2024-08-01", end="2024-10-15",
        scope={"product_category": "Hardware"}, magnitude=1.38,
        metric="unit_cost",
        description="Supplier component shortage inflates hardware unit costs ~38%, "
                    "compressing gross margin for two and a half months.",
    ),
    dict(
        event_id="EV-02", kind="revenue_drop",
        start="2025-02-01", end="2025-02-28",
        scope={}, magnitude=0.55,
        metric="transaction_volume",
        description="ERP migration outage cuts order intake to ~55% of expected "
                    "for the whole of February 2025.",
    ),
    dict(
        event_id="EV-03", kind="discount_surge",
        start="2024-11-01", end="2024-12-15",
        scope={"region": "Europe"}, magnitude=0.18,
        metric="discount",
        description="Unauthorised channel discounting in Europe adds ~18pp of "
                    "discount on top of normal terms.",
    ),
    dict(
        event_id="EV-04", kind="mispricing",
        start="2023-09-05", end="2023-09-25",
        scope={"product_category": "Peripherals"}, magnitude=0.55,
        metric="unit_price",
        description="Pricing-table bug lists peripherals at 55% of intended price, "
                    "producing a window of negative-margin sales.",
    ),
    dict(
        event_id="EV-05", kind="outlier_transactions",
        start="2023-01-01", end="2025-12-31",
        scope={}, magnitude=40.0, metric="quantity",
        description="18 isolated transactions booked at ~40x normal quantity "
                    "(bulk framework deals or keying errors).",
    ),
    dict(
        event_id="EV-06", kind="marketing_overspend",
        start="2025-06-01", end="2025-06-30",
        scope={}, magnitude=2.6, metric="marketing_spend",
        description="June 2025 campaign spends 2.6x budget with no measurable "
                    "revenue response in the same or following month.",
    ),
    dict(
        event_id="EV-07", kind="opex_step",
        start="2025-01-01", end="2025-12-31",
        scope={"expense_category": "Rent & Facilities"}, magnitude=1.42,
        metric="operating_expense",
        description="New headquarters lease steps facilities cost up 42% from "
                    "January 2025 onward - a level shift, not a spike.",
    ),
]


def _in_window(d: date, ev: dict) -> bool:
    return date.fromisoformat(ev["start"]) <= d <= date.fromisoformat(ev["end"])


def _event(event_id: str) -> dict:
    return next(e for e in INJECTED_EVENTS if e["event_id"] == event_id)


# --------------------------------------------------------------------------
# Dimension builders
# --------------------------------------------------------------------------
def build_products(rng: np.random.Generator) -> pd.DataFrame:
    rows, pid = [], 1
    for cat, spec in CATEGORIES.items():
        lo, hi = spec["price"]
        for k in range(spec["n_products"]):
            # log-uniform price so each category keeps a realistic long tail
            price = round(float(np.exp(rng.uniform(np.log(lo), np.log(hi)))), 2)
            margin = float(np.clip(rng.normal(spec["margin"], 0.05), 0.05, 0.88))
            launch = START_DATE
            if rng.random() < 0.25:
                launch = START_DATE + timedelta(days=int(rng.integers(0, 200)))
            rows.append(dict(
                product_id=f"PRD-{pid:04d}",
                product_name=f"{cat.split()[0]} {chr(65 + k)}{rng.integers(100, 999)}",
                product_category=cat,
                list_price=price,
                base_unit_cost=round(price * (1 - margin), 2),
                launch_date=launch.isoformat(),
            ))
            pid += 1
    return pd.DataFrame(rows)


def build_customers(rng: np.random.Generator) -> pd.DataFrame:
    total_days = (END_DATE - START_DATE).days
    rows = []
    for i in range(1, N_CUSTOMERS + 1):
        segment = str(rng.choice(SEGMENTS, p=SEGMENT_WEIGHTS))
        region = str(rng.choice(REGIONS, p=REGION_WEIGHTS))
        # 58% of the base exists on day one; the rest are acquired over time
        if rng.random() < 0.58:
            signup = START_DATE
        else:
            signup = START_DATE + timedelta(days=int(rng.integers(1, total_days - 30)))
        # churn risk is higher for small accounts
        churn_p = {"Enterprise": 0.06, "Mid-Market": 0.14, "SMB": 0.27, "Retail": 0.36}[segment]
        if rng.random() < churn_p:
            churn = min(signup + timedelta(days=int(rng.integers(90, total_days))), END_DATE)
        else:
            churn = END_DATE
        # heterogeneous purchasing intensity -> realistic revenue concentration
        intensity = float(rng.lognormal(0.0, 0.85)) * SEGMENT_PROFILE[segment]["activity"]
        rows.append(dict(
            customer_id=f"CUST-{i:05d}",
            customer_segment=segment,
            region=region,
            signup_date=signup.isoformat(),
            churn_date=churn.isoformat() if churn < END_DATE else "",
            _signup=signup, _churn=churn, _intensity=intensity,
        ))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Transaction ledger
# --------------------------------------------------------------------------
def _daily_expected_volume(d: date) -> float:
    t = (d - START_DATE).days / 365.25
    trend = (1 + ANNUAL_REVENUE_GROWTH) ** t
    return BASE_TXNS_PER_DAY * trend * MONTH_INDEX[d.month] * DOW_INDEX[d.weekday()]


def build_transactions(products: pd.DataFrame, customers: pd.DataFrame,
                       rng: np.random.Generator) -> pd.DataFrame:
    ev_drop = _event("EV-02")
    ev_cost = _event("EV-01")
    ev_disc = _event("EV-03")
    ev_price = _event("EV-04")

    cat_names = list(CATEGORIES)
    cat_share = np.array([CATEGORIES[c]["share"] for c in cat_names], dtype=float)
    cat_share /= cat_share.sum()

    # Pre-extract per-category numpy arrays: iterating a DataFrame 60k times is
    # the difference between 8 seconds and 4 minutes.
    prod_by_cat = {}
    for c in cat_names:
        sub = products.loc[products.product_category == c]
        prod_by_cat[c] = (sub["product_id"].to_numpy(),
                          sub["list_price"].to_numpy(dtype=float),
                          sub["base_unit_cost"].to_numpy(dtype=float))

    cust_signup = customers["_signup"].to_numpy()
    cust_churn = customers["_churn"].to_numpy()
    cust_intensity = customers["_intensity"].to_numpy(dtype=float)
    cust_id = customers["customer_id"].to_numpy()
    cust_seg = customers["customer_segment"].to_numpy()
    cust_reg = customers["region"].to_numpy()

    records = []
    txn_no = 1
    d = START_DATE
    while d <= END_DATE:
        lam = _daily_expected_volume(d)
        if _in_window(d, ev_drop):
            lam *= ev_drop["magnitude"]
        n = int(rng.poisson(lam))
        if n == 0:
            d += timedelta(days=1)
            continue

        active = (cust_signup <= d) & (cust_churn >= d)
        if not active.any():
            d += timedelta(days=1)
            continue
        w = cust_intensity * active
        w = w / w.sum()
        idx = rng.choice(len(cust_id), size=n, p=w)

        t_years = (d - START_DATE).days / 365.25
        price_drift = (1 + ANNUAL_PRICE_INFLATION) ** t_years
        cost_drift = (1 + ANNUAL_COST_INFLATION) ** t_years
        quarter_end = 0.05 if (d.month % 3 == 0 and d.day >= 20) else 0.0
        black_friday = 0.09 if (d.month == 11 and 20 <= d.day <= 30) else 0.0
        cost_shock = _in_window(d, ev_cost)
        price_shock = _in_window(d, ev_price)
        disc_shock = _in_window(d, ev_disc)

        cats = rng.choice(len(cat_names), size=n, p=cat_share)
        price_noise = rng.normal(1.0, 0.035, n)
        cost_noise = rng.normal(1.0, 0.028, n)
        disc_noise = rng.normal(0.0, 0.025, n)

        for k, j in enumerate(idx):
            segment = cust_seg[j]
            prof = SEGMENT_PROFILE[segment]
            cat = cat_names[int(cats[k])]
            pids, plist, pcost = prod_by_cat[cat]
            p = int(rng.integers(len(pids)))

            qty = int(max(1, round(rng.lognormal(prof["order_mu"], prof["order_sigma"]))))

            unit_price = plist[p] * price_drift * price_noise[k]
            if price_shock and cat == ev_price["scope"]["product_category"]:
                unit_price *= ev_price["magnitude"]

            unit_cost = pcost[p] * cost_drift * cost_noise[k]
            if cost_shock and cat == ev_cost["scope"]["product_category"]:
                unit_cost *= ev_cost["magnitude"]

            discount = prof["base_discount"] + quarter_end + black_friday
            discount += 0.03 if qty >= 10 else 0.0
            discount += 0.03 if qty >= 25 else 0.0
            discount += 0.04 if qty >= 50 else 0.0
            if disc_shock and cust_reg[j] == ev_disc["scope"]["region"]:
                discount += ev_disc["magnitude"]
            discount = float(np.clip(discount + disc_noise[k], 0.0, 0.62))

            records.append((
                f"TXN-{txn_no:07d}", d.isoformat(), cust_id[j], pids[p], cat,
                cust_reg[j], segment, qty, round(float(unit_price), 2),
                round(float(unit_cost), 2), round(discount, 4),
                str(rng.choice(PAYMENT_TYPES, p=PAYMENT_BY_SEGMENT[segment])),
            ))
            txn_no += 1
        d += timedelta(days=1)

    df = pd.DataFrame(records, columns=[
        "transaction_id", "transaction_date", "customer_id", "product_id",
        "product_category", "region", "customer_segment", "quantity",
        "unit_price", "unit_cost", "discount", "payment_type",
    ])

    # EV-05: isolated giant-quantity transactions
    ev_out = _event("EV-05")
    outlier_idx = rng.choice(len(df), size=18, replace=False)
    df.loc[outlier_idx, "quantity"] = (
        df.loc[outlier_idx, "quantity"] * ev_out["magnitude"]).round().astype(int)

    df["revenue"] = (df.quantity * df.unit_price * (1 - df.discount)).round(2)
    df["cost"] = (df.quantity * df.unit_cost).round(2)
    df["profit"] = (df.revenue - df.cost).round(2)
    return df


# --------------------------------------------------------------------------
# Supporting finance extracts
# --------------------------------------------------------------------------
def _month_range() -> pd.DatetimeIndex:
    return pd.date_range(START_DATE, END_DATE, freq="MS")


def build_operating_expenses(txns: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    ev = _event("EV-07")
    monthly_units = (txns.assign(m=pd.to_datetime(txns.transaction_date).dt.to_period("M"))
                     .groupby("m")["quantity"].sum())
    rows = []
    for ts in _month_range():
        t = (ts.date() - START_DATE).days / 365.25
        per = pd.Period(ts, freq="M")
        for cat, spec in OPEX_CATEGORIES.items():
            if cat == "Logistics & Freight":
                amount = float(monthly_units.get(per, 0)) * 2.15
            else:
                amount = spec["base"] * ((1 + spec["growth"]) ** t)
            amount *= float(rng.normal(1.0, spec["noise"]))
            if cat == ev["scope"]["expense_category"] and _in_window(ts.date(), ev):
                amount *= ev["magnitude"]
            rows.append(dict(month=ts.strftime("%Y-%m-01"), expense_category=cat,
                             amount=round(max(amount, 0.0), 2)))
    return pd.DataFrame(rows)


def build_marketing_spend(txns: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    ev = _event("EV-06")
    t = txns.assign(m=pd.to_datetime(txns.transaction_date).dt.strftime("%Y-%m-01"))
    rev = t.groupby(["m", "region"])["revenue"].sum()
    rows = []
    for (m, region), r in rev.items():
        # marketing runs ~8-11% of revenue, allocated across channels
        total = float(r) * float(rng.uniform(0.078, 0.112))
        if _in_window(date.fromisoformat(m), ev):
            total *= ev["magnitude"]
        weights = rng.dirichlet([4.0, 2.2, 2.6, 1.6])
        for ch, wgt in zip(MARKETING_CHANNELS, weights):
            rows.append(dict(month=m, region=region, channel=ch,
                             spend=round(float(total * wgt), 2)))
    return pd.DataFrame(rows).sort_values(["month", "region", "channel"]).reset_index(drop=True)


def build_employee_costs(rng: np.random.Generator) -> pd.DataFrame:
    base_hc = {"Sales": 74, "Engineering": 96, "Support": 58, "Operations": 41,
               "Finance & Admin": 22, "Marketing": 29}
    avg_cost = {"Sales": 9_400, "Engineering": 11_800, "Support": 6_300,
                "Operations": 5_900, "Finance & Admin": 7_600, "Marketing": 8_200}
    rows = []
    for ts in _month_range():
        t = (ts.date() - START_DATE).days / 365.25
        for dept in DEPARTMENTS:
            hc = int(round(base_hc[dept] * (1.14 ** t) + rng.normal(0, 1.2)))
            cost = hc * avg_cost[dept] * (1.045 ** t) * float(rng.normal(1.0, 0.02))
            rows.append(dict(month=ts.strftime("%Y-%m-01"), department=dept,
                             headcount=max(hc, 1), total_cost=round(cost, 2)))
    return pd.DataFrame(rows)


def build_budgets(txns: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Targets set the way a real FP&A team sets them: last year's actual grown
    by a stretch factor, with the first year planned bottom-up."""
    t = txns.assign(m=pd.to_datetime(txns.transaction_date).dt.to_period("M"))
    actual = t.groupby(["m", "region"]).agg(revenue=("revenue", "sum"),
                                            profit=("profit", "sum"))
    rows = []
    for (per, region), row in actual.iterrows():
        key = (per - 12, region)
        if key in actual.index:
            rev_t = actual.loc[key, "revenue"] * float(rng.normal(1.20, 0.05))
            prof_t = actual.loc[key, "profit"] * float(rng.normal(1.22, 0.07))
        else:
            rev_t = row.revenue * float(rng.normal(1.03, 0.09))
            prof_t = row.profit * float(rng.normal(1.05, 0.11))
        rows.append(dict(month=per.to_timestamp().strftime("%Y-%m-01"), region=region,
                         revenue_target=round(float(rev_t), 2),
                         profit_target=round(float(prof_t), 2)))
    return pd.DataFrame(rows).sort_values(["month", "region"]).reset_index(drop=True)


def build_accounts_receivable(txns: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Credit sales only. Payment lag depends on segment, so DSO and aging
    buckets are both meaningful."""
    credit = txns[txns.payment_type.isin(["Net 30 Invoice", "Bank Transfer"])]
    credit = credit.sample(frac=0.62, random_state=SEED)
    lag_mu = {"Enterprise": 3.55, "Mid-Market": 3.35, "SMB": 3.15, "Retail": 2.95}

    inv_dates = pd.to_datetime(credit["transaction_date"])
    terms = np.where(credit["payment_type"].to_numpy() == "Net 30 Invoice", 30, 15)
    mus = np.array([lag_mu[s] for s in credit["customer_segment"]])
    delays = np.minimum(np.round(rng.lognormal(mus, 0.55)), 240).astype(int)
    paid = inv_dates + pd.to_timedelta(delays, unit="D")
    still_open = (paid > pd.Timestamp(END_DATE)) | (rng.random(len(credit)) <= 0.06)

    return pd.DataFrame({
        "invoice_id": [f"INV-{i:06d}" for i in range(1, len(credit) + 1)],
        "transaction_id": credit["transaction_id"].to_numpy(),
        "customer_id": credit["customer_id"].to_numpy(),
        "invoice_date": inv_dates.dt.strftime("%Y-%m-%d").to_numpy(),
        "due_date": (inv_dates + pd.to_timedelta(terms, unit="D")).dt.strftime("%Y-%m-%d").to_numpy(),
        "paid_date": np.where(still_open, "", paid.dt.strftime("%Y-%m-%d").to_numpy()),
        "invoice_amount": credit["revenue"].to_numpy(),
    })


# --------------------------------------------------------------------------
# Data-quality defect injection
# --------------------------------------------------------------------------
def inject_data_quality_issues(df: pd.DataFrame,
                               rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """Degrade a clean ledger into a realistic operational extract.

    Returns the messy frame plus a manifest of what was done, which the tests
    use to confirm the cleaning pipeline recovers the ground truth.
    """
    df = df.copy()
    n = len(df)
    manifest: dict[str, int] = {}

    def pick(frac: float) -> np.ndarray:
        return rng.choice(df.index, size=int(n * frac), replace=False)

    # Columns that will receive dirty strings must tolerate mixed types
    for col in ["transaction_date", "customer_id", "product_category", "region",
                "payment_type", "unit_price", "discount", "revenue", "profit",
                "quantity", "cost", "customer_segment"]:
        df[col] = df[col].astype(object)

    # 1. Stale revenue/profit that no longer reconcile with their components
    idx = pick(0.021)
    df.loc[idx, "revenue"] = (np.asarray(df.loc[idx, "revenue"], dtype=float)
                              * rng.uniform(0.80, 1.25, len(idx))).round(2)
    df.loc[idx, "profit"] = (np.asarray(df.loc[idx, "profit"], dtype=float)
                             * rng.uniform(0.70, 1.35, len(idx))).round(2)
    manifest["stale_derived_values"] = len(idx)

    # 2. Impossible values
    idx = pick(0.004)
    df.loc[idx, "quantity"] = -rng.integers(1, 20, len(idx))
    manifest["negative_quantity"] = len(idx)

    idx = pick(0.0015)
    df.loc[idx, "quantity"] = 0
    manifest["zero_quantity"] = len(idx)

    idx = pick(0.002)
    df.loc[idx, "unit_price"] = -np.asarray(df.loc[idx, "unit_price"], dtype=float)
    manifest["negative_unit_price"] = len(idx)

    idx = pick(0.0025)
    df.loc[idx, "discount"] = rng.choice([1.4, -0.2, 2.0, 1.05], len(idx))
    manifest["out_of_range_discount"] = len(idx)

    # 3. Mixed and broken date formats
    iso = pd.to_datetime(df["transaction_date"], format="%Y-%m-%d")
    idx = pick(0.012)
    df.loc[idx, "transaction_date"] = iso.loc[idx].dt.strftime("%d/%m/%Y").to_numpy()
    manifest["dayfirst_dates"] = len(idx)

    idx = pick(0.006)
    df.loc[idx, "transaction_date"] = iso.loc[idx].dt.strftime("%Y.%m.%d").to_numpy()
    manifest["dotted_dates"] = len(idx)

    idx = pick(0.003)
    df.loc[idx, "transaction_date"] = rng.choice(["N/A", "", "unknown", "0000-00-00"], len(idx))
    manifest["unparseable_dates"] = len(idx)

    idx = pick(0.002)
    df.loc[idx, "transaction_date"] = [
        (date(2027, 1, 1) + timedelta(days=int(k))).isoformat()
        for k in rng.integers(0, 400, len(idx))
    ]
    manifest["future_dates"] = len(idx)

    # 4. Currency / thousands-separator strings in numeric columns
    idx = pick(0.030)
    df.loc[idx, "unit_price"] = ["$" + f"{v:,.2f}"
                                 for v in np.asarray(df.loc[idx, "unit_price"], dtype=float)]
    manifest["currency_string_prices"] = len(idx)

    idx = pick(0.022)
    df.loc[idx, "revenue"] = [f"{v:,.2f}"
                              for v in np.asarray(df.loc[idx, "revenue"], dtype=float)]
    manifest["comma_separated_revenue"] = len(idx)

    idx = pick(0.010)
    df.loc[idx, "discount"] = [f"{v * 100:.1f}%"
                               for v in np.asarray(df.loc[idx, "discount"], dtype=float)]
    manifest["percent_string_discount"] = len(idx)

    # 5. Inconsistent categorical spellings
    region_variants = {
        "North America": ["north america", "NORTH AMERICA", "N. America", " North America ", "NA"],
        "Europe": ["europe", "EUROPE", "EMEA", " Europe"],
        "APAC": ["apac", "Asia-Pacific", "ASIA PACIFIC", "Apac "],
        "LATAM": ["latam", "Latin America", "LATIN AMERICA"],
        "Middle East": ["middle east", "MIDDLE EAST", "M. East", "MiddleEast"],
    }
    idx = pick(0.085)
    df.loc[idx, "region"] = [str(rng.choice(region_variants[r])) for r in df.loc[idx, "region"]]
    manifest["region_variants"] = len(idx)

    idx = pick(0.055)
    df.loc[idx, "product_category"] = [
        str(rng.choice([c.upper(), c.lower(), c.replace(" ", "_"), f"  {c} "]))
        for c in df.loc[idx, "product_category"]
    ]
    manifest["category_variants"] = len(idx)

    pay_variants = {
        "Credit Card": ["CC", "credit card", "CREDIT_CARD", "Creditcard"],
        "Bank Transfer": ["bank transfer", "BANK_TRANSFER", "Wire", "wire transfer"],
        "Net 30 Invoice": ["net30", "NET 30", "Invoice", "net 30 invoice"],
        "Digital Wallet": ["digital wallet", "E-Wallet", "DIGITAL_WALLET", "wallet"],
        "Cash": ["cash", "CASH", "Cash "],
    }
    idx = pick(0.070)
    df.loc[idx, "payment_type"] = [str(rng.choice(pay_variants[p]))
                                   for p in df.loc[idx, "payment_type"]]
    manifest["payment_variants"] = len(idx)

    # 6. Inconsistent customer identifier formats
    idx = pick(0.060)
    restyled = []
    for cid in df.loc[idx, "customer_id"]:
        num = int(str(cid).split("-")[1])
        restyled.append(str(rng.choice([f"cust{num:05d}", f"C{num}", f" {cid} ",
                                        str(cid).lower(), f"CUST_{num:05d}"])))
    df.loc[idx, "customer_id"] = restyled
    manifest["customer_id_variants"] = len(idx)

    # 7. Missing values
    for col, frac in [("customer_id", 0.008), ("region", 0.014), ("unit_price", 0.007),
                      ("cost", 0.011), ("payment_type", 0.019), ("discount", 0.009),
                      ("product_category", 0.006), ("customer_segment", 0.012)]:
        idx = pick(frac)
        df.loc[idx, col] = np.nan
        manifest[f"missing_{col}"] = len(idx)

    # 8. Duplicates - exact re-exports and re-keyed near-duplicates
    exact = df.loc[rng.choice(df.index, size=int(n * 0.018), replace=False)].copy()
    manifest["exact_duplicates"] = len(exact)

    near = df.loc[rng.choice(df.index, size=int(n * 0.007), replace=False)].copy()
    near["transaction_id"] = [f"TXN-9{i:06d}" for i in range(len(near))]
    manifest["near_duplicates"] = len(near)

    out = pd.concat([df, exact, near], ignore_index=True)
    out = out.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    manifest["rows_written"] = len(out)
    return out, manifest


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    rng = np.random.default_rng(SEED)
    print("Generating reference dimensions ...")
    products = build_products(rng)
    customers = build_customers(rng)

    print("Generating transaction ledger ...")
    txns = build_transactions(products, customers, rng)
    print(f"  {len(txns):,} clean transactions | "
          f"revenue {txns.revenue.sum():,.0f} | profit {txns.profit.sum():,.0f}")

    print("Generating supporting finance extracts ...")
    opex = build_operating_expenses(txns, rng)
    marketing = build_marketing_spend(txns, rng)
    payroll = build_employee_costs(rng)
    budgets = build_budgets(txns, rng)
    ar = build_accounts_receivable(txns, rng)

    print("Injecting data-quality defects ...")
    messy, manifest = inject_data_quality_issues(txns, rng)

    messy.to_csv(config.RAW_TRANSACTIONS, index=False)
    products.to_csv(config.RAW_PRODUCTS, index=False)
    (customers.drop(columns=[c for c in customers.columns if c.startswith("_")])
              .to_csv(config.RAW_CUSTOMERS, index=False))
    opex.to_csv(config.RAW_OPEX, index=False)
    marketing.to_csv(config.RAW_MARKETING, index=False)
    payroll.to_csv(config.RAW_HEADCOUNT, index=False)
    budgets.to_csv(config.RAW_BUDGETS, index=False)
    ar.to_csv(config.RAW_AR, index=False)

    config.INJECTED_EVENTS.write_text(json.dumps(
        {"events": INJECTED_EVENTS, "data_quality_manifest": manifest}, indent=2))

    print(f"\nWrote {len(messy):,} raw transaction rows to {config.RAW_TRANSACTIONS.name}")
    print("Injected data-quality defects:")
    for k, v in manifest.items():
        print(f"  {k:<32} {v:>7,}")


if __name__ == "__main__":
    main()
