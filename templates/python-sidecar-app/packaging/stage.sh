#!/usr/bin/env bash
# stage.sh — Python スクリプトを実行可能スクリプトとして install（pack_deb.sh が変数を export）。
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"

install -D -m 0755 sidecar.py "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"
if [ -f assets/icon.png ]; then
  install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"
fi
