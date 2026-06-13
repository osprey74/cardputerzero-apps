# CardputerZero Apps

> M5Stack CardputerZero (Raspberry Pi CM0 搭載) 向けアプリケーション群

## プロジェクト概要

M5Stack CardputerZero 向けに開発するアプリ群のモノレポ。Rust (czdev / LVGL) を主軸に、必要に応じて Python サイドカーを組み合わせる。詳細仕様は [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md) を参照。

## ターゲットデバイス

- **SoC**: Broadcom BCM2837 / Quad-core Cortex-A53 @ 1GHz
- **RAM**: 512MB LPDDR2
- **LCD**: 1.9" ST7789V2 / 320×170 px
- **OS**: Raspberry Pi OS (Debian Linux ベース)
- **Launcher**: LVGL ベース GUI Launcher
- **AppStore**: https://github.com/m5stack/CardputerZeroRepository （公式 Debian apt リポジトリ・`.deb` 配布）

## アプリ一覧（予定）

| ID | アプリ | 優先度 | 主機能 |
|---|---|---|---|
| 01 | `gps-logger` | ★★★★★ | AT6668 GNSS による GPX ロガー |
| 02 | `lora-mesh-node` | ★★★★☆ | SX1262 + Meshtastic 互換ノード |
| 03 | `nfc-toolkit` | ★★★★☆ | ST25R3916 による NFC 学習ツール |
| 04 | `subghz-sniffer` | ★★★☆☆ | CC1101 Sub-GHz 受信解析 |
| 05 | `bsaf-client` | ★★★★☆ | BSAF v1 防災アラート受信 |
| 06 | `edge-ai` | ★★★☆☆ | 軽量 LLM オフラインアシスタント |
| 07 | `wifi-analyzer` | ★★★☆☆ | Wi-Fi 環境解析 |
| 13 | `tester` | ★★★★☆ | INA226 DC 電圧/電流テスター (Grove I2C) |
| 14 | `qr-toolkit` | ★★★★☆ | IMX219 カメラによる QR 読取・解析・構造学習（標準版限定） |

## 想定リポジトリ構成

```
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md
├── apps/
│   ├── gps-logger/
│   ├── lora-mesh-node/
│   ├── nfc-toolkit/
│   ├── subghz-sniffer/
│   ├── bsaf-client/
│   ├── edge-ai/
│   └── wifi-analyzer/
├── shared/
│   ├── lora_sx1262/      # SX1262 共通ドライバ
│   ├── gnss_at6668/      # AT6668 共通ドライバ
│   └── ui_theme/         # osprey74 カラーの共通 UI テーマ
└── scripts/
    ├── setup_device.sh
    └── deploy_all.sh
```

## 技術スタック

- **言語**: Rust (czdev / LVGL バインディング) + Python (周辺ツール・サイドカー)
- **UI フレームワーク**: LVGL (Light and Versatile Graphics Library)
- **ビルドツール**: czdev CLI (CardputerZero-AppBuilder)
- **ターゲット**: `aarch64-unknown-linux-gnu`（クロスコンパイル）
- **エミュレータ**: czdev (SDL2 ベース、320×170 LCD を PC 上で再現)
- **デプロイ**: SSH + scp
- **AppStore 登録**: cardputerzero.github.io への PR

## 開発環境

開発機は **macOS / Windows 11 の両方**を想定。今操作している環境に応じてパス・シェル構文を切り替える。

### Windows 11 開発機

