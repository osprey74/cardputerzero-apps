#!/usr/bin/env bash
# swap_cap_a.sh — Cap A (Cap LoRa-1262) 装着時のデバイスパス切替ヘルパー
#
# 用途: Cap A を物理的に装着した直後、関連デバイスパス (SPI/UART) の
#       状態確認と App 01/02/05 が期待する権限・シンボリックリンクの設定を行う
# 詳細: HANDOFF §1.4 Cap 構成早見表 / §3 App 01-02-05
#
# 想定動作:
#   1. /dev/spidev0.0 (SX1262) の存在確認
#   2. /dev/ttyS* (AT6668 NMEA) の存在確認
#   3. gpsd 再起動
#   4. アプリ側用 udev ルール反映
#
# TODO (実機到着後):
#   - 実機の SPI CE ピン番号確定後にデバイスパスを修正
#   - GPS UART ボーレート (9600 or 115200) の自動判別

set -euo pipefail

echo "[swap_cap_a.sh] Cap A (Cap LoRa-1262) 装着確認..."
echo "  ※ このスクリプトは未実装です。実機到着後に実装予定。"
exit 1
