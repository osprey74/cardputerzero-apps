#!/usr/bin/env bash
# deploy.sh <app-dir> [pi@host] — .deb をビルドしてデバイスへ scp + apt install する。
#
# HANDOFF §2.7.6【確定】の配布経路①（czdev deploy 相当の自前版）。
# 公式ツールを使う場合は代わりに:  czdev deploy --host pi@<ip> --deb <pkg>.deb
#
# ホスト指定: 引数2 > 環境変数 CZ_HOST > 既定 pi@cardputerzero.local
set -euo pipefail

APP_DIR="${1:?usage: deploy.sh <app-dir> [pi@host]}"
HOST="${2:-${CZ_HOST:-pi@cardputerzero.local}}"
HERE="$(cd "$(dirname "$0")" && pwd)"

DEB="$("$HERE/pack_deb.sh" "$APP_DIR")"
[ -n "$DEB" ] && [ -f "$DEB" ] || { echo "pack_deb produced no .deb" >&2; exit 1; }

BASE="$(basename "$DEB")"
echo "[deploy] scp $BASE -> $HOST:/tmp/"
scp "$DEB" "$HOST:/tmp/$BASE"

echo "[deploy] apt install on $HOST"
ssh "$HOST" "sudo apt-get install -y /tmp/$BASE && rm -f /tmp/$BASE"
echo "[deploy] done: $BASE"
