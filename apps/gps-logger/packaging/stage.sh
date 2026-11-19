#!/usr/bin/env bash
# stage.sh — アプリ本体と共通部品を配置する。cwd = apps/gps-logger。
#   $PREFIX/bin/gps-logger                       起動ラッパー
#   $PREFIX/lib/gps-logger/src/*.py              本体（src/../shared を import パスに足す）
#   $PREFIX/lib/gps-logger/shared/fb_ui/         画面・キー入力の共通部品
#   $PREFIX/lib/gps-logger/shared/gnss_at6668/   GNSS ドライバ（Cap／Grove の 5V 制御・NMEA）
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"
LIB="$STAGE$INSTALL_PREFIX/lib/$PKG_NAME"

install -D -m 0755 src/gps_logger.py "$LIB/src/gps_logger.py"
install -D -m 0644 src/track.py "$LIB/src/track.py"
for pkg in fb_ui gnss_at6668; do
  for f in ../../shared/$pkg/*.py; do
    install -D -m 0644 "$f" "$LIB/shared/$pkg/$(basename "$f")"
  done
done
install -D -m 0755 packaging/launcher.sh "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"
install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"