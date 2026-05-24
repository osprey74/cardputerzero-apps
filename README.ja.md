# CardputerZero Apps

> [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) 向けアプリケーションのモノレポ。Raspberry Pi CM0 を搭載したクレジットカードサイズの Linux ハンドヘルド端末用です。

[English README](./README.md)

本リポジトリは CardputerZero 向けに開発予定の 7 アプリ（GPS ロガー、LoRa Meshtastic ノード、NFC / Sub-GHz 学習ツール、BSAF 防災受信クライアント、エッジ AI アシスタント、Wi-Fi 解析ツール）を管理するモノレポです。

> **現在のステータス（2026-05-24）: 実機到着前。** CardputerZero は Kickstarter 出資プロジェクトであり、本体はまだ届いていません。このリポジトリは現時点で設計仕様書とディレクトリスケルトンのみを含みます。実装は実機到着後、[HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo) に列挙された未確認事項の検証完了後に開始する予定です。

---

## ターゲットデバイス

| 項目 | 仕様 |
|---|---|
| SoC | Broadcom BCM2837 / Quad-core Cortex-A53 @ 1GHz |
| RAM | 512MB LPDDR2 |
| LCD | 1.9 インチ ST7789V2（320×170） |
| ストレージ | microSD（標準版 32GB 付属） |
| 無線 | Wi-Fi 2.4GHz、Bluetooth 4.2/BLE |
| 有線 | 10/100M Ethernet |
| USB | USB-C × 2（Host/Slave 切替）、USB-A × 1 |
| カメラ | Sony IMX219 8MP（標準版のみ） |
| OS | Raspberry Pi OS（Debian Linux ベース） |
| Launcher | LVGL ベース GUI ランチャー |

ハードウェア仕様の全項目は [HANDOFF §1](./HANDOFF_cardputerzero.md#1-ハードウェア概要) を参照してください。

---

## アプリ一覧（予定）

| ID | アプリ | 優先度 | 主機能 |
|---|---|---|---|
| 01 | `gps-logger` | ★★★★★ | Cap LoRa 1262 上の AT6668 GNSS を用いた GPX トラックロガー |
| 02 | `lora-mesh-node` | ★★★★☆ | SX1262 による Meshtastic 互換オフグリッド通信ノード |
| 03 | `nfc-toolkit` | ★★★★☆ | NFC カード学習ツール（ST25R3916、ISO 14443A/B、FeliCa、ISO 15693） |
| 04 | `subghz-sniffer` | ★★★☆☆ | Sub-GHz 信号アナライザ（CC1101、日本国内では受信のみ） |
| 05 | `bsaf-client` | ★★★★☆ | [BSAF v1](https://github.com/osprey74/bsaf-protocol) 防災アラートのオフグリッド受信 |
| 06 | `edge-ai` | ★★★☆☆ | オフライン LLM アシスタント（量子化 1B パラメータ以下のモデル） |
| 07 | `wifi-analyzer` | ★★★☆☆ | Wi-Fi 環境スキャン・解析 |

各アプリの機能チェックリストは [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様) を参照してください。

---

## 技術スタック

- **言語**: Rust（主軸）、Python（サイドカー・周辺ツール）
- **UI フレームワーク**: [LVGL](https://lvgl.io/)（Light and Versatile Graphics Library）を [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder)（`czdev` CLI）経由で利用
- **ターゲットトリプル**: `aarch64-unknown-linux-gnu`
- **エミュレータ**: `czdev run`（SDL2 ベース、開発機上で 320×170 LCD を再現）
- **デプロイ**: SSH + `scp` 経由で `pi@cardputerzero.local` へ転送
- **アプリ配布**: [cardputerzero.github.io](https://cardputerzero.github.io) への PR ベース登録

---

## リポジトリ構成

```
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md   # 一次設計書
├── apps/
│   ├── gps-logger/            # App 01
│   ├── lora-mesh-node/        # App 02
│   ├── nfc-toolkit/           # App 03
│   ├── subghz-sniffer/        # App 04
│   ├── bsaf-client/           # App 05
│   ├── edge-ai/               # App 06
│   └── wifi-analyzer/         # App 07
├── shared/
│   ├── lora_sx1262/           # SX1262 LoRa ドライバ
│   ├── gnss_at6668/           # AT6668 GNSS ドライバ
│   └── ui_theme/              # 共通 LVGL テーマ
└── scripts/
    ├── setup_device.sh        # （実装予定）デバイス初期セットアップ
    └── deploy_all.sh          # （実装予定）一括デプロイヘルパー
```

---

## はじめかた

> ⚠️ 実装は未着手です。以下は実機到着後の想定開発フローです。

### 開発機（macOS または Windows 11）

```bash
# 1. Rust ツールチェーンのインストール
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu

# 2. czdev エミュレータ用 SDL2 のインストール
#    macOS:
brew install sdl2 sdl2_image sdl2_mixer
#    Windows 11: WSL2 (Ubuntu) を起動し、内部で apt 経由でインストール

# 3. CardputerZero-AppBuilder のクローン・ビルド
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
export PATH="$PATH:$(pwd)/target/release"

# 4. エミュレータの動作確認
czdev run examples/hello_cz
```

デバイス側の初期セットアップ（gpsd、SPI、UART 有効化等）を含む完全な手順は [HANDOFF §6](./HANDOFF_cardputerzero.md#6-開発環境セットアップ) を参照してください。

---

## 日本国内法令への配慮

無線周波数を扱う機能は、日本の電波法等への準拠を前提に設計しています。主な制約は以下のとおりです。

- **LoRa 送信**: 920MHz 帯のみ、技適取得済みモジュールに限定
- **Sub-GHz**: CC1101 は受信のみの運用（送信は技適取得機器でのみ可能）
- **NFC**: カードエミュレーション・UID 書き込みは自己所有カードに限定（教育・研究目的）
- **Wi-Fi 解析**: 対象を自己所有のアクセスポイントに限定

詳細と出典は [HANDOFF §7](./HANDOFF_cardputerzero.md#7-日本国内の法令技術基準) を参照してください。

---

## エコシステム連携

- **[Rindo（りんどう）](https://github.com/osprey74/Rindo-iOS)** — `gps-logger`（App 01）の GPX エクスポートを Rindo（札幌・道央圏サイクリングナビ）にインポート可能とする設計です
- **[bsaf-protocol](https://github.com/osprey74/bsaf-protocol)** — `bsaf-client`（App 05）が準拠する BSAF v1 仕様
- **bsaf-jma-bot** — Wi-Fi 接続時は BSAF の MQTT フィードを購読し、未接続時は LoRa 経由でフォールバック受信します

---

## ライセンス

[MIT License](./LICENSE) で公開しています。Copyright © 2026 osprey74 (Sohshi)。

---

## 関連リンク

- **Kickstarter**: https://www.kickstarter.com/projects/m5stack/cardputerzero
- **M5Stack 公式ストア**: https://shop.m5stack.com/pages/m5-cardputerzero
- **CardputerZero-AppBuilder**: https://github.com/m5stack/CardputerZero-AppBuilder
- **AppStore Hub**: https://cardputerzero.github.io
- **Cap LoRa 1262 モジュール**: https://shop.m5stack.com/products/cap-lora-1262-for-cardputer-adv-sx1262-atgm336h

---

## 作者

**osprey74（Sohshi）** — Bluesky: [@osprey74.bsky.social](https://bsky.app/profile/osprey74.bsky.social)
