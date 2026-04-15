#!/usr/bin/bash
set -eu
if [ $# -eq 0 ]; then
  if [ -z "${SERVICE:-}" ]; then
    echo "ERROR: SERVICE environment variable is not set" >&2
    exit 1
  fi
  if [ -z "${PORT:-}" ]; then
    echo "ERROR: PORT environment variable is not set" >&2
    exit 1
  fi
  set -- "$SERVICE" serve --port "$PORT" --host 0.0.0.0 --dev
fi
if [ -e /mnt/imbi-common/pyproject.toml ]; then
  exec uv run --active --with-editable /mnt/imbi-common "$@"
else
  exec uv run --active "$@"
fi
