from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = ROOT / "tools" / "flexlm_exporter" / "verify_exporter.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_exporter", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_missing_required_metrics_accepts_expected_exporter_output():
    verify = _load_verify_module()
    metrics = """
flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1
flexlm_server_status{app="simulator",fqdn="127.0.0.1",master="true",port="27000",version="v11.19.5"} 1
flexlm_feature_issued{app="simulator",name="alpha"} 2
flexlm_feature_used{app="simulator",name="alpha"} 1
flexlm_feature_used_users{app="simulator",name="alpha",since="1778112000",user="user1",version="(v1.0)"} 1
flexlm_feature_reserved_groups{app="simulator",group="engineering",name="alpha"} 2
flexlm_feature_reserved_host{app="simulator",host="buildhost1",name="alpha"} 1
"""

    assert verify.missing_required_metrics(metrics) == []


def test_missing_required_metrics_reports_absent_reservations():
    verify = _load_verify_module()
    metrics = """
flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1
flexlm_server_status{app="simulator",fqdn="127.0.0.1",master="true",port="27000",version="v11.19.5"} 1
flexlm_feature_issued{app="simulator",name="alpha"} 2
flexlm_feature_used{app="simulator",name="alpha"} 1
flexlm_feature_used_users{app="simulator",name="alpha",since="1778112000",user="user1",version="(v1.0)"} 1
"""

    missing = verify.missing_required_metrics(metrics)

    assert "group reservation metric" in missing
    assert "host reservation metric" in missing


def test_wait_for_required_metrics_retries_until_business_metrics_are_present(monkeypatch):
    verify = _load_verify_module()
    partial_metrics = 'flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1\n'
    complete_metrics = """
flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1
flexlm_server_status{app="simulator",fqdn="127.0.0.1",master="true",port="27000",version="v11.19.5"} 1
flexlm_feature_issued{app="simulator",name="alpha"} 2
flexlm_feature_used{app="simulator",name="alpha"} 1
flexlm_feature_used_users{app="simulator",name="alpha",since="1778112000",user="user1",version="(v1.0)"} 1
flexlm_feature_reserved_groups{app="simulator",group="engineering",name="alpha"} 2
flexlm_feature_reserved_host{app="simulator",host="buildhost1",name="alpha"} 1
"""
    responses = [partial_metrics, complete_metrics]

    class RunningProcess:
        def poll(self):
            return None

    def fake_wait_for_url(_url, _proc):
        return responses.pop(0)

    monkeypatch.setattr(verify, "_wait_for_url", fake_wait_for_url)

    metrics = verify._wait_for_required_metrics(9319, RunningProcess(), timeout=1, interval=0)

    assert metrics == complete_metrics
    assert responses == []
