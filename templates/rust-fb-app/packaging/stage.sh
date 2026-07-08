#!/usr/bin/env bash
# stage.sh — ビルド成果物をステージング領域へ install する。
# pack_deb.sh から export される変数: STAGE / INSTALL_PREFIX / PKG_NAME
set -euo pipefail

: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"

# 実行バイナリ（APP_EXEC=$INSTALL_PREFIX/bin/$PKG_NAME に一致）
install -D -m 0755 ".czbuild/$PKG_NAME" "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"

# アイコン（あれば）。48x48 PNG 推奨。
if [ -f assets/icon.png ]; then
  install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"
fi
