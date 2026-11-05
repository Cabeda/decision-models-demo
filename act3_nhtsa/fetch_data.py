"""Act 3, step 1: download NHTSA complaints into DuckDB and cut a replay sample.

NHTSA publishes every safety complaint it has received since 1995 as one big
tab-separated flat file. We load it into DuckDB (so the report can be plain
SQL on a projector), filter to Volkswagen Group makes with a usable narrative,
and write a small, seeded, local-only sample so the labelling demo replays
offline without the 100+ MB download.

    uv run act3_nhtsa/fetch_data.py            # download + load + sample
    uv run act3_nhtsa/fetch_data.py --sample-only   # rebuild sample from the DB

The 100 MB download and the full DuckDB live under data/ (gitignored). Only
act3_nhtsa/sample_300.csv is local-only.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DB_PATH = DATA / "nhtsa.duckdb"
ZIP_PATH = DATA / "FLAT_CMPL.zip"
SAMPLE_PATH = HERE / "sample_300.csv"
URL = "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip"

# The 51 columns of the flat file, in order, from the NHTSA CMPL.txt layout.
# We only use a handful downstream but name them all so the TSV parses cleanly.
COLUMNS = [
    "CMPLID", "ODINO", "MFR_NAME", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH",
    "FAILDATE", "FIRE", "INJURED", "DEATHS", "COMPDESC", "CITY", "STATE", "VIN",
    "DATEA", "LDATE", "MILES", "OCCURENCES", "CDESCR", "CMPL_TYPE",
    "POLICE_RPT_YN", "PURCH_DT", "ORIG_OWNER_YN", "ANTI_BRAKES_YN",
    "CRUISE_CONT_YN", "NUM_CYLS", "DRIVE_TRAIN", "FUEL_SYS", "FUEL_TYPE",
    "TRANS_TYPE", "VEH_SPEED", "DOT", "TIRE_SIZE", "LOC_OF_TIRE",
    "TIRE_FAIL_TYPE", "ORIG_EQUIP_YN", "MANUF_DT", "SEAT_TYPE", "RESTRAINT_TYPE",
    "DEALER_NAME", "DEALER_TEL", "DEALER_CITY", "DEALER_STATE", "DEALER_ZIP",
    "PROD_TYPE", "REPAIRED_YN", "MEDICAL_ATTN", "VEHICLES_TOWED_YN",
    "STATE_OF_INCIDENT", "VEHICLE_OPERATOR",
]

# Volkswagen Group makes as they actually appear in MAKETXT (upper-cased).
VW_GROUP = ["VOLKSWAGEN", "AUDI", "PORSCHE", "BENTLEY", "LAMBORGHINI"]

MIN_CHARS, MAX_CHARS = 150, 1200
MIN_YEAR = 2015          # "recent years"
SAMPLE_SIZE = 300
SEED = 42


def download() -> None:
    """Fetch the zip once; skip if it is already on disk."""
    DATA.mkdir(exist_ok=True)
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 1_000_000:
        print(f"zip already present: {ZIP_PATH} ({ZIP_PATH.stat().st_size // 1_000_000} MB)")
        return
    print(f"downloading {URL} ...")
    urllib.request.urlretrieve(URL, ZIP_PATH)
    print(f"saved {ZIP_PATH} ({ZIP_PATH.stat().st_size // 1_000_000} MB)")


def load_duckdb() -> duckdb.DuckDBPyConnection:
    """Load the flat file into a `complaints` table, typed for the fields we use."""
    # The zip holds a single .txt; extract it to a temp path DuckDB can scan.
    with zipfile.ZipFile(ZIP_PATH) as z:
        name = next(n for n in z.namelist() if n.upper().endswith(".TXT"))
        flat = DATA / "FLAT_CMPL.txt"
        if not flat.exists():
            print(f"extracting {name} -> {flat}")
            flat.write_bytes(z.read(name))

    con = duckdb.connect(str(DB_PATH))
    cols_ddl = ", ".join(f"'{c}': 'VARCHAR'" for c in COLUMNS)
    print("loading into DuckDB (this reads the whole flat file once) ...")
    con.execute("DROP TABLE IF EXISTS complaints")
    con.execute(
        f"""
        CREATE TABLE complaints AS
        SELECT
            * EXCLUDE (INJURED, DEATHS),
            TRY_CAST(INJURED AS INTEGER) AS INJURED,
            TRY_CAST(DEATHS  AS INTEGER) AS DEATHS,
            TRY_CAST(YEARTXT AS INTEGER) AS YEAR
        FROM read_csv(
            '{flat.as_posix()}',
            delim='\t', header=false, quote='', escape='',
            ignore_errors=true, columns={{{cols_ddl}}}
        )
        """
    )
    n = con.execute("SELECT count(*) FROM complaints").fetchone()[0]
    print(f"loaded {n:,} complaint rows")
    return con


# One SQL WHERE clause shared by the DB build and the sample cut, so the sample
# is exactly a seeded subset of what the report scores.
FILTER_SQL = f"""
    UPPER(MAKETXT) IN ({", ".join("'" + m + "'" for m in VW_GROUP)})
    AND YEAR BETWEEN {MIN_YEAR} AND 2026
    AND PROD_TYPE = 'V'
    AND length(CDESCR) BETWEEN {MIN_CHARS} AND {MAX_CHARS}
    AND COMPDESC IS NOT NULL AND COMPDESC <> ''
