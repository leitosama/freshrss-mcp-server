#!/bin/bash
# Claude Code on the web: make `uv run` work out of the box.
#
# The sandbox image ships an old uv whose newest known 3.14 is 3.14.0rc2,
# which pydantic cannot import on. .python-version pins an exact final
# release instead, and if the image's uv is too old to know that release,
# a current uv is installed from PyPI and put first on PATH.
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

if ! uv python install --no-progress >/dev/null 2>&1; then
  python3 -m pip install --quiet --upgrade uv
  uv_dir="$(dirname "$(python3 -c 'import uv; print(uv.find_uv_bin())')")"
  export PATH="$uv_dir:$PATH"
  [ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export PATH=\"$uv_dir:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  uv python install --no-progress
fi

uv sync --locked
