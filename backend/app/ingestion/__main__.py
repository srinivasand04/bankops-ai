"""Data ingestion CLI.

    python -m app.ingestion validate datasets/synthetic        # schema + references + dry-run replay
    python -m app.ingestion load datasets/synthetic            # load (skips if the source is already loaded)
    python -m app.ingestion load datasets/synthetic --replace  # reload that source only
    python -m app.ingestion sources                            # row counts per data source
    python -m app.ingestion reset --yes                        # wipe ALL data (development only)
"""

import argparse
import json
import sys

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.ingestion.loader import LoadError, dry_run, load_dataset, reset_all, source_counts
from app.ingestion.reader import DatasetError, read_dataset


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion", description="BankOps AI data ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "load"):
        cmd = sub.add_parser(name)
        cmd.add_argument("dataset", help="path to a dataset folder containing manifest.json")
        if name == "load":
            cmd.add_argument("--replace", action="store_true", help="replace data previously loaded from this source")
    sub.add_parser("sources")
    reset = sub.add_parser("reset")
    reset.add_argument("--yes", action="store_true", help="confirm wiping every table")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)

    with SessionLocal() as db:
        try:
            if args.command == "validate":
                dataset = read_dataset(args.dataset)
                report = dry_run(db, dataset)
                print(f"Dataset '{dataset.manifest.name}' ({dataset.manifest.data_source}) is valid: {report.counts}")
            elif args.command == "load":
                dataset = read_dataset(args.dataset)
                report = load_dataset(db, dataset, replace=args.replace)
                if report.skipped:
                    print(f"Source {report.data_source} is already loaded - skipping (use --replace to reload).")
                else:
                    print(f"Loaded {report.data_source}: {report.counts}")
            elif args.command == "sources":
                print(json.dumps(source_counts(db), indent=2))
            elif args.command == "reset":
                if not args.yes:
                    print("Refusing to wipe the database without --yes")
                    return 2
                reset_all(db)
                print("All tables truncated; incident references restart at INC-1001.")
        except (DatasetError, LoadError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
