from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    checks: list[dict]
    summary: dict


def validate_run(run_dir: Path | str, min_samples: int = 5) -> ValidationResult:
    path = Path(run_dir)
    checks: list[dict] = []
    required = ["metadata.json", "license.dat", "lmgrd.log", "samples.sqlite"]
    missing = [name for name in required if not (path / name).exists()]
    checks.append(_check("required_files", not missing, {"missing": missing}))
    if missing:
        return ValidationResult(False, checks, {"missing": missing})

    conn = sqlite3.connect(path / "samples.sqlite")
    sample_count = conn.execute("select count(*) from samples").fetchone()[0]
    checks.append(_check("sample_count", sample_count >= min_samples, {"count": sample_count, "minimum": min_samples}))

    invariant_failures = conn.execute(
        "select count(*) from feature_samples where in_use < 0 or in_use > total or queued < 0"
    ).fetchone()[0]
    checks.append(_check("feature_invariants", invariant_failures == 0, {"failures": invariant_failures}))

    granted = conn.execute("select count(*) from workload_events where action = 'checkout' and status = 'GRANTED'").fetchone()[0]
    returned = conn.execute("select count(*) from workload_events where action = 'return' and status = 'RETURNED'").fetchone()[0]
    unknown = conn.execute(
        "select count(*) from workload_events where action = 'checkout' and status = 'REJECTED' and reason = 'UNKNOWN_FEATURE'"
    ).fetchone()[0]
    checks.append(_check("has_granted_checkout", granted > 0, {"count": granted}))
    checks.append(_check("has_returned_checkout", returned > 0, {"count": returned}))
    checks.append(_check("has_unknown_feature_rejection", unknown > 0, {"count": unknown}))

    log_text = (path / "lmgrd.log").read_text(encoding="utf-8")
    checks.append(_check("log_has_out", "OUT:" in log_text, {}))
    checks.append(_check("log_has_in", "IN:" in log_text, {}))

    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    clean_exit = metadata.get("lmgrd_exit_status") in (0, -15, None)
    checks.append(_check("lmgrd_cleaned_up", clean_exit, {"exit_status": metadata.get("lmgrd_exit_status")}))

    passed = all(check["passed"] for check in checks)
    return ValidationResult(
        passed=passed,
        checks=checks,
        summary={"samples": sample_count, "granted": granted, "returned": returned, "unknown_feature": unknown},
    )


def write_validation_report(run_dir: Path | str, result: ValidationResult) -> None:
    payload = {"passed": result.passed, "checks": result.checks, "summary": result.summary}
    (Path(run_dir) / "validation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _check(name: str, passed: bool, details: dict) -> dict:
    return {"name": name, "passed": passed, "details": details}
