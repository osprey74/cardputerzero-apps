# CardputerZero Apps

> [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) 向けアプリケーションのモノレポ。Raspberry Pi CM0 を搭載したクレジットカードサイズの Linux ハンドヘルド端末用です。

[English README](./README.md)

本リポジトリは CardputerZero 向けに開発予定の 11 アプリ（GPS ロガー＋天球図表示、LoRa Meshtastic ノード、NFC / Sub-GHz セキュリティツール、BSAF 防災受信、SDR 広帯域受信、LAN 調査ツール 等）を管理するモノレポです。

> **現在のステータス（2026-06-07）: 実機到着前。** CardputerZero は Kickstarter 出資プロジェクトであり、本体はまだ届いていません。このリポジトリは現時点で設計仕様書とディレクトリスケルトンのみを含みます。実装は実機到着後、[HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo) に列挙された未確認事項の検証完了後に開始する予定です。

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
| AppStore | Debian `.deb` apt リポジトリ（[CardputerZeroRepository](https://github.com/m5stack/CardputerZeroRepository)） |

ハードウェア仕様の全項目は [HANDOFF §1](./HANDOFF_cardputerzero.md#1-ハードウェア概要) を参照してください。

### Cap モジュール（上部スロット差し替え式）

| | Cap A: Cap LoRa-1262 | Cap B: Hacker Cap |
|---|---|---|
| 無線 | SX1262（LoRa、868–923 MHz） | CC1101（Sub-GHz、315/433/868/920 MHz） |
| GNSS | AT6668（GPS / QZSS / GLO / GAL / BDS） | — |
| NFC | — | ST25R3916（ISO 14443A/B、FeliCa、ISO 15693） |
| 主な使用アプリ | App 01 / 02 / 05 | App 03 / 04 |

Cap A と Cap B は同じ上部スロットを使うため同時装着不可。

### 関連デバイス（推奨周辺機器）

| デバイス | 役割 |
|---|---|
| [M5Stack C6L Meshtastic Unit](https://www.switch-science.com/products/10809) | 自宅 LoRa ゲートウェイ（インターネット ↔ Meshtastic ブリッジ、Wi-Fi 6 内蔵） |
| [M5Stack Chain Encoder × 2](https://www.switch-science.com/collections/m5stack/products/10919) | デイジーチェーン式ロータリーノブ（周波数チューニング・リスト送り） |
| [RTL-SDR Blog V4](https://www.rtl-sdr.com/rtl-sdr-blog-v4-dongle-initial-release/) | USB SDR ドングル（500 kHz – 1.75 GHz 広帯域受信） |

---

## アプリ一覧（予定）

| ID | アプリ | 優先度 | ハードウェア | 主機能 |
|---|---|---|---|---|
| 01 | `gps-logger` | ★★★★★ | Cap A | GPX トラックロガー + GNSS 衛星の天球図表示 |
| 02 | `lora-mesh-node` | ★★★★☆ | Cap A + C6L | Meshtastic 互換オフグリッド通信ノード |
| 03 | `nfc-toolkit` | ★★★★☆ | Cap B | NFC カード学習ツール（ISO 14443A/B、FeliCa、ISO 15693） |
| 04 | `subghz-sniffer` | ★★★☆☆ | Cap B | Sub-GHz 信号アナライザ（日本国内では受信のみ） |
| 05 | `bsaf-client` | ★★★★☆ | Cap A + Wi-Fi | [BSAF v1](https://github.com/osprey74/bsaf-protocol) 防災アラート二系統受信（MQTT 主・LoRa 副） |
| 06 | `edge-ai` | ★★★☆☆ | 本体内蔵 | オフライン LLM アシスタント（量子化 1B パラメータ以下） |
| 07 | `wifi-analyzer` | ★★★☆☆ | 本体内蔵 | Wi-Fi 環境スキャン・解析 |
| 08 | `nfc-checkpoint` | ★★★☆☆ | Cap A + Cap B | NFC タグ × GPS チェックポイントロガー |
| 09 | `nfc-lora-auth` | ★★☆☆☆ | Cap A + Cap B | オフグリッドバッジ認証 PoC（NFC 読取 → LoRa 中継） |
| 10 | `sdr-receiver` | ★★★★☆ | RTL-SDR V4 | 広帯域 SDR 受信 + 自作統合モニター（FM / ADS-B / AIS / NOAA APT / rtl_433） |
| 11 | `lan-scanner` | ★★★★☆ | 本体内蔵 | ポケットサイズネット診断機（nmap / arp-scan、Wi-Fi + 有線 LAN） |

各アプリの機能チェックリストは [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様) を参照してください。

---

## 技術スタック

- **言語**: Rust（主軸）、Python（サイドカー・周辺ツール）
- **UI フレームワーク**: [LVGL](https://lvgl.io/) を [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder)（`czdev` CLI）経由で利用
- **ターゲットトリプル**: `aarch64-unknown-linux-gnu`
- **エミュレータ**: `czdev run`（SDL2 ベース、開発機上で 320×170 LCD を再現）
- **デプロイ**: SSH + `scp` 経由で `pi@cardputerzero.local` へ転送
- **アプリ配布**: `czdev upload` で公式 Debian apt リポジトリ [m5stack/CardputerZeroRepository](https://github.com/m5stack/CardputerZeroRepository) に投稿、エンドユーザは `apt install` で取得
- **リモート開発**: Tailscale VPN 経由で自宅 Mac Mini に接続しフル Claude モデルをリモート実行（CardputerZero の 512MB RAM ではローカル実行困難なため）

---

## リポジトリ構成

```
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md   # 一次設計書
├── apps/
│   ├── gps-logger/            # App 01 [Cap A]
│   ├── lora-mesh-node/        # App 02 [Cap A]
│   ├── nfc-toolkit/           # App 03 [Cap B]
│   ├── subghz-sniffer/        # App 04 [Cap B]
│   ├── bsaf-client/           # App 05 [Cap A + Wi-Fi]
│   ├── edge-ai/               # App 06 [本体]
│   ├── wifi-analyzer/         # App 07 [本体]
│   ├── nfc-checkpoint/        # App 08 [Cap A + Cap B 交互]
│   ├── nfc-lora-auth/         # App 09 [Cap A + Cap B 交互]
│   ├── sdr-receiver/          # App 10 [RTL-SDR USB]
│   └── lan-scanner/           # App 11 [本体 Wi-Fi / 有線 LAN]
├── shared/
│   ├── lora_sx1262/           # SX1262 LoRa ドライバ [Cap A]
│   ├── gnss_at6668/           # AT6668 GNSS ドライバ [Cap A]
│   ├── nfc_st25r3916/         # ST25R3916 NFC ドライバ [Cap B]
│   ├── rf_cc1101/             # CC1101 Sub-GHz ドライバ [Cap B]
│   ├── input_encoder/         # Chain Encoder 共通入力ドライバ [Grove UART]
│   └── ui_theme/              # 共通 LVGL テーマ
└── scripts/
    ├── setup_device.sh        # デバイス初期セットアップ
    ├── setup_rtlsdr.sh        # RTL-SDR V4 ドライバセットアップ (App 10)
    ├── swap_cap_a.sh          # Cap A 用デバイスパス切替ヘルパー
    ├── swap_cap_b.sh          # Cap B 用デバイスパス切替ヘルパー
    └── deploy_all.sh          # 全アプリ一括デプロイ
```

---

## はじめかた

> ⚠️ 実装は未着手です。以下は実機到着後の想定開発フローです。

### 開発機

macOS / Linux / **Windows 11（MSYS2 MINGW64）** が公式サポート対象です（AppBuilder の `DESKTOP_DEV.md` 参照）。

```bash
# 1. Rust ツールチェーンのインストール
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu

# 2. czdev エミュレータ用 SDL2 のインストール
#    macOS:        brew install sdl2 sdl2_image sdl2_mixer
#    Linux:        sudo apt install libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev
#    Windows 11:   pacman -S mingw-w64-x86_64-SDL2 mingw-w64-x86_64-SDL2_image mingw-w64-x86_64-SDL2_mixer
#                  (MSYS2 MINGW64 シェル内で実行)

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

無線周波数を扱う機能は、日本の電波法等への準拠を前提に設計しています。主な制約：

- **LoRa 送信**: 920MHz 帯のみ、ファームウェアで +13dBm（20mW）以下に出力制限、技適取得済みモジュールに限定
- **Sub-GHz**: CC1101 は受信のみの運用（送信は技適取得機器でのみ可能）
- **NFC**: カードエミュレーション・UID 書き込みは自己所有カードに限定（教育・研究目的）
- **Wi-Fi 解析**: 対象を自己所有のアクセスポイントに限定
- **LAN スキャン**: 管理権限のあるネットワークのみ（ISMS 規程に従う）
- **SDR 受信**: 受信専用。受信内容の第三者への漏洩は電波法第 59 条により禁止

詳細と出典は [HANDOFF §7](./HANDOFF_cardputerzero.md#7-日本国内の法令技術基準) を参照してください。

---

## エコシステム連携

- **[Rindo（りんどう）](https://github.com/osprey74/Rindo-iOS)** — `gps-logger`（App 01）の GPX エクスポートを Rindo（札幌・道央圏サイクリングナビ）にインポート可能とする設計
- **[Michi-Navi](https://github.com/osprey74/michi-navi)** — `nfc-checkpoint`（App 08）は北海道の道の駅スタンプラリーとの連携を想定
- **[bsaf-protocol](https://github.com/osprey74/bsaf-protocol)** — `bsaf-client`（App 05）が準拠する BSAF v1 仕様
- **bsaf-jma-bot** — Wi-Fi 接続時は BSAF の MQTT フィードを購読し、未接続時は C6L 経由の LoRa でフォールバック受信

---

## ライセンス

[MIT License](./LICENSE) で公開しています。Copyright © 2026 osprey74 (Sohshi)。

---

## 関連リンク

- **Kickstarter**: https://www.kickstarter.com/projects/m5stack/cardputerzero
- **M5Stack 公式ストア**: https://shop.m5stack.com/pages/m5-cardputerzero
- **CardputerZero-AppBuilder**: https://github.com/m5stack/CardputerZero-AppBuilder
- **AppStore（apt リポジトリ）**: https://github.com/m5stack/CardputerZeroRepository
- **Cap LoRa-1262（Cap A）**: https://docs.m5stack.com/ja/cap/Cap_LoRa-1262
- **Hacker Cap / Cap CC1101（Cap B）**: https://docs.m5stack.com/en/cap/Cap_CC1101

---

## 作者

**osprey74（Sohshi）** — Bluesky: [@osprey74.bsky.social](https://bsky.app/profile/osprey74.bsky.social)
