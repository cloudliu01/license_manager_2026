from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from .runner import run_workload
from .validator import validate_run, write_validation_report


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--duration-seconds", type=int, default=300)
    run_parser.add_argument("--users", type=int, default=20)
    run_parser.add_argument("--sample-interval-seconds", type=int, default=60)
    run_parser.add_argument("--out", type=Path)
    run_parser.add_argument("--seed", type=int)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--run-dir", type=Path, required=True)
    validate_parser.add_argument("--min-samples", type=int, default=5)

    args = parser.parse_args()
    if args.command == "run":
        out = args.out or Path("runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result = run_workload(out, args.duration_seconds, args.users, args.sample_interval_seconds, args.seed)
        print(result.run_dir)
        return 0 if result.validation_passed else 1

    validation = validate_run(args.run_dir, min_samples=args.min_samples)
    write_validation_report(args.run_dir, validation)
    print(args.run_dir / "validation.json")
    return 0 if validation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
