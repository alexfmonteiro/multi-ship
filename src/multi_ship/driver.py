"""The orchestration loop. Dumb: routes only on item/verdict JSON files."""
from __future__ import annotations
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import claude_cli, runlog, handoff, endrun, notify_telegram
from .config import Config

try:  # zoneinfo is stdlib 3.9+, but stay fail-soft if the tz db is missing
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

# --wait-for-quota guards
_MAX_QUOTA_WAIT_S = 6 * 3600     # never sleep more than 6h on one reset
_QUOTA_FALLBACK_WAIT_S = 1800    # unparseable reset phrase -> re-probe in 30 min
_MAX_WAIT_CYCLES = 8             # backstop against an infinite wait loop

_RESET_TIME_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(([^)]+)\))?", re.I)

def _seconds_until_reset(resets_at: str | None) -> int | None:
    """Best-effort parse of a quota-reset phrase ("5:20pm (America/Sao_Paulo)",
    "11:20am", "5pm") -> seconds from now until that time. None if unparseable.
    Honours a named tz when present and resolvable; else uses local time."""
    if not resets_at:
        return None
    m = _RESET_TIME_RE.search(resets_at)
    if not m or not m.group(1):
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ampm, tzname = (m.group(3) or "").lower(), m.group(4)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    tz = None
    if tzname and ZoneInfo is not None:
        try:
            tz = ZoneInfo(tzname.strip())
        except Exception:
            tz = None
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())

def _wait_for_quota(resets_at: str | None, repo: str) -> bool:
    """Sleep until the quota reset (clamped to [60s, 6h], +60s buffer), then
    re-probe. Returns True iff the quota is available afterward. Only called when
    --wait-for-quota is set."""
    secs = _seconds_until_reset(resets_at)
    secs = _QUOTA_FALLBACK_WAIT_S if secs is None else secs + 60
    secs = min(max(secs, 60), _MAX_QUOTA_WAIT_S)
    sys.stderr.write(
        f"multi-ship: session quota exhausted; --wait-for-quota sleeping {secs}s"
        + (f" (resets {resets_at})" if resets_at else "") + " then re-probing...\n")
    time.sleep(secs)
    available, _ = claude_cli.probe_quota(repo)
    return available

def _stay_awake_cmd() -> list[str] | None:
    """Return a long-running command that blocks system sleep on this OS, or
    None if no inhibitor is available (the run just isn't sleep-protected).

    macOS  -> caffeinate -dimsu
    Linux  -> systemd-inhibit ... sleep infinity (when systemd is present)
    other  -> None (no-op)
    """
    system = platform.system()
    if system == "Darwin" and shutil.which("caffeinate"):
        return ["caffeinate", "-dimsu"]
    if system == "Linux" and shutil.which("systemd-inhibit"):
        return ["systemd-inhibit", "--what=idle:sleep:shutdown",
                "--why=multi-ship run in progress", "--mode=block",
                "sleep", "infinity"]
    return None

def _caffeinate():
    cmd = _stay_awake_cmd()
    if cmd is None:
        return None
    try:
        return subprocess.Popen(cmd)
    except (FileNotFoundError, OSError):
        return None  # inhibitor vanished between probe and spawn: stay fail-soft

def _kill_caffeinate(proc):
    if proc:
        proc.terminate()

def _cleanup_worktree(branch: str, repo: str):
    """Remove the build worktree checked out to `branch`, if any. Fail-soft: a
    cleanup failure (or a missing git) must never crash the run. Parses
    `git worktree list --porcelain` (blank-line-separated blocks of `worktree
    <path>` / `branch refs/heads/<name>`)."""
    if not branch:
        return
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    target, path = f"refs/heads/{branch}", None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and line[len("branch "):] == target and path:
            try:
                subprocess.run(["git", "worktree", "remove", "--force", path], cwd=repo,
                               check=True, capture_output=True, text=True)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                stderr = getattr(e, "stderr", "") or ""
                sys.stderr.write(f"multi-ship: worktree cleanup for {branch} failed "
                                 f"(non-fatal): {stderr.strip()}\n")
            return