- 作業パス: `g:\dev\cardputerzero-apps\`
- シェル: PowerShell 7 (pwsh) を標準、ビルド時は **MSYS2 MINGW64** シェルを使用
- **AppBuilder は MSYS2 MINGW64 で公式サポート対象**（AppBuilder の `DESKTOP_DEV.md §4` 参照）
- SDL2 等のツールチェーンは `pacman` で `mingw-w64-x86_64-SDL2` 系を導入
- クロスコンパイル: MSYS2 上で `rustup target add aarch64-unknown-linux-gnu`
- WSL2 (Ubuntu) も使用可だが、SDL2 エミュレータの表示には WSLg / X サーバが必要なため MSYS2 ネイティブが安定

### macOS 開発機

- 作業パス: `~/dev/cardputerzero-apps/`（想定）
- シェル: zsh
- SDL2 等は Homebrew で導入: `brew install sdl2 sdl2_image sdl2_mixer`
- クロスコンパイル: `rustup target add aarch64-unknown-linux-gnu`

### デバイス接続（共通）

- SSH: `ssh pi@cardputerzero.local`（デフォルトホスト名、実機到着後に要確認）
- ポート: 22

## 開発コマンド（czdev）

- ビルド: `czdev build`
- エミュレータ実行: `czdev run`
- デプロイ: `./scripts/deploy.sh <app-name>`（実装予定）
- テスト: `cargo test`

## アーキテクチャ原則

- 共通ハードウェアドライバは `shared/` 配下に集約し、各アプリは依存パッケージとして取り込む
- LCD 解像度 320×170 を前提に UI を設計（縦長レイアウト不可、横スクロールは極力避ける）
- RAM 512MB の制約下で動作させるため、大規模ライブラリの抱え込みを避ける
- エッジ AI は Q4_K_M 量子化 1B パラメータ以下のモデルを使用
- LoRa 送信は日本国内 920MHz 帯のみ、技適取得済みモジュールに限定
- NFC / Sub-GHz / Wi-Fi 解析機能は **自己所有デバイス・教育目的のみ**（HANDOFF §7 参照）

## アプリメタデータ (app.yaml)

各アプリのルートに `app.yaml` を配置。Launcher / AppStore 登録に必要。

```yaml
name: "GPS Logger"
id: "com.osprey74.gps-logger"
version: "1.0.0"
description: "AT6668 GNSS による GPX ロガー"
author: "osprey74"
category: "navigation"
icon: "assets/icon.png"   # 48x48 PNG
requires:
  - cap_lora_1262
entry: "src/main"
```

## エコシステム連携

- **Rindo (りんどう / サイクリングナビ)**: App 01 (`gps-logger`) からの GPX エクスポートを Rindo にインポート可能とする
- **bsaf-protocol**: App 05 (`bsaf-client`) が準拠する仕様。一次資料は `bsaf-protocol/docs/bsaf-spec-ja.md`
- **bsaf-jma-bot**: App 05 が Wi-Fi 接続時に MQTT 経由でサブスクライブする供給側 Bot

## 日本国内法令遵守

| 項目 | 規制 | 対応 |
|---|---|---|
| LoRa 送信 | 920MHz 帯特定小電力 (最大 20mW) | 技適番号確認必須 |
| Sub-GHz 送信 | 技適取得済み機器のみ | CC1101 は受信のみ運用 |
| NFC 書き込み | 不正アクセス禁止法 | 自己所有カードのみ |
| Wi-Fi 解析 | 電波法 (他者ネットワーク接続禁止) | 自己所有 AP のみ |
| 通信傍受 | 電波法 / 通信傍受法 | 受信のみ・内容漏洩禁止 |

> ⚠️ セキュリティ系機能の業務・対外利用については、弁護士または技術士への確認を推奨します。

## Task Management

- **task_file**: [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md) の §9「既知の未確認事項・TODO」セクションおよび各アプリ §3 の「機能一覧」チェックボックス
- **done_marker**: `[x]`
- **progress_summary**: false（フェーズ表は実装着手時に追加検討）

## Documentation

- **docs_to_update**: `README.md` / `README.ja.md`（未作成、Kickstarter 到着後に整備）
- **doc_pairs**: `README.md` ⇔ `README.ja.md`
- **primary_spec**: [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md)（一次情報・設計書、仕様変更時はこちらを正とする）

## Versioning

- **version_files**: 各アプリの `app.yaml` 内 `version` フィールド（アプリ単位で独立バージョニング）
- **mono_version**: false（モノレポだがアプリごとに独立バージョン）
- **cargo_lockfile**: true（Rust アプリごとに `Cargo.lock` を保持）

## CI/CD

- **cicd**: false（未整備、Kickstarter 到着・実機検証後に GitHub Actions の導入を検討）
- **cicd_platform_candidate**: GitHub Actions (Linux aarch64 クロスビルド)

## SNS

- **sns_accounts**:
  - Bluesky: `@osprey74.bsky.social`（実機到着後にアプリリリース告知予定）

## 制約事項

- **未着手段階**: CardputerZero は Kickstarter 出資品で実機未到着（2026-05-24 時点）。仕様の最終確定は実機検証後
- **HANDOFF_cardputerzero.md §9** に列挙された未確認事項（Grove ピンアサイン、SX1262 技適番号、AT6668 と gpsd の互換性等）は実機到着後に検証する
- 仕様の不整合が発生した場合は `HANDOFF_cardputerzero.md` を一次資料として更新する

## 参照ドキュメント

- [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md) — 本プロジェクトの一次設計書
- [M5Stack CardputerZero 公式](https://shop.m5stack.com/pages/m5-cardputerzero)
- [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder)
- [AppStore Hub](https://cardputerzero.github.io)
- [BSAF Protocol](https://github.com/osprey74/bsaf-protocol)
