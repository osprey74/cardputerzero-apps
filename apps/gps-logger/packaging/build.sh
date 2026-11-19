#!/usr/bin/env bash
# build.sh — Python なのでコンパイル不要。構文チェックのみ（pack_deb.sh から呼ばれる）。
set -euo pipefail
python3 -m py_compile src/gps_logger.py src/track.py ../../shared/fb_ui/fbui.py \
  ../../shared/gnss_at6668/nmea.py ../../shared/gnss_at6668/reader.py
echo "[build.sh] py_compile ok" >&2