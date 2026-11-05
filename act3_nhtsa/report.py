"""Act 3, step 3: compare the labels against NHTSA ground truth, in DuckDB SQL.

Everything measured here is plain SQL in report.sql; this script just wires the
data together and prints each query with its result, so the whole thing reads on
a projector. Ground truth is the dataset's own fields:

  * component     -> the simplified group of COMPDESC (groups.group_of)
  * safety_flag   -> CRASH='Y' OR FIRE='Y' OR INJURED>0
  * severity cue  -> the same flags (a real incident should score high)

    uv run act3_nhtsa/report.py              # all models that have labels
    uv run act3_nhtsa/report.py --model kev:4b

Reads the local-only sample + data/labels.duckdb, so it runs offline after a
`label.py --replay` pass with no big download.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from groups import GROUPS, group_of  # noqa: E402

SAMPLE_PATH = HERE / "sample_300.csv"
LABELS_DB = HERE.parent / "data" / "labels.duckdb"
REPORT_SQL = HERE / "report.sql"


def show(con: duckdb.DuckDBPyConnection, title: str, sql: str) -> None:
    """Print a titled query and its result table, SQL visible on screen."""
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}")
    print(sql.strip())
    print()
    print(con.sql(sql))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", help="restrict the report to one model")
    args = ap.parse_args()

    if not LABELS_DB.exists():
        sys.exit(f"no {LABELS_DB}; run label.py first")

    con = duckdb.connect(":memory:")
    # Ground-truth component group is computed in Python (the mapping lives in
    # groups.py), materialised as a tiny lookup table the SQL can join to.
    con.execute("CREATE TABLE complaints AS "
                f"SELECT * FROM read_csv('{SAMPLE_PATH.as_posix()}', header=true)")
    truth = con.execute("SELECT CMPLID, COMPDESC, CRASH, FIRE, INJURED FROM complaints").fetchall()
    con.execute("CREATE TABLE truth (cmplid VARCHAR, truth_group VARCHAR, truth_safety BOOLEAN)")
    con.executemany("INSERT INTO truth VALUES (?,?,?)", [
        [c, group_of(cd), (crash == "Y") or (fire == "Y") or (int(inj or 0) > 0)]
        for c, cd, crash, fire, inj in truth
    ])
    con.execute(f"ATTACH '{LABELS_DB.as_posix()}' AS lab (READ_ONLY)")

    # DuckDB views cannot bind parameters: materialise the safely bound filter.
    con.execute("CREATE TEMP TABLE selected_labels AS SELECT * FROM lab.labels WHERE (? IS NULL OR model = ?)",
                [args.model, args.model])
    # The joined view every report.sql macro reads from.
    con.execute(f"""
        CREATE VIEW scored AS
        SELECT l.model, l.cmplid, t.truth_group, l.pred_group, l.comp_conf,
               l.safety_critical, t.truth_safety, l.severity, l.sev_conf,
               l.min_conf, l.latency_ms
        FROM selected_labels l
        JOIN truth t USING (cmplid)
    """)

    models = [r[0] for r in con.execute("SELECT DISTINCT model FROM scored ORDER BY model").fetchall()]
    if not models:
        sys.exit("no labels match; run label.py for a model first")
    print(f"models in report: {', '.join(models)}")
    print(f"component groups ({len(GROUPS)}): {', '.join(GROUPS)}")

    con.execute(REPORT_SQL.read_text())  # defines the q_* macros

    show(con, "1. Headline agreement vs ground truth", "SELECT * FROM q_headline()")
    show(con, "2. Component agreement by confidence band "
              "(does agreement rise with confidence?)", "SELECT * FROM q_by_confidence()")
    show(con, "3. Needs-human-review bucket at Gate=0.35 "
              "(min confidence across the 3 answers)", "SELECT * FROM q_review_bucket(0.35)")
    show(con, "4. KEY INSIGHT: auto-accept share vs auto-accepted accuracy, "
              "swept over the Gate", "SELECT * FROM q_gate_sweep()")

    print("\nGround-truth notes: 'component' agreement is against a coarse COMPDESC "
          "mapping (NHTSA's own category is itself consumer-entered and noisy); "
          "'safety' truth is CRASH/FIRE/INJURED, which under-counts near-misses.")
    con.close()


if __name__ == "__main__":
    main()
