#!/usr/bin/env bash
# stage.sh — アプリ本体と shared/fb_ui を配置する。cwd = apps/wifi-analyzer。
#   $PREFIX/bin/wifi-analyzer                 起動ラッパー
#   $PREFIX/lib/wifi-analyzer/src/*.py        本体（src/../shared を import パスに足す）
#   $PREFIX/lib/wifi-analyzer/shared/fb_ui/   画面・キー入力の共通部品
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"
LIB="$STAGE$INSTALL_PREFIX/lib/$PKG_NAME"

install -D -m 0755 src/wifi_analyzer.py "$LIB/src/wifi_analyzer.py"
install -D -m 0644 src/wifi_scan.py "$LIB/src/wifi_scan.py"
for f in ../../shared/fb_ui/*.py; do
  install -D -m 0644 "$f" "$LIB/shared/fb_ui/$(basename "$f")"
done
install -D -m 0755 packaging/launcher.sh "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"
install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"