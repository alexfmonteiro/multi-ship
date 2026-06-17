"""Pre-burst spec readiness checks.

Surfaces mechanical readiness gaps in specs *before* an unattended run starts,
so the operator answers them up front in one batch instead of being interrupted
by a per-item plan-gate stop. This catches placeholder issue numbers, a missing
Definition of Done, and explicit unresolved-design markers. It does NOT catch
latent design ambiguity (the kind a plan panel discovers) — that still surfaces
at the build's plan gate.
"""
from __future__ import annotations
import re
from pathlib import Path

# High-signal, low-false-positive markers only. (Deliberately not "TODO"/"open
# question", which appear in legitimate spec prose.)
_MARKERS = re.compile(r"(?<![A-Za-z])(TBD|FIXME|\?\?\?)(?![A-Za-z])")
_PLACEHOLDER_ISSUES = {"0", "", "tbd", "null", "none", "n/a"}


def lint_spec(text: str) -> list[str]:
    """Return readiness problems for one spec's text. Empty list == ready."""
    problems = []
    m = re.search(r"^Issue:\s*(.*)$", text, re.M)
    if not m:
        problems.append("no `Issue:` frontmatter — set a tracking issue number")
    elif m.group(1).strip().lower() in _PLACEHOLDER_ISSUES:
        problems.append(f"placeholder issue number (`Issue: {m.group(1).strip()}`) "
                        "— set a real tracking issue so `Closes #N` resolves")
    if not re.search(r"^#{1,3}\s+Definition of Done", text, re.M | re.I):
        problems.append("no Definition of Done section")
    markers = sorted({hit.group(1) for hit in _MARKERS.finditer(text)})
    if markers:
        problems.append(f"unresolved-design marker(s) present: {', '.join(markers)}")
    return problems


def lint_specs(paths) -> dict:
    """Map each spec path with problems -> its problem list. Clean specs are
    omitted. A missing file is reported as a problem too."""
    out = {}
    for p in paths:
        path = Path(p)
        if not path.exists():
            out[str(p)] = ["file not found"]
            continue
        probs = lint_spec(path.read_text())
        if probs:
            out[str(p)] = probs
    return out
