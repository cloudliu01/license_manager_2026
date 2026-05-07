from __future__ import annotations

import argparse
import importlib.util
import sys
import os
from datetime import datetime
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_startup_log(license_path: str, log_path: str) -> list[str]:
    base_dir = Path(__file__).resolve().parent
    license_parser = _load_module("license_parser", base_dir / "license_parser.py")
    logs = _load_module("logs", base_dir / "logs.py")

    config = license_parser.parse_license_file(license_path)
    ts = datetime.now()
    server_name = config.server_name or "127.0.0.1"
    pid = os.getpid()
    version = "v11.19.5.1"
    build = "293554"

    lines = logs.startup_banner(
        ts=ts,
        server_name=server_name,
        license_path=license_path,
        port=config.port,
        pid=pid,
        version=version,
        build=build,
        options_path=log_path,
    )

    daemons = config.daemons or ["default"]
    for idx, daemon in enumerate(daemons):
        lines.extend(logs.redundancy_attempt(ts, "10.10.10.102", "secondary", True))
        features = [f.name for f in config.features.values() if f.daemon == daemon]
        lines.extend(
            logs.vendor_daemon_startup(
                ts=ts,
                daemon=daemon,
                port=config.port + 1000 + idx,
                pid=pid + idx + 1,
                version=version,
                kit_version=build,
                host=server_name,
                features=features,
            )
        )

    sample_out = logs.checkout_line(
        ts, daemons[0], "sample_feature", "user", "host", "Sample Detail", 1
    )
    lines.append(sample_out)
    return lines


def write_log(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", dest="license_path", required=True)
    parser.add_argument("-l", dest="log_path", required=True)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    license_parser = _load_module("license_parser", base_dir / "license_parser.py")
    state_mod = _load_module("state", base_dir / "state.py")
    api_mod = _load_module("api", base_dir / "api.py")

    config = license_parser.parse_license_file(args.license_path)
    state = state_mod.SimulatorState.from_license(config)

    lines = build_startup_log(args.license_path, args.log_path)
    write_log(args.log_path, lines)

    app = api_mod.create_app(state, config.server_name or "127.0.0.1", config.port)
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
