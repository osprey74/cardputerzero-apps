#!/usr/bin/env bash
# build.sh — UI をビルド/検査して .czbuild/ へ。pack_deb.sh 経由で $PKG_NAME 等が渡る。
#
# CZ_UI=fb  （既定）フレームバッファ UI（Python）。コンパイル不要・構文チェックのみ。
# CZ_UI=sdl  SDL2 UI（Rust）もビルドして同梱する（uConsole 等の検証用。CardputerZero の LCD には出ない）。
#            クロス: CZ_TARGET（既定 aarch64）/ 実機ネイティブ: CZ_TARGET=
set -euo pipefail

BIN="${PKG_NAME:?PKG_NAME 未設定（pack_deb.sh 経由で実行すること）}"
UI="${CZ_UI:-fb}"

python3 -m py_compile sidecar/stellar_sidecar.py sidecar/heading_source.py                       ui_fb/stellar_fb.py tools/render_scene.py
echo "[build.sh] py_compile ok (CZ_UI=$UI)" >&2

if [ "$UI" = sdl ] && [ "${CZ_SKIP_BUILD:-0}" != 1 ]; then
  TARGET="${CZ_TARGET-aarch64-unknown-linux-gnu}"
  if [ -n "$TARGET" ]; then
    ( cd ui && cargo build --release --target "$TARGET" )
    SRC="ui/target/$TARGET/release/$BIN"
  else
    ( cd ui && cargo build --release )
    SRC="ui/target/release/$BIN"
  fi
  mkdir -p .czbuild
  cp "$SRC" ".czbuild/$BIN"
  echo "[build.sh] -> .czbuild/$BIN" >&2
fi
