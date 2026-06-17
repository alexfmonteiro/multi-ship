---
Issue: 0
Difficulty: routine
title: "Built-in Telegram notify backend"
---

# Spec: built-in Telegram notify backend

## Goal

Make Telegram a **first-class, built-in notify backend** in multi-ship. When a
project opts in (`"notify": "telegram"`) and a bot token + chat id are available
in the environment or the project's `.env` file, the driver sends its end-of-run
summary straight to Telegram via the Bot API — no per-project shim script, no new
dependencies.

Today `endrun.run_notify` only shells the `notify` string with the message piped
on stdin. Projects that want Telegram have to write a wrapper that sources `.env`,
reads stdin, and calls their own sender. This spec removes that friction: drop the
credentials in `.env`, set `"notify": "telegram"`, done.

## Why built-in (not a shim)

- Zero per-project glue code — any consuming repo gets Telegram for free.
- Keeps the **stdlib-only** invariant: send via `urllib.request`, parse `.env`
  with a tiny hand-rolled reader. No `requests`, no `python-dotenv` — `dependencies`
  in `pyproject.toml` stays `[]`.
- Credentials never enter config or git: they live in `.env` (gitignored) or the
  process environment, and are referenced only by **variable name**.

## Design

### Config surface (parametrized, backward compatible)

`notify` remains the selector:

| `notify` value | Behavior |
|---|---|
| `"telegram"` | **New** — built-in Telegram backend (this spec). |
| `"none"` or `""` | No-op (unchanged). |
| any other string | Shell command, message on stdin (unchanged). |

Add an **optional** config block (absent ⇒ all defaults):

```json
"notify": "telegram",
"notify_telegram": {
  "bot_token_env": "TELEGRAM_BOT_TOKEN",
  "chat_id_env": "TELEGRAM_CHAT_ID",
  "env_file": ".env"
}
```

- `bot_token_env` — env var name holding the bot token. Default `"TELEGRAM_BOT_TOKEN"`.
- `chat_id_env` — env var name holding the destination chat id. Default `"TELEGRAM_CHAT_ID"`.
- `env_file` — repo-relative dotenv file to consult as a fallback. Default `".env"`.

`notify_telegram` is **optional**: it must NOT be added to `_REQUIRED_KEYS`. Extend
the `Config` dataclass with a field defaulting to an empty dict, and have
`load_config` populate it only when present. All existing configs (no
`notify_telegram` key) must continue to load unchanged.

### Credential resolution

Given the two env-var names:

1. Look each up in `os.environ` first (process env wins — 12-factor).
2. For any name not found in the environment, fall back to the dotenv file
   (`env_file`, resolved relative to the repo root) if it exists.
3. If, after both sources, **either** token or chat id is still missing →
   fail-soft: print one clear line to stderr (e.g.
   `multi-ship: telegram notify skipped — TELEGRAM_CHAT_ID not set in env or .env`)
   and return. The run must still exit normally; a missing-credential case is not
   a run failure.

### Dotenv reader (stdlib, minimal)

A small pure function `parse_dotenv(text: str) -> dict[str, str]`:

- Ignore blank lines and lines whose first non-space char is `#`.
- Strip an optional leading `export ` prefix.
- Split on the **first** `=` only.
- Strip surrounding whitespace from key and value, then strip a single matching
  pair of surrounding quotes (`"..."` or `'...'`) from the value.
- Later assignments override earlier ones.

### Sender

`https://api.telegram.org/bot<token>/sendMessage`, POST, form-urlencoded body with
`chat_id` and `text`, via `urllib.request.urlopen` with a timeout (e.g. 15s).

- Truncate `text` to Telegram's 4096-character limit before sending (append an
  ellipsis marker if truncated).
- Wrap the network call so any `urllib.error.URLError` / `OSError` / timeout is
  caught, logged to stderr as a one-liner, and swallowed — same fail-soft contract
  as the current shell `run_notify`.

### Wiring

- New module `src/multi_ship/notify_telegram.py` holding `parse_dotenv`,
  credential resolution, and a `send(cfg, repo, message)` entry point.
- The end-of-run notify call site in `driver._end_of_run` dispatches: when
  `cfg.notify == "telegram"`, call the built-in backend (it needs `repo` to locate
  `env_file` and `cfg.notify_telegram` for the var names); otherwise call the
  existing `endrun.run_notify(cfg.notify, message)` shell path. Keep `run_notify`
  for the shell case — do not break it.

## Definition of Done

- [ ] `"notify": "telegram"` routes the end-of-run summary to the built-in backend; any other non-empty value still shells exactly as before; `"none"`/`""` still no-op.
- [ ] Bot token and chat id resolve from `os.environ` first, then from the configured `env_file` (default `.env`) as a fallback.
- [ ] `notify_telegram` config block is **optional** with documented defaults (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `.env`); existing configs without the block load unchanged.
- [ ] Missing token or chat id → one clear stderr line and a graceful no-op; the run still exits 0.
- [ ] Message is truncated to ≤4096 chars before sending.
- [ ] Network/transport errors are caught and swallowed (fail-soft), never crashing the run.
- [ ] `pyproject.toml` `dependencies` stays `[]` — implementation is stdlib-only (`urllib`, no new packages).
- [ ] Unit tests cover: dotenv parsing (comments, `export`, quotes, first-`=` split, override); env-precedence-over-dotenv; missing-credential no-op; payload/URL construction with `urlopen` mocked; 4096 truncation; backend selection (`telegram` vs shell vs none); optional-config defaults.
- [ ] `CHANGELOG.md` "Unreleased" gets an entry; `README.md` notify section documents the `telegram` backend and the env vars.

## Test plan (TDD order)

1. `parse_dotenv` — failing test for comment/blank/`export`/quote/first-`=` handling → implement.
2. Credential resolution — env present; env absent + dotenv fallback; both absent (no-op). Mock `os.environ` and a temp `.env`.
3. Payload builder — assert URL is `…/bot<token>/sendMessage` and body carries `chat_id`+`text`; mock `urllib.request.urlopen`.
4. Truncation — message >4096 is cut to ≤4096.
5. Dispatch — `cfg.notify == "telegram"` calls the backend; other values call the shell `run_notify` (mock both).
6. Config — `notify_telegram` absent ⇒ defaults; present ⇒ overrides parsed.

## Notes

- Set `Issue:` to a real tracking issue number before shipping so the PR body's
  `Closes #N` resolves (the `0` above is a placeholder).
- For dogfooding on the multi-ship repo itself, drop a gitignored `.env` with
  `TELEGRAM_BOT_TOKEN=…` and `TELEGRAM_CHAT_ID=…` and set `"notify": "telegram"`
  in `.claude/multi-ship.json`.
- Keep the chat-id value as a string end-to-end (Telegram chat ids can be negative
  for groups; don't coerce to int).
