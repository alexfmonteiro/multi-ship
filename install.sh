#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DST="${HOME}/.claude/skills"
BIN_DST="${HOME}/.local/bin"
mkdir -p "$SKILLS_DST" "$BIN_DST"

for dep in python3 claude gh; do
  command -v "$dep" >/dev/null 2>&1 || { echo "WARN: '$dep' not found on PATH"; }
done

for d in "$ROOT"/skills/*/; do
  name="$(basename "$d")"; dst="$SKILLS_DST/$name"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "SKIP $name: a non-symlink skill already exists at $dst — remove it first"; continue
  fi
  ln -sfn "$d" "$dst"; echo "linked skill: $name"
done

ln -sfn "$ROOT/bin/multi-ship" "$BIN_DST/multi-ship"; echo "linked bin: $BIN_DST/multi-ship"
case ":$PATH:" in *":$BIN_DST:"*) ;; *) echo "ADD TO PATH: export PATH=\"$BIN_DST:\$PATH\"";; esac
echo "done. Per-repo setup: cd <repo> && multi-ship init"
