#!/usr/bin/env bash
# build.sh — Python はコンパイル不要。構文チェック（py_compile）だけ行う。
set -euo pipefail

if [ "${CZ_SKIP_BUILD:-0}" = 1 ]; then
  echo "[build.sh] skip (CZ_SKIP_BUILD=1)" >&2
  exit 0
fi

python3 -m py_compile sidecar.py
echo "[build.sh] py_compile ok" >&2
