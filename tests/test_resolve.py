"""Tests for src/multi_ship/resolve.py — spec/issue resolver.

TDD: all tests are written before the implementation. Run with:
    PYTHONPATH=src pytest tests/test_resolve.py -q
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from multi_ship.config import Config, load_config
from multi_ship.resolve import ResolveError, resolve_specs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATE = Path(__file__).parent.parent / "templates" / "multi-ship.json"

def _make_cfg(spec_glob: str = "docs/specs/*.md") -> Config:
    """Build a minimal Config with the given spec_glob."""
    return load_config(TEMPLATE)._replace(spec_glob=spec_glob)  # type: ignore[attr-defined]


def _make_cfg_direct(spec_glob: str = "docs/specs/*.md") -> Config:
    """Build Config directly without relying on _replace (frozen dataclass)."""
    import dataclasses
    base = load_config(TEMPLATE)
    return dataclasses.replace(base, spec_glob=spec_glob)


def _cfg(spec_glob: str = "docs/specs/*.md") -> Config:
    return _make_cfg_direct(spec_glob)


# ---------------------------------------------------------------------------
# 1. spec_dir derivation
# ---------------------------------------------------------------------------

class TestSpecDirDerivation:
    """test_spec_dir_from_spec_glob"""

    def test_nested_spec_dir(self, tmp_path):
        """docs/specs/*.md -> spec_dir docs/specs"""
        cfg = _cfg("docs/specs/*.md")
        repo = tmp_path
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "P14.md").write_text("# P14")
        result = resolve_specs(["P14"], [], cfg, repo)
        assert result == ["docs/specs/P14.md"]

    def test_dot_spec_dir(self, tmp_path):
        """*.md -> spec_dir '.' -> bare id produces 'P14.md' (no './' prefix)"""
        cfg = _cfg("*.md")
        (tmp_path / "P14.md").write_text("# P14")
        result = resolve_specs(["P14"], [], cfg, tmp_path)
        assert result == ["P14.md"]
        # Ensure Path(sid).name == 'P14.md' (no ./ prefix)
        assert Path(result[0]).name == "P14.md"


# ---------------------------------------------------------------------------
# 2. Bare-id resolution
# ---------------------------------------------------------------------------

class TestBareIdResolution:
    """test_bare_id_resolution: repo != CWD"""

    def test_bare_id_nested(self, tmp_path):
        """P14 -> docs/specs/P14.md (repo != process CWD)"""
        cfg = _cfg("docs/specs/*.md")
        spec_file = tmp_path / "docs" / "specs" / "P14.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# P14")
        # Intentionally do NOT chdir to tmp_path (repo != CWD)
        result = resolve_specs(["P14"], [], cfg, tmp_path)
        assert result == ["docs/specs/P14.md"]

    def test_bare_id_dot_spec_dir(self, tmp_path):
        """spec_glob *.md + token P14 -> P14.md at repo root"""
        cfg = _cfg("*.md")
        (tmp_path / "P14.md").write_text("# P14")
        result = resolve_specs(["P14"], [], cfg, tmp_path)
        assert result == ["P14.md"]

    def test_token_with_slash_is_not_bare_id(self, tmp_path):
        """A token with a slash is NOT a bare id; if it doesn't exist -> error."""
        cfg = _cfg("docs/specs/*.md")
        with pytest.raises(ResolveError, match="docs/specs/P14.md"):
            resolve_specs(["docs/specs/P14.md"], [], cfg, tmp_path)

    def test_token_ending_in_md_is_not_bare_id(self, tmp_path):
        """A token ending in .md is not a bare id; treated as existing-path -> error if missing."""
        cfg = _cfg("docs/specs/*.md")
        with pytest.raises(ResolveError):
            resolve_specs(["P14.md"], [], cfg, tmp_path)

    def test_pure_digit_is_bare_id_not_issue(self, tmp_path, monkeypatch):
        """test_pure_digit_is_bare_id: '42' routes to bare id, NOT issue path."""
        cfg = _cfg("docs/specs/*.md")
        spec_file = tmp_path / "docs" / "specs" / "42.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# 42")

        # gh seam must NOT be called
        called = []

        def fake_title(num):
            called.append(num)
            return "[42] something"

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", fake_title)
        result = resolve_specs(["42"], [], cfg, tmp_path)
        assert result == ["docs/specs/42.md"]
        assert called == [], "gh seam must not be called for bare digit token"


# ---------------------------------------------------------------------------
# 3. Missing-file error (existence gate)
# ---------------------------------------------------------------------------

class TestMissingFileError:
    """test_missing_file_error"""

    def test_bare_id_missing_raises(self, tmp_path):
        """Bare id with no matching file -> ResolveError."""
        cfg = _cfg("docs/specs/*.md")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        with pytest.raises(ResolveError, match="P99"):
            resolve_specs(["P99"], [], cfg, tmp_path)

    def test_existing_path_missing_raises(self, tmp_path):
        """An explicit path that doesn't exist -> ResolveError."""
        cfg = _cfg("docs/specs/*.md")
        with pytest.raises(ResolveError):
            resolve_specs(["docs/specs/nonexistent.md"], [], cfg, tmp_path)

    def test_no_run_started_on_missing(self, tmp_path, monkeypatch):
        """CLI exits non-zero and driver.run_loop is NOT called when a path is missing."""
        import shutil
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")

        called = []

        def fake_run_loop(**kw):
            called.append(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        rc = cli.main(["NonExistentSpec", "--repo", str(tmp_path)])
        assert rc != 0
        assert called == []


# ---------------------------------------------------------------------------
# 4. Issue title-prefix extraction (pure unit — no gh, no I/O)
# ---------------------------------------------------------------------------

class TestIssueTitlePrefixExtraction:
    """test_issue_title_prefix_extraction"""

    def test_bracket_prefix_extracts(self):
        import re
        m = re.match(r"^\[([^\]]+)\]", "[P14] fix the thing")
        assert m is not None
        assert m.group(1) == "P14"

    def test_malformed_no_close_bracket(self):
        import re
        m = re.match(r"^\[([^\]]+)\]", "[P14 missing close")
        assert m is None

    def test_malformed_no_open_bracket(self):
        import re
        m = re.match(r"^\[([^\]]+)\]", "P14] reversed")
        assert m is None

    def test_no_prefix(self):
        import re
        m = re.match(r"^\[([^\]]+)\]", "Just a plain title")
        assert m is None


# ---------------------------------------------------------------------------
# 5. Issue resolution — end-to-end (gh mocked)
# ---------------------------------------------------------------------------

class TestIssueResolution:
    """test_issue_resolution_title_path + test_issue_resolution_body_fallback"""

    def test_title_prefix_path(self, tmp_path, monkeypatch):
        """_gh_issue_title returns '[P14] something' -> resolves to docs/specs/P14.md"""
        cfg = _cfg("docs/specs/*.md")
        spec_file = tmp_path / "docs" / "specs" / "P14.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# P14")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "[P14] something")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "no path here")
        result = resolve_specs(["#14"], [], cfg, tmp_path)
        assert result == ["docs/specs/P14.md"]

    def test_body_fallback_path(self, tmp_path, monkeypatch):
        """Title has no prefix; body contains docs/specs/foo.md path -> resolves to it"""
        cfg = _cfg("docs/specs/*.md")
        spec_file = tmp_path / "docs" / "specs" / "foo.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# foo")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "No bracket title")
        monkeypatch.setattr(
            "multi_ship.resolve._gh_issue_body",
            lambda n: "See spec at docs/specs/foo.md for details",
        )
        result = resolve_specs(["#42"], [], cfg, tmp_path)
        assert result == ["docs/specs/foo.md"]

    def test_issue_via_issue_numbers_arg(self, tmp_path, monkeypatch):
        """--issue 42 (passed as issue_numbers=[42]) resolves via gh seam."""
        cfg = _cfg("docs/specs/*.md")
        spec_file = tmp_path / "docs" / "specs" / "P14.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# P14")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "[P14] something")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "")
        result = resolve_specs([], [42], cfg, tmp_path)
        assert result == ["docs/specs/P14.md"]

    def test_issue_unresolvable_raises(self, tmp_path, monkeypatch):
        """test_issue_unresolvable_errors: neither title prefix nor body yields existing file."""
        cfg = _cfg("docs/specs/*.md")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "No bracket")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "no path here")
        with pytest.raises(ResolveError, match="42"):
            resolve_specs(["#42"], [], cfg, tmp_path)

    def test_gh_failure_clear_error(self, tmp_path, monkeypatch):
        """test_gh_failure_is_clear_error: FileNotFoundError from gh -> clear ResolveError."""
        cfg = _cfg("docs/specs/*.md")
        (tmp_path / "docs" / "specs").mkdir(parents=True)

        def fake_title(n):
            raise FileNotFoundError("gh not found")

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", fake_title)
        with pytest.raises(ResolveError, match="#42"):
            resolve_specs(["#42"], [], cfg, tmp_path)

    def test_gh_called_process_error_clear(self, tmp_path, monkeypatch):
        """CalledProcessError from gh -> clear ResolveError naming issue number."""
        cfg = _cfg("docs/specs/*.md")
        (tmp_path / "docs" / "specs").mkdir(parents=True)

        def fake_title(n):
            raise subprocess.CalledProcessError(1, "gh")

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", fake_title)
        with pytest.raises(ResolveError, match="#42"):
            resolve_specs(["#42"], [], cfg, tmp_path)


# ---------------------------------------------------------------------------
# 6. CLI wiring — --issue flag and #N token
# ---------------------------------------------------------------------------

class TestCLIWiring:
    """test_cli_wiring_issue_flag"""

    def test_issue_flag_repeatable(self, tmp_path, monkeypatch):
        """--issue is repeatable (action=append); multiple --issue flags produce all specs."""
        import shutil
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")

        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P14.md").write_text("# P14")
        (spec_dir / "P15.md").write_text("# P15")

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: f"[P1{n}] spec")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "")

        captured = {}

        def fake_run_loop(**kw):
            captured.update(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        rc = cli.main(["--issue", "4", "--issue", "5", "--repo", str(tmp_path)])
        assert rc == 0
        assert captured["specs"] == ["docs/specs/P14.md", "docs/specs/P15.md"]

    def test_issue_flag_rejects_non_integer(self, tmp_path, capsys):
        """--issue abc should fail at argparse layer (type=int)."""
        import shutil
        from multi_ship import cli

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--issue", "abc", "--repo", str(tmp_path)])
        assert exc_info.value.code != 0

    def test_hash_token_routes_to_issue(self, tmp_path, monkeypatch):
        """'#42' positional routes to issue resolution."""
        import shutil
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")

        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P14.md").write_text("# P14")

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "[P14] spec")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "")

        captured = {}

        def fake_run_loop(**kw):
            captured.update(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        rc = cli.main(["#42", "--repo", str(tmp_path)])
        assert rc == 0
        assert captured["specs"] == ["docs/specs/P14.md"]

    def test_path_and_glob_pass_through(self, tmp_path, monkeypatch):
        """Explicit path and glob still work, unchanged."""
        import shutil
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")

        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P14.md").write_text("# P14")
        (spec_dir / "P15.md").write_text("# P15")

        captured = {}

        def fake_run_loop(**kw):
            captured.update(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        # Existing path
        rc = cli.main(["docs/specs/P14.md", "--repo", str(tmp_path)])
        assert rc == 0
        assert captured["specs"] == ["docs/specs/P14.md"]

    def test_no_arg_fallback_globs_spec_glob(self, tmp_path, monkeypatch):
        """test_no_arg_fallback_globs_spec_glob: no specs, no --issue -> globs cfg.spec_glob."""
        import shutil
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")

        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "A.md").write_text("# A")
        (spec_dir / "B.md").write_text("# B")

        captured = {}

        def fake_run_loop(**kw):
            captured.update(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        rc = cli.main(["--repo", str(tmp_path)])
        assert rc == 0
        # Should glob and return repo-relative paths sorted
        assert "docs/specs/A.md" in captured["specs"]
        assert "docs/specs/B.md" in captured["specs"]


# ---------------------------------------------------------------------------
# 7. Glob passthrough, order preservation, repo != CWD
# ---------------------------------------------------------------------------

class TestGlobAndOrder:
    """test_glob_passthrough_sorted + test_order_preserved + test_repo_not_cwd"""

    def test_glob_passthrough_sorted(self, tmp_path):
        """Glob token expands to sorted matches, repo-relative."""
        cfg = _cfg("docs/specs/*.md")
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P11.md").write_text("# P11")
        (spec_dir / "P12.md").write_text("# P12")
        (spec_dir / "P13.md").write_text("# P13")
        result = resolve_specs(["docs/specs/P1*.md"], [], cfg, tmp_path)
        assert result == ["docs/specs/P11.md", "docs/specs/P12.md", "docs/specs/P13.md"]

    def test_existing_single_path_unchanged(self, tmp_path):
        """An existing explicit path passes through as-is (repo-relative)."""
        cfg = _cfg("docs/specs/*.md")
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P14.md").write_text("# P14")
        result = resolve_specs(["docs/specs/P14.md"], [], cfg, tmp_path)
        assert result == ["docs/specs/P14.md"]

    def test_order_preserved_across_mixed_forms(self, tmp_path, monkeypatch):
        """test_order_preserved_across_mixed_forms: input order wins, globs expand sorted internally."""
        cfg = _cfg("docs/specs/*.md")
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "x.md").write_text("# x")
        (spec_dir / "P20.md").write_text("# P20")
        (spec_dir / "P11.md").write_text("# P11")
        (spec_dir / "P12.md").write_text("# P12")
        (spec_dir / "P13.md").write_text("# P13")

        monkeypatch.setattr("multi_ship.resolve._gh_issue_title", lambda n: "[x] spec")
        monkeypatch.setattr("multi_ship.resolve._gh_issue_body", lambda n: "")

        # Input: explicit path, issue ref, bare id, glob
        # Using P20 as bare id so the glob 'docs/specs/P1*.md' does NOT match it
        tokens = ["docs/specs/x.md", "#42", "P20", "docs/specs/P1*.md"]
        result = resolve_specs(tokens, [], cfg, tmp_path)
        # explicit path first
        assert result[0] == "docs/specs/x.md"
        # issue next (resolves to x.md via title '[x] spec')
        assert result[1] == "docs/specs/x.md"
        # bare id P20
        assert result[2] == "docs/specs/P20.md"
        # glob expansion sorted: P11, P12, P13
        assert result[3:] == ["docs/specs/P11.md", "docs/specs/P12.md", "docs/specs/P13.md"]

    def test_repo_not_cwd(self, tmp_path):
        """test_repo_not_cwd: resolve against a tmp tree different from process CWD."""
        cfg = _cfg("docs/specs/*.md")
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "P14.md").write_text("# P14")

        # Make sure we are NOT in tmp_path (use the file's parent instead)
        original_cwd = os.getcwd()
        assert str(tmp_path) != original_cwd  # sanity

        result = resolve_specs(["P14"], [], cfg, tmp_path)
        # Must return repo-relative string, not absolute
        assert result == ["docs/specs/P14.md"]
        assert not result[0].startswith("/")

    def test_recursive_glob_in_token_rejected(self, tmp_path):
        """A token containing '**' -> ResolveError."""
        cfg = _cfg("docs/specs/*.md")
        with pytest.raises(ResolveError, match=r"\*\*"):
            resolve_specs(["docs/**/*.md"], [], cfg, tmp_path)

    def test_recursive_glob_in_spec_glob_rejected(self, tmp_path):
        """test_recursive_glob_rejected: cfg.spec_glob with '**' -> ResolveError at resolve time."""
        cfg = _cfg("specs/**/*.md")
        (tmp_path / "specs").mkdir(parents=True)
        with pytest.raises(ResolveError, match=r"\*\*"):
            resolve_specs(["P14"], [], cfg, tmp_path)

    def test_recursive_glob_rejected_no_arg(self, tmp_path, monkeypatch):
        """CLI no-arg fallback: cfg.spec_glob with '**' -> non-zero exit via the
        recursive-glob rejection, not the empty-glob guard.

        cli.py binds load_config via ``from .config import load_config``, so
        patching ``config_mod.load_config`` would be inert. Write a real config
        file with the ``**`` glob instead. Also create a spec the glob WOULD
        match if it weren't rejected, so a passing exit can only come from the
        ``**`` rejection -- never from an empty match set.
        """
        import json
        from multi_ship import cli, driver

        (tmp_path / ".claude").mkdir(parents=True)
        cfg_data = json.loads(TEMPLATE.read_text())
        cfg_data["spec_glob"] = "specs/**/*.md"
        (tmp_path / ".claude" / "multi-ship.json").write_text(json.dumps(cfg_data))

        # A spec the '**' glob WOULD match if not rejected.
        sub = tmp_path / "specs" / "sub"
        sub.mkdir(parents=True)
        (sub / "P14.md").write_text("# P14")

        called = []

        def fake_run_loop(**kw):
            called.append(kw)
            return {"shipped": [], "stopped_at": None}

        monkeypatch.setattr(driver, "run_loop", fake_run_loop)
        rc = cli.main(["--repo", str(tmp_path)])
        assert rc != 0
        assert called == []
