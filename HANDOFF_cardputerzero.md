# HANDOFF: CardputerZero 開発ガイド

> **作成日**: 2026-05-24  
> **対象デバイス**: M5Stack CardputerZero (Raspberry Pi CM0 搭載)  
> **開発者**: 総司 (osprey74)  
> **開発方針**: Spec-Driven / Claude Code + czdev ワークフロー  
> **リポジトリ予定**: `osprey74/cardputerzero-apps`

---

## 1. ハードウェア概要

### 1.1 本体スペック

| 項目 | 仕様 |
|------|------|
| SoC | Broadcom BCM2837 (Raspberry Pi CM0) |
| CPU | Quad-core Cortex-A53 @ 1GHz |
| GPU | VideoCore-IV @ 400MHz |
| RAM | 512MB LPDDR2 |
| ストレージ | microSD (標準版: 32GB 付属) |
| ディスプレイ | 1.9" LCD ST7789V2 (320×170) |
| キーボード | 46キー マトリクス |
| バッテリー | 3.7V 1500mAh Li-Po |
| Wi-Fi | 2.4GHz 802.11 b/g/n |
| Bluetooth | 4.2 / BLE |
| 有線LAN | 10/100M Ethernet |
| USB | USB-C × 2 (Host/Slave 切替) + USB-A × 1 |
| カメラ (標準版) | Sony IMX219 8MP (CSI) |
| IMU (標準版) | Bosch BMI270 6軸 |
| RTC | Epson RX8130CE |
| HDMI | 最大 1080p30 出力 |
| サイズ | 85 × 54mm (クレジットカードサイズ) |

### 1.2 拡張インターフェース

| ポート | 仕様 | 主な用途 |
|--------|------|----------|
| Grove | HY2.0-4P (I2C / UART 切替) | GNSS, センサー類 |
| SPI | 2.54mm ヘッダー | SX1262 LoRa, CC1101 |
| I2C | 2.54mm ヘッダー | NFC (ST25R3916), IMU |
| UART | 2.54mm ヘッダー | GNSS NMEA, シリアル通信 |
| GPIO | 2.54mm ヘッダー | 汎用 |
| CSI | カメラコネクタ | IMX219 |

### 1.3 装着確認済みモジュール

| モジュール | 接続方式 | 確認方法 |
|------------|----------|----------|
| Cap LoRa 1262 (SX1262 + AT6668) | 上部スロット (Kickstarter公式画像) | ✅ 物理マウント互換 |
| Unit NFC (ST25R3916) | Grove / I2C | ✅ M5Stack公式対応明記 |
| CC1101 Sub-GHz | SPI / GPIO | ✅ M5Stack公式対応明記 |
| Grove センサー 100+種 | Grove HY2.0-4P | ✅ 互換 |

---

## 2. ソフトウェア環境

### 2.1 OS・Launcher

