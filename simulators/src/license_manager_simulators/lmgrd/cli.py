from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime

import uvicorn

from license_manager_simulators.core.license_parser import parse_license_file
from license_manager_simulators.core.log_writer import FileLogWriter, startup_banner, vendor_daemon_startup
from license_manager_simulators.core.service import SimulatorService
from license_manager_simulators.core.store import SimulatorStore
from license_manager_simulators.lmgrd.app import create_app


def build_service(license_path: str, log_path: str) -> SimulatorService:
    config = parse_license_file(license_path)
    server_name = config.server_name or "127.0.0.1"
    writer = FileLogWriter(log_path)
    ts = datetime.now()
    version = "v11.19.5.1"
    build = "293554"
    pid = os.getpid()
    lines = startup_banner(ts, server_name, license_path, config.port, pid, version, build, log_path)
    daemons = config.daemons or sorted({feature.daemon for feature in config.features.values()}) or ["default"]
    for idx, daemon in enumerate(daemons):
        features = [feature.name for feature in config.features.values() if feature.daemon == daemon]
        lines.extend(
            vendor_daemon_startup(
                ts, daemon, config.port + 1000 + idx, pid + idx + 1, version, build, server_name, features
            )
        )
    writer.write_raw_lines(lines)
    return SimulatorService(
        store=SimulatorStore.from_license(config),
        log_writer=writer,
        server_name=server_name,
        port=config.port,
        config_hash=_config_hash(license_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", dest="license_path", required=True)
    parser.add_argument("-l", dest="log_path", required=True)
    args = parser.parse_args()

    service = build_service(args.license_path, args.log_path)
    app = create_app(service)
    uvicorn.run(app, host="0.0.0.0", port=service.port, log_level="info")
    return 0


def _config_hash(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
