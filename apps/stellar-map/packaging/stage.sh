#!/usr/bin/env bash
# stage.sh — UI バイナリ・サイドカー・shared パッケージ・カタログを install。
# pack_deb.sh が STAGE/INSTALL_PREFIX/PKG_NAME を export。cwd = apps/stellar-map。
#
# インストール配置（launcher.sh の PYTHONPATH/STELLAR_SIDECAR と整合）:
#   $PREFIX/bin/stellar-map                       起動ラッパー
#   $PREFIX/lib/stellar-map/stellar-map           SDL2 UI バイナリ
#   $PREFIX/lib/stellar-map/sidecar/stellar_sidecar.py   サイドカー（_APP/data=既定データ）
#   $PREFIX/lib/stellar-map/data/*                カタログ（stars.bin 等・raw は含めない）
#   $PREFIX/lib/stellar-map/shared/star_catalog/* Python 名前空間パッケージ（PYTHONPATH 経由）
#   $PREFIX/lib/stellar-map/ephem.py              惑星・月（skyfield があれば有効）
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"

LIB="$STAGE$INSTALL_PREFIX/lib/$PKG_NAME"

install -D -m 0755 ".czbuild/$PKG_NAME"        "$LIB/$PKG_NAME"
install -D -m 0755 sidecar/stellar_sidecar.py  "$LIB/sidecar/stellar_sidecar.py"
install -D -m 0644 tools/ephem.py              "$LIB/ephem.py"

for f in ../../shared/star_catalog/*.py; do
  install -D -m 0644 "$f" "$LIB/shared/star_catalog/$(basename "$f")"
done

for f in data/*.bin data/*.json; do
  [ -e "$f" ] && install -D -m 0644 "$f" "$LIB/data/$(basename "$f")"
done

install -D -m 0755 packaging/launcher.sh "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"

if [ -f assets/icon.png ]; then
  install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"
fi
