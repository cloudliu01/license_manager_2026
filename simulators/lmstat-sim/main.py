from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
        raise SystemExit(1)

    host, port = parse_port_server(args.port_server)
    base_dir = Path(__file__).resolve().parent
    output_mod = _load_module("output", base_dir / "output.py")
    client_mod = _load_module("client", base_dir / "client.py")

    try:
        status = client_mod.fetch_status(host, port)
    except RuntimeError:
        raise SystemExit(1)

    features = []
    for item in status.get("features", []):
        if args.feature_name and item.get("feature") != args.feature_name:
            continue
        features.append(
            {
                "name": item.get("feature"),
                "total": item.get("total", 0),
                "in_use": item.get("in_use", 0),
                "queued": item.get("queued", 0),
                "expired": item.get("expired", False),
                "details": [],
            }
        )

    if args.include_details:
        checkouts = client_mod.fetch_checkouts(host, port)
        by_feature = {}
        for entry in checkouts.get("checkouts", []):
            by_feature.setdefault(entry.get("feature"), []).append(entry)
        for feature in features:
            feature["details"] = by_feature.get(feature.get("name"), [])

    output = output_mod.generate_output(host, port, features, args.include_details)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
