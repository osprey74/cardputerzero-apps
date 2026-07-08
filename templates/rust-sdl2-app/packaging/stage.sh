#!/usr/bin/env bash
# stage.sh — 成果物をステージングへ install（pack_deb.sh が STAGE/INSTALL_PREFIX/PKG_NAME を export）。
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"

install -D -m 0755 ".czbuild/$PKG_NAME" "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"
if [ -f assets/icon.png ]; then
  install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"
fi
