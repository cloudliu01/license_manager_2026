from __future__ import annotations

import argparse
import os
import signal
from datetime import UTC, datetime
from threading import Event

from license_manager_simulators.core.license_parser import parse_license_file
from license_manager_simulators.core.log_writer import (
    startup_banner,
    vendor_daemon_startup,
)
from license_manager_simulators.lmgrd.manager import serve
from license_manager_simulators.lmgrd.processes import start_process_group


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", dest="license_path", required=True)
    parser.add_argument("-l", dest="log_path", required=True)
    args = parser.parse_args()

    config = parse_license_file(args.license_path)
    stop = Event()

    def shutdown(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    with start_process_group(config, args.license_path, host="0.0.0.0", log_path=args.log_path) as group:
        writer = group.log_writer
        assert writer is not None
        ts = datetime.now(UTC)
        server_name = config.server_name or "127.0.0.1"
        writer.write_raw_lines(startup_banner(
            ts, server_name, args.license_path, config.port, os.getpid(),
            "v11.19.5.1", "293554", args.log_path,
        ))
        for name, worker in group.workers.items():
            features = [feature.name for feature in config.features.values() if feature.daemon == name]
            writer.write_raw_lines(vendor_daemon_startup(
                ts, name, worker.port, worker.pid, "v11.19.5.1", "293554", server_name, features,
            ))
        writer.write_line("lmgrd", "SIM1 synthetic TCP only; not a real FlexNet wire implementation")
        serve(config, group, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
