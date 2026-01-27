import re
from datetime import datetime
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


def test_startup_banner_line_prefixes():
    base_dir = Path(__file__).resolve().parents[1] / "lmgrd-sim"
    logs = _load_module("logs", base_dir / "logs.py")
    lines = logs.startup_banner(
        ts=datetime(2026, 1, 20, 16, 24, 11),
        server_name="10.10.10.101",
        license_path="./license.dat",
        port=5280,
        pid=1234,
        version="v11.19.5.1",
        build="293554",
        options_path="./logs/license.log.2026-01-20",
    )
    prefix = re.compile(r"^\d{2}:\d{2}:\d{2} \([^)]+\) ")
    assert all(prefix.match(line) for line in lines)
    assert any("Please Note:" in line for line in lines)
