#!/usr/bin/env bash
# setup_rtlsdr.sh — RTL-SDR Blog V4 USB-C 専用ドライバセットアップ
#
# 用途: App 10 (sdr-receiver) の前提となる RTL-SDR V4 ドライバを導入
# 重要: 標準の "rtl-sdr" パッケージは V4 (R828D チューナー) に対応していない
# 詳細: HANDOFF §3 App 10 ステップ 0-3
#
# TODO (実機到着後):
#   - rtlsdrblog リポジトリの最新版へのリンク確認
#   - CardputerZero (Raspberry Pi OS) での動作確認
#   - GQRX / SDR++ / dump1090-fa / rtl_433 / rtl_ais / noaa-apt の一括セットアップ

set -euo pipefail

echo "[setup_rtlsdr.sh] RTL-SDR Blog V4 ドライバセットアップを開始します..."
echo "  ※ このスクリプトは未実装です。HANDOFF §3 App 10 を手動で参照してください。"
exit 1
