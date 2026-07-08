#!/usr/bin/env bash
# build.sh — SDL2 UI (Rust) をビルドし .czbuild/ へ。Python は非コンパイル。
# pack_deb.sh 経由で $PKG_NAME 等が渡る。クロス: CZ_TARGET（既定 aarch64）/ 実機: CZ_TARGET=
set -euo pipefail

BIN="${PKG_NAME:?PKG_NAME 未設定（pack_deb.sh 経由で実行すること）}"
TARGET="${CZ_TARGET-aarch64-unknown-linux-gnu}"

if [ "${CZ_SKIP_BUILD:-0}" = 1 ]; then
  echo "[build.sh] skip cargo (CZ_SKIP_BUILD=1)" >&2
  exit 0
fi

if [ -n "$TARGET" ]; then
  ( cd ui && cargo build --release --target "$TARGET" )
  SRC="ui/target/$TARGET/release/$BIN"
else
  ( cd ui && cargo build --release )
  SRC="ui/target/release/$BIN"
fi

mkdir -p .czbuild
cp "$SRC" ".czbuild/$BIN"
# サイドカーの Python 構文チェック
python3 -m py_compile sidecar/stellar_sidecar.py
echo "[build.sh] -> .czbuild/$BIN (+py_compile ok)" >&2
