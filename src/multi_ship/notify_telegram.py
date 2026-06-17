"""Built-in stdlib-only Telegram notification backend.

Public API:
    parse_dotenv(text: str) -> dict[str, str]
    send(cfg, repo: str, message: str) -> None
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Telegram max message length
_MAX_LEN = 4096
# Ellipsis marker appended when truncation occurs
_MARKER = "…"  # U+2026 HORIZONTAL ELLIPSIS
# Network timeout in seconds
_TIMEOUT = 15


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse a .env file text into a dict.

    Rules:
    - Blank lines ignored.
    - Lines whose first non-space char is '#' are comments — ignored.
    - Optional leading 'export ' prefix stripped.
    - Split on FIRST '=' only (so value 'a=b=c' -> 'a=b=c').
    - Whitespace stripped from key and value.
    - A single matching surrounding quote pair stripped from VALUE only
      (double or single quotes); mismatched quotes left intact.
    - CRLF handled via str.splitlines().
    - Later assignment overrides earlier.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # strip optional 'export ' prefix
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        # strip one matching surrounding quote pair from value only
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]
        result[key] = value
    return result


def _resolve_credentials(cfg, repo: str):
    """Return (token, chat_id) or None if either is unavailable."""
    nt = getattr(cfg, "notify_telegram", {}) if hasattr(cfg, "notify_telegram") else {}
    if not isinstance(nt, dict):
        nt = {}

    token_var = nt.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    chat_id_var = nt.get("chat_id_env", "TELEGRAM_CHAT_ID")
    env_file = nt.get("env_file", ".env")

    # Look up each var in os.environ first
    token = os.environ.get(token_var)
    chat_id = os.environ.get(chat_id_var)

    # For any missing var, try the env_file as fallback
    if token is None or chat_id is None:
        env_path = Path(repo) / env_file
        dotenv_data: dict[str, str] = {}
        if env_path.exists():
            try:
                dotenv_data = parse_dotenv(env_path.read_text())
            except OSError:
                pass  # fail-soft: treat as empty
        if token is None:
            token = dotenv_data.get(token_var)
        if chat_id is None:
            chat_id = dotenv_data.get(chat_id_var)

    # If either still missing, print one stderr line and return None
    if not token:
        print(
            f"multi-ship: telegram notify skipped — {token_var} not set in env or .env",
            file=sys.stderr,
        )
        return None
    if not chat_id:
        print(
            f"multi-ship: telegram notify skipped — {chat_id_var} not set in env or .env",
            file=sys.stderr,
        )
        return None

    return token, str(chat_id)  # chat_id always stays a string


def _truncate(message: str) -> str:
    """Truncate message to _MAX_LEN chars, appending _MARKER only if truncated."""
    if len(message) <= _MAX_LEN:
        return message
    # slice to leave room for the marker
    return message[: _MAX_LEN - len(_MARKER)] + _MARKER


def send(cfg, repo: str, message: str) -> None:
    """Send a Telegram message using the bot API.

    Reads credentials from os.environ, falling back to repo/.env.
    Truncates message to 4096 chars.
    Fail-soft on network errors: prints one line to stderr, returns None.
    """
    creds = _resolve_credentials(cfg, repo)
    if creds is None:
        return None

    token, chat_id = creds
    text = _truncate(message)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=body)

    try:
        urllib.request.urlopen(req, timeout=_TIMEOUT)
    except (urllib.error.URLError, OSError) as exc:
        # Deliberately do NOT include the token in the error message
        print(f"multi-ship: telegram notify failed — {exc.__class__.__name__}: {exc.reason if hasattr(exc, 'reason') else exc}", file=sys.stderr)
        return None

    return None
