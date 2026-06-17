# tests/test_notify_telegram.py
"""Tests for notify_telegram: parse_dotenv, credential resolution, send(), fail-soft."""
from __future__ import annotations
import io
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from multi_ship import notify_telegram
from multi_ship.notify_telegram import parse_dotenv


# ---------------------------------------------------------------------------
# STEP 1 / STEP 2: parse_dotenv
# ---------------------------------------------------------------------------

def test_dotenv_blank_lines_ignored():
    assert parse_dotenv("\n\n") == {}


def test_dotenv_comment_lines_ignored():
    assert parse_dotenv("# FOO=bar\n  # BAR=baz\n") == {}


def test_dotenv_export_prefix_stripped():
    result = parse_dotenv("export FOO=bar\n")
    assert result == {"FOO": "bar"}


def test_dotenv_split_on_first_equals():
    result = parse_dotenv("A=b=c\n")
    assert result == {"A": "b=c"}


def test_dotenv_whitespace_stripped_key_and_value():
    result = parse_dotenv("  FOO  =  bar  \n")
    assert result == {"FOO": "bar"}


def test_dotenv_double_quote_pair_stripped_from_value():
    result = parse_dotenv('FOO="hello"\n')
    assert result == {"FOO": "hello"}


def test_dotenv_single_quote_pair_stripped_from_value():
    result = parse_dotenv("FOO='hello'\n")
    assert result == {"FOO": "hello"}


def test_dotenv_quotes_NOT_stripped_from_key():
    # key with quotes stays as-is
    result = parse_dotenv('"KEY"=value\n')
    assert '"KEY"' in result


def test_dotenv_mismatched_quotes_left_intact():
    result = parse_dotenv('FOO=val"\n')
    assert result["FOO"] == 'val"'


def test_dotenv_crlf_handling():
    text = "FOO=bar\r\nBAZ=qux\r\n"
    result = parse_dotenv(text)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_dotenv_later_overrides_earlier():
    result = parse_dotenv("FOO=first\nFOO=second\n")
    assert result == {"FOO": "second"}


def test_dotenv_mixed_content():
    text = """
# comment
export TOKEN=abc123
CHAT_ID=-100987
EMPTY=
"""
    result = parse_dotenv(text)
    assert result["TOKEN"] == "abc123"
    assert result["CHAT_ID"] == "-100987"
    assert result["EMPTY"] == ""


# ---------------------------------------------------------------------------
# STEP 3 / STEP 4: credential resolution (tested through send())
# ---------------------------------------------------------------------------

def _make_cfg(bot_token_env="TELEGRAM_BOT_TOKEN", chat_id_env="TELEGRAM_CHAT_ID",
              env_file=".env", notify="telegram"):
    """Minimal Config-like object for send() tests."""
    return SimpleNamespace(
        notify=notify,
        notify_telegram={
            "bot_token_env": bot_token_env,
            "chat_id_env": chat_id_env,
            "env_file": env_file,
        },
    )


def test_credentials_from_env_used_directly(monkeypatch, tmp_path):
    """Both vars in os.environ -> used; .env never consulted."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append((req, timeout))
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "hello")
    assert len(calls) == 1  # actually sent


def test_credentials_per_variable_env_file_fallback(monkeypatch, tmp_path):
    """One var in env, other only in repo/.env -> both resolved."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok_from_env")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("TELEGRAM_CHAT_ID=-9999\n")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "hello")
    assert len(calls) == 1


def test_credentials_both_absent_no_op_stderr(monkeypatch, tmp_path, capsys):
    """Both absent (env + missing .env) -> returns None, exactly one stderr line."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # .env does not exist

    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: calls.append(1))
    result = notify_telegram.send(_make_cfg(), str(tmp_path), "hello")
    assert result is None
    assert len(calls) == 0
    captured = capsys.readouterr()
    # exactly one stderr line naming the missing var
    stderr_lines = [l for l in captured.err.splitlines() if l.strip()]
    assert len(stderr_lines) == 1
    assert "TELEGRAM_BOT_TOKEN" in stderr_lines[0] or "TELEGRAM_CHAT_ID" in stderr_lines[0]


def test_custom_var_names_honored(monkeypatch, tmp_path):
    """Custom var names from config (bot_token_env='CUSTOM_TOKEN') are honored."""
    monkeypatch.setenv("CUSTOM_TOKEN", "ctok")
    monkeypatch.setenv("CUSTOM_CHAT", "-888")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    cfg = _make_cfg(bot_token_env="CUSTOM_TOKEN", chat_id_env="CUSTOM_CHAT")
    notify_telegram.send(cfg, str(tmp_path), "hello")
    assert len(calls) == 1


def test_chat_id_kept_as_string(monkeypatch, tmp_path):
    """chat_id must be str in the POST body, never int-coerced."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234")
    captured_body = []

    def fake_urlopen(req, timeout=None):
        captured_body.append(req.data)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "msg")
    assert captured_body
    from urllib.parse import parse_qs
    params = parse_qs(captured_body[0].decode())
    # chat_id must be a string (list entry), not an int
    chat_id_val = params["chat_id"][0]
    assert chat_id_val == "-1001234"
    assert isinstance(chat_id_val, str)


