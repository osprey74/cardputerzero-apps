# CardputerZero Apps

> M5Stack CardputerZero (Raspberry Pi CM0 搭載) 向けアプリケーション群

## プロジェクト概要

M5Stack CardputerZero 向けに開発するアプリ群のモノレポ。Rust (czdev / LVGL) を主軸に、必要に応じて Python サイドカーを組み合わせる。詳細仕様は [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md) を参照。

## ターゲットデバイス

- **SoC**: Broadcom BCM2837 (Raspberry Pi CM0 / RP3A0) / Quad-core Cortex-A53 @ 1GHz (aarch64)
- **RAM**: 512MB LPDDR2
- **LCD**: 1.9" ST7789v3 / native 170×320（縦）※本プロジェクトは 320×170 横向き運用
- **センサー**: BMI270（6軸 IMU・I2C `0x68`）＋ BMM150（3軸地磁気・`0x10`）／RX8130CE RTC（`0x32`）／キーボード TCA8418（`0x34`）
  - ⚠️ **BMM150 は Kickstarter 版のみ搭載**（EOL・retail 版は非搭載／Lite は元々 IMU 無し・KS Update #11 2026-08-13）。「磁力計内蔵＝単体で方位取得可」は **KS 版限定**。App16 星座盤は方位を CoreS3 の BMM150 経由で取得する設計のため実装影響なし（retail 配布時のみ CoreS3 or 手動アライン必須）
- **AppStore サイト状態**: `cardputer.cc` は **beta**（Hub は work in progress・KS Update #11）
- **バッテリ**: 3.7V 1750mAh（NTC 内蔵・BQ27220YZFR 燃料計・充電 5V/2A）
- **OS**: Raspberry Pi OS (Debian Linux ベース)
- **Launcher**: LVGL ベース GUI Launcher
- **AppStore**: 公式サイト https://cardputer.cc/ （Hub / AppStore & Registry・Web エミュレータ `/emulator/`）／開発者ポータル https://dev.cardputer.cc/ ／apt リポジトリ https://github.com/m5stack/CardputerZeroRepository
  - 配布は `.deb`・メタは `app-builder.json`（`app.yaml` は非公式・旧）。レジストリはパッケージ名**先着順**（名前照合は `-` `_` `.` を無視）。ショップ掲載はスクショ 320×170 PNG 最大6・正方形 PNG アイコン。SDK/Kernel docs は公式に "coming soon"（2026-08-13 時点）

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
| 15 | `ncir-thermometer` | ★★★☆☆ | MLX90614 非接触温度センサ（PaHUB CH1 / 業務点検・PC サーマル・料理補助） |
| 16 | `stellar-map` | ★★★☆☆ | オフライン星座盤（Skyfield＋HYG／内蔵 RTC・GNSS・NTP／HDMI プラネタリウム） |

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

- SSH: `ssh pi@cardputerzero.local`（2026-11-17 実機で接続確認済み。ユーザー名 `pi` は初回セットアップウィザードで設定・SSH もウィザードで有効化。現状はパスワード認証で、鍵認証は未設定）
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

## アプリメタデータ (app-builder.json)

公式マニフェストは各アプリルートの `app-builder.json`（Launcher / AppStore 登録に必要）。
`caps` 予約語は `keyboard` / `audio` / `network` / `filesystem` / `pty` / `process`。
実例は `apps/stellar-map/`・`apps/ncir_thermometer/`。

```json
{
  "package_name": "ncir-thermometer",
  "version": "0.1.0",
  "app_name": "NCIR Thermometer",
  "bin_name": "thermometer_poc.py",
  "description": "App15 MLX90614 non-contact thermometer PoC ...",
  "runtime": "legacy-deb-only",
  "caps": ["keyboard", "filesystem"]
}
```

> ⚠️ 旧来の `app.yaml`（`com.osprey74.*` 形式）は**非公式**。HANDOFF §2.7.3 参照。ショップ掲載メタ
> （カテゴリ最大6・正方形 PNG アイコン・320×170 PNG スクショ最大6）も `app-builder.json` 側に持つ。
> `runtime`: `legacy-deb-only`（独立実行＝C/Python/Rust 等自由）／`lvgl-dlopen`（C 共有ライブラリ・LVGL 9.5）。

## エコシステム連携

- **Rindo (りんどう / サイクリングナビ)**: App 01 (`gps-logger`) からの GPX エクスポートを Rindo にインポート可能とする
- **bsaf-protocol**: App 05 (`bsaf-client`) が準拠する仕様。一次資料は `bsaf-protocol/docs/bsaf-spec-ja.md`
- **bsaf-jma-bot**: App 05 が Wi-Fi 接続時に MQTT 経由でサブスクライブする供給側 Bot

## 日本国内法令遵守

| 項目 | 規制 | 対応 |
|---|---|---|
| LoRa 送信 | 920MHz 帯特定小電力 | Cap LoRa-1262 は工事設計認証 211-251216（総務省 DB 照合済み 2026-11-17）。**922〜923.4MHz・8 波・最大 5.0mW（≒7dBm）の範囲のみ**送信可 |
| Sub-GHz 送信 | 技適取得済み機器のみ | Cap CC1101 は工事設計認証 219-269336（315MHz 0.04mW／922〜923.4MHz のみ対象・433/868/915MHz は認証外）。当面は受信のみ運用を継続（HANDOFF §9.1） |
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

- **version_files**: 各アプリの `app-builder.json`（および併存する `app.yaml`）内 `version` フィールド（アプリ単位で独立バージョニング）
- **mono_version**: false（モノレポだがアプリごとに独立バージョン）
- **cargo_lockfile**: true（Rust アプリごとに `Cargo.lock` を保持）

## CI/CD

- **cicd**: false（未整備、Kickstarter 到着・実機検証後に GitHub Actions の導入を検討）
- **cicd_platform_candidate**: GitHub Actions (Linux aarch64 クロスビルド)

## SNS

- **sns_accounts**:
  - Bluesky: `@osprey74.bsky.social`（実機到着後にアプリリリース告知予定）

## 制約事項

- **実機到着済み（2026-11-17・本体＋Cap LoRa-1262＋Cap CC1101）**: 仕様の最終確定は実機検証で行う。初回起動はセットアップウィザード（ユーザー名・ネットワーク・SSH）。Cap はホットプラグ不可、Grove/EXT の 5V 出力は既定 OFF（Settings > ExtPort）
- **⚠️ カメラ不具合（KS Update #15・2026-11-10）**: システム更新や追加アプリ導入後にカメラが動かなくなる報告あり（ソフト起因）。公式修正 OTA の適用を確認するまで、不要な `apt upgrade` を避け、パッケージ導入前に microSD をバックアップする。詳細は HANDOFF 変更履歴 2026-11-17
- **HANDOFF_cardputerzero.md §9** に列挙された未確認事項（Grove ピンアサイン、SX1262 技適番号、AT6668 と gpsd の互換性等）は実機到着後に検証する
- 仕様の不整合が発生した場合は `HANDOFF_cardputerzero.md` を一次資料として更新する

## 参照ドキュメント

- [HANDOFF_cardputerzero.md](HANDOFF_cardputerzero.md) — 本プロジェクトの一次設計書
- [M5Stack CardputerZero 公式](https://shop.m5stack.com/pages/m5-cardputerzero)
- [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder)
- [AppStore Hub](https://cardputerzero.github.io)
- [BSAF Protocol](https://github.com/osprey74/bsaf-protocol)
