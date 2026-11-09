"""ML command line.

    python -m app.ml list                     # tasks and their active models
    python -m app.ml train --task sla_breach  # one task (every algorithm of it)
    python -m app.ml train-all                # every task
    python -m app.ml export-bundle            # copy active models + runs into ml_bundle/ (hosted demo)
"""

import argparse
import json
import sys

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging


def main() -> int:
    from app.ml.bundle import export_bundle
    from app.ml.registry import active_run
    from app.ml.trainer import TASKS, train_all, train_task

    parser = argparse.ArgumentParser(prog="python -m app.ml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    t = sub.add_parser("train")
    t.add_argument("--task", required=True, choices=list(TASKS))
    sub.add_parser("train-all")
    sub.add_parser("export-bundle")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)

    with SessionLocal() as db:
        if args.command == "list":
            for task, desc in TASKS.items():
                run = active_run(db, task)
                print(f"{task:12} {desc:55} {run.algorithm + ' ' + json.dumps(run.metrics) if run else '(not trained)'}")
        elif args.command == "train":
            print(json.dumps(train_task(db, args.task, "cli"), indent=2, default=str))
        elif args.command == "train-all":
            for r in train_all(db, "cli"):
                print(json.dumps(r, default=str))
        elif args.command == "export-bundle":
            print(json.dumps(export_bundle(db), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
