"""Load, run and export the SQL query library in sql/analysis_queries.sql.

Keeping the SQL in a .sql file rather than in Python string literals means the
queries stay readable, diffable and runnable in any database client - and the
Python here is a thin runner rather than a place where the analysis hides.

Run with:  python -m src.sql_analysis          (runs everything, exports CSVs)
           python -m src.sql_analysis top_customers   (runs one, prints it)
"""
from __future__ import annotations

import re
import sys

import pandas as pd

from src import config
from src.db_load import get_engine, query

RESULTS_DIR = config.REPORTS_DIR / "sql_results"
QUERY_FILE = config.SQL_DIR / "analysis_queries.sql"


def load_queries(path=QUERY_FILE) -> dict[str, dict[str, str]]:
    """Parse the query library into {name: {"description":..., "sql":...}}."""
    text = path.read_text()
    blocks = re.split(r"^-- name:\s*", text, flags=re.MULTILINE)[1:]
    queries: dict[str, dict[str, str]] = {}
    for block in blocks:
        lines = block.splitlines()
        name = lines[0].strip()
        desc_lines, sql_lines, in_desc = [], [], False
        for line in lines[1:]:
            if line.startswith("-- description:"):
                in_desc = True
                desc_lines.append(line.split(":", 1)[1].strip())
            elif in_desc and line.startswith("--"):
                desc_lines.append(line.lstrip("- ").strip())
            else:
                in_desc = False
                sql_lines.append(line)
        sql = "\n".join(sql_lines).strip()
        # Drop the trailing semicolon: DBAPI drivers take one statement, and
        # some reject the terminator.
        queries[name] = {"description": " ".join(desc_lines).strip(),
                         "sql": sql.rstrip().rstrip(";")}
    return queries


def run_named(name: str, engine=None) -> pd.DataFrame:
    """Execute one named query and return its result."""
    queries = load_queries()
    if name not in queries:
        raise KeyError(f"Unknown query '{name}'. Available: {', '.join(sorted(queries))}")
    return query(queries[name]["sql"], engine)


def run_all(export: bool = True, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Execute every query in the library, optionally exporting each to CSV."""
    engine = get_engine()
    queries = load_queries()
    results: dict[str, pd.DataFrame] = {}
    if export:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Running {len(queries)} queries from {QUERY_FILE.name}\n")
    for name, spec in queries.items():
        df = query(spec["sql"], engine)
        results[name] = df
        if export:
            df.to_csv(RESULTS_DIR / f"{name}.csv", index=False)
        if verbose:
            print(f"  {name:<34} {len(df):>6,} rows x {df.shape[1]:>2} cols")

    if verbose and export:
        print(f"\nResults exported to {RESULTS_DIR.relative_to(config.ROOT)}/")
    return results


def catalogue() -> pd.DataFrame:
    """The query library as a browsable table - used by the dashboard."""
    return pd.DataFrame([{"query": n, "description": s["description"]}
                         for n, s in load_queries().items()])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pd.set_option("display.width", 200, "display.max_columns", 50)
        result = run_named(sys.argv[1])
        print(result.to_string(index=False))
    else:
        run_all()
