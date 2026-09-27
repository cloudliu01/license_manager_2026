"""Attach by lmgrd PID and capture SIM1 TCP into a local SQLite database."""

from __future__ import annotations

import argparse
import signal
import sys

from license_manager_simulators.monitor.capture import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive Linux SIM1 monitor (not a FlexNet decoder)")
    parser.add_argument("--pid", type=int, required=True, help="actual lmgrd Python PID, not a wrapper shell PID")
    parser.add_argument("--db", required=True, help="SQLite output path")
    parser.add_argument("--iface", default="lo", help="capture interface (default: lo; IPv4 only)")
    parser.add_argument("--ready-file", help="optional file created after capture socket and PID discovery are ready")
    args = parser.parse_args()

    def stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        run(args.pid, args.db, args.iface, args.ready_file)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"monitor unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