- **OS**: Raspberry Pi OS (Debian Linux ベース)
- **Launcher**: GUI ランチャー搭載 (1.9" LCD 上でグラフィカル起動)
- **AppBuilder フレームワーク**: LVGL (Light and Versatile Graphics Library)
- **AppStore**: `https://cardputerzero.github.io` (GitHub Pages ベース静的レジストリ)

### 2.2 開発ツールチェーン

```
# czdev CLIのセットアップ (Mac / Linux)
sudo apt install -y build-essential cmake pkg-config \
  libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libfreetype-dev

# Rust ツールチェーン
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# AppBuilder リポジトリ
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
```

### 2.3 開発ワークフロー

```
1. PC 上で Claude Code を使い設計・実装
   ↓
2. czdev エミュレータで 320×170 LCD 画面を確認 (デバイス不要)
   ↓
3. SSH でデバイスへデプロイ & 実機テスト
   ↓
4. AppStore へ登録 → Launcher から起動
```

### 2.4 Claude Code 統合

```bash
# SSH 経由で CardputerZero に直接 Claude Code セッション
ssh pi@cardputerzero.local
claude code  # デバイス上で直接実行 (軽量タスク向け)

# または PC 側から SSH リモートとして利用 (推奨: 512MB RAM 節約)
# Tauri/PC で claude code → SSH 経由でデプロイ
```

---

## 3. アプリ開発仕様

### App 01: GPS ロガー (`gps-logger`)

**優先度**: ★★★★★ (最優先)

#### 概要
Cap LoRa 1262 の AT6668 GNSS チップを使い、走行・サイクリングルートを記録するツール。Launcher から起動し、1.9" 画面上でリアルタイム表示。

#### 技術スタック

| レイヤー | 採用技術 |
|----------|----------|
| GPS 受信 | `/dev/ttyS*` UART → NMEA 解析 |
| パースライブラリ | `pynmea2` (Python) または `nmea` crate (Rust) |
| ログ形式 | GPX 1.1 / GeoJSON / CSV |
| ストレージ | `/mnt/sdcard/gps_logs/` (microSD) |
| UI フレームワーク | LVGL (czdev) |
| 地図表示 (将来) | MapLibre GL (HDMI 外部出力時) |

#### 機能一覧

- [ ] NMEA センテンス受信・パース (GGA, RMC, GSV)
- [ ] リアルタイム座標・速度・高度表示 (LCD)
- [ ] GPX ファイル記録 (microSD)
- [ ] トラック統計 (総距離・平均速度・最高速度・累積標高)
- [ ] 衛星捕捉数・精度 (HDOP) 表示
- [ ] 起動時の衛星ロック待機画面
- [ ] 記録開始 / 一時停止 / 終了 操作
- [ ] Rindo (りんどう) との GPX インポート連携

#### デバイスパス (仮)

```python
GPS_UART  = "/dev/ttyS0"   # AT6668 NMEA 出力
GPS_BAUD  = 9600            # デフォルト (変更可: 115200)
LOG_DIR   = "/mnt/sdcard/gps_logs"
```

#### LoRa 位置共有 (拡張)

```python
LORA_SPI  = "/dev/spidev0.0"   # SX1262
LORA_FREQ = 920.8              # MHz (日本 920MHz 帯)
# Meshtastic POSITION パケットで周囲ノードへブロードキャスト
```

---

### App 02: LoRa Meshtastic ノード (`lora-mesh-node`)

**優先度**: ★★★★☆

#### 概要
SX1262 を使い CardputerZero を Meshtastic 互換のオフグリッド通信ノードとして動作させる。BSAF プロトコルの送受信にも対応。

#### 機能一覧

- [ ] Meshtastic 互換パケット送受信
- [ ] 近隣ノードマップ表示 (LCD)
- [ ] テキストメッセージ送信 (キーボード入力)
- [ ] GPS 座標の自動ブロードキャスト (App01 連携)
- [ ] BSAF v1 アラートパケット受信・表示
- [ ] 中継 (Router) モード動作
- [ ] Wi-Fi ゲートウェイ (LoRa ↔ MQTT ブリッジ)

#### 周波数・電波法注意事項

```
日本国内での使用可能帯域:
  920.6 MHz ～ 928.0 MHz (特定小電力無線)
  最大出力: 20mW (技適取得済みモジュール使用必須)
※ SX1262 モジュールの技適番号を事前確認すること
※ アマチュア無線局免許では使用不可 (特小扱い)
```

---

### App 03: NFC セキュリティツール群 (`nfc-toolkit`)

**優先度**: ★★★★☆

#### 概要
Unit NFC (ST25R3916) を Grove/I2C 接続し、カードの読み取り・書き込み・エミュレーションを行う実践的セキュリティ学習ツール。教育・研究・ペネトレーションテスト学習を目的とする。

#### サポートプロトコル

| プロトコル | 用途 |
|------------|------|
| ISO 14443A | Mifare Classic, NTAG, FeliCa |
| ISO 14443B | 一部交通系カード |
| FeliCa | Suica / PASMO (読み取り学習) |
| ISO 15693 | HF-RFID (物流タグ等) |

#### 機能一覧

- [ ] カード UID 読み取り・表示
- [ ] NDEF メッセージ読み取り / 書き込み
- [ ] カードエミュレーションモード (アクセスバッジ学習)
- [ ] UID スプーフィング (教育目的・自己所有カードのみ)
- [ ] パケットキャプチャ・ダンプ (カスタムプロトコル)
- [ ] Mifare Classic セクター解析
- [ ] ログ記録 (JSON 形式 → microSD)

#### ライブラリ

```python
# Python: nfcpy (ISO 14443A/B, FeliCa, ISO 15693)
pip install nfcpy

# または libst25r3916 (公式 C ライブラリ) をバインディング
```

#### ⚠️ 法的注意事項

```
・他者所有のカードへの無断アクセスは不正アクセス禁止法に抵触する可能性あり
・交通系カードへの書き込みは電子計算機損壊等業務妨害罪に該当する可能性あり
・本ツールは自己所有カードの学習・研究目的にのみ使用すること
・ペネトレーションテストは書面による事前合意がある場合のみ実施
```

---

### App 04: Sub-GHz スニファー (`subghz-sniffer`)

**優先度**: ★★★☆☆

#### 概要
CC1101 モジュール (SPI 接続) を使い、Sub-GHz 帯の無線信号を受信・解析する。Flipper Zero の Sub-GHz 機能に相当。

#### 対応周波数 (日本国内受信のみ)

| バンド | 用途例 |
|--------|--------|
| 315 MHz | 旧式リモコン類 |
| 433 MHz | 欧州 IoT, 温度計等 |
| 920 MHz | 特定小電力, スマートメーター |

#### 機能一覧

- [ ] 信号受信・スペクトル表示 (受信のみ: 電波法上問題なし)
- [ ] OOK / ASK / FSK 変調デコード
- [ ] リプレイ攻撃テスト (自己所有デバイスへの教育目的のみ)
- [ ] 信号ダンプ・保存 (`.sub` 形式 / Flipper Zero 互換)
- [ ] 周波数スキャン (受信レベルグラフ)

#### ⚠️ 法的注意事項

```
・電波の受信は原則合法 (通信の秘密侵害に注意)
・送信は技術基準適合証明 (技適) 取得済み機器でのみ可能
・他者の通信内容の傍受・漏洩は電波法・通信傍受法に抵触する可能性あり
・リプレイ送信は自己所有システムへの教育目的のみとする
```

---

### App 05: BSAF 防災受信クライアント (`bsaf-client`)

**優先度**: ★★★★☆

#### 概要
LoRa 経由で BSAF v1 アラートパケットを受信し、気象警報・地震情報を画面表示する。2018年北海道胆振東部地震のような大規模停電時でもオフグリッドで情報受信。

#### BSAF v1 タグ構造

```json
{
  "bsaf": "v1",
  "type": "earthquake",
  "value": "7",
  "time": "2026-05-24T09:00:00Z",
  "target": "北海道",
  "source": "JMA"
}
```

#### 機能一覧

- [ ] BSAF v1 パケット受信・パース
- [ ] 地震情報表示 (震度・震源地・時刻)
- [ ] 津波警報表示 (bsaf-jma-bot 対応後)
- [ ] 気象警報表示
- [ ] アラート音・バイブレーション (スピーカー経由)
- [ ] 受信ログ保存
- [ ] Wi-Fi 接続時: bsaf-jma-bot の MQTT にも購読

#### 関連リポジトリ

- `bsaf-protocol` (仕様): `osprey74/bsaf-protocol`
- `bsaf-jma-bot` (供給側): 津波・気象警報パース追加予定

---

### App 06: Edge AI アシスタント (`edge-ai`)

**優先度**: ★★★☆☆

#### 概要
OpenClaw 等の軽量 LLM エッジツールを使い、オフラインでのコード補完・質問応答を実現。

#### 候補フレームワーク

| ツール | 特徴 |
|--------|------|
| OpenClaw | M5Stack 公式推奨 |
| llama.cpp | Llama 3 / Phi-3 対応 |
| whisper.cpp | 音声認識 (マイク活用) |

#### 制約

```
RAM: 512MB → モデルは Q4_K_M 量子化 1B 以下推奨
ストレージ: microSD に格納 (読み込み速度がボトルネック)
```

---

### App 07: Wi-Fi 解析ツール (`wifi-analyzer`)

**優先度**: ★★★☆☆

#### 概要
Linux の `iw` / `hostapd` / `aircrack-ng` 系ツールを活用した Wi-Fi 環境解析・ペネトレーションテスト学習環境。

#### 機能一覧

- [ ] 周辺 AP スキャン・チャンネルマップ表示
- [ ] RSSI グラフ (時系列)
- [ ] WPA ハンドシェイクキャプチャ (自己所有 AP のみ)
- [ ] アクセスポイントモード (Wi-Fi ホットスポット化)
- [ ] Wireshark リモート連携 (SSH 経由)

---

## 4. Launcher 登録仕様

### 4.1 アプリメタデータ形式 (AppStore)

```yaml
# app.yaml (各アプリルートに配置)
name: "GPS Logger"
id: "com.osprey74.gps-logger"
version: "1.0.0"
description: "AT6668 GNSS による GPX ロガー"
author: "osprey74"
category: "navigation"
icon: "assets/icon.png"         # 48x48 PNG
requires:
  - cap_lora_1262
entry: "src/main"               # czdev エントリポイント
```

### 4.2 Launcher 登録手順

```bash
# 1. ビルド
cargo run -p czdev --release -- build

# 2. デバイスへ転送
scp -r dist/ pi@cardputerzero.local:/apps/gps-logger/

# 3. AppStore 登録 (PR ベース)
#    cardputerzero.github.io の registry.json へ追加
```

---

## 5. リポジトリ構成

```
osprey74/cardputerzero-apps/
├── CLAUDE.md                   # Claude Code 設定
├── HANDOFF_cardputerzero.md    # 本ドキュメント
├── apps/
│   ├── gps-logger/             # App 01
│   │   ├── app.yaml
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── gnss.rs         # NMEA パーサー
│   │   │   ├── gpx.rs          # GPX 出力
│   │   │   └── ui.rs           # LVGL 画面
│   │   └── tests/
│   ├── lora-mesh-node/         # App 02
│   ├── nfc-toolkit/            # App 03
│   ├── subghz-sniffer/         # App 04
│   ├── bsaf-client/            # App 05
│   ├── edge-ai/                # App 06
│   └── wifi-analyzer/          # App 07
├── shared/
│   ├── lora_sx1262/            # SX1262 共通ドライバ
│   ├── gnss_at6668/            # AT6668 共通ドライバ
│   └── ui_theme/               # 共通 UI テーマ (osprey74 カラー)
└── scripts/
    ├── setup_device.sh         # デバイス初期セットアップ
    └── deploy_all.sh           # 全アプリ一括デプロイ
```

---

## 6. 開発環境セットアップ

### 6.1 PC 側 (開発機)

```bash
# 前提: macOS または Linux
# 1. Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu   # クロスコンパイル

# 2. SDL2 (エミュレータ用)
# macOS:
brew install sdl2 sdl2_image sdl2_mixer

# 3. CardputerZero AppBuilder
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
export PATH="$PATH:$(pwd)/target/release"

# 4. エミュレータ起動テスト
czdev run examples/hello_cz
```

### 6.2 デバイス側 初期セットアップ

```bash
# SSH でデバイスに接続
ssh pi@cardputerzero.local  # デフォルトホスト名 (要確認)

# 必要パッケージ
sudo apt update && sudo apt install -y \
  python3-pip \
  gpsd gpsd-clients \
  python3-gps \
  nfcpy \
  wireshark-common

# SPI 有効化 (raspi-config または config.txt)
sudo raspi-config  # Interface Options → SPI → Enable
# または /boot/config.txt に追記:
# dtparam=spi=on

# UART 有効化 (GPS 用)
# /boot/config.txt:
# enable_uart=1
# dtoverlay=disable-bt  # BT との競合回避

# GPS デーモン起動
sudo systemctl enable gpsd
sudo systemctl start gpsd
```

### 6.3 Claude Code 設定 (CLAUDE.md)

```markdown
# CLAUDE.md - CardputerZero Apps

## プロジェクト概要
CardputerZero 向けアプリ群。Rust (czdev/LVGL) + Python で実装。

## 開発コマンド
- ビルド: `czdev build`
- エミュレータ: `czdev run`
- デプロイ: `./scripts/deploy.sh <app-name>`
- テスト: `cargo test`

## デバイス接続
- SSH: `ssh pi@cardputerzero.local`
- ポート: `22`

## 重要な制約
- LCD 解像度: 320×170 px (LVGL)
- RAM: 512MB (エッジAI は 1B モデル以下)
- LORA 周波数: 920MHz 帯のみ (日本)
- NFC/Sub-GHz: 自己所有デバイスへの教育目的のみ

## 共有ドライバ
- SX1262: `shared/lora_sx1262/`
- AT6668: `shared/gnss_at6668/`
```

---

## 7. 日本国内の法令・技術基準

| 項目 | 規制内容 | 対応 |
|------|----------|------|
| LoRa 送信 | 920MHz 帯特定小電力 (最大 20mW) | 技適番号確認必須 |
| Sub-GHz 送信 | 技適取得済み機器のみ | CC1101 は受信のみ推奨 |
| NFC 書き込み | 他者カードへの無断書き込み禁止 | 自己所有のみ |
| Wi-Fi 解析 | 他者ネットワークへの接続禁止 | 自己所有 AP のみ |
| 通信傍受 | 電波法・通信傍受法 | 受信のみ・内容漏洩禁止 |
| GPS | 受信は無制限 | 問題なし |

> ⚠️ **専門家確認推奨**: セキュリティツールの業務利用・社外利用については、弁護士または技術士への確認を推奨します。

---

## 8. 関連リンク・出典

| リソース | URL |
|----------|-----|
| Kickstarter | https://www.kickstarter.com/projects/m5stack/cardputerzero |
| M5Stack 公式ストア | https://shop.m5stack.com/pages/m5-cardputerzero |
| AppBuilder GitHub | https://github.com/m5stack/CardputerZero-AppBuilder |
| AppStore Hub | https://cardputerzero.github.io |
| Cap LoRa 1262 | https://shop.m5stack.com/products/cap-lora-1262-for-cardputer-adv-sx1262-atgm336h |
| Unit NFC ドキュメント | https://docs.m5stack.com/en/unit/Unit_NFC |
| LinuxGizmos スペック詳細 | https://linuxgizmos.com/m5stack-previews-cardputerzero-handheld-raspberry-pi-cm0-system/ |
| Hackster.io レビュー | https://www.hackster.io/news/m5stack-unveils-the-cardputerzero-... |
| BSAF プロトコル | https://github.com/osprey74/bsaf-protocol |
| Rindo (りんどう) | HANDOFF_cycling-nav.md 参照 |

---

## 9. 既知の未確認事項・TODO

- [ ] CardputerZero の Grove ポートの物理ピンアサイン (公式ドキュメント待ち)
- [ ] SX1262 の日本向け技適番号確認 (Kickstarter 到着後)
- [ ] czdev の ARM クロスコンパイル設定の検証
- [ ] Launcher の app.yaml スキーマ正式仕様 (AppBuilder リポジトリ要確認)
- [ ] Cap LoRa 1262 の SPI CE (Chip Enable) ピン番号
- [ ] AT6668 と Linux gpsd の互換性テスト

---

*このドキュメントは Kickstarter 到着・実機検証後に更新予定*  
*最終更新: 2026-05-24 by 総司 (osprey74)*
