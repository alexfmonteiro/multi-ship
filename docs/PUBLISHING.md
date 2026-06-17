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

```bash
# build sdist + wheel
python -m build

# sanity-check metadata + long description render
pipx run twine check dist/*

# verify the wheel installs and resolves bundled resources in a clean venv
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl
HOME=/tmp/vhome /tmp/v/bin/multi-ship install-skills   # should link all 5 skills

# upload (TestPyPI first, then PyPI)
pipx run twine upload --repository testpypi dist/*
pipx run twine upload dist/*
```

Once published, the README's recommended install simplifies to:

```bash
pipx install multi-ship
multi-ship install-skills
```

Prefer **PyPI Trusted Publishing** (OIDC from GitHub Actions) over a long-lived
API token — add a `release.yml` workflow triggered on `v*` tags.

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

Consider adding a job to `.github/workflows/test.yml` that runs
`claude plugin validate . --strict` (when the CLI is available) so a malformed
manifest can't land on `main`.
