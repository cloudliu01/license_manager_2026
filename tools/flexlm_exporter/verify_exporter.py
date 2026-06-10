from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
EXPORTER_DIR = ROOT / "third_party" / "flexlm_exporter"
LMGRD = ROOT / "simulators" / "wrappers" / "lmgrd"
LMUTIL = ROOT / "tools" / "flexlm_exporter" / "lmutil"

REQUIRED_METRICS = (
    ("lmstat info metric", "flexlm_lmstat_info"),
    ("server status metric", "flexlm_server_status"),
    ("issued feature metric", 'flexlm_feature_issued{app="simulator",name="alpha"} 2'),
    ("used feature metric", 'flexlm_feature_used{app="simulator",name="alpha"} 1'),
    ("user usage metric", "flexlm_feature_used_users{"),
    ("version label", 'version="(v1.0)"'),
    ("group reservation metric", "flexlm_feature_reserved_groups"),
    ("host reservation metric", "flexlm_feature_reserved_host"),
)


def missing_required_metrics(metrics: str) -> list[str]:
    return [name for name, expected in REQUIRED_METRICS if expected not in metrics]


def main() -> int:
    if not EXPORTER_DIR.exists() or not (EXPORTER_DIR / "go.mod").exists():
        print("third_party/flexlm_exporter with go.mod is required", file=sys.stderr)
        return 1
    if shutil.which("go") is None:
        print("Go toolchain is required to build flexlm_exporter", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        exporter_bin = tmp_path / "flexlm_exporter"
        _build_exporter(exporter_bin)

        simulator_port = _free_port()
        exporter_port = _free_port()
        license_path = tmp_path / "license.dat"
        log_path = tmp_path / "license.log"
        config_path = tmp_path / "licenses.yml"
        _write_license_file(license_path, simulator_port)
        _write_exporter_config(config_path, simulator_port)

        lmgrd_proc = None
        exporter_proc = None
        try:
            lmgrd_proc = _start_lmgrd(license_path, log_path)
            _wait_for_url(f"http://127.0.0.1:{simulator_port}/v1/health", lmgrd_proc)
            _post_json(
                simulator_port,
                "/v1/checkout",
                {"request_id": "verify-1", "feature": "alpha", "user": "user1", "host": "host1", "pid": 101},
            )

            exporter_proc = _start_exporter(exporter_bin, exporter_port, config_path)
            metrics = _wait_for_required_metrics(exporter_port, exporter_proc)
            missing = missing_required_metrics(metrics)
            if missing:
                print("Missing required metrics: " + ", ".join(missing), file=sys.stderr)
                return 1

            print("flexlm_exporter simulator verification passed")
            return 0
        finally:
            _stop_process(exporter_proc)
            _stop_process(lmgrd_proc)


def _build_exporter(output_path: Path) -> None:
    subprocess.run(["go", "build", "-o", str(output_path), "."], cwd=EXPORTER_DIR, check=True)


def _write_license_file(path: Path, port: int) -> None:
    path.write_text(
        f"PORT {port}\n"
        "DAEMON vendorA\n"
        "FEATURE alpha 2 DAEMON vendorA EXP 2026-11-01 "
        "RESERVE 2 GROUP engineering RESERVE 1 HOST buildhost1\n",
        encoding="utf-8",
    )


def _write_exporter_config(path: Path, simulator_port: int) -> None:
    path.write_text(
        "licenses:\n"
        "  - name: simulator\n"
        f"    license_server: {simulator_port}@127.0.0.1\n"
        "    monitor_users: true\n"
        "    monitor_reservations: true\n"
        "    monitor_versions: true\n",
        encoding="utf-8",
    )


def _start_lmgrd(license_path: Path, log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHON"] = sys.executable
    return subprocess.Popen(
        [str(LMGRD), "-c", str(license_path), "-l", str(log_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _start_exporter(executable: Path, port: int, config_path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(executable),
            f"--web.listen-address=127.0.0.1:{port}",
            f"--path.lmutil={LMUTIL}",
            f"--path.config={config_path}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_url(url: str, proc: subprocess.Popen, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Process exited before {url} became available")
        try:
            with urlopen(url, timeout=0.5) as response:
                return response.read().decode("utf-8")
        except URLError as exc:
            last_error = exc
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def _wait_for_required_metrics(
    port: int,
    proc: subprocess.Popen,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> str:
    deadline = time.monotonic() + timeout
    metrics = ""
    while time.monotonic() < deadline:
        metrics = _wait_for_url(f"http://127.0.0.1:{port}/metrics", proc)
        if not missing_required_metrics(metrics):
            return metrics
        time.sleep(interval)
    return metrics


def _post_json(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
