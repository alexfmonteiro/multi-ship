# Publishing

How to cut a release: the PyPI package and the Claude Code plugin/marketplace.

## Versioning

Bump the version in **three** places (keep them in sync):

- `pyproject.toml` → `[project].version`
- `.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[0].version`

Add a dated section to `CHANGELOG.md`.

## PyPI

The wheel is already PyPI-ready and bundles the skills/templates/workflow (see
`[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml`).

### Automated (recommended): tag a release

`.github/workflows/release.yml` builds and publishes to PyPI via **Trusted
Publishing** (OIDC — no API token stored in the repo) whenever you push a `v*`
tag. One-time setup:

1. **PyPI** → the `multi-ship` project → *Publishing* → add a GitHub trusted
   publisher: owner `alexfmonteiro`, repo `multi-ship`, workflow `release.yml`,
   environment `pypi`. (For the very first release, use PyPI's *pending publisher*
   form since the project doesn't exist yet.)
2. **GitHub** → Settings → Environments → create an environment named `pypi`.

Then cut a release:

```bash
# bump the version in all three manifests + CHANGELOG, commit, then:
git tag v0.1.1 && git push origin v0.1.1
```

The workflow runs the version-sync guard, builds, `twine check`s, and publishes.

### Manual

```bash
python -m build                      # sdist + wheel
pipx run twine check dist/*          # metadata + long-description render
# verify the wheel installs and resolves bundled resources in a clean venv:
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl
HOME=/tmp/vhome /tmp/v/bin/multi-ship install-skills   # should link all 5 skills
pipx run twine upload --repository testpypi dist/*     # TestPyPI first
pipx run twine upload dist/*                           # then PyPI
```

Once published, the README's recommended install simplifies to:

```bash
pipx install multi-ship
multi-ship install-skills
```

## Claude Code plugin / marketplace

The repo is its own marketplace: `.claude-plugin/marketplace.json` lists the
`multi-ship` plugin with `"source": "."` (the plugin root is the repo root, where
`skills/` and `workflows/` already live — no relocation needed).

Validate before tagging a release:

```bash
claude plugin validate .                 # marketplace + plugin manifests
claude plugin validate . --strict        # treat warnings as errors (use in CI)
```

Users install with:

```text
/plugin marketplace add alexfmonteiro/multi-ship
/plugin install multi-ship@multi-ship
```

Relative `source` paths only resolve when the marketplace is added via Git (a
GitHub repo or git URL) — which is exactly the install line above, so this is
fine. To get listed in a *third-party* marketplace, open a PR adding an entry that
points at `{ "source": "github", "repo": "alexfmonteiro/multi-ship" }`.

### CI guard

`.github/workflows/plugin.yml` guards `main` on every push/PR:

- **Blocking:** `scripts/validate_plugin.py` — pure-Python, no auth. Checks both
  manifests parse, required keys are present, every `skills/<name>/` has a
  `SKILL.md`, and the version matches across `pyproject.toml`, `plugin.json`, and
  `marketplace.json`.
- **Best-effort:** `claude plugin validate . --strict` via the npm-installed CLI.
  CI has no authenticated Claude session, so this step is informational and can't
  block the merge — run it locally before tagging a release.
