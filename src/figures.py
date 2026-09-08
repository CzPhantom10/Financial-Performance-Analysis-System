"""Render the report figures as static PNGs.

The dashboard is the interactive deliverable; this module produces the static
versions that go into the written report, the README and any slide deck -
generated from the same artefacts, so they cannot drift from the analysis.

Matplotlib rather than Plotly here on purpose: Plotly's static export needs
Kaleido and a browser engine, which is a heavy dependency for something whose
only job is to write a PNG.

Run with:  python -m src.figures
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # no display needed; must be set before pyplot import

import json  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.clean_pipeline import load_clean  # noqa: E402

PALETTE = ["#3D6E9C", "#E08A3C", "#4C9F70", "#B0446C", "#7C6D9E",
           "#C2A03A", "#5FA0AE", "#8C6D4F"]
GOOD, BAD, GREY = "#2E8B57", "#C0392B", "#7F8C8D"

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "600",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.7,
    "legend.frameon": False,
})


def _millions(ax) -> None:
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}M"))


def _save(fig, name: str) -> str:
    path = config.FIGURES_DIR / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    return name


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
def fig_revenue_trend(monthly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(monthly.month_start, monthly.revenue, width=22,
           color=PALETTE[0], alpha=0.55, label="Monthly revenue")
    ax.plot(monthly.month_start, monthly.revenue.rolling(3).mean(),
            color=PALETTE[1], linewidth=2.6, label="3-month moving average")
    ax.set_title("Monthly revenue and 3-month moving average")
    ax.set_ylabel("Revenue")
    _millions(ax)
    ax.legend(loc="upper left")
    return _save(fig, "01_revenue_trend")


def fig_margin_decline(monthly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(monthly.month_start, monthly.profit_margin_pct, color=PALETTE[0],
            linewidth=2, marker="o", markersize=3.5, label="Gross margin %")

    x = np.arange(len(monthly))
    slope, intercept = np.polyfit(x, monthly.profit_margin_pct, 1)
    ax.plot(monthly.month_start, intercept + slope * x, color=BAD,
            linestyle="--", linewidth=2,
            label=f"Linear trend ({slope * 12:+.2f} pp/year)")
    ax.set_title("Gross margin is declining structurally")
    ax.set_ylabel("Gross margin (%)")
    ax.legend()
    return _save(fig, "02_margin_decline")


def fig_cost_vs_revenue_growth(df: pd.DataFrame) -> str:
    yearly = (df.groupby("year")
                .agg(revenue=("revenue", "sum"), cost=("cost", "sum"))
                .reset_index())
    yearly["revenue_growth"] = yearly.revenue.pct_change() * 100
    yearly["cost_growth"] = yearly.cost.pct_change() * 100
    yearly = yearly.dropna()

    fig, ax = plt.subplots(figsize=(7, 4.2))
    width = 0.36
    x = np.arange(len(yearly))
    ax.bar(x - width / 2, yearly.revenue_growth, width, color=PALETTE[0],
           label="Revenue growth")
    ax.bar(x + width / 2, yearly.cost_growth, width, color=BAD,
           label="Cost growth")
    for i, row in enumerate(yearly.itertuples()):
        ax.text(i - width / 2, row.revenue_growth + 0.4,
                f"{row.revenue_growth:.1f}%", ha="center", fontsize=9)
        ax.text(i + width / 2, row.cost_growth + 0.4,
                f"{row.cost_growth:.1f}%", ha="center", fontsize=9)
    ax.set_xticks(x, yearly.year.astype(int).astype(str))
    ax.set_title("Cost is growing faster than revenue, every year")
    ax.set_ylabel("Year-on-year growth (%)")
    ax.legend()
    return _save(fig, "03_cost_vs_revenue_growth")


def fig_seasonal_index() -> str | None:
    path = config.REPORTS_DIR / "timeseries_analysis.json"
    if not path.exists():
        return None
    idx = pd.DataFrame(json.loads(path.read_text())["seasonality"]["seasonal_index"])

    fig, ax = plt.subplots(figsize=(10, 4))
    colours = [GOOD if v >= 0 else BAD for v in idx.pct_vs_average]
    ax.bar(idx.month_name, idx.pct_vs_average, color=colours, alpha=0.85)
    ax.axhline(0, color=GREY, linewidth=1)
    for i, v in enumerate(idx.pct_vs_average):
        ax.text(i, v + (1.2 if v >= 0 else -2.4), f"{v:+.0f}%", ha="center",
                fontsize=8.5)
    ax.set_title("Seasonal index: typical deviation from trend by month")
    ax.set_ylabel("% vs trend")
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    return _save(fig, "04_seasonal_index")


def fig_discount_vs_margin(df: pd.DataFrame) -> str:
    bands = pd.cut(df.discount, [-0.001, 0.0001, 0.05, 0.10, 0.15, 0.25, 0.40, 1.01],
                   labels=["0%", "0-5%", "5-10%", "10-15%", "15-25%",
                           "25-40%", "40%+"])
    summary = (df.assign(band=bands).groupby("band", observed=True)
                 .agg(revenue=("revenue", "sum"), profit=("profit", "sum"))
                 .reset_index())
    summary["margin"] = summary.profit / summary.revenue * 100

    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.bar(summary.band.astype(str), summary.revenue, color=PALETTE[0],
           alpha=0.5, label="Revenue")
    _millions(ax)
    ax.set_ylabel("Revenue")

    ax2 = ax.twinx()
    ax2.plot(summary.band.astype(str), summary.margin, color=BAD, linewidth=2.6,
             marker="o", markersize=7, label="Realised margin %")
    ax2.axhline(0, color=GREY, linewidth=1, linestyle=":")
    ax2.set_ylabel("Profit margin (%)")
    ax2.grid(False)

    # The margin line runs across the top-left, so the legend goes above the
    # axes rather than on top of the series it is describing.
    ax.set_title("Realised margin falls monotonically as discount deepens", pad=28)
    handles = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 1.005),
              ncols=2)
    return _save(fig, "05_discount_vs_margin")


def fig_customer_concentration(df: pd.DataFrame) -> str:
    per_customer = (df[df.is_customer_attributed]
                    .groupby("customer_id")["revenue"].sum()
                    .sort_values(ascending=False))
    cumulative = per_customer.cumsum() / per_customer.sum() * 100
    share = np.arange(1, len(per_customer) + 1) / len(per_customer) * 100

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(share, cumulative, color=PALETTE[0], linewidth=2.6, label="Actual")
    ax.fill_between(share, cumulative, alpha=0.15, color=PALETTE[0])
    ax.plot([0, 100], [0, 100], color=GREY, linestyle="--", linewidth=1.4,
            label="Perfectly even distribution")

    at20 = float(np.interp(20, share, cumulative))
    ax.axvline(20, color=BAD, linestyle=":", linewidth=1.6)
    ax.annotate(f"Top 20% of customers\n= {at20:.0f}% of revenue",
                xy=(20, at20), xytext=(34, at20 - 26),
                arrowprops=dict(arrowstyle="->", color=BAD, linewidth=1.3),
                fontsize=9.5, color=BAD)

    ax.set_title("Revenue concentration (Lorenz curve)")
    ax.set_xlabel("% of customers, largest first")
    ax.set_ylabel("% of cumulative revenue")
    ax.legend(loc="lower right")
    return _save(fig, "06_customer_concentration")


def fig_category_profitability(df: pd.DataFrame) -> str:
    cat = (df.groupby("product_category")
             .agg(revenue=("revenue", "sum"), profit=("profit", "sum"))
             .reset_index())
    cat["margin"] = cat.profit / cat.revenue * 100
    cat["revenue_share"] = cat.revenue / cat.revenue.sum() * 100
    cat["profit_share"] = cat.profit / cat.profit.sum() * 100
    cat = cat.sort_values("margin")

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    y = np.arange(len(cat))
    height = 0.38
    ax.barh(y + height / 2, cat.revenue_share, height, color=PALETTE[0],
            label="% of revenue")
    ax.barh(y - height / 2, cat.profit_share, height, color=PALETTE[2],
            label="% of profit")
    ax.set_yticks(y, [f"{c}\n({m:.0f}% margin)"
                      for c, m in zip(cat.product_category, cat.margin)],
                  fontsize=8.5)
    ax.set_xlabel("Share (%)")
    ax.set_title("Revenue share against profit share by category")
    ax.legend(loc="lower right")
    return _save(fig, "07_category_profitability")


def fig_anomaly_timeline() -> str | None:
    path = config.PROCESSED_DIR / "anomalies.csv"
    if not path.exists():
        return None
    anomalies = pd.read_csv(path)
    anomalies["period_ts"] = pd.to_datetime(anomalies.period, errors="coerce")
    dated = anomalies.dropna(subset=["period_ts"])
    if "material" in dated:
        dated = dated[dated.material]
    if dated.empty:
        return None

    colours = {"Critical": "#B03A2E", "High": "#D68910",
               "Medium": "#5D6D7E", "Low": "#95A5A6"}
    fig, ax = plt.subplots(figsize=(11, 4.4))
    for severity, group in dated.groupby("severity"):
        ax.scatter(group.period_ts, group.score,
                   s=np.clip(group.score.abs() * 14, 25, 320),
                   color=colours.get(severity, GREY), alpha=0.72,
                   edgecolors="white", linewidths=0.6, label=severity)
    ax.axhline(0, color=GREY, linewidth=1)
    ax.set_title("Material anomalies over time (bubble size = |z|)")
    ax.set_ylabel("z-score (signed)")
    ax.legend(title="Severity", loc="lower left", ncols=4)
    return _save(fig, "08_anomaly_timeline")


def fig_seasonal_decomposition() -> str | None:
    path = config.PROCESSED_DIR / "seasonal_components.csv"
    if not path.exists():
        return None
    c = pd.read_csv(path, parse_dates=["month_start"])

    fig, axes = plt.subplots(3, 1, figsize=(10.5, 7), sharex=True)
    axes[0].plot(c.month_start, c.observed, color=PALETTE[0], linewidth=1.8)
    axes[0].set_title("Observed revenue")
    _millions(axes[0])

    axes[1].plot(c.month_start, c.stl_trend, color=PALETTE[2], linewidth=2.4)
    axes[1].set_title("Trend component")
    _millions(axes[1])

    axes[2].plot(c.month_start, c.stl_seasonal, color=PALETTE[1], linewidth=1.8)
    axes[2].axhline(1.0, color=GREY, linewidth=1, linestyle=":")
    axes[2].set_title("Seasonal component (multiplicative)")

    fig.suptitle("STL decomposition of monthly revenue", y=0.995,
                 fontsize=13, fontweight="600")
    fig.tight_layout()
    return _save(fig, "09_seasonal_decomposition")


def fig_transaction_distribution(df: pd.DataFrame) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    axes[0].hist(df.revenue, bins=80, range=(0, df.revenue.quantile(0.98)),
                 color=PALETTE[0], alpha=0.85)
    axes[0].set_title("Transaction value (linear scale)")
    axes[0].set_xlabel("Revenue ($)")
    axes[0].set_ylabel("Transactions")

    positive = df.revenue[df.revenue > 0]
    axes[1].hist(np.log10(positive), bins=80, color=PALETTE[2], alpha=0.85)
    axes[1].set_title("Transaction value (log scale)")
    axes[1].set_xlabel("log10 revenue ($)")

    fig.suptitle("Transaction values are lognormal - which is why the outlier "
                 "fences are computed on the log scale", fontsize=11, y=1.02)
    fig.tight_layout()
    return _save(fig, "10_transaction_distribution")


# --------------------------------------------------------------------------
def build_all(verbose: bool = True) -> list[str]:
    df = load_clean()
    monthly = (df.groupby("month_start")
                 .agg(revenue=("revenue", "sum"), profit=("profit", "sum"),
                      cost=("cost", "sum"))
                 .reset_index().sort_values("month_start"))
    monthly["profit_margin_pct"] = monthly.profit / monthly.revenue * 100

    built = [
        fig_revenue_trend(monthly),
        fig_margin_decline(monthly),
        fig_cost_vs_revenue_growth(df),
        fig_seasonal_index(),
        fig_discount_vs_margin(df),
        fig_customer_concentration(df),
        fig_category_profitability(df),
        fig_anomaly_timeline(),
        fig_seasonal_decomposition(),
        fig_transaction_distribution(df),
    ]
    built = [b for b in built if b]
    if verbose:
        print(f"Wrote {len(built)} figures to "
              f"{config.FIGURES_DIR.relative_to(config.ROOT)}/")
        for name in built:
            print(f"  {name}.png")
    return built


if __name__ == "__main__":
    build_all()
