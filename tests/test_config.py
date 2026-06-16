# tests/test_config.py
import json
import pytest
from multi_ship.config import load_config, ConfigError

REQUIRED = {
    "build_workflow": "mixed-model-burst",
    "spec_glob": "docs/specs/*.md",
    "verify": "gh pr checks $PR --watch",
    "notify": "echo",
    "pr_body_convention": "Closes #{issue}",
    "complete_cmd": "/complete-spec {slug}",
    "test_cmd": "pytest -x",
    "build_invariants": "TDD test-first",
    "smoke_instructions": "load config; exercise path",
    "roles": {
        "scout": "haiku", "reader": "haiku", "planner": "opus",
        "judges": ["opus", "sonnet", "haiku"],
        "coder": {"hard": "opus", "routine": "sonnet"}, "verifier": "opus",
    },
}

def _write(tmp_path, data):
    p = tmp_path / "multi-ship.json"
    p.write_text(json.dumps(data))
    return p

def test_load_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, REQUIRED))
    assert cfg.build_workflow == "mixed-model-burst"
    assert cfg.roles["judges"] == ["opus", "sonnet", "haiku"]
    assert cfg.roles["coder"]["hard"] == "opus"

def test_missing_key_raises(tmp_path):
    bad = {k: v for k, v in REQUIRED.items() if k != "verify"}
    with pytest.raises(ConfigError, match="verify"):
        load_config(_write(tmp_path, bad))

def test_missing_role_subkey_raises(tmp_path):
    bad = json.loads(json.dumps(REQUIRED))
    del bad["roles"]["planner"]
    with pytest.raises(ConfigError, match="roles.planner"):
        load_config(_write(tmp_path, bad))

def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")

def test_bad_json_raises(tmp_path):
    p = tmp_path / "multi-ship.json"
    p.write_text("{not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(p)