def _pr_state(pr: str, repo: str) -> str:
    try:
        r = subprocess.run(["gh", "pr", "view", pr, "--json", "state", "-q", ".state"],
                           cwd=repo, capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

def _merge_pr(pr: str, repo: str):
    r = subprocess.run(["gh", "pr", "merge", pr, "--squash", "--delete-branch"],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode == 0:
        return
    # Non-zero can mean the squash merge succeeded but post-merge branch cleanup
    # failed (e.g. a leftover build worktree still has the branch checked out).
    # That must NOT crash the run — fail-soft per the repo invariant. Only re-raise
    # if the PR did not actually merge (a real merge failure must fail the item).
    if _pr_state(pr, repo) == "MERGED":
        sys.stderr.write(f"multi-ship: {pr} merged but branch cleanup failed "
                         f"(non-fatal): {(r.stderr or '').strip()}\n")
        return
    raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)

def _read_json(p: Path) -> dict:
    return json.loads(Path(p).read_text())

def _fix_prompt(sid: str, reason: str) -> str:
    """Build the --fix re-dispatch prompt, neutralizing quotes/newlines in the
    judge-authored reason so the single quoted arg isn't split."""
    safe = (reason or "").replace('"', "'").replace("\n", " ").strip()
    return f'/ship-one {sid} --fix "{safe}"'

def run_loop(repo: str, specs: list[str], cfg: Config, stop_on_failure: bool,
             state_dir: Path, resume: bool = False,
             wait_for_quota: bool = False) -> dict:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    run_log = state_dir / "run-log.json"
    if not run_log.exists():
        runlog.init_run_log(run_log, order=specs, stop_on_failure=stop_on_failure,
                            notification_surface=cfg.notify)
    elif resume:
        runlog.reset_for_resume(run_log)
    init_h = state_dir / "HANDOFF.md"
    handoff.init_handoff(init_h)
    baseline = endrun.git_snapshot(repo)

    caf = _caffeinate()
    shipped, stopped_at, attempted = [], None, set()
    paused = None  # set to {"item", "resets_at"} when we stop on quota
    wait_cycles = 0

    def _on_quota(sid: str, resets_at: str | None) -> str:
        """Shared quota handling. Returns 'retry' (waited, quota back — re-loop),
        or 'pause' (stop cleanly). Never marks the item failed: quota is not an
        item failure, so the item is left/reset to pending for a clean --resume."""
        nonlocal wait_cycles, paused
        try:
            runlog.force_pending(run_log, sid, failure_kind=None,
                                 paused_reason="quota_exhausted", resets_at=resets_at)
        except (runlog.StatusError, KeyError):
            pass
        if wait_for_quota and wait_cycles < _MAX_WAIT_CYCLES:
            wait_cycles += 1
            if _wait_for_quota(resets_at, repo):
                return "retry"
        paused = {"item": sid, "resets_at": resets_at}
        return "pause"

    try:
        log = runlog.read_run_log(run_log)
        while True:
            sid = runlog.next_item(log, skip=attempted)
            if sid is None:
                break
            # Pre-flight quota probe: surface exhaustion BEFORE spending a full
            # multi-agent build that the inner workflow would only half-finish
            # and report ambiguously. Cheap (one tiny claude -p), fail-open.
            available, resets_at = claude_cli.probe_quota(repo)
            if not available:
                if _on_quota(sid, resets_at) == "retry":
                    log = runlog.read_run_log(run_log)
                    continue
                break
            attempted.add(sid)
            try:
                ok = _process_item(sid, repo, cfg, state_dir, run_log)
            except claude_cli.QuotaExhausted as q:
                # Quota ran out mid-item (e.g. during judge/complete). Not a
                # failure — pause/retry cleanly; the item is reset to pending.
                attempted.discard(sid)
                if _on_quota(sid, q.resets_at) == "retry":
                    log = runlog.read_run_log(run_log)
                    continue
                break
            except Exception as e:
                # ANY other failure (missing skill file, claude -p error, a
                # genuine un-mergeable PR, an unexpected state) must fail just that
                # item and keep the run alive so end-of-run/notify still fires — a
                # single item must never crash the whole driver via an unhandled
                # exception (regression: a CalledProcessError once killed the run).
                try:
                    runlog.set_item_status(run_log, sid, "failed",
                                           error=str(e)[:300], failure_kind="error")
                except runlog.StatusError:
                    pass
                ok = False
            log = runlog.read_run_log(run_log)
            if ok:
                shipped.append(sid)
            else:
                if runlog.should_stop(log, item_failed=True):
                    stopped_at = sid
                    break
        _end_of_run(repo, cfg, state_dir, run_log, shipped, stopped_at, baseline,
                    paused=paused)
    finally:
        _kill_caffeinate(caf)
    return {"shipped": shipped, "stopped_at": stopped_at, "paused": paused}

def _judge_verdict(sid: str, iid: str, pr: str, repo: str, state_dir: Path) -> dict:
    """Run the cold judge and return a FRESH verdict dict.

    Fail-open per the documented contract (README: a flaky judge can't trap a
    good run): a judge crash, an unreadable verdict, or a judge session that
    returns without rewriting verdict-<id>.json all yield {ok: true} with a
    fail-open reason. Freshness is checked by mtime so a stale verdict from a
    prior round is never trusted. Quota exhaustion is NOT a judge failure — it
    propagates so the driver pauses cleanly."""
    vpath = state_dir / f"verdict-{iid}.json"
    before = vpath.stat().st_mtime_ns if vpath.exists() else 0
    try:
        claude_cli.run(f"/judge-shipped {sid} {pr}", repo=repo)
    except claude_cli.QuotaExhausted:
        raise
    except claude_cli.ClaudeError as e:
        sys.stderr.write(f"multi-ship: judge run for {iid} failed — fail-open: {e}\n")
        return {"ok": True, "reason": f"judge could not run — fail-open: {str(e)[:200]}"}
    if not vpath.exists() or vpath.stat().st_mtime_ns <= before:
        sys.stderr.write(
            f"multi-ship: judge wrote no fresh verdict for {iid} — fail-open\n")
        return {"ok": True, "reason": "judge produced no fresh verdict — fail-open"}
    try:
        return _read_json(vpath)
    except (json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"multi-ship: unreadable verdict for {iid} — fail-open: {e}\n")
        return {"ok": True, "reason": f"unreadable verdict — fail-open: {str(e)[:200]}"}

def _process_item(sid: str, repo: str, cfg: Config, state_dir: Path, run_log: Path) -> bool:
    # State files are keyed by the spec FILENAME (the skill contract), not the
    # full spec path — a path like docs/specs/x.md would otherwise become a
    # nested filename `item-docs/specs/x.md.json`. The prompt still gets the full
    # spec path so the skill can locate the spec.
    iid = Path(sid).name
    # Idempotent recovery: if a prior attempt already merged this item's PR (a
    # crash can leave the run-log non-shipped while the PR is merged on GitHub),
    # don't rebuild/re-judge/re-merge — just finish the interrupted tail (archive
    # + shipped). Cheap to check, saves a full build cycle on resume.
    prev_path = state_dir / f"item-{iid}.json"
    if prev_path.exists():
        prev = _read_json(prev_path)
        if prev.get("pr") and _pr_state(prev["pr"], repo) == "MERGED":
            runlog.set_item_status(run_log, sid, "awaiting_judge",
                                   pr=prev.get("pr"), branch=prev.get("branch"))
            _cleanup_worktree(prev.get("branch"), repo)
            claude_cli.run(cfg.complete_cmd.format(slug=Path(sid).stem), repo=repo)
            runlog.set_item_status(run_log, sid, "shipped")
            return True
    # Build + ship-tail → ship-one writes item-<filename>.json, pauses before merge.
    # Stamp the time first so we can detect a STALE report: if ship-one returns
    # but never rewrites item-<id>.json (a quota/crash mid-build can leave the
    # prior round's file in place), reading it would record a misleading status
    # (e.g. a stale plan_gate_rework). Treat "no fresh report" as an honest error.
    item_path = state_dir / f"item-{iid}.json"
    before = item_path.stat().st_mtime_ns if item_path.exists() else 0
    claude_cli.run(f"/ship-one {sid}", repo=repo)
    if not item_path.exists() or item_path.stat().st_mtime_ns <= before:
        raise claude_cli.ClaudeError(
            f"ship-one produced no fresh item report for {iid} "
            "(stale/unchanged item-<id>.json — likely quota or crash mid-build)")
    item = _read_json(item_path)
    if item.get("status") == "failed":
        fields = {k: item.get(k) for k in ("pr", "parent_notes") if item.get(k)}
        fields["failure_kind"] = item.get("failure_kind") or "unknown"
        runlog.set_item_status(run_log, sid, "failed", **fields)
        return False
    if not item.get("pr"):
        raise claude_cli.ClaudeError(
            f"ship-one report for {iid} has status '{item.get('status')}' but no 'pr' "
            "— cannot judge or merge")
    runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"), branch=item.get("branch"))

    # Cold judge, with one fix retry
    for attempt in range(2):
        verdict = _judge_verdict(sid, iid, item.get("pr", ""), repo, state_dir)
        if verdict.get("ok"):
            # Remove the build worktree first so it stops leaking AND can't hold
            # the branch open against `gh pr merge --delete-branch`.
            _cleanup_worktree(item.get("branch"), repo)
            _merge_pr(item["pr"], repo)
            slug = Path(sid).stem
            claude_cli.run(cfg.complete_cmd.format(slug=slug), repo=repo)
            runlog.set_item_status(run_log, sid, "shipped")
            return True
        if attempt == 0:
            # re-dispatch ship-one to FIX using the judge's reason, then re-judge.
            # Same freshness + failed-status discipline as the first build: a fix
            # that crashed without rewriting the report must not be re-judged
            # from stale data, and an honest failed fix keeps the builder's kind.
            runlog.set_item_status(run_log, sid, "needs_fix")
            fix_before = item_path.stat().st_mtime_ns if item_path.exists() else 0
            claude_cli.run(_fix_prompt(sid, verdict.get("reason", "")), repo=repo)
            if not item_path.exists() or item_path.stat().st_mtime_ns <= fix_before:
                raise claude_cli.ClaudeError(
                    f"ship-one --fix produced no fresh item report for {iid} "
                    "(stale/unchanged item-<id>.json — likely quota or crash mid-fix)")
            item = _read_json(item_path)
            if item.get("status") == "failed":
                fields = {k: item.get(k) for k in ("pr", "parent_notes") if item.get(k)}
                fields["failure_kind"] = item.get("failure_kind") or "unknown"
                runlog.set_item_status(run_log, sid, "failed", **fields)
                return False
            runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"))
    jf = {"judge_reason": verdict.get("reason"), "failure_kind": "judge_rejected"}
    if item.get("parent_notes"):
        jf["parent_notes"] = item.get("parent_notes")
    runlog.set_item_status(run_log, sid, "failed", **jf)
    return False

def _end_of_run(repo: str, cfg: Config, state_dir: Path, run_log: Path,
                shipped: list, stopped_at, baseline: dict, paused: dict | None = None):
    log = runlog.read_run_log(run_log)
    handoff_text = (state_dir / "HANDOFF.md").read_text()
    # dream-run is OPTIONAL end-of-run consolidation — it must NEVER crash the
    # driver. (Regression: an unwrapped /dream-run that hit the session quota
    # raised QuotaExhausted past the loop's handlers and killed the run with a
    # traceback.) Skip it entirely if we're pausing on quota — the window is shut.
    if paused is None and runlog.worth_dreaming(log, handoff_text):
        try:
            claude_cli.run("/dream-run", repo=repo)
        except claude_cli.ClaudeError as e:
            sys.stderr.write(f"multi-ship: /dream-run skipped (non-fatal): {e}\n")
    reports = endrun.read_item_reports(state_dir)
    followups = endrun.collect_followups(reports)
    followups_path = None
    if followups:
        fp = Path(state_dir) / "followups.md"
        fp.write_text("# multi-ship follow-ups\n\n" + "\n".join(f"- {f}" for f in followups) + "\n")
        followups_path = str(fp)
    problems = endrun.compare_git_state(baseline, endrun.git_snapshot(repo))
    stop_kind = stop_notes = None
    if stopped_at:
        stopped_item = next((it for it in log["items"] if it["id"] == stopped_at), None)
        if stopped_item is not None:
            stop_kind = stopped_item.get("failure_kind")
            stop_notes = stopped_item.get("parent_notes")
    msg = endrun.format_notification(shipped, stopped_at, followups, str(run_log),
                                     followups_path, stop_kind=stop_kind,
                                     stop_notes=stop_notes)
    if paused:
        resets = paused.get("resets_at")
        msg += ("\n\nPAUSED — Claude session quota exhausted"
                + (f" (resets {resets})" if resets else "")
                + f".\nItem left pending: {paused.get('item')}. "
                "Re-run with --resume after the reset to continue.")
    if problems:
        msg += "\n\nWARNING — parent checkout changed unexpectedly:\n" + "\n".join(f"  - {p}" for p in problems)
    if cfg.notify == "telegram":
        notify_telegram.send(cfg, repo, msg)
    else:
        endrun.run_notify(cfg.notify, msg)
