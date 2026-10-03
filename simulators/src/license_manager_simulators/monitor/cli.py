"""Attach by lmgrd PID and capture SIM1 TCP into a local SQLite database."""

from __future__ import annotations

import argparse
import signal
import sys

from license_manager_simulators.monitor.capture import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive Linux SIM1 monitor (not a FlexNet decoder)")
    parser.add_argument("--pid", type=int, action="append", default=[],
                        help="actual lmgrd Python PID, not a wrapper shell PID; "
                             "repeat the flag to monitor several services in one instance; "
                             "in --discovery auto these trees are pinned in addition to "
                             "the auto-discovered ones")
    parser.add_argument("--discovery", choices=("manual", "auto"), default="manual",
                        help="manual: watch exactly the --pid trees and exit when one of "
                             "them dies (default); auto: re-scan the host every refresh "
                             "for lmgrd processes, adopting new trees and surviving "
                             "their death – never exits on tree churn")
    parser.add_argument("--db", required=True, help="SQLite output path")
    parser.add_argument("--iface", default="lo", help="capture interface (default: lo; IPv4 only)")
    parser.add_argument("--ready-file", help="optional file created after capture socket and PID discovery are ready")
    parser.add_argument("--filter-queries", action="store_true",
                        help="drop lmstat-style seat-query traffic (0x3c/0x4e/0x14) entirely")
    parser.add_argument("--self-query", action="store_true",
                        help="spawn lmutil lmstat every 30s and capture its loopback "
                             "traffic for poller detail/summary; external pollers' "
                             "query streams are fully excluded from the --iface socket")
    parser.add_argument("--lmstat-timeout", type=float, default=5.0,
                        help="kill a self-query dump after this many seconds and roll "
                             "back its partial rows (default: 5; failure logged in "
                             "self_query_errors)")
    args = parser.parse_args()

    if args.discovery == "manual" and not args.pid:
        parser.error("--pid is required unless --discovery auto")

    def stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        run(args.pid, args.db, args.iface, args.ready_file, args.filter_queries,
            args.self_query, args.lmstat_timeout, args.discovery == "auto")
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"monitor unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
