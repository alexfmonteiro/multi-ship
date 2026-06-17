---
Issue: 0
Difficulty: routine
title: "Resolve specs by id and GitHub issue number"
---

# Spec: resolve specs by id and GitHub issue number

## Goal

Let `multi-ship` accept work references the way an operator actually thinks about
them — not just full spec paths. Today the CLI only understands paths and globs
(`multi-ship docs/specs/P14.md`, `docs/specs/P1*.md`). Extend resolution so all of
these work too:

- **Bare spec id:** `multi-ship P14` → `docs/specs/P14.md`
- **Issue reference:** `multi-ship "#42"` or `multi-ship --issue 42` → resolve the
  GitHub issue to its spec file
- **Existing path / glob:** unchanged

The spec directory is derived from the project's configured `spec_glob`, so this
stays domain-agnostic and parametrized — no hardcoded `docs/specs`.

## Design

### Resolution order (per argument)

Enhance spec resolution (in `cli._resolve_specs`, or a new `src/multi_ship/resolve.py`
imported by it). For each positional token, in order:

1. **Glob** — contains any of `*?[` → expand with `glob.glob`, sorted (today).
2. **Existing path** — the token is a path that exists on disk → use as-is (today).
3. **Issue reference** — token matches `^#\d+$` (e.g. `#42`), or the value supplied
   via the new `--issue N` flag → resolve via GitHub (below).
4. **Bare spec id** — anything else with no `/` and not ending in `.md` (e.g.
   `P14`) → `<spec_dir>/<token>.md`.

`<spec_dir>` is `Path(cfg.spec_glob).parent` (e.g. `docs/specs/*.md` → `docs/specs`).

After resolution, if a produced path does **not** exist → stop with a clear error
naming the unresolved reference and exit non-zero. Never start a run against a
spec file that isn't there.

### Resolved decisions (operator)

These pin down the two questions the plan-panel flagged as open, plus one
correctness invariant. Treat them as settled requirements:

1. **Repo-relative base — one base for all forms.** The driver runs resolution
   with `cwd=repo` (`--repo` may differ from the process CWD). The resolver MUST
   take the resolved `repo` Path and resolve every form against it: glob with
   `glob.glob(..., root_dir=repo)`, test existence with `(repo / token).exists()`,
   and derive `<spec_dir>` relative to `repo`. It returns **repo-relative path
   strings** (e.g. `docs/specs/P14.md`) — never absolutized, never CWD-relative —
   so `driver._process_item` keying off `Path(sid).name` / `.stem` stays correct.
2. **Argument order is preserved (input order wins).** The final resolved spec
   list keeps the order the tokens/`--issue` flags were given on the command line;
   the driver runs them in that order. A single glob token still expands to its
   matches in `sorted()` order for determinism, but the overall list is **not**
   re-sorted — this overrides the legacy `_resolve_specs` `sorted()` behavior.
3. **Recursive globs are rejected, not silently stripped.** If `cfg.spec_glob`
   (or a token) contains `**`, deriving `<spec_dir>` via `Path(...).parent` is
   ambiguous (`specs/**/*.md` → `specs/**`). Do NOT strip the glob prefix —
   raise a clear error explaining that recursive `**` spec globs are unsupported
   for `<spec_dir>` derivation, and exit non-zero. A unit test asserts this.

### Issue → spec resolution

Isolate the GitHub call behind a single mockable seam (a module-level function,
e.g. `_gh_issue_title(num) -> str` / `_gh_issue_body(num) -> str`, each shelling
`gh issue view <num> --json <field> -q .<field>`). Resolution strategy:

1. Read the issue **title**. If it starts with a bracketed id prefix
   `^\[([^\]]+)\]` (the burst convention, e.g. `[P14] …`), take that id →
   `<spec_dir>/<id>.md`.
2. Otherwise read the issue **body** and scan for the first `docs/specs/…​.md`-style
   path (more generally, a path ending in `.md` under `<spec_dir>`); use it.
