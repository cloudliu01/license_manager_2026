from __future__ import annotations

import json
import random
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from .sampler import sample_once
from .scenario import DEFAULT_MISSING_FEATURE, Scenario, SyntheticUser
from .sqlite_sink import SQLiteSink, WorkloadEvent
from .validator import validate_run, write_validation_report


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    validation_passed: bool


def run_workload(
    out_dir: Path | str,
    duration_seconds: int = 300,
    users: int = 20,
    sample_interval_seconds: int = 60,
    seed: int | None = None,
) -> RunResult:
    run_dir = Path(out_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seed = seed if seed is not None else random.SystemRandom().randint(1, 2_000_000_000)
    port = _free_port()
    scenario = Scenario.default(port=port, users=users, seed=seed)
    license_path = run_dir / "license.dat"
    log_path = run_dir / "lmgrd.log"
    db_path = run_dir / "samples.sqlite"
    metadata_path = run_dir / "metadata.json"
    license_path.write_text(scenario.license_text(), encoding="utf-8")

    simulators_root = _simulators_root()
    lmgrd = simulators_root / "wrappers" / "lmgrd"
    lmstat = simulators_root / "wrappers" / "lmstat"
    sink = SQLiteSink(db_path)
    sink.initialize()
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    proc: subprocess.Popen | None = None
    exit_status: int | None = None
    started_at = datetime.now(UTC)
    error: str | None = None

    try:
        proc = subprocess.Popen([str(lmgrd), "-c", str(license_path), "-l", str(log_path)])
        _wait_for_health(port)
        _seed_required_events(port, sink)

        for idx, user in enumerate(scenario.users):
            thread = threading.Thread(
                target=_user_loop,
                args=(port, sink, user, stop_event, seed + idx),
                daemon=True,
            )
            thread.start()
            threads.append(thread)

        end_time = time.time() + duration_seconds
        next_sample = 0.0
        while time.time() < end_time:
            if time.time() >= next_sample:
                try:
                    sample_once(lmstat, port, sink)
                except Exception as exc:
                    sink.insert_event(_event("sampler", "sample", None, "FAILED", str(exc), None))
                next_sample = time.time() + sample_interval_seconds
            time.sleep(0.1)
        try:
            sample_once(lmstat, port, sink)
        except Exception as exc:
            sink.insert_event(_event("sampler", "sample", None, "FAILED", str(exc), None))
    except Exception as exc:
        error = str(exc)
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=2)
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                exit_status = proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_status = proc.wait(timeout=3)
        ended_at = datetime.now(UTC)
        sink.close()
        metadata = {
            "duration_seconds": duration_seconds,
            "users": users,
            "sample_interval_seconds": sample_interval_seconds,
            "seed": seed,
            "port": port,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "lmgrd_path": str(lmgrd),
            "lmstat_path": str(lmstat),
            "lmgrd_exit_status": exit_status,
            "error": error,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    validation = validate_run(run_dir, min_samples=2 if duration_seconds < 300 else 5)
    write_validation_report(run_dir, validation)
    return RunResult(run_dir=run_dir, validation_passed=validation.passed)


def _user_loop(port: int, sink: SQLiteSink, user: SyntheticUser, stop_event: threading.Event, seed: int) -> None:
    rng = random.Random(seed)
    held: list[str] = []
    counter = 0
    while not stop_event.is_set():
        counter += 1
        if held and rng.random() < 0.25:
            checkout_id = held.pop(0)
            response = _post_json(port, "/v1/return", {"checkout_id": checkout_id, "request_id": f"{user.user}-return-{counter}"})
            sink.insert_event(_event(user.user, "return", response.get("feature"), response.get("status"), response.get("reason"), response.get("checkout_id")))
        else:
            feature = _choose_feature(rng)
            response = _post_json(
                port,
                "/v1/checkout",
                {
                    "request_id": f"{user.user}-checkout-{counter}",
                    "feature": feature,
                    "user": user.user,
                    "host": user.host,
                    "pid": 1000 + counter,
                },
            )
            if response.get("status") == "GRANTED" and response.get("checkout_id"):
                held.append(response["checkout_id"])
            sink.insert_event(_event(user.user, "checkout", feature, response.get("status"), response.get("reason"), response.get("checkout_id")))
        stop_event.wait(rng.uniform(0.2, 1.0))

    for checkout_id in list(held):
        try:
            response = _post_json(port, "/v1/return", {"checkout_id": checkout_id, "request_id": f"{user.user}-cleanup-{checkout_id}"})
            sink.insert_event(_event(user.user, "return", response.get("feature"), response.get("status"), response.get("reason"), response.get("checkout_id")))
        except Exception:
            pass


def _seed_required_events(port: int, sink: SQLiteSink) -> None:
    checkout = _post_json(
        port,
        "/v1/checkout",
        {"request_id": "seed-checkout", "feature": "alpha", "user": "user00", "host": "host00", "pid": 1},
    )
    sink.insert_event(_event("user00", "checkout", "alpha", checkout.get("status"), checkout.get("reason"), checkout.get("checkout_id")))
    if checkout.get("checkout_id"):
        returned = _post_json(port, "/v1/return", {"request_id": "seed-return", "checkout_id": checkout["checkout_id"]})
        sink.insert_event(_event("user00", "return", "alpha", returned.get("status"), returned.get("reason"), returned.get("checkout_id")))
    missing = _post_json(
        port,
        "/v1/checkout",
        {"request_id": "seed-missing", "feature": DEFAULT_MISSING_FEATURE, "user": "user00", "host": "host00", "pid": 2},
    )
    sink.insert_event(_event("user00", "checkout", DEFAULT_MISSING_FEATURE, missing.get("status"), missing.get("reason"), missing.get("checkout_id")))


def _choose_feature(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.10:
        return DEFAULT_MISSING_FEATURE
    if roll < 0.45:
        return "alpha"
    return rng.choice(["alpha", "beta", "gamma"])


def _event(user: str, action: str, feature: str | None, status: str | None, reason: str | None, checkout_id: str | None) -> WorkloadEvent:
    return WorkloadEvent(datetime.now(UTC).isoformat(), user, action, feature, status, reason, checkout_id)


def _post_json(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(port: int, timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("lmgrd health endpoint not ready")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _simulators_root() -> Path:
    return Path(__file__).resolve().parents[3]
