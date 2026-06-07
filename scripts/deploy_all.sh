#!/usr/bin/env bash
# deploy_all.sh — 全アプリ一括デプロイヘルパー
#
# 用途: ローカル開発機で全 11 アプリをビルドし、CardputerZero へ転送
# 詳細: HANDOFF §4.2 Launcher 登録手順
#
# TODO (実機到着後):
#   - czdev build の正式 CLI 仕様確認
#   - .deb パッケージ生成フローの確定
#   - scp 転送 + apt install の自動化
#   - czdev upload による AppStore (CardputerZeroRepository) 投稿

set -euo pipefail

echo "[deploy_all.sh] 全アプリ一括デプロイを開始します..."
echo "  ※ このスクリプトは未実装です。実機到着後に実装予定。"
exit 1