def test_missing_env_file_no_crash(monkeypatch, tmp_path, capsys):
    """Missing env_file silently falls back to env-only mode; no exception."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # .env does NOT exist in tmp_path
    cfg = _make_cfg(env_file=".env")

    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: calls.append(1))
    result = notify_telegram.send(cfg, str(tmp_path), "hello")
    assert result is None  # no creds -> no-op
    assert len(calls) == 0
    # should not raise


# ---------------------------------------------------------------------------
# STEP 5 / STEP 6: payload/URL + truncation
# ---------------------------------------------------------------------------

MARKER = "…"  # U+2026 HORIZONTAL ELLIPSIS


def test_url_is_correct(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mytoken")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "test")
    assert captured
    assert captured[0].full_url == "https://api.telegram.org/botmytoken/sendMessage"


def test_body_is_form_urlencoded(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "hello world")
    from urllib.parse import parse_qs
    params = parse_qs(captured[0].data.decode())
    assert params["chat_id"] == ["-200"]
    assert params["text"] == ["hello world"]


def test_urlopen_called_with_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")
    timeout_used = []

    def fake_urlopen(req, timeout=None):
        timeout_used.append(timeout)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    notify_telegram.send(_make_cfg(), str(tmp_path), "msg")
    assert timeout_used and timeout_used[0] is not None


def test_long_message_truncated_to_4096(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    long_msg = "x" * 5000
    notify_telegram.send(_make_cfg(), str(tmp_path), long_msg)
    from urllib.parse import parse_qs
    params = parse_qs(captured[0].data.decode())
    sent_text = params["text"][0]
    assert len(sent_text) <= 4096
    assert sent_text.endswith(MARKER)


def test_short_message_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    short_msg = "hello"
    notify_telegram.send(_make_cfg(), str(tmp_path), short_msg)
    from urllib.parse import parse_qs
    params = parse_qs(captured[0].data.decode())
    sent_text = params["text"][0]
    assert sent_text == short_msg
    assert MARKER not in sent_text


def test_exactly_4096_message_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    exact_msg = "y" * 4096
    notify_telegram.send(_make_cfg(), str(tmp_path), exact_msg)
    from urllib.parse import parse_qs
    params = parse_qs(captured[0].data.decode())
    sent_text = params["text"][0]
    assert sent_text == exact_msg
    assert MARKER not in sent_text


# ---------------------------------------------------------------------------
# STEP 7 / STEP 8: fail-soft network
# ---------------------------------------------------------------------------

def test_urlerror_caught_no_reraise(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-200")

    def bad_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", bad_urlopen)
    result = notify_telegram.send(_make_cfg(), str(tmp_path), "msg")
    assert result is None
    captured = capsys.readouterr()
    stderr_lines = [l for l in captured.err.splitlines() if l.strip()]
    assert len(stderr_lines) == 1
    # bot token must NOT appear in stderr
    assert "tok" not in captured.err


def test_oserror_caught_no_reraise(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok2")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-300")

    def bad_urlopen(req, timeout=None):
        raise OSError("broken pipe")

    monkeypatch.setattr(urllib.request, "urlopen", bad_urlopen)
    result = notify_telegram.send(_make_cfg(), str(tmp_path), "msg")
    assert result is None
    captured = capsys.readouterr()
    stderr_lines = [l for l in captured.err.splitlines() if l.strip()]
    assert len(stderr_lines) == 1
    assert "tok2" not in captured.err


def test_socket_timeout_caught_no_reraise(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok3")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-400")

    def bad_urlopen(req, timeout=None):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", bad_urlopen)
    result = notify_telegram.send(_make_cfg(), str(tmp_path), "msg")
    assert result is None
    captured = capsys.readouterr()
    stderr_lines = [l for l in captured.err.splitlines() if l.strip()]
    assert len(stderr_lines) == 1
    assert "tok3" not in captured.err
