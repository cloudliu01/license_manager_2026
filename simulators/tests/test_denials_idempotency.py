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


def test_denies_unknown_feature():
    base_dir = Path(__file__).resolve().parents[1] / "lmgrd-sim"
    license_parser = _load_module("license_parser", base_dir / "license_parser.py")
    state_mod = _load_module("state", base_dir / "state.py")
    config = license_parser.parse_license_text("PORT 27000\nFEATURE alpha 1\n")
    state = state_mod.SimulatorState.from_license(config)

    result = state.checkout("beta", "user1", "host1", 101, request_id="r1")
    assert result.status == "REJECTED"
    assert result.reason == "UNKNOWN_FEATURE"


def test_idempotent_checkout_by_request_id():
    base_dir = Path(__file__).resolve().parents[1] / "lmgrd-sim"
    license_parser = _load_module("license_parser", base_dir / "license_parser.py")
    state_mod = _load_module("state", base_dir / "state.py")
    config = license_parser.parse_license_text("PORT 27000\nFEATURE alpha 1\n")
    state = state_mod.SimulatorState.from_license(config)

    first = state.checkout("alpha", "user1", "host1", 101, request_id="r1")
    second = state.checkout("alpha", "user1", "host1", 101, request_id="r1")

    assert first.checkout_id == second.checkout_id
    assert first.status == second.status