3. If neither yields an existing spec file → clear error naming the issue number.

Keep the `gh` invocation out of the hot path of the pure resolver so unit tests can
monkeypatch it (no real network / no `gh` needed in CI).

### CLI surface

- Add `--issue N` to the argparse parser (repeatable via `action="append"` is a
  nice-to-have; a single value is sufficient for DoD). Each `--issue` value is
  resolved through the issue path and appended to the spec list.
- A positional `#42` token routes through the same issue path.
- Pure digits **without** `#` (e.g. `42`) are treated as a **bare spec id**
  (`<spec_dir>/42.md`), not an issue — `#` is the explicit issue sigil. Document
  this so it's unambiguous.

### Backward compatibility

Existing path and glob usage must be untouched. The default (no positional args)
still falls back to `glob.glob(cfg.spec_glob)`.

## Definition of Done

- [ ] `multi-ship P14` resolves to `<spec_dir>/P14.md`, where `<spec_dir>` comes from `cfg.spec_glob` (not hardcoded).
- [ ] `multi-ship "#42"` and `multi-ship --issue 42` resolve via `gh issue view`: `[id]` title prefix → `<spec_dir>/<id>.md`, falling back to a `*.md` path parsed from the issue body.
- [ ] Existing path args and glob args resolve exactly as before; no-arg run still globs `spec_glob`.
- [ ] A resolved spec path that doesn't exist → clear error message + non-zero exit, and **no** run is started.
- [ ] An issue that resolves to no existing spec → clear error naming the issue number.
- [ ] Pure-digit token without `#` is treated as a spec id, not an issue (documented behavior).
- [ ] The `gh` call is behind a mockable seam; unit tests cover id resolution, issue-title-prefix resolution (gh mocked), issue-body-fallback resolution (gh mocked), glob passthrough, path passthrough, missing-file error, and `spec_dir` derivation from a nested `spec_glob`.
- [ ] Resolution is rebased on the `repo` Path (glob `root_dir=repo`, `(repo/token).exists()`), returns repo-relative strings, and preserves input argument order (not `sorted()`); a recursive `**` spec glob raises a clear error and exits non-zero. Unit tests cover the `repo != CWD` case, order preservation across mixed-form args, and the `**` rejection.
- [ ] `CHANGELOG.md` "Unreleased" entry; `README.md` usage section documents id / `#issue` / `--issue` forms.

## Test plan (TDD order)

1. `spec_dir` from `spec_glob` — `docs/specs/*.md` → `docs/specs`; `*.md` → `.`.
2. Bare-id resolution — `P14` → `<spec_dir>/P14.md` (file exists in a tmp tree).
3. Missing-file error — bare id with no matching file → raises / non-zero, no run.
4. Issue title-prefix extraction — `[P14] title` → `P14` (pure unit, no gh).
5. Issue resolution end-to-end — monkeypatch the gh seam to return a title, assert the spec path; then a no-prefix title with a body link.
6. CLI wiring — `--issue 42` and `#42` both reach the issue path; path/glob still pass through; pure `42` → spec id.
7. Repo-base + order + `**` — resolve with `repo` set to a tmp tree different from CWD (assert it finds the spec there, returns a repo-relative string); mixed-form args come back in input order, not sorted; a `**` spec glob raises the clear error (red → green).

## Notes

- Set `Issue:` to a real tracking issue number before shipping so `Closes #N`
  resolves (the `0` above is a placeholder). This feature is itself about issue
  references — opening a real issue for it makes a nice end-to-end check.
- `gh` must be authenticated in the environment where the run executes; the error
  path for an unauthenticated / missing `gh` should be the same clear, non-crashing
  message as an unresolved reference.
- Don't over-engineer issue-body parsing — first `<spec_dir>/*.md` match wins; the
  title prefix is the primary, most reliable signal.
