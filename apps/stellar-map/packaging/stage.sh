#!/usr/bin/env bash
# stage.sh — UI・サイドカー・shared パッケージ・カタログを install。
# pack_deb.sh が STAGE/INSTALL_PREFIX/PKG_NAME を export。cwd = apps/stellar-map。
#
# インストール配置（launcher.sh の PYTHONPATH/STELLAR_SIDECAR と整合）:
#   $PREFIX/bin/stellar-map                         起動ラッパー
#   $PREFIX/lib/stellar-map/ui_fb/stellar_fb.py     フレームバッファ UI（既定）
#   $PREFIX/lib/stellar-map/tools/render_scene.py   Scene 描画（UI が共用）
#   $PREFIX/lib/stellar-map/sidecar/*.py            サイドカー（_APP/data=既定データ）
#   $PREFIX/lib/stellar-map/data/*                  カタログ（stars.bin 等・raw は含めない）
#   $PREFIX/lib/stellar-map/shared/{star_catalog,compass}/*  Python 名前空間パッケージ（PYTHONPATH 経由）
#   $PREFIX/lib/stellar-map/ephem.py                惑星・月（skyfield があれば有効）
#   $PREFIX/lib/stellar-map/stellar-map             SDL2 UI バイナリ（CZ_UI=sdl でビルドした場合のみ）
set -euo pipefail
: "${STAGE:?}"; : "${INSTALL_PREFIX:?}"; : "${PKG_NAME:?}"

LIB="$STAGE$INSTALL_PREFIX/lib/$PKG_NAME"

install -D -m 0755 ui_fb/stellar_fb.py         "$LIB/ui_fb/stellar_fb.py"
install -D -m 0644 tools/render_scene.py       "$LIB/tools/render_scene.py"
install -D -m 0755 sidecar/stellar_sidecar.py  "$LIB/sidecar/stellar_sidecar.py"
install -D -m 0644 sidecar/heading_source.py   "$LIB/sidecar/heading_source.py"
install -D -m 0644 tools/ephem.py              "$LIB/ephem.py"

for pkg in star_catalog compass; do
  for f in ../../shared/$pkg/*.py; do
    install -D -m 0644 "$f" "$LIB/shared/$pkg/$(basename "$f")"
  done
done

n=0
for f in data/*.bin data/*.json; do
  [ -e "$f" ] && { install -D -m 0644 "$f" "$LIB/data/$(basename "$f")"; n=$((n + 1)); }
done
[ "$n" -gt 0 ] || { echo "[stage.sh] data/ にカタログが無い（tools/build_*.py を先に実行）" >&2; exit 1; }

if [ -f ".czbuild/$PKG_NAME" ]; then
  install -D -m 0755 ".czbuild/$PKG_NAME" "$LIB/$PKG_NAME"
fi

install -D -m 0755 packaging/launcher.sh "$STAGE$INSTALL_PREFIX/bin/$PKG_NAME"

if [ -f assets/icon.png ]; then
  install -D -m 0644 assets/icon.png "$STAGE$INSTALL_PREFIX/share/images/$PKG_NAME.png"
fi
