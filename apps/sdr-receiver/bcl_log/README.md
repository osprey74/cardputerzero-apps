# App 10 BCL ログモード (uConsole 先行構築版)

CardputerZero (CM0) 実機到着前に **ClockworkPi uConsole (CM4)** で App 10 の
BCL ログモードを先行検証するためのサブプロジェクト。

中核ロジック（UpNote `x-callback-url` 連携、Tailscale 経由の Mac Mini SSH 投稿、
既知局 DB、`_pending/` キュー）は機種非依存の Python で実装し、後段で CZ 用
LVGL UI を別途追加する想定。

仕様の一次資料は [HANDOFF_cardputerzero.md](../../../HANDOFF_cardputerzero.md) §3 App 10
「BCL ログモード」を参照。

## 必須前提

- Tailscale が uConsole / Mac Mini 双方で稼働しており、相互疎通可能
- Mac Mini 側で UpNote.app が起動し、`BCL_LogBook` ノートブックが存在する
- uConsole → Mac Mini の SSH 鍵認証が通っている（パスワードなしで `ssh so4330@mac-mini` できる）
- Python 3.9+（uConsole 標準: 3.9.2）

## セットアップ (uConsole 上で実行)

```bash
# 1. リポジトリを clone（または rsync で配布）
git clone https://github.com/osprey74/cardputerzero-apps.git
cd cardputerzero-apps/apps/sdr-receiver/bcl_log

# 2. 依存パッケージ
python3 -m pip install --user -r requirements.txt

# 3. 設定ファイル配置
mkdir -p ~/.config/cardputerzero
cp config.example.yaml ~/.config/cardputerzero/bcl_config.yaml
${EDITOR:-nano} ~/.config/cardputerzero/bcl_config.yaml   # mac_mini.* / default_location を環境に合わせて編集

# 4. Mac Mini への SSH 鍵を登録（未登録時のみ・1 回だけ）
ssh-keygen -t ed25519 -C "uconsole-bcl"      # ~/.ssh/id_ed25519 を生成
ssh-copy-id so4330@100.108.134.69            # Mac Mini に登録
ssh so4330@100.108.134.69 'echo ok'          # 疎通確認

# 5. 動作確認
python3 -m bcl_log new
```

## 使い方

| サブコマンド | 用途 |
| --- | --- |
| `python3 -m bcl_log new` | 新規 BCL ログを作成・UpNote へ投稿 |
| `python3 -m bcl_log resend` | `_pending/` の未送信ログを一括再送 |
| `python3 -m bcl_log list` | `_pending/` の一覧を表示 |

## 開発・デプロイ (Windows 開発機から)

```bash
# このリポジトリのルートで rsync 経由デプロイ
./apps/sdr-receiver/bcl_log/scripts/deploy_uconsole.sh
```

## モジュール構成

| モジュール | 役割 |
| --- | --- |
| `bcl_log/upnote.py` | `upnote://x-callback-url/note/new` URL 生成 + SSH 経由 `open` ディスパッチ |
| `bcl_log/ssh_target.py` | MagicDNS → Tailscale 固定 IP フォールバック解決 |
| `bcl_log/stations.py` | 既知局 YAML DB ロード + 周波数近傍検索 |
| `bcl_log/markdown_template.py` | UpNote ノート本文 (Markdown) 組み立て |
| `bcl_log/pending.py` | `_pending/` キューの保存・列挙・読み出し |
| `bcl_log/config.py` | `~/.config/cardputerzero/bcl_config.yaml` ロード |
| `bcl_log/cli.py` | Rich ベースのターミナル UI エントリ |

## 既知の制約 (uConsole 先行版)

- **録音機能は無効**（HANDOFF の案 ③）: GQRX 側で手動録音し、ファイル名を入力欄に貼り付ける運用。Mac Mini への scp 転送・CZ 側削除は本実装スコープ外
- **NOAA SWPC 取得は無効**: SFI / K-index は手動入力 or 未記載で投稿
- **GPS 連携は無効**: `default_location` を使用
- **Chain Encoder UI は存在しない**: フルキーボード + Enter / 数字選択のシンプル TUI

これらは CardputerZero 実機到着後にネイティブ実装で順次置換予定。
