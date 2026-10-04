#!/usr/bin/env bash
# Render native Python build (no Docker, so the free instance needs no card).
# Mirrors docker/Dockerfile: front-end assets with Node, then Python deps into .venv.
set -euo pipefail
cd "$(dirname "$0")/.."

NODE_MAJOR=22
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt "$NODE_MAJOR" ]; then
  version=$(curl -fsSL https://nodejs.org/dist/index.json \
    | python3 -c "import json,sys; print(next(r['version'] for r in json.load(sys.stdin) if r['version'].startswith('v$NODE_MAJOR.')))")
  mkdir -p .render/node
  curl -fsSL "https://nodejs.org/dist/$version/node-$version-linux-x64.tar.xz" | tar -xJ -C .render/node --strip-components=1
  export PATH="$PWD/.render/node/bin:$PATH"
fi
echo "node $(node -v)"
(cd src/frontend && npm ci --no-audit --no-fund && npm run build)

python3 -m pip install --quiet --upgrade uv
# Uses Render's Python when it satisfies requires-python; otherwise uv fetches one into
# the project dir, which (unlike $HOME) is kept for the runtime.
UV_PYTHON_INSTALL_DIR="$PWD/.render/python" python3 -m uv sync --frozen --no-dev --no-install-project
