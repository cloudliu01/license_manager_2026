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


def test_parse_license_text_basic():
    base_dir = Path(__file__).resolve().parents[1] / "lmgrd-sim"
    license_parser = _load_module("license_parser", base_dir / "license_parser.py")

    config = license_parser.parse_license_text(
        """
        PORT 27000
        SERVER_NAME test-host
        DAEMON vendorA
        FEATURE alpha 10 DAEMON vendorA EXP 2026-12-31
        FEATURE beta 5
        """
    )
    assert config.port == 27000
    assert "vendorA" in config.daemons
    assert "alpha" in config.features
    assert config.features["alpha"].daemon == "vendorA"


def test_startup_banner_contains_required_blocks():
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
    banner_text = "\n".join(lines)
    assert "Please Note:" in banner_text
    assert "Server's System Date and Time" in banner_text
