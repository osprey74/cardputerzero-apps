# CardputerZero Apps

> [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) 向けアプリケーションのモノレポ。Raspberry Pi CM0 を搭載したクレジットカードサイズの Linux ハンドヘルド端末用です。

[English README](./README.md)

本リポジトリは CardputerZero 向けに開発予定の 15 アプリ（GPS ロガー＋天球図表示、LoRa Meshtastic ノード、NFC / Sub-GHz セキュリティツール、BSAF 防災受信、SDR 広帯域受信、LAN 調査ツール、オフライン星座盤 等）を管理するモノレポです。

> **現在のステータス（2026-11-19）: 4 アプリが実機で動作中。** GPS ロガー（App 01）、Wi-Fi アナライザー（App 07）、LAN スキャナー（App 11）、星座盤（App 16）を実装し、`.deb` にまとめて、実機の標準ランチャーから起動できることを確認しました。ほかのアプリは設計または試作の段階です。未確認事項は [HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo) で管理しています。アプリは手元の端末で使うためのもので、公式 AppStore には公開していません。

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
| OS | Raspberry Pi OS（Debian 13 trixie。工場出荷イメージの Python は 3.13） |
| Launcher | LVGL ベース GUI ランチャー |
| AppStore | Debian `.deb` apt リポジトリ（[CardputerZeroRepository](https://github.com/m5stack/CardputerZeroRepository)） |

ハードウェア仕様の全項目は [HANDOFF §1](./HANDOFF_cardputerzero.md#1-ハードウェア概要) を参照してください。

### Cap モジュール（上部スロット差し替え式）

| | Cap A: Cap LoRa-1262 | Cap B: Hacker Cap |
|---|---|---|
| 無線 | SX1262（LoRa、868–923 MHz／国内送信は 922.0–923.4 MHz のみ） | CC1101（Sub-GHz、315/433/868/920 MHz／国内は受信のみ運用） |
| GNSS | AT6668（GPS / QZSS / GLO / GAL / BDS） | — |
| NFC | — | ST25R3916（ISO 14443A/B、FeliCa、ISO 15693） |
| 主な使用アプリ | App 01 / 02 / 05 | App 03 / 04 |

Cap A と Cap B は同じ上部スロットを使うため同時装着不可。Cap はホットプラグに対応していないため、差し替えは電源を切ってから行います。GPS ロガーと星座盤は、Cap の GNSS の代わりに Grove ポートの M5Stack Unit GPS v1.1 も使えます。

### 関連デバイス（推奨周辺機器）

| デバイス | 役割 |
|---|---|
| [M5Stack C6L Meshtastic Unit](https://www.switch-science.com/products/10809) | 自宅 LoRa ゲートウェイ（インターネット ↔ Meshtastic ブリッジ、Wi-Fi 6 内蔵） |
| [M5Stack Chain Encoder × 2](https://www.switch-science.com/collections/m5stack/products/10919) | デイジーチェーン式ロータリーノブ（周波数チューニング・リスト送り） |
| [RTL-SDR Blog V4](https://www.rtl-sdr.com/rtl-sdr-blog-v4-dongle-initial-release/) | USB SDR ドングル（500 kHz – 1.75 GHz 広帯域受信） |

---

## アプリ一覧

| ID | アプリ | 優先度 | ハードウェア | 主機能 | 状況 |
|---|---|---|---|---|---|
| 01 | [`gps-logger`](./apps/gps-logger/) | ★★★★★ | Cap A または Grove の GPS | GPX 1.1 トラックロガー（速度・距離の統計、GNSS 衛星の天球図、軌跡表示） | **v0.1.0** |
| 02 | `lora-mesh-node` | ★★★★☆ | Cap A + C6L | Meshtastic 互換オフグリッド通信ノード | 受信確認ツールのみ |
| 03 | `nfc-toolkit` | ★★★★☆ | Cap B | NFC カード学習ツール（ISO 14443A/B、FeliCa、ISO 15693） | 予定 |
| 04 | `subghz-sniffer` | ★★★☆☆ | Cap B | Sub-GHz 信号アナライザ（日本国内では受信のみ） | 予定 |
| 05 | `bsaf-client` | ★★★★☆ | Cap A + Wi-Fi | [BSAF v1](https://github.com/osprey74/bsaf-protocol) 防災アラート二系統受信（MQTT 主・LoRa 副） | 予定 |
| 06 | `edge-ai` | ★★★☆☆ | 本体内蔵 | オフライン LLM アシスタント（量子化 1B パラメータ以下） | 予定 |
| 07 | [`wifi-analyzer`](./apps/wifi-analyzer/) | ★★★☆☆ | 本体内蔵 | 周辺 AP の一覧・2.4GHz チャンネルマップ・信号グラフ（受信のみ） | **v0.1.1** |
| 08 | `nfc-checkpoint` | ★★★☆☆ | Cap A + Cap B | NFC タグ × GPS チェックポイントロガー | 予定 |
| 09 | `nfc-lora-auth` | ★★☆☆☆ | Cap A + Cap B | オフグリッドバッジ認証 PoC（NFC 読取 → LoRa 中継） | 予定 |
| 10 | `sdr-receiver` | ★★★★☆ | RTL-SDR V4 | 広帯域 SDR 受信 + 自作統合モニター（FM / ADS-B / AIS / NOAA APT / rtl_433） | 試作中（uConsole） |
| 11 | [`lan-scanner`](./apps/lan-scanner/) | ★★★★☆ | 本体内蔵 | 接続中のサブネットの機器発見（ICMP＋ARP）・mDNS／DNS の名前・メーカー名・TCP ポート確認 | **v0.1.1** |
| 13 | `tester` | ★★★★☆ | INA226（Grove I2C） | DC 電圧・電流テスター | 予定 |
| 14 | `qr-toolkit` | ★★★★☆ | 本体カメラ（標準版） | QR コードの読み取りと構造の解析 | 予定 |
| 15 | `ncir_thermometer` | ★★★☆☆ | MLX90614 + PaHUB（Grove） | 非接触温度計 | Python の PoC |
| 16 | [`stellar-map`](./apps/stellar-map/) | ★★★☆☆ | 本体内蔵（GNSS は任意） | 惑星・月も表示するオフライン星座盤 | **v0.1.6** |

App 12 は App 10 に統合しました。各アプリの機能チェックリストは [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様) を参照してください。

---

## 技術スタック

- **言語**: 方針としては Rust を優先していますが、aarch64 Linux 向けの Rust ビルド環境がまだ整っていないため、実装済みのアプリは **Python** で書いています。依存は工場出荷イメージにあるもの（Python 3.13・Pillow・numpy）だけで、`apt` での追加導入はしません
- **UI**: 標準ランチャーや標準アプリと同じく、フレームバッファ（`/dev/fb0`・320×170・RGB565）へ直接描き、キーボードは evdev から直接読みます。SDL2 のウィンドウは LCD に表示されません。共通の UI 部品は [`shared/fb_ui`](./shared/fb_ui/) にあります（日本語は Noto Sans CJK で表示）
- **ランタイム**: `legacy-deb-only`。各アプリは単体で起動するプログラムで、`/usr/share/APPLaunch/applications/<name>.desktop` でランチャーに登録します
- **パッケージ**: [`scripts/pack_deb.sh`](./scripts/pack_deb.sh) が各アプリの `packaging/` から `.deb` を作ります。`dpkg-deb` が必要なため、実機の上で実行します
- **画面の確認とテスト**: 各アプリは `--headless` と `--script`（LCD とキーボードに触れずに動かし、PNG で保存）に対応し、一部は `--demo`（疑似データ）にも対応しています。PC でも SSH 経由でも画面を確認できます。`czdev` のエミュレータは使っていません
- **アプリ配布**: 手元の端末で `apt install` して使うためのもので、公式 AppStore には公開していません
- **リモート開発**: Tailscale VPN 経由で自宅 Mac Mini に接続しフル Claude モデルをリモート実行（CardputerZero の 512MB RAM ではローカル実行困難なため）

---

## リポジトリ構成

```text
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md     # 一次設計書
├── apps/                        # アプリごとに src/・packaging/・app-builder.json・README.md
│   ├── gps-logger/              # App 01  v0.1.0
│   ├── lora-mesh-node/          # App 02  受信確認ツール
│   ├── nfc-toolkit/             # App 03
│   ├── subghz-sniffer/          # App 04
│   ├── bsaf-client/             # App 05
│   ├── edge-ai/                 # App 06
│   ├── wifi-analyzer/           # App 07  v0.1.1
│   ├── nfc-checkpoint/          # App 08
│   ├── nfc-lora-auth/           # App 09
│   ├── sdr-receiver/            # App 10  試作中
│   ├── lan-scanner/             # App 11  v0.1.1
│   ├── tester/                  # App 13
│   ├── ncir_thermometer/        # App 15  Python の PoC
│   └── stellar-map/             # App 16  v0.1.6
├── shared/
│   ├── fb_ui/                   # フレームバッファ UI と evdev のキー入力（Python）
│   ├── gnss_at6668/             # GNSS ドライバ（Cap／Grove の 5V 制御・NMEA の RMC/GGA/GSA/GSV）
│   ├── star_catalog/            # 星表と投影（App 16）
│   ├── compass/                 # 方位（BMM150 など）
│   ├── cores3_bridge/           # CoreS3 フロントエンドとの USB CDC 連携
│   ├── lora_sx1262/             # SX1262 LoRa ドライバ（予定）
│   ├── nfc_st25r3916/           # ST25R3916 NFC ドライバ（予定）
│   ├── rf_cc1101/               # CC1101 Sub-GHz ドライバ（予定）
│   ├── input_encoder/           # Chain Encoder 入力（予定）
│   └── ui_theme/                # 共通テーマ（予定）
├── templates/                   # 新規アプリの雛形（rust-fb-app / rust-sdl2-app / python-sidecar-app）
├── firmware/                    # CoreS3 用ファームウェア（フロントエンド・水準器・タイマー）
├── scripts/                     # pack_deb.sh（.deb の作成）・deploy.sh・セットアップ用スクリプト
├── assets/                      # 構成図（SVG）
└── docs/                        # 資料・技適の資料
```

---

## はじめかた

### PC で画面を確認する

UI のコードに必要なのは Python 3 と Pillow・numpy だけです。`--demo` に対応したアプリは、疑似データで PC 上でも動きます。

```bash
pip install pillow numpy
python apps/gps-logger/src/gps_logger.py --demo --headless \
  --script "4 enter; 30 shot /tmp/dash.png; 30.5 2; 31 shot /tmp/sky.png; 32 quit"
python -m unittest discover -s apps/gps-logger/tests
```

### 実機でパッケージを作って導入する

```bash
# リポジトリ（またはアプリ・shared/・scripts/）を実機へコピーし、実機の上で:
bash scripts/pack_deb.sh apps/gps-logger
apt-get -s install ./apps/gps-logger/dist-cz/*.deb    # 試算: ほかのパッケージが変わらないことを確認
sudo apt install ./apps/gps-logger/dist-cz/*.deb
```

導入すると標準ランチャーにアイコンが出ます。終了は ESC の長押しです。キーボードのカーソルは Fn＋F/X/C/Z ですが、各アプリは Fn なしの F/X/C/Z でも動きます。キー操作やオプションは各アプリの README を参照してください。

> 実機で `apt upgrade` は実行しないでください。内蔵の Camera アプリは、工場出荷イメージの libcamera の版に合わせて作られています（[HANDOFF §9.1](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo)）。

実機側の注意点（初回セットアップウィザード・SSH・ランチャーの仕組み）は [HANDOFF §4.2.1](./HANDOFF_cardputerzero.md) と [HANDOFF §6](./HANDOFF_cardputerzero.md#6-開発環境セットアップ) を参照してください。

---

## 日本国内法令への配慮

無線周波数を扱う機能は、日本の電波法等への準拠を前提に設計しています。主な制約：

- **LoRa 送信**: Cap LoRa-1262 の工事設計認証（211-251216）の条件内に限定します。922.0〜923.4MHz の 8 波、125kHz 幅で 5mW 以下、1 回の送信は 0.4 秒未満、キャリアセンス必須、付属アンテナのみ。条件を満たす実装を確認するまでは受信のみで運用します
- **Sub-GHz**: Cap CC1101 は受信のみで運用します。工事設計認証（219-269336）の対象は 315MHz と 922〜923.4MHz のみで、433／868／915MHz は国内で送信できません
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
