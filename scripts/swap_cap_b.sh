#!/usr/bin/env bash
# swap_cap_b.sh — Cap B (Hacker Cap = CC1101 + ST25R3916) 装着時のデバイスパス切替ヘルパー
#
# 用途: Cap B を物理的に装着した直後、関連デバイスパス (SPI 共有バス) の
#       状態確認と App 03/04 が期待する権限・シンボリックリンクの設定を行う
# 詳細: HANDOFF §1.4 Cap 構成早見表 / §3 App 03-04
#
# 想定動作 (公式回路図 V0.3 ベース):
#   1. /dev/spidev0.* (共有 SPI バス) の存在確認
#   2. CC1101: CS=G5, RF_SW0=G13, GDO0=G15
#   3. ST25R3916: NFC_IRQ=G4, NFC_CS=G6
#   4. アプリ側用 udev ルール反映
#
# TODO (実機到着後):
#   - 同時アクセス時の SPI バス調停確認
#   - 各 CS ピンの状態リセット

set -euo pipefail

echo "[swap_cap_b.sh] Cap B (Hacker Cap) 装着確認..."
echo "  ※ このスクリプトは未実装です。実機到着後に実装予定。"
exit 1
