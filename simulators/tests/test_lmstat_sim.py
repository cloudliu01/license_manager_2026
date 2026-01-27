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


def test_generate_output_includes_header_and_features():
    base_dir = Path(__file__).resolve().parents[1] / "lmstat-sim"
    output_mod = _load_module("output", base_dir / "output.py")

    content = output_mod.generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {"name": "alpha", "total": 10, "in_use": 2, "queued": 0, "expired": False}
        ],
        include_details=False,
    )
    assert "LMSTAT_SIM_FORMAT_VERSION=1" in content
    assert "feature: alpha" in content
