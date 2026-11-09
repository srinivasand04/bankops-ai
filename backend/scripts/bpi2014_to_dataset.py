"""Convert the raw BPI Challenge 2014 CSVs into a small BankOps dataset folder.

    python scripts/bpi2014_to_dataset.py --raw ../data/raw/bpi2014 --out datasets/bpi2014
    python -m app.ingestion validate datasets/bpi2014
    python -m app.ingestion load datasets/bpi2014

The raw files (Detail_Incident.csv, Detail_Incident_Activity.csv, Detail_Change.csv) come from
4TU.ResearchData and are not stored in git; see app/ingestion/bpi2014.py for the mapping rules.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.bpi2014 import build, write  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default="../data/raw/bpi2014", help="folder with the BPI 2014 CSV files")
    parser.add_argument("--out", default="datasets/bpi2014")
    args = parser.parse_args()
    counts = write(build(Path(args.raw)), Path(args.out))
    print(json.dumps({"written_to": args.out, **counts}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
