"""Act 3, step 2: label NHTSA complaint narratives with one Decider call each.

For every complaint we ask THREE typed questions about the narrative State:

  * Choice  `component`       -> one of ~10 simplified component groups
  * Noul    `safety_critical` -> could this defect cause a crash, fire or injury
  * Score   `severity`        -> a 4-level ordered rubric

The answer (label + probabilities + confidence + model + latency) is written
back into a DuckDB `labels` table. One row in, one typed row out: no text.

    uv run act3_nhtsa/label.py --model laya:typed-decisions
    uv run act3_nhtsa/label.py --model kev:0.8b --limit 50
    uv run act3_nhtsa/label.py --model laya:typed-decisions --replay   # offline

Without the big data/nhtsa.duckdb present (or with --replay) we label the
local-only act3_nhtsa/sample_300.csv in a temporary in-memory DuckDB, after the optional data download.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
from typesafe_sdk import Choice, Noul, Score

from dm import Decider, DecisionError, certainty, common_parser, parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groups import GROUPS, group_of  # noqa: E402

HERE = Path(__file__).resolve().parent
DB_PATH = HERE.parent / "data" / "nhtsa.duckdb"
SAMPLE_PATH = HERE / "sample_300.csv"

# Per-model character budget for the State (the narrative). The window is in
# tokens (~4 chars each) and the three questions also cost tokens, so we cut
# the narrative in CODE well short of the raw window and never rely on the
# server to truncate (it returns 422 STATE_TRUNCATED rather than guessing).
#   laya:typed-decisions -> 1024-token window
#   kev:0.8b / kev:4b    -> 8192-token window
CHAR_BUDGET = {
    "laya:typed-decisions": 1500,
    "laya:multilingual": 1500,
    "laya:en": 1200,
    "kev:0.8b": 6000,
    "kev:4b": 6000,
}
DEFAULT_BUDGET = 1500

# The three typed questions. Built once; the same object is reused every row.
QUESTIONS = {
    "component": Choice(
        instructions="Which vehicle component does this complaint describe?",
        criteria=GROUPS,
    ),
    "safety_critical": Noul(
        instructions="This defect could cause a crash, a fire, or an injury.",
    ),
    "severity": Score(
        instructions="How severe is the problem described?",
        criteria=[
            "Annoyance, no safety impact",       # 0
            "Degraded function, inconvenient",   # 1
            "Could strand or endanger the driver",  # 2
            "Crash, fire or injury risk",        # 3
        ],
    ),
}


def budget_for(model: str) -> int:
    return CHAR_BUDGET.get(model, DEFAULT_BUDGET)


def load_rows(con: duckdb.DuckDBPyConnection, limit: int | None) -> list[tuple]:
    sql = """
        SELECT CMPLID, MAKETXT, COMPDESC, CDESCR,
               CRASH, FIRE, INJURED, DEATHS
        FROM complaints
        ORDER BY CMPLID
    """
    if limit:
        sql += f" LIMIT {limit}"
    return con.execute(sql).fetchall()


def open_source() -> duckdb.DuckDBPyConnection:
    """Label the local-only 300-row sample, always.

    Labelling the SAME rows live and in replay is what makes `--replay` produce
    byte-identical output: the only thing that changes between the two is where
    the Decider's answers come from (the server vs fixtures/act3.jsonl). The big
    data/nhtsa.duckdb is only the source fetch_data.py cut the sample from; it is
    never scored directly, and is excluded from public distribution.
    """
    if not SAMPLE_PATH.exists():
        sys.exit(f"no {SAMPLE_PATH}; run fetch_data.py first")
    print(f"source: {SAMPLE_PATH} (300-row sample, in-memory DuckDB)")
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE TABLE complaints AS SELECT * FROM read_csv('{SAMPLE_PATH.as_posix()}', header=true)"
    )
    return con


def main() -> None:
    p = common_parser(__doc__)
    p.add_argument("--limit", type=int, default=None, help="label only the first N rows")
    p.add_argument("--workers", type=int, default=4, help="parallel Decider calls (politely small)")
    args = parse(p)

    con = open_source()
    rows = load_rows(con, args.limit)
    budget = budget_for(args.model)
    decider = Decider("act3", model=args.model)

    print(f"model: {args.model}   rows: {len(rows)}   char budget: {budget}   "
          f"{'REPLAY' if args.replay else 'LIVE'}\n")

    results: list[dict] = []
    agree = 0          # running component-group agreement vs ground truth
    done = 0
    truncated = 0
    errors = 0
    t0 = time.perf_counter()

    def work(row: tuple) -> dict | None:
        cmplid, make, compdesc, cdescr, crash, fire, injured, deaths = row
        state = cdescr or ""
        was_cut = len(state) > budget
        if was_cut:
            state = state[:budget]            # cut in CODE, not on the server
        try:
            d = decider.decide(state, QUESTIONS)
        except DecisionError as exc:
            return {"cmplid": cmplid, "error": str(exc)[:80], "cut": was_cut}
        comp = d["component"]
        sev = d["severity"]
        noul = d["safety_critical"]
        return {
            "cmplid": cmplid, "make": make, "compdesc": compdesc,
            "truth_group": group_of(compdesc),
            "pred_group": comp["choice"], "comp_conf": comp["confidence"],
            "comp_probs": comp["probabilities"],
            "safety_critical": noul["noul"],
            "severity": sev["score"], "sev_conf": sev["confidence"],
            "min_conf": min(certainty(comp), certainty(sev), certainty(noul)),
            "latency_ms": d.latency_ms, "model": d.model, "cached": d.cached,
            "cut": was_cut,
        }

    # A small thread pool keeps the demo quick without hammering Ollaya.
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for r in pool.map(work, rows):
            done += 1
            if r is None:
                continue
            if "error" in r:
                errors += 1
                print(f"  [{done:3d}/{len(rows)}] {r['cmplid']}  ERROR {r['error']}")
                continue
            if r["cut"]:
                truncated += 1
            results.append(r)
            if r["pred_group"] == r["truth_group"]:
                agree += 1
            run_agree = agree / max(1, len(results))
            print(f"  [{done:3d}/{len(rows)}] {r['cmplid']}  "
                  f"{r['pred_group']:<20} conf {r['comp_conf']:.2f}  "
                  f"sc {r['safety_critical']:.0%}  sev {r['severity']:.1f}  "
                  f"{'CUT ' if r['cut'] else '    '}"
                  f"agree {run_agree:.0%}")

    elapsed = time.perf_counter() - t0
    print(f"\n{len(results)} labelled, {errors} errors, {truncated} narratives cut "
          f"to fit the {budget}-char budget, in {elapsed:.1f}s "
          f"({elapsed / max(1, len(rows)):.2f}s/row).")

    write_labels(con, args.model, results)
    con.close()


def write_labels(con: duckdb.DuckDBPyConnection, model: str, results: list[dict]) -> None:
    """Persist labels to data/labels.duckdb (gitignored), keyed by model so the
    three models can be labelled independently and compared in the report."""
    LABELS_DB = HERE.parent / "data" / "labels.duckdb"
    LABELS_DB.parent.mkdir(exist_ok=True)
    target = duckdb.connect(str(LABELS_DB))
    target.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            cmplid VARCHAR, model VARCHAR,
            pred_group VARCHAR, comp_conf DOUBLE,
            safety_critical DOUBLE, severity DOUBLE, sev_conf DOUBLE,
            min_conf DOUBLE, latency_ms DOUBLE, was_cut BOOLEAN
        )
    """)
    # Re-labelling a model replaces its previous rows (idempotent demo reruns).
    target.execute("DELETE FROM labels WHERE model = ?", [model])
    target.executemany(
        "INSERT INTO labels VALUES (?,?,?,?,?,?,?,?,?,?)",
        [[r["cmplid"], r["model"], r["pred_group"], r["comp_conf"],
          r["safety_critical"], r["severity"], r["sev_conf"], r["min_conf"],
          r["latency_ms"], r["cut"]] for r in results],
    )
    print(f"wrote {len(results)} rows to labels table in {LABELS_DB}")
    target.close()


if __name__ == "__main__":
    main()
