#!/usr/bin/env bash
# build.sh — Rust バイナリをビルドし .czbuild/ へ配置（pack_deb.sh 経由で $PKG_NAME 等が渡る）。
# クロス: CZ_TARGET=aarch64-unknown-linux-gnu（既定） / 実機ネイティブ: CZ_TARGET=（空）
# ※ SDL2 のクロスは要 aarch64 の libsdl2-dev（sysroot）。実機ネイティブビルドが簡単。
set -euo pipefail

BIN="${PKG_NAME:?PKG_NAME 未設定（pack_deb.sh 経由で実行すること）}"
TARGET="${CZ_TARGET-aarch64-unknown-linux-gnu}"

if [ "${CZ_SKIP_BUILD:-0}" = 1 ]; then
  echo "[build.sh] skip cargo (CZ_SKIP_BUILD=1)" >&2
  exit 0
fi

if [ -n "$TARGET" ]; then
  cargo build --release --target "$TARGET"
  SRC="target/$TARGET/release/$BIN"
else
  cargo build --release
  SRC="target/release/$BIN"
fi

mkdir -p .czbuild
cp "$SRC" ".czbuild/$BIN"
echo "[build.sh] -> .czbuild/$BIN" >&2
