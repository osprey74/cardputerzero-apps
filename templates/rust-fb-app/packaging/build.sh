#!/usr/bin/env bash
# build.sh — Rust バイナリをビルドし .czbuild/ へ配置する。
# pack_deb.sh から meta.env の変数を export された状態で呼ばれる（$PKG_NAME 等が使える）。
#
# クロスビルド（Win/mac 開発機）: CZ_TARGET=aarch64-unknown-linux-gnu（既定）
# 実機ネイティブビルド:            CZ_TARGET= （空）で実行
set -euo pipefail

BIN="${PKG_NAME:?PKG_NAME 未設定（pack_deb.sh 経由で実行すること）}"
TARGET="${CZ_TARGET-aarch64-unknown-linux-gnu}"

# CZ_SKIP_BUILD=1 で cargo を飛ばす（.czbuild/$BIN が既にある前提。パッカー検証/CI 用）
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
