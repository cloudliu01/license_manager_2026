from __future__ import annotations

import argparse
import sys

from .client import fetch_checkouts, fetch_status
from .output import generate_output


def parse_port_server(value: str) -> tuple[str, int]:
    if "@" in value:
        port_str, host = value.split("@", 1)
    else:
        port_str, host = value, "127.0.0.1"
    return host, int(port_str)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", dest="port_server", required=True)
    parser.add_argument("-a", dest="all_features", action="store_true")
    parser.add_argument("-f", dest="feature_name")
    parser.add_argument("-i", dest="include_details", action="store_true")
    args = parser.parse_args()

    if not args.all_features and not args.feature_name:
        sys.stderr.write("INVALID_ARGUMENTS\n")
        return 1

    try:
        host, port = parse_port_server(args.port_server)
        status = fetch_status(host, port)
        details = fetch_checkouts(host, port, feature=args.feature_name) if args.include_details else {"checkouts": []}
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"INVALID_RESPONSE: {exc}\n")
        return 1

    by_feature: dict[str, list[dict]] = {}
    for detail in details.get("checkouts", []):
        by_feature.setdefault(detail.get("feature"), []).append(detail)

    features = []
    for item in status.get("features", []):
        feature_name = item.get("feature")
        if args.feature_name and feature_name != args.feature_name:
            continue
        features.append(
            {
                "name": feature_name,
                "total": item.get("total", 0),
                "in_use": item.get("in_use", 0),
                "queued": item.get("queued", 0),
                "expired": item.get("expired", False),
                "details": by_feature.get(feature_name, []),
            }
        )

    print(generate_output(host, port, features, args.include_details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
