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


# ---------------------------------------------------------------------------
# STEP 9 / STEP 10: optional notify_telegram field
# ---------------------------------------------------------------------------

def test_config_without_notify_telegram_defaults_to_empty_dict(tmp_path):
    """A config that omits notify_telegram must still load and expose {} default."""
    cfg = load_config(_write(tmp_path, REQUIRED))
    assert cfg.notify_telegram == {}


def test_config_with_notify_telegram_parses_dict(tmp_path):
    """A config WITH notify_telegram dict is available on cfg.notify_telegram."""
    data = dict(REQUIRED)
    data["notify_telegram"] = {
        "bot_token_env": "MY_BOT_TOKEN",
        "chat_id_env": "MY_CHAT_ID",
        "env_file": ".secrets",
    }
    cfg = load_config(_write(tmp_path, data))
    assert cfg.notify_telegram == {
        "bot_token_env": "MY_BOT_TOKEN",
        "chat_id_env": "MY_CHAT_ID",
        "env_file": ".secrets",
    }


def test_notify_telegram_not_in_required_keys(tmp_path):
    """notify_telegram must NOT be in _REQUIRED_KEYS — omitting it must not raise."""
    from multi_ship.config import _REQUIRED_KEYS
    assert "notify_telegram" not in _REQUIRED_KEYS
    # omitting it should not raise ConfigError
    cfg = load_config(_write(tmp_path, REQUIRED))
    assert hasattr(cfg, "notify_telegram")