"""


def write_sample(con: duckdb.DuckDBPyConnection) -> None:
    """Write a deterministic, component-group-balanced 300-row sample CSV.

    Stratify on the top-level COMPDESC category (the text before the first ':'),
    take a seeded, evenly-sized slice of each group, and order the result so the
    file is byte-identical on every run.
    """
    # Keep only the fields the labeller and report need, plus a stable group key.
    base = f"""
        SELECT
            CMPLID, MAKETXT, MODELTXT, YEAR, CRASH, FIRE, INJURED, DEATHS,
            COMPDESC, CDESCR,
            trim(split_part(COMPDESC, ':', 1)) AS comp_group
        FROM complaints
        WHERE {FILTER_SQL}
    """
    groups = con.execute(
        f"SELECT comp_group, count(*) c FROM ({base}) GROUP BY 1 ORDER BY c DESC"
    ).fetchall()
    n_groups = len(groups)
    per_group = max(1, SAMPLE_SIZE // n_groups)
    print(f"{n_groups} component groups; aiming for ~{per_group} rows each")

    # Seeded per-group slice: hash(CMPLID, seed) gives a stable pseudo-random order.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sample AS
        WITH ranked AS (
            SELECT *,
                row_number() OVER (
                    PARTITION BY comp_group
                    ORDER BY hash(CMPLID || '{SEED}')
                ) AS rn
            FROM ({base})
        )
        SELECT * EXCLUDE (rn) FROM ranked WHERE rn <= {per_group}
        """
    )
    # Top up to exactly SAMPLE_SIZE with the next rows, still seeded and stable.
    con.execute(
        f"""
        INSERT INTO sample
        WITH ranked AS (
            SELECT *,
                row_number() OVER (PARTITION BY comp_group ORDER BY hash(CMPLID || '{SEED}')) AS rn
            FROM ({base})
        )
        SELECT * EXCLUDE (rn) FROM ranked
        WHERE rn > {per_group}
          AND CMPLID NOT IN (SELECT CMPLID FROM sample)
        ORDER BY hash(CMPLID || '{SEED}')
        LIMIT {SAMPLE_SIZE} - (SELECT count(*) FROM sample)
        """
    )
    con.execute(
        f"COPY (SELECT * FROM sample ORDER BY comp_group, CMPLID) "
        f"TO '{SAMPLE_PATH.as_posix()}' (HEADER, DELIMITER ',')"
    )
    n = con.execute("SELECT count(*) FROM sample").fetchone()[0]
    print(f"wrote {SAMPLE_PATH} ({n} rows, balanced across {n_groups} groups, seed={SEED})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample-only", action="store_true",
                    help="rebuild sample_300.csv from an existing data/nhtsa.duckdb")
    args = ap.parse_args()

    if args.sample_only:
        if not DB_PATH.exists():
            sys.exit(f"no {DB_PATH}; run without --sample-only first")
        con = duckdb.connect(str(DB_PATH))
    else:
        download()
        con = load_duckdb()
    write_sample(con)
    con.close()


if __name__ == "__main__":
    main()
