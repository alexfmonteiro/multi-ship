"""The orchestration loop. Dumb: routes only on item/verdict JSON files."""
from __future__ import annotations
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import claude_cli, runlog, handoff, endrun, notify_telegram
from .config import Config

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
             state_dir: Path, resume: bool = False) -> dict:
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
    try:
        log = runlog.read_run_log(run_log)
        while True:
            sid = runlog.next_item(log, skip=attempted)
            if sid is None:
                break
            attempted.add(sid)
            try:
                ok = _process_item(sid, repo, cfg, state_dir, run_log)
            except Exception as e:
                # ANY failure in an item (missing skill file, claude -p error, a
                # genuine un-mergeable PR, an unexpected state) must fail just that
                # item and keep the run alive so end-of-run/notify still fires — a
                # single item must never crash the whole driver via an unhandled
                # exception (regression: a CalledProcessError once killed the run).
                try:
                    runlog.set_item_status(run_log, sid, "failed", error=str(e)[:300])
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
        _end_of_run(repo, cfg, state_dir, run_log, shipped, stopped_at, baseline)
    finally:
        _kill_caffeinate(caf)
    return {"shipped": shipped, "stopped_at": stopped_at}

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
    # Build + ship-tail → ship-one writes item-<filename>.json, pauses before merge
    claude_cli.run(f"/ship-one {sid}", repo=repo)
    item = _read_json(state_dir / f"item-{iid}.json")
    if item.get("status") == "failed":
        runlog.set_item_status(run_log, sid, "failed", **{k: item.get(k) for k in ("pr",) if item.get(k)})
        return False
    runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"), branch=item.get("branch"))

    # Cold judge, with one fix retry
    for attempt in range(2):
        claude_cli.run(f"/judge-shipped {sid} {item.get('pr','')}", repo=repo)
        verdict = _read_json(state_dir / f"verdict-{iid}.json")
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
            # re-dispatch ship-one to FIX using the judge's reason, then re-judge
            runlog.set_item_status(run_log, sid, "needs_fix")
            claude_cli.run(_fix_prompt(sid, verdict.get("reason", "")), repo=repo)
            item = _read_json(state_dir / f"item-{iid}.json")
            runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"))
    runlog.set_item_status(run_log, sid, "failed", judge_reason=verdict.get("reason"))
    return False

def _end_of_run(repo: str, cfg: Config, state_dir: Path, run_log: Path,
                shipped: list, stopped_at, baseline: dict):
    log = runlog.read_run_log(run_log)
    handoff_text = (state_dir / "HANDOFF.md").read_text()
    if runlog.worth_dreaming(log, handoff_text):
        claude_cli.run("/dream-run", repo=repo)
    reports = endrun.read_item_reports(state_dir)
    followups = endrun.collect_followups(reports)
    followups_path = None
    if followups:
        fp = Path(state_dir) / "followups.md"
        fp.write_text("# multi-ship follow-ups\n\n" + "\n".join(f"- {f}" for f in followups) + "\n")
        followups_path = str(fp)
    problems = endrun.compare_git_state(baseline, endrun.git_snapshot(repo))
    msg = endrun.format_notification(shipped, stopped_at, followups, str(run_log), followups_path)
    if problems:
        msg += "\n\nWARNING — parent checkout changed unexpectedly:\n" + "\n".join(f"  - {p}" for p in problems)
    if cfg.notify == "telegram":
        notify_telegram.send(cfg, repo, msg)
    else:
        endrun.run_notify(cfg.notify, msg)
