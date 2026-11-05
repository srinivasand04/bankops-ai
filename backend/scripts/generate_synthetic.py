"""Generate the large synthetic dataset (12 months of banking IT history) for the ML module.

    python scripts/generate_synthetic.py                          # defaults: seed 42, 12 months, scale 1.0
    python scripts/generate_synthetic.py --seed 7 --months 6 --scale 0.5 --out datasets/synthetic_large
    python -m app.ingestion load datasets/synthetic_large         # then load it (after the demo dataset)

The signal rules live in app/synthetic/generator.py and are described in documents/synthetic-data.md.
Same arguments (including --end) -> identical files.
"""

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable when run as a script

from app.synthetic.generator import GeneratorConfig, SyntheticGenerator, write_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the large BankOps AI synthetic dataset")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--scale", type=float, default=1.0, help="1.0 = about 4,000 incidents / 650 changes per year")
    parser.add_argument("--end", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC),
                        help="last day of history (YYYY-MM-DD, default: today 00:00 UTC)")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "datasets" / "synthetic_large")
    args = parser.parse_args()

    config = GeneratorConfig(seed=args.seed, months=args.months, scale=args.scale)
    if args.end:
        config.end = args.end
    started = time.perf_counter()
    generator = SyntheticGenerator(config)
    dataset = generator.generate()
    sizes = write_dataset(dataset, args.out)
    print(f"Generated in {time.perf_counter() - started:.1f} s -> {args.out}")
    for key, value in generator.stats().items():
        print(f"  {key}: {value}")
    print(f"  size: {sum(sizes.values()) / 1e6:.1f} MB ({', '.join(f'{k} {v / 1e6:.1f} MB' for k, v in sizes.items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
