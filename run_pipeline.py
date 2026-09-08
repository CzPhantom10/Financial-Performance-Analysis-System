"""End-to-end pipeline runner.

Executes every stage in dependency order, from raw data generation through to
the written business report, so the whole project reproduces from a clean
checkout with one command.

    python run_pipeline.py                 # everything
    python run_pipeline.py --skip-generate # keep the existing raw data
    python run_pipeline.py --stage clean   # run a single stage

Stages:
    generate  -> data/raw/*.csv                       (synthetic source extracts)
    clean     -> data/processed/transactions_clean.csv (+ rejects, audit log)
    database  -> data/finance.db                       (star schema, views)
    sql       -> reports/sql_results/*.csv             (query library output)
    kpi       -> reports/kpi_summary.json
    stats     -> reports/statistical_analysis.json
    timeseries-> reports/timeseries_analysis.json
    anomaly   -> reports/anomaly_report.json
    figures   -> reports/figures/*.png
    report    -> reports/business_insights_report.md
"""
from __future__ import annotations

import argparse
import time
import traceback

STAGES = ["generate", "clean", "database", "sql", "kpi", "stats",
          "timeseries", "anomaly", "figures", "report"]


def _run_stage(name: str) -> None:
    if name == "generate":
        from src.generate_data import main
        main()
    elif name == "clean":
        from src.clean_pipeline import run
        run()
    elif name == "database":
        from src.db_load import load
        load()
    elif name == "sql":
        from src.sql_analysis import run_all
        run_all()
    elif name == "kpi":
        from src.kpi import run_all
        run_all()
    elif name == "stats":
        from src.stats_analysis import run_all
        run_all()
    elif name == "timeseries":
        from src.timeseries import run_all
        run_all()
    elif name == "anomaly":
        from src.anomaly import run_all
        run_all()
    elif name == "figures":
        from src.figures import build_all
        build_all()
    elif name == "report":
        from src.report import build_report
        build_report()
    else:
        raise ValueError(f"Unknown stage: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=STAGES,
                        help="run a single stage instead of the whole pipeline")
    parser.add_argument("--skip-generate", action="store_true",
                        help="reuse the existing raw data rather than regenerating it")
    args = parser.parse_args()

    stages = [args.stage] if args.stage else list(STAGES)
    if args.skip_generate and "generate" in stages and not args.stage:
        stages.remove("generate")

    total_start = time.perf_counter()
    failures = []
    for i, stage in enumerate(stages, start=1):
        print("\n" + "#" * 78)
        print(f"# STAGE {i}/{len(stages)}: {stage}")
        print("#" * 78 + "\n")
        start = time.perf_counter()
        try:
            _run_stage(stage)
            print(f"\n-> {stage} finished in {time.perf_counter() - start:.1f}s")
        except Exception:
            failures.append(stage)
            print(f"\n!! {stage} FAILED after {time.perf_counter() - start:.1f}s")
            traceback.print_exc()
            # Later stages read this stage's output, so continuing would only
            # produce a second, more confusing failure.
            break

    elapsed = time.perf_counter() - total_start
    print("\n" + "=" * 78)
    if failures:
        print(f"PIPELINE FAILED at stage '{failures[0]}' after {elapsed:.1f}s")
        return 1
    print(f"PIPELINE COMPLETE - {len(stages)} stages in {elapsed:.1f}s")
    print("=" * 78)
    print("\nNext: launch the dashboard with")
    print("    python -m src.api        (then open http://127.0.0.1:8000)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
