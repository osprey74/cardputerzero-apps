#!/usr/bin/env bash
# build.sh — Python なのでコンパイル不要。構文チェックのみ（pack_deb.sh から呼ばれる）。
set -euo pipefail
python3 -m py_compile src/lan_scanner.py src/netscan.py ../../shared/fb_ui/fbui.py
echo "[build.sh] py_compile ok" >&2