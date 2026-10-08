import json

import pytest

from a2a_workbench.core.faults.profile import PRESETS, FaultProfile, load_profile


def test_presets_exist():
    assert set(PRESETS) == {
        "stable",
        "flaky_stream",
        "slow_agent",
        "offline",
        "rate_limited",
        "server_error",
    }
    assert PRESETS["stable"].rules == []
    assert PRESETS["flaky_stream"].rules[0].kind == "drop_stream"
    assert all(p.name == key for key, p in PRESETS.items())


def test_load_preset_by_name():
    assert load_profile("offline").rules[0].kind == "refuse"


def test_load_from_file(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"name": "mine", "rules": [{"kind": "delay", "params": {"ms": 5}}]}))
    assert load_profile(str(p)).name == "mine"


def test_bad_spec_is_value_error(tmp_path):
    with pytest.raises(ValueError, match="preset"):
        load_profile("no-such-preset")
    bad = tmp_path / "b.json"
    bad.write_text('{"rules": [{"kind": "explode"}]}')
    with pytest.raises(ValueError):
        load_profile(str(bad))
    notjson = tmp_path / "n.json"
    notjson.write_text("{")
    with pytest.raises(ValueError):
        load_profile(str(notjson))


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "drop_stream", "params": {}},
        {"kind": "http_status", "params": {"code": 99}},
        {"kind": "delay", "params": {"ms": -1}},
        {"kind": "truncate", "params": {}},
        {"kind": "refuse", "mode": "probability", "probability": 2},
    ],
)
def test_param_validation(rule):
    with pytest.raises(ValueError):
        FaultProfile.model_validate({"rules": [rule]})
