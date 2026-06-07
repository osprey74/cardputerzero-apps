#!/usr/bin/env bash
# setup_device.sh — CardputerZero 初期セットアップ
#
# 用途: 実機到着後、SSH 接続した CardputerZero 上で1回だけ実行
# 内容: 必要パッケージ導入・SPI/UART 有効化・gpsd デーモン起動
# 詳細: HANDOFF §6.2 デバイス側 初期セットアップ
#
# 使い方:
#   ssh pi@cardputerzero.local
#   curl -fsSL https://raw.githubusercontent.com/osprey74/cardputerzero-apps/main/scripts/setup_device.sh | bash
#
# TODO (実機到着後):
#   - 実機ホスト名 / ユーザ名の確認
#   - raspi-config の非対話モードでの SPI/UART 有効化
#   - dtoverlay 設定の確定 (BT 競合回避等)

set -euo pipefail

echo "[setup_device.sh] CardputerZero 初期セットアップを開始します..."
echo "  ※ このスクリプトは未実装です。HANDOFF §6.2 を手動で参照してください。"
exit 1
