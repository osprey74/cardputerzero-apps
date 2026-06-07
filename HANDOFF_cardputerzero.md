# HANDOFF: CardputerZero 開発ガイド

> **作成日**: 2026-05-24 / **最終更新**: 2026-06-07  
> **対象デバイス**: M5Stack CardputerZero (Raspberry Pi CM0 搭載)  
> **開発者**: 総司 (osprey74)  
> **開発方針**: Spec-Driven / Claude Code + czdev ワークフロー  
> **リポジトリ予定**: `osprey74/cardputerzero-apps`

| 更新日 | 変更内容 |
|--------|----------|
| 2026-05-24 | 初版作成 |
| 2026-05-27 | KS 開始確認・§2.5 Tailscale 連携・§2.6 日本語入力 追記 |
| 2026-05-27 | Cap B (Hacker Cap: CC1101+NFC) 詳細仕様追記・App 03/04 更新・App 08/09 追加 |
| 2026-05-27 | 公式ドキュメント確認・Cap B ピンマップ確定・App 10 (SDR 広帯域受信) 追加・TODO 更新 |
| 2026-05-27 | App 10: RTL-SDR V4 USB-C 専用ドライバ手順・トラブルシューティング追記 |
| 2026-05-27 | App 11 (LAN 調査ツール) 追加・法令テーブル・CLAUDE.md 更新 |
| 2026-06-06 | App 12 (汎用電波受信アプリ) 追加 |
| 2026-06-07 | AppStore URL 確定（CardputerZeroRepository）・Cap LoRa-1262 技適メモ・C6L ゲートウェイ・App02 LoRa 構成・App05 二系統受信に再設計・MSYS2 Windows 対応・HANDOFF2 統合 |
| 2026-06-07 | App 12 を App 10 の「自作統合モニターモード」として吸収（重複解消） |
| 2026-06-07 | 入力デバイス拡張（Scroll Unit / Chain Encoder）追記・App 10 物理 UI 拡張サブセクション追加 |
| 2026-06-07 | App 01 に Sky Plot（天球図）表示仕様を追加（LCD 分割ビュー + HDMI フルスクリーン） |
| 2026-06-07 | `shared/input_encoder/` 共通入力ドライバを新設（App01 / App10 / App11 で共有） |
| 2026-06-07 | Scroll Unit を仕様から外し Chain Encoder 一本化・App 11 に Chain Encoder 連携機能を追加 |
| 2026-06-07 | §10 購入リスト・見積もり、§11 Phase ロードマップ を新設 |

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
| **Cap A**: Cap LoRa 1262 (SX1262 + ATGM336H-6N@AT6668) | 上部 Cap スロット | ✅ Kickstarter公式画像で確認 / ⚠️ 技適番号は実機到着後に要確認 |
| **Cap B**: Hacker Cap (CC1101 + ST25R3916 NFC) | 上部 Cap スロット | ✅ M5Stack公式X・プレスリリースで確認 / ⚠️ CC1101 技適は実機到着後に要確認 |
| Grove センサー 100+種 | Grove HY2.0-4P | ✅ 互換 |

> ⚠️ **Cap スロット制約**: Cap A と Cap B は上部スロットを共用するため**同時装着不可**。
> 用途に応じて付け替えて使用する。Grove ポートを使った片方常駐構成は実機到着後に要検証。

#### 関連デバイス（自宅 LoRa ゲートウェイ用）

| デバイス | 役割 | 主な仕様 |
|----------|------|----------|
| [M5Stack C6L Meshtastic Unit](https://www.switch-science.com/products/10809) | 自宅 LoRa ゲートウェイ（App02 §家側） | SX1262 + ESP32-C6 / Wi-Fi 6 (2.4GHz) / Meshtastic 対応 / USB-C 給電 / ¥4,290 |

- CardputerZero の Cap LoRa-1262 と**同一の SX1262** を搭載しているため LoRa レイヤで完全互換
- Wi-Fi 内蔵のため**デスクトップ PC への接続は必須ではない**。USB 充電器に挿すだけで MQTT ⇔ LoRa ブリッジとして稼働可能（構成A）
- 必要なら USB Serial 経由で PC からカスタム制御も可能（構成B、§3 App02 参照）
- ⚠️ 技適番号は Cap LoRa-1262 と同様、実機購入後にラベル確認 → 総務省データベース照合が必要

#### 関連デバイス（入力デバイス拡張）

App 10（SDR 受信機）の周波数選択、その他 LCD 上での一覧スクロールやズーム操作に
利用する Grove 接続のロータリーエンコーダモジュール。

| デバイス | 役割 | 主な仕様 |
|----------|------|----------|
| [M5Stack Chain Encoder](https://www.switch-science.com/collections/m5stack/products/10919) | 多ノブ入力（採用）| Grove UART デイジーチェーン (2× HY2.0-4P) / STM32G031 内蔵 / AB 相 / ノブ押下検知 / WS2812 RGB / ¥1,122 |

- **エンコーダ方式**: AB 相**増分（incremental）エンコーダ**で、機械的なストッパーがなく**物理的には無限回転**する。回転検出はソフトウェア側でパルスを積算する方式
- **採用構成**: **Chain Encoder × 2 個デイジーチェーン**（ノブA = 周波数粗調整 / ノブB = 周波数微調整 or ゲイン）。Grove ポート 1 つだけで多ノブ運用が可能
- **他アプリへの転用**: App 01（GPS ロガー: 衛星リスト送り）、App 11（LAN Scanner: ホストリスト送り）等の LCD 一覧操作にも利用
- **設計指針**: アプリ側は `shared/input_encoder/` 共通ドライバ経由で抽象 API（`RotateDelta` / `ButtonPress` / `LedSet`）を扱う

#### Cap LoRa-1262 技適状況メモ（2026-06-07 時点）

| 情報源 | 技適番号 | 最大出力（仕様） | 備考 |
|--------|----------|------------------|------|
| [M5Stack 公式 docs (ja)](https://docs.m5stack.com/ja/cap/Cap_LoRa-1262) | 記載なし | +22dBm | 製品スペック上の最大値 |
| [スイッチサイエンス販売ページ](https://www.switch-science.com/products/10940) | 記載なし | 22dBm | 国内代理店扱い |
| [個人ブログ (note.com / moridenki_note)](https://note.com/moridenki_note/n/n6de42aa276b1) | 番号なし | — | 「技適も通っている」との記述のみ（補助情報） |

**確実性**: 一次情報源には技適番号の明記なし。国内代理店で販売されている事実は技適取得の可能性を示唆するが証明ではない（送信機能を使わなければ技適不要で販売可能のため）。

**実機到着後の確認手順**:

1. モジュール本体・パッケージの技適マーク・番号表記を目視確認
2. 番号を [総務省 電波利用ホームページ 技術基準適合証明等を受けた機器の検索](https://www.tele.soumu.go.jp/giteki/SearchServlet) で照合
3. 結果を本ドキュメント §1.3 に追記（技適番号・有効周波数・出力上限）

### 1.4 Cap 構成早見表

| | Cap A: Cap LoRa 1262 | Cap B: Hacker Cap |
|---|---|---|
| 無線チップ | SX1262 (LoRa 専用変調) | CC1101 (汎用 Sub-GHz) |
| 対応周波数 | 868〜923 MHz | 315 / 433 / 868 / 920 MHz |
| 変調方式 | LoRa / FSK / GFSK / OOK | FSK / GFSK / MSK / ASK / OOK |
| 送信出力 | 最大 +22 dBm（日本では 13dBm 以下に制限要） | 最大 +10 dBm |
| 受信感度 | -147 dBm (LoRa 低速) | -116 dBm (FSK 1.2kbps) |
| 測位チップ | AT6668 GNSS (6衛星系) | なし |
| NFC チップ | なし | ST25R3916 (13.56 MHz) |
| NFC プロトコル | なし | ISO 14443A/B · FeliCa · ISO 15693 |
| NFC 動作モード | なし | R/W · カードエミュレーション · カスタム |
| アンテナ | SMA (LoRa) + セラミック (GNSS) | 内蔵アンテナ (要確認) |
| 主用途 | GPS ロガー / Meshtastic / BSAF | NFC 解析 / RF スニファー |

---

## 2. ソフトウェア環境

### 2.1 OS・Launcher

- **OS**: Raspberry Pi OS (Debian Linux ベース)
- **Launcher**: GUI ランチャー搭載 (1.9" LCD 上でグラフィカル起動)
- **AppBuilder フレームワーク**: LVGL (Light and Versatile Graphics Library)
- **AppStore**: `https://github.com/m5stack/CardputerZeroRepository` (公式 Debian apt リポジトリ / GitHub Pages 配信)
  - 配布形式: `.deb` パッケージ (GitHub Release アセットとして保管)
  - インストール: デバイス上から `apt install` で直接導入可能
  - 信頼性: GPG 署名 (`KEY.gpg`) による検証

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
claude  # デバイス上で直接実行 (軽量タスク向け)

# または PC 側から SSH リモートとして利用 (推奨: 512MB RAM 節約)
# PC 側で claude → SSH 経由でデプロイ
```

### 2.5 Tailscale VPN 経由 Claude 連携

CardputerZero の 512MB RAM ではフル Claude モデルのローカル実行は現実的でない。
自宅の Mac Mini を Tailscale でピアツーピア接続し、Claude Code をリモート実行する構成を標準とする。

#### アーキテクチャ

```
CardputerZero (フィールド)
  └── tailscale up        # 自宅 Mac Mini とピアツーピア接続
       └── [WireGuard トンネル / NAT 越え自動]
            └── Mac Mini @ 自宅 (Tailscale ノード)
                 ├── claude code  (フル Sonnet / Opus)
                 ├── Rust / czdev ビルド環境
                 └── scp → CardputerZero へデプロイ
```

#### セットアップ (CardputerZero 側)

```bash
# Tailscale インストール (Raspberry Pi OS / Debian)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# 接続確認
tailscale status          # Mac Mini の 100.x.x.x を確認
ping mac-mini             # Tailscale MagicDNS 名で疎通確認

# Claude Code セッション開始
ssh mac-mini              # Mac Mini へ SSH
claude                    # フルモデルで起動
```

#### ユースケース別の使い分け

| シーン | 手段 | Tailscale 要否 |
|--------|------|---------------|
| フィールドでコード生成・相談 | SSH → Mac Mini の claude | ✅ 必要 |
| GPS ロガー単独動作 | CardputerZero ローカルアプリ | ❌ 不要 |
| BSAF 受信 (停電時) | CardputerZero ローカル (オフグリッド) | ❌ 不要 |
| アプリビルド | Mac Mini でクロスコンパイル → scp 転送 | ✅ 必要 |
| LTE テザリング時 | Tailscale が NAT 越えを自動処理 | ✅ 透過的 |

#### ポートフォワーディング (claude.ai Web UI)

1.9" LCD (320×170) での Web ブラウザ操作は実用困難。
フィールドでの Claude 操作は **SSH + CLI が基本**。
HDMI 外部モニター接続時のみ Chromium Web UI が現実的。

### 2.6 日本語入力環境

#### 結論: 動作は可能だが制約あり

CardputerZero はフル Linux (Raspberry Pi OS) なので、
`fcitx5-mozc` を導入すれば日本語かな漢字変換は**技術的に動作する**。
ただし 46 キーの特殊レイアウトと 1.9" の極小画面に起因する
実用上の制約が複数存在する。

#### インストール手順

```bash
# パッケージ導入
sudo apt update
sudo apt install -y fcitx5-mozc \
  fonts-noto-cjk \
  fonts-noto-cjk-extra

# ロケール設定
sudo raspi-config
# → Localisation Options → Locale → ja_JP.UTF-8
# → Localisation Options → Keyboard → Generic 104-key (後述のカスタムマップで上書き)

# 入力メソッド設定
im-config -n fcitx5

# 再起動
sudo reboot
```

#### IME 切替キーの問題と対処

CardputerZero の 46 キーには **半角/全角キーが存在しない**。
デフォルトの切替キーは `Ctrl+Space` だが、
これは claude / vim 等と競合する場合がある。

```bash
# fcitx5 の切替キーをカスタマイズ
# ~/.config/fcitx5/config を編集
[Hotkey]
TriggerKeys=Super+Space   # Win/Cmd 相当キー + Space に変更
                           # CardputerZero の Fn キーとの組み合わせで要検証
```

#### 46 キーレイアウトとキーマップ

CardputerZero のキーボードは独自 USB HID デバイスとして認識される見込み。
キーマップが正しく設定されないと、`@` や `[` などの記号が
期待通りに入力できない可能性がある。

```bash
# キーマップ確認
xev   # キー入力イベントを確認
# → KeySym が期待値と異なる場合、カスタム xkb ルールを作成

# 暫定対処: US 配列として設定
setxkbmap us
# その後 fcitx5-mozc で日本語入力レイヤーを追加
```

#### 実用シナリオ別の評価

| シナリオ | 実用性 | 備考 |
|----------|--------|------|
| **HDMI 外部モニター + USB キーボード接続** | ◎ 快適 | 1080p 表示でIME候補も見やすい |
| **1.9" 本体 LCD + 46 キー入力** | △ 厳しい | 変換候補ウィンドウが極小、画面占有率大 |
| **SSH 先 (Mac Mini) で日本語入力** | ◎ 快適 | Mac 側の IME を使うため問題なし |
| **CLI のみ (vim / nano)** | ○ 可能 | fcitx5 + Ctrl+Space で切替 |
| **LVGL アプリ内日本語入力** | ✗ 要実装 | fcitx5 は X11/Wayland 向け、LVGL は独自対応が必要 |

#### LVGL アプリへの日本語入力統合 (要開発)

Launcher (LVGL) アプリ内での日本語入力は fcitx5 が使えないため、
アプリ側で IME 相当を実装する必要がある。

```
実装方針案:
  A) 簡易ローマ字→かな変換テーブルをアプリ内に組み込む (軽量)
  B) Unix ドメインソケット経由で fcitx5 プロセスと通信 (高品質)
  C) 入力が必要な場面は SSH → Mac Mini 側に委譲 (最も現実的)
```

GPS ロガー / BSAF クライアント等、**日本語入力が不要なアプリを優先開発**し、
日本語入力が必要な用途（メッセージ送信など）は
Mac Mini への Tailscale SSH セッションを使うことを推奨。

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
| Sky Plot 描画 | LVGL 円グラフィック + 仰角/方位角 → 極座標変換 |
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
- [ ] **天球図（Sky Plot）表示**: 円形ビュー（170×170）+ 衛星リスト分割
- [ ] 衛星カラーコード（GPS / QZSS / GLO / GAL / BDS の 5 色）
- [ ] SNR をドットサイズで可視化
- [ ] Chain Encoder（`shared/input_encoder/` 経由・App 10 と共通）で衛星リスト送り・プロット連動ハイライト
- [ ] HDMI 接続時は PRN ラベル付きフルスクリーン Sky Plot に切替

#### Sky Plot（天球図）表示仕様

GPS 衛星の天球上の見え方を視覚化するビュー。1.9" LCD では分割ビューを基本仕様、
HDMI 外部出力時はフルスクリーン詳細プロットへ自動切替する。

##### 基本仕様: 分割ビュー（LCD 320×170）

```
┌────────────────┬──────────────────┐
│      N         │ G07 ███████ 32   │
│  ●         ●   │ G15 ████    28   │
│ ●  ○○●        │ R12 ██████  29   │
│●   ●  ●    ●   │ E11 ██      18   │
│●  ●  ●     ●   │ Q01 █       12   │ ← Q=QZSS みちびき
│ ●  ○○●        │ ──────────────── │
│  ●         ●   │ Total: 12 / Fix: │
│      S         │ 3D / HDOP: 1.4   │
└────────────────┴──────────────────┘
   170×170          150×170
```

- **左 170×170**: 円形プロット（衛星はカラードットのみ、ラベルなし）
  - 中心 = 天頂（仰角 90°）/ 外周 = 水平線（仰角 0°）
  - 北 = 上、東 = 右
  - SNR をドットサイズで表現（強信号 = 大 / 弱信号 = 小）
- **右 150×170**: PRN / SNR バー / 仰角リスト（Chain Encoder ノブで選択スクロール）
- 選択行の衛星はプロット上で**白縁取り表示**して紐付け

##### 衛星系カラー割り当て

| 系統 | PRN プレフィックス | 色 | NMEA Talker ID |
|------|-------------------|-----|---------------|
| GPS | G | 緑 | $GPGSV |
| QZSS (みちびき) | Q | 赤 | $QZGSV |
| GLONASS | R | 青 | $GLGSV |
| Galileo | E | 黄 | $GAGSV |
| BeiDou | B | 紫 | $BDGSV / $GBGSV |

##### フォールバック: HDMI フルスクリーン Sky Plot

HDMI 外部モニター接続検出時は自動切替。1080p で全衛星 PRN ラベル付きの
詳細プロットを描画する。LCD 側は「ロック中衛星数」「HDOP」だけ大きく
表示する**運用判断モード**となり、フィールドでは LCD、解析時は HDMI、と使い分け。

##### 極座標変換ロジック

```python
import math
from dataclasses import dataclass

@dataclass
class Satellite:
    prn: str       # "G07", "Q01" 等
    elev: float    # 仰角 0-90°
    azim: float    # 方位角 0-360° (北=0, 東=90)
    snr: int       # 0-99 dBHz
    talker: str    # "GP" / "QZ" / "GL" / "GA" / "GB"

def to_lcd_xy(sat: Satellite, cx: int = 85, cy: int = 85,
              radius: int = 80) -> tuple[int, int]:
    """仰角・方位角を LCD のピクセル座標に変換 (左 170x170 ビュー基準)"""
    # 仰角 90° → 中心 / 0° → 外周
    r = radius * (1.0 - sat.elev / 90.0)
    # 方位角: 北=上=-Y方向、時計回り
    theta = math.radians(sat.azim - 90)  # 北を 12 時方向に
    x = cx + r * math.cos(theta)
    y = cy + r * math.sin(theta)
    return int(x), int(y)

def snr_to_dot_size(snr: int) -> int:
    """SNR を 3-8px のドット直径にマッピング"""
    if snr < 15:  return 3
    if snr < 25:  return 4
    if snr < 35:  return 6
    return 8
```

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

#### 自宅 LoRa ゲートウェイ構成

App02 を実用化するには、インターネット ↔ LoRa の橋渡しをする**自宅側ゲートウェイ**が必要。
推奨ハードウェアは **M5Stack C6L Meshtastic Unit**（§1.3 関連デバイス表参照）。

##### 構成A: C6L 単独ゲートウェイ（推奨）

```
[bsaf-jma-bot (Fly.io)]
       ↓ MQTT publish
[MQTT Broker (HiveMQ / Mosquitto)]
       ↓ MQTT subscribe (Wi-Fi 経由)
[C6L (自宅・USB充電器給電)]
       ↓ LoRa 920MHz 送信 (≤ +13dBm)
[CardputerZero (外出先)]
```

- PC 起動不要・24 時間稼働・消費電力数 W
- C6L の Meshtastic ファームウェア標準機能で MQTT ⇔ LoRa ブリッジが完結

##### 構成B: デスクトップ PC + C6L（カスタム制御）

```
[bsaf-jma-bot] → [デスクトップ PC (custom bridge)] → USB Serial → [C6L] → LoRa → [CardputerZero]
```

- BSAF パケットのフィルタリング・整形を PC 側で柔軟に実施可能
- PC ダウン時にゲートウェイ停止する点に注意

#### 想定到達距離（日本国内・SX1262 / 13dBm / SF12-BW125kHz）

| 環境 | 実用到達距離 |
|------|--------------|
| 都市部（札幌中心部）| 500m〜2km |
| 郊外住宅地 | 2〜5km |
| 田園・農地 | 5〜10km |
| 見通し条件（山岳・海上）| 10〜30km |

メッシュ拡張により 3〜5 ホップで実効カバレッジ拡大可能。Rindo サイクリング想定スコープ
（道央圏 札幌〜近郊）であれば自宅ゲートウェイ 1 + 中継 1〜2 ノードで実用範囲を確保できる。

#### 周波数・電波法注意事項

```
日本国内での使用可能帯域:
  920.6 MHz ～ 928.0 MHz (ARIB STD-T108 特定小電力無線)
  最大出力: 20mW (= 13dBm) ※特定小電力の上限
※ SX1262 モジュールの技適番号を事前確認すること
※ アマチュア無線局免許では使用不可 (特小扱い)
```

⚠️ **Cap LoRa-1262 の出力に関する注意**:

- モジュール仕様上の最大出力は **+22dBm（約158mW）**（M5Stack 公式 / スイッチサイエンス記載値）
- これは中国・欧州向けの仕様値であり、**そのまま日本で送信すれば違法**
- 一般に海外仕様モジュールでも、国内向け技適は「+13dBm 以下に絞った状態」で取得されるケースが多い
- 実装側で SX1262 のレジスタ設定により出力を **+13dBm 以下に制限**すること（推測ですが、ファームウェアレベルでの強制設定を推奨）
- 詳細な技適状況・出力上限は §1.3「Cap LoRa-1262 技適状況メモ」を参照

---

### App 03: NFC セキュリティツール群 (`nfc-toolkit`)

**優先度**: ★★★★☆  
**必要ハードウェア**: Cap B (Hacker Cap) — ST25R3916 NFC チップ

#### 概要
Hacker Cap に内蔵の ST25R3916 (13.56 MHz NFC) を使い、カードの読み取り・書き込み・エミュレーションを行う実践的セキュリティ学習ツール。教育・研究・ペネトレーションテスト学習を目的とする。Cap スロット経由で SPI 接続される点に注意（Grove 接続の Unit NFC とは別構成）。

#### ハードウェア接続（公式回路図 V0.3 より）

```
Hacker Cap — ST25R3916 (NFC)
  接続バス: SPI (共有バス)
  ピンアサイン:
    NFC_IRQ: G4
    NFC_CS:  G6
    SCLK/MOSI/MISO は CC1101 と共有
```

#### サポートプロトコル

| プロトコル | 用途 |
|------------|------|
| ISO 14443A | Mifare Classic, NTAG2xx, Mifare DESFire |
| ISO 14443B | 一部住基カード・運転免許証 |
| FeliCa | Suica / PASMO / nanaco (読み取り学習) |
| ISO 15693 | HF-RFID (物流タグ・図書館カード等) |

#### 機能一覧

- [ ] カード UID 読み取り・表示 (LCD)
- [ ] NDEF メッセージ読み取り / 書き込み
- [ ] カードエミュレーションモード (アクセスバッジ学習)
- [ ] UID スプーフィング (教育目的・自己所有カードのみ)
- [ ] パケットキャプチャ・カスタムプロトコルダンプ
- [ ] Mifare Classic セクター解析 (MFCUK / Mfoc 学習)
- [ ] FeliCa サービスコード探索 (自己所有カードのみ)
- [ ] ログ記録 (JSON 形式 → microSD)

#### ライブラリ

```python
# Python: nfcpy (ISO 14443A/B, FeliCa, ISO 15693)
# ST25R3916 の nfcpy 対応状況は実機確認後に検証
pip install nfcpy

# 代替: libst25r3916 公式 C ライブラリ + Python ctypes バインディング
# ST25R3916 Linux ドライバ (STMicroelectronics 公式)
# https://github.com/STMicroelectronics/st25r3916

# Rust: libnfc-sys クレート (nfc-nci バックエンド)
cargo add libnfc-sys
```

#### ⚠️ 法的注意事項

```
・他者所有のカードへの無断アクセスは不正アクセス禁止法に抵触する可能性あり
・Suica 等交通系カードへの書き込みは電子計算機損壊等業務妨害罪に該当する可能性あり
・本ツールは自己所有カードの学習・研究目的にのみ使用すること
・ペネトレーションテストは書面による事前合意がある場合のみ実施
・FeliCa の仕様は Sony が非公開部分を含む — 逆解析は利用規約に注意
```

---

### App 04: Sub-GHz スニファー (`subghz-sniffer`)

**優先度**: ★★★☆☆  
**必要ハードウェア**: Cap B (Hacker Cap) — CC1101 Sub-GHz チップ

#### 概要
Hacker Cap に内蔵の CC1101 を使い、Sub-GHz 帯の無線信号を受信・解析する。Flipper Zero の Sub-GHz 機能に相当するが、フル Linux 上で動作するため Python で高度な解析が可能。

#### CC1101 チップ詳細スペック

| 項目 | 仕様 |
|------|------|
| 対応周波数 | 315 / 433 / 868 / 920 MHz (マルチバンド) |
| 変調方式 | 2-FSK / 4-FSK / GFSK / MSK / ASK / OOK |
| 受信感度 | -116 dBm (FSK 1.2kbps) |
| 送信出力 | 最大 +10 dBm |
| インターフェース | SPI (4線式) |
| データレート | 0.6 〜 600 kbps |

#### ハードウェア接続（公式回路図 V0.3 より）

```python
# CC1101 SPI 接続 (Hacker Cap 経由)
CC1101_CS    = "G5"    # SPI Chip Select
CC1101_SCLK  = "G40"
CC1101_MOSI  = "G14"
CC1101_MISO  = "G39"
CC1101_RF_SW0 = "G13"  # RF スイッチ制御
CC1101_GDO0  = "G15"   # 割り込み出力
```

#### 対応周波数と用途 (日本国内)

| バンド | 主な用途 | 変調 | 備考 |
|--------|----------|------|------|
| 315 MHz | 旧式リモコン類 | OOK/ASK | 受信のみ推奨 |
| 433 MHz | 欧州 IoT センサー・温湿度計 | OOK/FSK | 受信のみ |
| 868 MHz | 欧州 LoRa / 特小 | FSK | 参考観測 |
| 920 MHz | 日本特小・スマートメーター | FSK | 受信のみ |

#### 機能一覧

- [ ] 信号受信・RSSI グラフ表示 (LCD / HDMI)
- [ ] OOK / ASK / FSK / GFSK デコード
- [ ] 信号ダンプ・保存 (`.sub` 形式 / Flipper Zero 互換)
- [ ] 周波数スキャン (受信レベルヒートマップ)
- [ ] 温湿度センサー (433MHz) プロトコル自動解析
- [ ] rtl_433 互換デコーダー統合
- [ ] スペクトラムアナライザーモード (HDMI 出力時)
- [ ] リプレイ送信 (自己所有デバイスへの教育目的のみ)

#### ライブラリ

```bash
# Python: pyCC1101 / smbus2 (SPI 経由)
pip install pyCC1101 smbus2

# rtl_433 互換デコーダー (多数のセンサープロトコル対応)
sudo apt install rtl-433
# CC1101 バックエンドで動作させるには要パッチ (コミュニティ実装あり)

# Rust: cc1101 crate
cargo add cc1101
```

#### ⚠️ 法的注意事項

```
・電波の受信は原則合法 (ただし通信の秘密侵害に注意)
・送信は技術基準適合証明 (技適) 取得済み機器でのみ可能
  CC1101 単体は技適未取得のため「送信」は行わないこと
・他者の通信内容の傍受・漏洩は電波法・通信傍受法に抵触する可能性あり
・スマートメーター信号の受信は合法だが内容の利用には注意
・リプレイ送信は自己所有システムへの教育目的のみとする
```

---

### App 05: BSAF 防災受信クライアント (`bsaf-client`)

**優先度**: ★★★★☆

#### 概要
BSAF v1 アラートパケット（気象警報・地震情報）を受信し、画面表示する。
**Wi-Fi 経由（主系統）と Meshtastic LoRa 経由（副系統）の二系統受信**に対応する。

#### 受信経路設計

BSAF の本来の配信チャネルは Bluesky（AT Protocol / HTTPS）であり、LoRa から直接
インターネットには接続できない。そのため受信経路は以下の二系統で構成する。

##### 主系統: Wi-Fi 経由（MQTT 購読）

```
[bsaf-jma-bot (Fly.io)] → MQTT publish → [MQTT Broker] → CardputerZero (Wi-Fi で購読)
```

- 通常時の主経路。低遅延・高信頼
- 前提: bsaf-jma-bot 側に MQTT publish 機能の追加が必要（§9 関連 TODO 参照）

##### 副系統: Meshtastic LoRa 経由（オフライン耐性）

```
[bsaf-jma-bot] → MQTT → [自宅 C6L ゲートウェイ] → LoRa → CardputerZero
```

- Wi-Fi 未接続エリア（サイクリング中・郊外）でも受信可能
- 自宅 C6L が稼働している限り、メッシュ経由で外出先まで届く
- App02 (`lora-mesh-node`) と共通の LoRa ドライバを利用
- ⚠️ 大規模停電で自宅ゲートウェイ・MQTT ブローカー共にダウンする場合は受信不可
  （完全オフグリッド受信には別途専用送信局が必要で、個人開発の範囲を超える）

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

- [ ] BSAF v1 パケット受信・パース（MQTT / LoRa 共通フォーマット）
- [ ] Wi-Fi 経由 MQTT 購読（主系統）
- [ ] Meshtastic LoRa 経由受信（副系統、App02 と共通ドライバ）
- [ ] 二系統重複受信時の de-duplication（同一 BSAF パケットの重複表示防止）
- [ ] 地震情報表示 (震度・震源地・時刻)
- [ ] 津波警報表示 (bsaf-jma-bot 対応後)
- [ ] 気象警報表示
- [ ] アラート音・バイブレーション (スピーカー経由)
- [ ] 受信ログ保存
- [ ] 接続状態インジケータ（Wi-Fi / LoRa / 両系統 / どちらも切断）

#### 関連リポジトリ・依存

- `bsaf-protocol` (仕様): `osprey74/bsaf-protocol`
- `bsaf-jma-bot` (供給側): MQTT publish 機能の追加が必要（§9 関連 TODO）
- App02 (`lora-mesh-node`): 共通 LoRa / Meshtastic ドライバを `shared/` に切り出し

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

### App 08: NFC × GPS チェックポイント (`nfc-checkpoint`)

**優先度**: ★★★☆☆  
**必要ハードウェア**: Cap A (GPS記録) + Cap B (NFC読取) を場面ごとに交換

#### 概要
サイクリング・ハイキング中に各スポットへ設置した NFC タグをタッチ→ GPS 座標と組み合わせてチェックポイントとして記録する。Michi-Navi の道の駅スタンプラリーとの連携も視野に入れる。

```
動作フロー:
  NFC タグ読取 (Cap B) → UID / NDEF 取得
  → GPS 座標記録 (Cap A / 既取得座標) と紐付け
  → GeoJSON / GPX にチェックポイントとして書き込み
  → Rindo / Michi-Navi へエクスポート
```

#### 機能一覧

- [ ] NFC タグ UID スキャン
- [ ] チェックポイント名・メモの NDEF 読み取り
- [ ] GPS 座標と紐付けて記録 (GeoJSON)
- [ ] チェックポイント一覧表示 (LCD)
- [ ] Rindo / Michi-Navi 向け GPX エクスポート
- [ ] Cap 交換ガイド UI (「Cap A に交換してください」等の案内)

---

### App 09: NFC × LoRa オフグリッド認証 PoC (`nfc-lora-auth`)

**優先度**: ★★☆☆☆ (研究・学習用途)  
**必要ハードウェア**: Cap A (LoRa) + Cap B (NFC) を場面ごとに交換

#### 概要
NFC でバッジ認証 → LoRa で管理ノードへ結果を中継する、インターネット不要の入退場管理プロトタイプ。既存インフラのない野外イベント・災害時等での利用を想定した PoC。

```
認証フロー:
  参加者 NFC バッジ読取 (Cap B)
  → UID ハッシュを LoRa パケットへ変換 (Cap A)
  → Meshtastic ノードが中継
  → 管理端末 (別の CardputerZero) で受信・ログ
```

#### ⚠️ 注意事項

```
・本 App は研究・PoC 目的のみ
・実運用での個人認証システムとしての利用には
  個人情報保護法・不正アクセス禁止法への適合が必要
・専門家への法的確認を推奨
```

---

### App 10: SDR 広帯域受信 (`sdr-receiver`)

**優先度**: ★★★★☆  
**必要ハードウェア**: RTL-SDR V4 ドングル (USB-A ポートへ接続、M5Stack 純正品不要)

#### 概要

Cap LoRa-1262 (868-923 MHz) と Cap CC1101 (315/433/868/915 MHz) は特定バンドの
狭帯域トランシーバーであり、アマチュア無線受信機のような広帯域受信には対応しない。
CardputerZero の USB-A ポートに **RTL-SDR V4 ドングル** を接続することで、
500 kHz〜1.75 GHz の全帯域をカバーするソフトウェア無線受信環境を構築できる。
Raspberry Pi OS は librtlsdr を標準サポートしており、追加ドライバ不要で動作する。

#### 推奨ハードウェア

| 機器 | 型番 / 型式 | 周波数範囲 | 価格目安 |
|------|------------|-----------|---------|
| **RTL-SDR Blog V4** (推奨) | RTL2832U + R828D + 1PPM TCXO | 500 kHz〜1.75 GHz | $30〜40 |
| Nooelec NESDR Smart v5 | RTL2832U + R820T2 + TCXO | 25 MHz〜1.75 GHz | $25〜35 |
| HackRF One (送受信が必要な場合) | HackRF | 1 MHz〜6 GHz | $300〜 |

> RTL-SDR V4 の HF 受信 (500 kHz 〜) は R828D チューナーと 1PPM TCXO により
> 同価格帯で最高の性能を発揮する。アンテナキット同梱版を推奨。

#### 接続構成

```
CardputerZero
  └── USB-A ポート
       └── RTL-SDR V4 ドングル (SMA-F コネクタ)
            ├── RP-SMA → SMA 変換アダプタ (Cap のアンテナ共用可)
            ├── 付属ディスコーンアンテナ (広帯域受信)
            └── 帯域別専用アンテナ (ADS-B: 1090 MHz、気象衛星: 137 MHz 等)
```

#### 受信可能帯域と用途

| 帯域 | 周波数 | 内容 | ソフトウェア |
|------|--------|------|------------|
| 中波 AM | 535〜1705 kHz | AM ラジオ (要アップコンバーター) | GQRX / SDR++ |
| 短波 HF | 3〜30 MHz | 国際放送・アマチュア無線 (要アップコンバーター) | GQRX |
| FM ラジオ | 76〜108 MHz | FM ステレオ受信 | rtl_fm / GQRX |
| 航空 VHF | 118〜137 MHz | 管制交信・ATIS (航空情報放送) | GQRX / dump1090 |
| 気象衛星 | 137〜138 MHz | NOAA APT 画像受信 | WXtoImg / noaa-apt |
| 船舶 AIS | 161〜162 MHz | 近海船舶追跡 | rtl_ais |
| 特小・業務 | 400〜470 MHz | 簡易無線・業務無線 (傍受のみ) | GQRX |
| 920 MHz IoT | 920 MHz 帯 | スマートメーター・特小 | rtl_433 |
| ADS-B 航空機 | 1090 MHz | 航空機位置追跡 | dump1090 / readsb |

#### ⚠️ V4 USB-C 版の重要注意事項

> RTL-SDR Blog V4 (USB-C 版) は **`apt install rtl-sdr` の標準ドライバでは動作しない**。
> R828D チューナー対応の RTL-SDR Blog 専用ドライバが必須。
> 標準ドライバを入れた状態で接続しても「信号が受信できない」となるため、
> 必ず以下の手順でセットアップすること。

#### ステップ 0: 事前準備（CardputerZero を USB-C ケーブルで接続する前に実施）

```bash
# 既存の標準 rtl-sdr パッケージが入っている場合は先に削除
sudo apt purge -y rtl-sdr
sudo apt autoremove -y

# DVB ドライバのブラックリスト登録（必須）
# これをしないとカーネルが先に掴んでしまい RTL-SDR が認識されない
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
echo 'blacklist rtl2832'          | sudo tee -a /etc/modprobe.d/blacklist-rtlsdr.conf
echo 'blacklist rtl2830'          | sudo tee -a /etc/modprobe.d/blacklist-rtlsdr.conf
sudo update-initramfs -u

# ビルド依存パッケージのインストール
sudo apt install -y git cmake build-essential libusb-1.0-0-dev pkg-config
```

#### ステップ 1: RTL-SDR Blog 専用ドライバのビルド・インストール

```bash
# RTL-SDR Blog 公式リポジトリ（V4 R828D 対応版）をクローン
git clone https://github.com/rtlsdrblog/rtl-sdr-blog.git
cd rtl-sdr-blog

# ビルド
mkdir build && cd build
cmake .. -DINSTALL_UDEV_RULES=ON
make -j$(nproc)
sudo make install
sudo ldconfig

# udev ルール反映（USB 認識権限の設定）
sudo cp ../rtl-sdr.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

#### ステップ 2: 再起動・接続確認

```bash
# 再起動（ブラックリストとドライバを確実に反映）
sudo reboot

# 再起動後、V4 USB-C を USB-C ケーブルで CardputerZero に接続してから確認
rtl_test -t
# 正常時の出力例:
#   Found 1 device(s):
#     0:  Realtek, RTL2838UHIDIR, SN: 00000001
#   Using device 0: Generic RTL2832U OEM
#   Found Rafael Micro R828D tuner   ← R828D と表示されれば成功

# デバイス情報詳細確認
rtl_eeprom
```

#### ステップ 3: アプリケーションのインストール

```bash
# GQRX (GUI スペクトラムアナライザー) — HDMI 外部出力推奨
sudo apt install -y gqrx-sdr

# 起動コマンド (SSH X11 転送 or HDMI 直接)
gqrx

# SDR++ (軽量代替、低リソース消費)
# GitHub Releases から ARM64 バイナリを取得
wget https://github.com/AlexandreRouma/SDRPlusPlus/releases/latest/download/sdrpp_debian_bookworm_arm64.deb
sudo dpkg -i sdrpp_debian_bookworm_arm64.deb

# ADS-B 航空機追跡 (新千歳・丘珠の発着確認)
sudo apt install -y dump1090-fa
sudo systemctl enable dump1090-fa
sudo systemctl start dump1090-fa
# → http://cardputerzero.local:8080 でブラウザ地図表示

# 気象衛星 NOAA APT 画像受信
pip install noaa-apt --break-system-packages
# 受信周波数:
#   137.500 MHz → NOAA-15
#   137.620 MHz → NOAA-18
#   137.912 MHz → NOAA-19
# 衛星通過予測: https://www.n2yo.com/?s=25338 (NOAA-15)

# 船舶 AIS
sudo apt install -y rtl-ais
# 起動: rtl_ais -n (標準出力にデコード結果)

# IoT センサー自動デコード (Cap CC1101 との役割補完)
sudo apt install -y rtl-433
# 起動: rtl_433 -f 433.92M -A (433MHz 帯の自動デコード)

# FM ラジオ (CLI 音声再生)
# ※ CardputerZero にスピーカー / イヤフォンジャック要確認
rtl_fm -f 76.1M -M wbfm -s 200000 | aplay -r 48000 -f S16_LE
```

#### ステップ 4: V4 動作確認チェックリスト

```
□ rtl_test -t で "Found Rafael Micro R828D tuner" が表示される
□ rtl_test -t で "No samples were lost" が表示される (サンプルロスなし)
□ GQRX 起動後、FM 放送帯 (76-108 MHz) でスペクトラムが表示される
□ dump1090-fa 起動後、ブラウザで航空機が表示される
□ USB バスパワーが安定している (V4 は約 320mA 消費)
   → 不安定な場合は USB-C 充電しながら使用
```

#### トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `No RTL-SDR devices found` | DVB ドライバが掴んでいる | ステップ 0 のブラックリスト設定を確認・再起動 |
| `R820T` と表示される | 標準ドライバが使われている | `apt purge rtl-sdr` 後に専用ドライバを再インストール |
| 信号が全く受信できない | R828D 未対応ドライバ | rtlsdrblog リポジトリのドライバを使っているか確認 |
| サンプルロスが多い | USB 帯域不足・電力不足 | USB ハブを外す・充電しながら使用 |
| GQRX が起動しない | X11/Wayland 未設定 | SSH の `-X` オプション使用、または HDMI 直接接続 |

#### LVGL Launcher アプリとしての統合

1.9" LCD (320×170) でのリアルタイム受信は表示解像度の制約上、
既存ツール経由のテキスト情報表示と自作統合 UI 経由のスペアナ表示を
モード切替で使い分ける。

```
受信モード選択画面 (LCD):
  [1] ADS-B 航空機追跡          ← dump1090 連携
  [2] FM ラジオ (音声)          ← rtl_fm 連携
  [3] 気象衛星スケジュール表示  ← noaa-apt 連携
  [4] AIS 船舶追跡              ← rtl_ais 連携
  [5] IoT センサーデコード      ← rtl_433 連携
  [6] 統合モニターモード        ← 自作 UI（次節）
  → 選択後は LCD 簡易表示 or HDMI 出力で起動
```

#### 自作統合モニターモード（`sdr-monitor` mode）

スペクトラムアナライザー・周波数スイムレーン・自動信号分類・最強信号の大型表示を
1つの画面に統合した汎用電波受信モード。HDMI 接続時にフル機能を発揮し、
1.9" LCD では簡易モード（大型周波数表示 + 検出リスト）で動作する。

```
画面構成（HDMI フルスクリーン）:
  ┌─────────────────────────────────┐
  │ [最強信号] 137.912 MHz  気象衛星 │  ← 42px 大型表示
  │ RSSI: -58 dBm  ● 受信中         │
  ├──────────────┬──────────────────┤
  │ スペアナ波形  │ 自動検出リスト   │
  │ (2.4MHz幅)   │ (RSSI 強順)      │
  ├──────────────┴──────────────────┤
  │ スイムレーン (25 MHz ─ 1.1 GHz) │
  └─────────────────────────────────┘
```

##### 技術スタック

| レイヤー | 採用技術 |
|----------|---------|
| SDR バックエンド | `pyrtlsdr` (RTL-SDR Python バインディング) |
| FFT 処理 | `numpy.fft` |
| 自動分類 DB | 周波数→用途マッピング JSON (自作) |
| RSSI 検出 | FFT ピーク検出アルゴリズム |
| LCD UI (1.9") | LVGL (czdev) — 簡易モード |
| HDMI UI | PyQt6 / GTK4 — フルスクリーン |

##### 周波数分類データベース (抜粋)

```json
[
  {"range": [76.0, 108.0], "label": "FM ラジオ",     "badge": "fm",  "color": "#1D9E75"},
  {"range": [108.0, 137.0],"label": "航空 VHF",      "badge": "air", "color": "#378ADD"},
  {"range": [137.0, 138.0],"label": "気象衛星",      "badge": "wx",  "color": "#7F77DD"},
  {"range": [161.0, 162.5],"label": "船舶 AIS",      "badge": "ais", "color": "#EF9F27"},
  {"range": [400.0, 470.0],"label": "業務/特小",     "badge": "sig", "color": "#D85A30"},
  {"range": [915.0, 928.0],"label": "920MHz IoT",    "badge": "iot", "color": "#639922"},
  {"range": [1089.5,1090.5],"label":"ADS-B",         "badge": "ads", "color": "#E24B4A"}
]
```

##### コアロジック (Python)

```python
import numpy as np
from rtlsdr import RtlSdr
import json

FREQ_DB = json.load(open("freq_db.json"))

def classify(freq_mhz: float) -> dict:
    for entry in FREQ_DB:
        lo, hi = entry["range"]
        if lo <= freq_mhz <= hi:
            return entry
    return {"label": "不明", "badge": "unknown", "color": "#888"}

def scan_peaks(sdr: RtlSdr, center_mhz: float, bw_mhz: float = 2.4) -> list[dict]:
    sdr.center_freq = center_mhz * 1e6
    sdr.sample_rate = bw_mhz * 1e6
    sdr.gain = "auto"

    samples = sdr.read_samples(256 * 1024)
    fft = np.abs(np.fft.fftshift(np.fft.fft(samples)))
    fft_db = 20 * np.log10(fft + 1e-12)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(len(samples), 1 / sdr.sample_rate)
    ) / 1e6 + center_mhz

    # ピーク検出 (簡易: ノイズフロア + 15dB 以上)
    noise_floor = np.percentile(fft_db, 30)
    threshold = noise_floor + 15
    peaks = []
    for i in range(1, len(fft_db) - 1):
        if fft_db[i] > threshold and fft_db[i] >= fft_db[i-1] and fft_db[i] >= fft_db[i+1]:
            freq = round(freqs[i], 3)
            rssi = round(fft_db[i], 1)
            peaks.append({
                "freq_mhz": freq,
                "rssi_dbm": rssi,
                **classify(freq)
            })
    return sorted(peaks, key=lambda x: -x["rssi_dbm"])
```

##### モニターモード機能一覧

- [ ] FFT スペクトラムアナライザーリアルタイム表示
- [ ] 25 MHz〜1.1 GHz スイムレーン (帯域ガイド)
- [ ] 自動ピーク検出・周波数用途分類
- [ ] 検出信号の RSSI 強順リスト表示
- [ ] 最強信号の大型周波数表示 (HDMI: 42px / LCD: 24px)
- [ ] 受信信号ログ保存 (JSON → microSD)

#### 物理 UI 拡張（Chain Encoder × 2 デイジーチェーン）

CardputerZero の 46 キーキーボードだけでは SDR の周波数微調整が困難。
Grove ポートに **M5Stack Chain Encoder × 2** をデイジーチェーン接続し、
Flipper Zero ライクな物理ノブ操作を実現する。

> 実装は **`shared/input_encoder/` 共通入力ドライバ**経由で行う（App01 Sky Plot
> や App11 ホストリスト送りと同じ抽象 API を使う）。
> 抽象 API 仕様は §9.4 共通モジュール設計 参照。

##### 推奨ハードウェア構成

```
CardputerZero
  └── Grove ポート (HY2.0-4P / UART モード)
       └── Chain Encoder #1 (粗調整)
            └── Chain Encoder #2 (微調整)  ← デイジーチェーン
```

| ノブ | 役割 | 押下時の動作 |
|------|------|--------------|
| ノブA (#1) | 周波数 **粗調整** （1 MHz 刻み / バンド送り） | プリセット確定・モード戻る |
| ノブB (#2) | 周波数 **微調整** （10 kHz 刻み）または ゲイン | センター周波数リセット |

> ℹ️ Chain Encoder は AB 相**増分エンコーダ**のため**物理的には無限回転**する
> （回転角の上限なし）。ノブ位置は STM32G031 が累積パルスとして保持し、
> ホスト側ソフトウェアでオーバーフロー処理する。
> 必要に応じて「最大周波数で停止」「ラップアラウンドして反対端へ」等の
> 挙動はソフトウェアでカスタマイズする。

##### Python 読み取りサンプル

```python
import serial, struct

# Grove UART デイジーチェーン (CardputerZero 側 /dev/ttyAMA0 想定)
ser = serial.Serial("/dev/ttyAMA0", baudrate=115200, timeout=0.1)

def read_encoders():
    """デイジーチェーン上の全 Chain Encoder の状態を取得"""
    ser.write(b"\xAA\x55\x01")          # 状態取得コマンド (仮)
    raw = ser.read(8)                    # ノブ A/B の状態を 4byte ずつ受信
    if len(raw) < 8:
        return None
    knobA_delta, knobA_btn, knobB_delta, knobB_btn = struct.unpack("<hBhB", raw)
    return {"A": {"delta": knobA_delta, "btn": bool(knobA_btn)},
            "B": {"delta": knobB_delta, "btn": bool(knobB_btn)}}

# 周波数チューニングループ
center_mhz = 137.5
while True:
    s = read_encoders()
    if s is None: continue
    center_mhz += s["A"]["delta"] * 1.0       # ノブA: 1 MHz 刻み
    center_mhz += s["B"]["delta"] * 0.01      # ノブB: 10 kHz 刻み
    center_mhz = max(25.0, min(1750.0, center_mhz))  # V4 受信帯域内に clamp
    if s["A"]["btn"]:
        confirm_preset()
```

> ⚠️ 上記コマンド仕様（0xAA55... 8byte レスポンス）は **仮**。
> 実機到着後に Chain Encoder の公式 Arduino ライブラリを参照し、
> Linux ホストからアクセスする UART プロトコルを確定する必要あり（§9.1 TODO 参照）。

##### 統合モニターモードでのキー割り当て

| 入力 | アクション |
|------|----------|
| ノブA 回転 | 中心周波数 粗調整 (1 MHz / 1 step) |
| ノブB 回転 | 中心周波数 微調整 (10 kHz / 1 step) |
| ノブA 押下 | バンドプリセット 1 周（FM → 航空 → AIS → ADS-B → IoT → 戻る） |
| ノブB 押下 | ゲイン Auto / Manual トグル |
| 両ノブ同時押下 | モニターモード終了 |
| 46 キー | コマンド入力・録音開始/停止 |

#### Cap との役割分担

| シナリオ | RTL-SDR | Cap CC1101 | Cap LoRa-1262 |
|----------|---------|-----------|--------------|
| 広帯域スキャン・傍受 | ✅ 主役 | ✗ | ✗ |
| IoT 433MHz 受信 | ✅ 可能 | ✅ 双方向 | ✗ |
| LoRa パケット送受信 | ✗ | ✗ | ✅ 主役 |
| GPS 測位 | ✗ | ✗ | ✅ 主役 |
| NFC カード操作 | ✗ | ✅ 主役 | ✗ |
| 信号リプレイ (送信) | ✗ | ✅ (教育目的) | ✗ |

#### ⚠️ 法的注意事項

```
・電波の受信は原則合法 (電波法に受信規制なし)
・受信した通信内容の第三者への漏洩は電波法・通信傍受法に抵触する可能性あり
・暗号化されていない業務無線・航空無線の傍受は合法だが内容の公開は不可
・RTL-SDR は受信専用のため送信による電波法違反のリスクなし
・HackRF 等の送受信機を使う場合は技適取得済み機器であることを確認すること
・アマチュア無線の送信には第三・四級以上のアマチュア無線技士免許が必要
```

---

### App 11: LAN 調査ツール (`lan-scanner`)

**優先度**: ★★★★☆  
**必要ハードウェア**: 本体内蔵 Wi-Fi / 有線 LAN (Ethernet) — 追加モジュール不要

#### 概要

業務で日常的に使用するネットワーク調査ツールを CardputerZero に集約する。
Wi-Fi と有線 LAN の両インターフェースを持つ CardputerZero は、
現場への持ち込みや素早い接続切替が可能なポケットサイズのネット診断機として機能する。
`nmap` を核とし、IP アドレス・MAC アドレス・OS・開放ポート・稼働サービスを
1.9" LCD に一覧表示、結果を JSON/CSV で microSD へ保存する。

```
典型的な業務ユースケース:
  現場ネットワークへ有線 LAN 接続
  → ホスト発見スキャン (arp-scan / nmap -sn)
  → 対象ホストの OS・ポート・サービス特定 (nmap -O -sV)
  → 結果を LCD 一覧表示 & microSD に保存
  → 帰社後 PC で詳細レポートを確認
```

#### ネットワークインターフェース構成

| I/F | デバイス名 (仮) | 用途 |
|-----|----------------|------|
| 有線 LAN (Ethernet 100M) | `eth0` | 調査対象ネットワークへの有線接続 |
| Wi-Fi 2.4GHz | `wlan0` | 調査対象 AP への無線接続 / 管理接続 |
| Tailscale VPN | `tailscale0` | 自宅 Mac Mini へのリモートアクセス |

#### 機能一覧

**ホスト発見**
- [ ] ARP スキャン (`arp-scan`) による高速ホスト一覧取得
- [ ] ICMP Ping スイープ (`nmap -sn`) によるサブネット全体スキャン
- [ ] ホスト名 (mDNS / NetBIOS / DNS) 解決・表示
- [ ] MAC アドレスベースのベンダー名解決 (OUI データベース)

**詳細調査**
- [ ] OS フィンガープリント (`nmap -O`)
- [ ] 開放ポートスキャン (`nmap -sS` / `-sT`)
- [ ] サービス・バージョン検出 (`nmap -sV`)
- [ ] よく使うポートのクイックスキャンプリセット
  - Web: 80/443/8080/8443
  - 管理: 22/23/3389/5900
  - DB: 3306/5432/1433/6379
  - IoT: 1883/8883 (MQTT), 502 (Modbus)

**結果管理**
- [ ] LCD 一覧表示 (IP・MAC・ホスト名・OS・主要ポート)
- [ ] JSON / CSV 保存 (microSD → `/mnt/sdcard/lan_scans/`)
- [ ] スキャン履歴比較 (前回との差分ハイライト)
- [ ] Tailscale 経由で Mac Mini へ結果を自動転送

**UI (LCD / HDMI)**
- [ ] スキャン対象 CIDR 入力 (例: `192.168.1.0/24`)
- [ ] プリセット選択: [クイック] [標準] [詳細] [カスタム]
- [ ] リアルタイム進捗表示 (発見ホスト数・残り時間)
- [ ] ホスト詳細ドリルダウン画面

**物理入力 (Chain Encoder 連携)**
- [ ] Chain Encoder（`shared/input_encoder/` 経由）でホストリスト送り
  - ノブA 回転: ホストリスト送り (1 件 / 1 step)
  - ノブA 押下: 選択ホストの詳細ドリルダウン表示
  - ノブB 回転: 列スクロール（IP / MAC / ホスト名 / OS / 主要ポートの表示切替）
  - ノブB 押下: スキャンプリセット切替 (クイック → 標準 → 詳細 → カスタム → 戻る)
- [ ] LED フィードバック (`LedSet`) でスキャン進捗を可視化（緑=完了 / 黄=進行中 / 赤=失敗）

#### 技術スタック

```bash
# コアスキャンエンジン
sudo apt install -y nmap arp-scan netdiscover

# OUI ベンダーデータベース更新
sudo nmap --script-updatedb

# Python バインディング (LVGL アプリから呼び出し)
pip install python-nmap --break-system-packages

# mDNS / Bonjour 解決
sudo apt install -y avahi-utils
avahi-browse -a  # mDNS サービス一覧

# ネットワーク詳細情報
sudo apt install -y net-tools iproute2 tcpdump
```

#### 主要コマンドリファレンス

```bash
# ① 高速ホスト発見 (ARP、有線 LAN 向け)
sudo arp-scan --localnet --interface eth0

# ② Ping スイープ (Wi-Fi / 有線共通)
sudo nmap -sn 192.168.1.0/24 --oJ /mnt/sdcard/lan_scans/$(date +%Y%m%d_%H%M).json

# ③ OS + サービス + ポート (標準調査)
sudo nmap -O -sV -T4 192.168.1.1 \
  --oX /mnt/sdcard/lan_scans/detail_$(date +%Y%m%d_%H%M).xml

# ④ よく使うポートのクイックスキャン
sudo nmap -p 22,80,443,3389,8080 192.168.1.0/24 --open

# ⑤ IoT デバイス向け (MQTT/Modbus)
sudo nmap -p 1883,8883,502 192.168.1.0/24 --open -sV

# ⑥ 前回スキャンとの差分確認
ndiff /mnt/sdcard/lan_scans/prev.xml /mnt/sdcard/lan_scans/latest.xml
```

#### Python ラッパー (LVGL アプリから呼び出す想定)

```python
import nmap
import json
from pathlib import Path
from datetime import datetime

def quick_scan(cidr: str, iface: str = "eth0") -> list[dict]:
    """ARP + OS フィンガープリントによる標準スキャン"""
    nm = nmap.PortScanner()
    nm.scan(hosts=cidr, arguments=f"-sn -O --interface {iface}")

    results = []
    for host in nm.all_hosts():
        results.append({
            "ip":       host,
            "mac":      nm[host]["addresses"].get("mac", "N/A"),
            "vendor":   nm[host].get("vendor", {}).get(
                        nm[host]["addresses"].get("mac",""), "Unknown"),
            "hostname": nm[host].hostname(),
            "os":       nm[host].get("osmatch", [{}])[0].get("name", "Unknown"),
            "state":    nm[host].state(),
        })

    # microSD へ自動保存
    out = Path(f"/mnt/sdcard/lan_scans/{datetime.now():%Y%m%d_%H%M}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    return results
```

#### インターフェース切替ヘルパー

```bash
# 有線 LAN (eth0) を使ってスキャン
sudo ip route add 192.168.1.0/24 dev eth0
scan_target="192.168.1.0/24"

# Wi-Fi (wlan0) に切替してスキャン
sudo ip route add 10.0.0.0/24 dev wlan0
scan_target="10.0.0.0/24"
```

#### ⚠️ 法的・倫理的注意事項

```
・ネットワークスキャンは管理権限のあるネットワークのみ実施すること
・他者のネットワークへの無断スキャンは不正アクセス禁止法に抵触する
  (ポートスキャン自体は違法ではないが、
   不正アクセスの意図があると見なされる場合がある)
・業務利用では情報セキュリティポリシー・ISMS 規程に基づいた
  適切な手順と承認のもとで実施すること
・スキャン結果に含まれる IP・MAC・OS 情報は機密情報として扱うこと
・Polaris Solutions の ISMS 認証範囲内での利用は社内手順に従うこと
```

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
# 1. ビルド (.deb パッケージ生成)
czdev build

# 2. ローカル開発時: デバイスへ直接転送・インストール
scp dist/*.deb pi@cardputerzero.local:/tmp/
ssh pi@cardputerzero.local "sudo apt install /tmp/<app-name>.deb"

# 3. AppStore 公開: czdev upload で公式リポジトリへ投稿
czdev upload   # m5stack/CardputerZeroRepository へ提出 (CI 検証 → 公開)
# 公開後、エンドユーザは「apt install <app-id>」または Launcher AppStore から取得
```

---

## 5. リポジトリ構成

```
osprey74/cardputerzero-apps/
├── CLAUDE.md                   # Claude Code 設定
├── HANDOFF_cardputerzero.md    # 本ドキュメント
├── apps/
│   ├── gps-logger/             # App 01 [Cap A]
│   │   ├── app.yaml
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── gnss.rs         # NMEA パーサー
│   │   │   ├── gpx.rs          # GPX 出力
│   │   │   └── ui.rs           # LVGL 画面
│   │   └── tests/
│   ├── lora-mesh-node/         # App 02 [Cap A]
│   ├── nfc-toolkit/            # App 03 [Cap B]
│   ├── subghz-sniffer/         # App 04 [Cap B]
│   ├── bsaf-client/            # App 05 [Cap A + Wi-Fi]
│   ├── edge-ai/                # App 06 [本体]
│   ├── wifi-analyzer/          # App 07 [本体]
│   ├── nfc-checkpoint/         # App 08 [Cap A + Cap B 交互]
│   ├── nfc-lora-auth/          # App 09 [Cap A + Cap B 交互] PoC
│   ├── sdr-receiver/           # App 10 [RTL-SDR USB] (旧 App 12 統合済み)
│   └── lan-scanner/            # App 11 [本体 Wi-Fi / 有線 LAN]
├── shared/
│   ├── lora_sx1262/            # SX1262 共通ドライバ [Cap A]
│   ├── gnss_at6668/            # AT6668 共通ドライバ [Cap A]
│   ├── nfc_st25r3916/          # ST25R3916 共通ドライバ [Cap B]
│   ├── rf_cc1101/              # CC1101 共通ドライバ [Cap B]
│   ├── input_encoder/          # Chain Encoder 共通入力ドライバ [Grove UART]
│   └── ui_theme/               # 共通 UI テーマ (osprey74 カラー)
└── scripts/
    ├── setup_device.sh         # デバイス初期セットアップ
    ├── setup_rtlsdr.sh         # RTL-SDR 環境セットアップ (App 10)
    ├── swap_cap_a.sh           # Cap A 用デバイスパス切替ヘルパー
    ├── swap_cap_b.sh           # Cap B 用デバイスパス切替ヘルパー
    └── deploy_all.sh           # 全アプリ一括デプロイ
```

---

## 6. 開発環境セットアップ

### 6.1 PC 側 (開発機)

#### macOS

```bash
# 1. Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu   # クロスコンパイル

# 2. SDL2 (エミュレータ用)
brew install sdl2 sdl2_image sdl2_mixer

# 3. CardputerZero AppBuilder
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
export PATH="$PATH:$(pwd)/target/release"

# 4. エミュレータ起動テスト
czdev run examples/hello_cz
```

#### Linux (Debian / Ubuntu)

```bash
# 1. 依存パッケージ
sudo apt install -y build-essential cmake pkg-config \
  libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libfreetype-dev

# 2. Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu

# 3. AppBuilder (macOS と同じ手順)
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
```

#### Windows 11

AppBuilder は **MSYS2 MINGW64 シェル**経由で公式サポート対象
（AppBuilder リポジトリの `DESKTOP_DEV.md §4` Windows-specific notes 参照）。

```powershell
# 1. MSYS2 インストール (https://www.msys2.org/)
#    インストール後、MSYS2 MINGW64 シェルを起動して以下を実行

# 2. MSYS2 MINGW64 シェル上で:
pacman -Syu
pacman -S --needed base-devel mingw-w64-x86_64-toolchain \
  mingw-w64-x86_64-cmake mingw-w64-x86_64-pkg-config \
  mingw-w64-x86_64-SDL2 mingw-w64-x86_64-SDL2_image mingw-w64-x86_64-SDL2_mixer \
  mingw-w64-x86_64-freetype mingw-w64-x86_64-rust

rustup target add aarch64-unknown-linux-gnu

# 3. AppBuilder クローン・ビルド
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
```

> 補足: WSL2 (Ubuntu) を使えば Linux 手順がそのまま使えるが、SDL2 エミュレータの
> ウィンドウ表示には WSLg または X サーバが必要。MSYS2 ネイティブ実行のほうが
> エミュレータの表示は安定する。

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
- LORA 周波数: 920MHz 帯のみ (日本)・出力 13dBm 以下に制限
- NFC/Sub-GHz: 自己所有デバイスへの教育目的のみ
- LAN スキャン: 管理権限のあるネットワークのみ / ISMS 規程に従うこと

## 共有ドライバ
- SX1262: `shared/lora_sx1262/`
- AT6668: `shared/gnss_at6668/`
- ST25R3916: `shared/nfc_st25r3916/`
- CC1101: `shared/rf_cc1101/`
- Chain Encoder: `shared/input_encoder/`
```

---

## 7. 日本国内の法令・技術基準

| 項目 | 規制内容 | 対応 |
|------|----------|------|
| LoRa 送信 | 920MHz 帯特定小電力 (最大 20mW) | 技適番号確認必須・出力 13dBm 以下に制限 |
| Sub-GHz 送信 | 技適取得済み機器のみ | CC1101 は受信のみ推奨 |
| NFC 書き込み | 他者カードへの無断書き込み禁止 | 自己所有のみ |
| Wi-Fi 解析 | 他者ネットワークへの接続禁止 | 自己所有 AP のみ |
| 通信傍受 | 電波法・通信傍受法 | 受信のみ・内容漏洩禁止 |
| GPS | 受信は無制限 | 問題なし |
| RTL-SDR 受信 | 受信専用のため送信規制なし | 内容の第三者漏洩は不可 |
| アマチュア無線送信 | 三・四級以上のアマ無線技士免許 | 送信する場合は免許取得 |
| LAN スキャン | 他者ネットワークへの無断スキャン禁止 | 管理権限のあるネットワークのみ |

> ⚠️ **専門家確認推奨**: セキュリティツールの業務利用・社外利用については、弁護士または技術士への確認を推奨します。

---

## 8. 関連リンク・出典

| リソース | URL |
|----------|-----|
| Kickstarter | https://www.kickstarter.com/projects/m5stack/cardputerzero |
| M5Stack 公式ストア | https://shop.m5stack.com/pages/m5-cardputerzero |
| AppBuilder GitHub | https://github.com/m5stack/CardputerZero-AppBuilder |
| AppStore (公式 apt リポジトリ) | https://github.com/m5stack/CardputerZeroRepository |
| Cap LoRa 1262 公式ドキュメント (Cap A) | https://docs.m5stack.com/ja/cap/Cap_LoRa-1262 |
| Cap LoRa 1262 国内代理店 | https://www.switch-science.com/products/10940 |
| Cap CC1101 公式ドキュメント (Cap B) | https://docs.m5stack.com/en/cap/Cap_CC1101 |
| Cap CC1101 回路図 V0.3 | https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1250/SCH_Cap_CC1101_SCH_V0.3_20260528.pdf |
| M5Stack C6L Meshtastic Unit (家側ゲートウェイ) | https://www.switch-science.com/products/10809 |
| M5Stack Chain Encoder (Grove UART デイジーチェーン) | https://www.switch-science.com/collections/m5stack/products/10919 |
| RTL-SDR Blog V4 (推奨ドングル) | https://www.rtl-sdr.com/rtl-sdr-blog-v4-dongle-initial-release/ |
| dump1090-fa (ADS-B) | https://github.com/flightaware/dump1090 |
| GQRX SDR (スペクトラムアナライザー) | https://gqrx.dk |
| SDR++ (軽量 SDR フロントエンド) | https://github.com/AlexandreRouma/SDRPlusPlus |
| noaa-apt (気象衛星受信) | https://noaa-apt.mbernardi.com.ar |
| rtl-ais (船舶 AIS) | https://github.com/dgiardini/rtl-ais |
| Hacker Cap (Cap B) — M5Stack X 発表 | https://x.com/M5Stack/status/1947947317614846284 |
| ST25R3916 データシート | https://www.st.com/en/nfc/st25r3916.html |
| CC1101 データシート | https://www.ti.com/product/CC1101 |
| ST25R3916 Linux ドライバ | https://github.com/STMicroelectronics/st25r3916 |
| rtl_433 (Sub-GHz デコーダー) | https://github.com/merbanan/rtl_433 |
| nfcpy (Python NFC ライブラリ) | https://nfcpy.readthedocs.io |
| 総務省 技術基準適合証明検索 | https://www.tele.soumu.go.jp/giteki/SearchServlet |
| LinuxGizmos スペック詳細 | https://linuxgizmos.com/m5stack-previews-cardputerzero-handheld-raspberry-pi-cm0-system/ |
| Hackster.io レビュー | https://www.hackster.io/news/m5stack-unveils-the-cardputerzero-... |
| BSAF プロトコル | https://github.com/osprey74/bsaf-protocol |
| Rindo (りんどう) | HANDOFF_cycling-nav.md 参照 |

---

## 9. 既知の未確認事項・TODO

### 9.1 ハードウェア検証（実機到着後）

#### Cap A: Cap LoRa-1262

- [ ] Cap LoRa-1262 の日本向け技適番号確認（実機ラベル → 総務省データベース照合、§1.3 参照）
- [ ] Cap LoRa 1262 の SPI CE (Chip Enable) ピン番号
- [ ] AT6668 (ATGM336H-6N) と Linux gpsd の互換性テスト
- [ ] SX1262 レジスタ設定で +13dBm 以下に出力制限する手順の検証

#### Cap B: Hacker Cap

- [x] **[Cap B]** 公式ドキュメント確認済み → [docs.m5stack.com/en/cap/Cap_CC1101](https://docs.m5stack.com/en/cap/Cap_CC1101)
- [x] **[Cap B]** CC1101 SPI ピンアサイン確認済み (回路図 V0.3 より: CS=G5, RF_SW0=G13, G0=G15, SCLK=G40, MOSI=G14, MISO=G39)
- [x] **[Cap B]** ST25R3916 SPI 接続確認済み (NFC_IRQ=G4, NFC_CS=G6, 共有 SPI バス)
- [ ] **[Cap B]** Cap A / Cap B の Grove 常駐併用可否の実機検証
- [ ] **[Cap B]** CC1101 の技適状況確認 (送信可否の判断に必要)
- [ ] **[Cap B]** nfcpy の ST25R3916 対応確認 (未対応の場合は libst25r3916 C バインディングを検討)

#### その他

- [ ] CardputerZero の Grove ポートの物理ピンアサイン (公式ドキュメント待ち)
- [ ] M5Stack C6L Meshtastic Unit の日本向け技適番号確認（同上）
- [ ] **[App 10]** RTL-SDR V4 と CardputerZero USB-A ポートの給電能力確認 (USB バスパワー 500mA 要件)
- [ ] **[App 10]** RTL-SDR アンテナと Cap LoRa-1262 SMA アンテナの共用可否 (RP-SMA 変換アダプタ)

#### 入力デバイス拡張（Chain Encoder）

- [ ] **[Grove]** CardputerZero の Grove ポート（HY2.0-4P）が UART モードで Chain Encoder と通信可能か実機検証
  - 切替が DT overlay / GPIO ピン / ソフトウェアのいずれで行われるかを実機で確認
  - 他 Grove デバイス（I2C 系センサー等）との同居可否も合わせて検証
- [ ] **[App 10]** Chain Encoder のデイジーチェーン UART プロトコル仕様確認
  - 公式 Arduino ライブラリのソースを参照し、Linux Python からアクセス可能な実装を確定
  - HANDOFF §3 App10「Python 読み取りサンプル」のコマンド仕様（0xAA55... 8byte）は**仮**のため要更新
- [ ] **[App 10]** Chain Encoder × 2 連結時のアドレス割り当て・識別ロジックの検証
- [ ] **[共通]** `shared/input_encoder/` の抽象 API がアプリ側コードで実用に足るかの早期検証（App 01 / App 10 / App 11 のいずれかで PoC）

### 9.2 ソフトウェア・ツールチェーン検証

- [ ] czdev の ARM クロスコンパイル設定の検証（macOS / Linux / Windows MSYS2 の3環境）
- [ ] Launcher の `app.yaml` スキーマ正式仕様 (AppBuilder リポジトリ要確認)
- [ ] `czdev upload` による CardputerZeroRepository への投稿フロー検証
- [ ] `.deb` パッケージ生成とデバイス側 `apt install` の動作確認
- [x] **[App 10]** V4 USB-C 専用ドライバ手順確定 (rtlsdrblog リポジトリ + DVB ブラックリスト)
- [ ] **[App 10]** GQRX / SDR++ の RPi CM0 (BCM2837) でのパフォーマンス検証
- [ ] **[App 10]** dump1090-fa の ARM 向けビルド確認
- [ ] **[2.6]** fcitx5-mozc + 46 キーレイアウトでの IME 切替動作検証
- [ ] **[2.6]** LVGL アプリ内日本語入力の実装方針確定 (簡易ローマ字 / fcitx5 IPC / Mac 委譲のいずれか)

### 9.3 外部プロジェクト連携 TODO

- [ ] **bsaf-jma-bot に MQTT publish 機能を追加**（App05 副系統・App02 LoRa ブリッジの前提）
  - 既存の Bluesky ポスト処理に並列で MQTT publish を実装
  - 配信トピック設計（例: `bsaf/v1/{type}/{target}`）
  - 認証情報管理（Fly.io secrets）
- [ ] MQTT Broker 選定（HiveMQ Cloud Free / Mosquitto セルフホスト等）
- [ ] BSAF v1 パケットの LoRa 最適化エンコーディング検討（Meshtastic ペイロード上限 約237byte）
- [ ] Tailscale ノード命名規則の整理 (Mac Mini / CardputerZero / iPhone 各端末)
- [ ] Rindo / Michi-Navi との GPX エクスポートフォーマット整合性確認 (App01 / App08)

### 9.4 共通モジュール設計

- [ ] `shared/lora_sx1262/` ドライバの API 設計（App02 と App05 で共有）
- [ ] `shared/gnss_at6668/` ドライバの API 設計（App01 で使用）
- [ ] `shared/nfc_st25r3916/` ドライバの API 設計 (App03 / App08 / App09 で共有)
- [ ] `shared/rf_cc1101/` ドライバの API 設計 (App04 で使用)
- [ ] `shared/input_encoder/` 共通入力ドライバの API 設計
  - バックエンド: M5Stack Chain Encoder（Grove UART デイジーチェーン）一本化
  - 想定利用元: App01 (Sky Plot 衛星リスト送り) / App10 (周波数選択) / App11 (ホストリスト送り) 等
  - 抽象 API 要件:
    - イベント型: `RotateDelta(idx, ±N)` / `ButtonPress(idx)` / `ButtonRelease(idx)` / `LedSet(idx, rgb)`
    - 多ノブ識別: デイジーチェーン上の連番 (`idx = 0, 1, 2, ...`)
    - 非同期通知 (LVGL イベントループへのコールバック登録)
    - 将来別バックエンド（I2C 系エンコーダ等）を追加できる拡張余地を残す抽象化
- [ ] BSAF パケットの de-duplication ロジック設計（MQTT / LoRa 二系統受信時）
- [ ] Cap A / Cap B 交換時のデバイスパス再検出ヘルパー (`scripts/swap_cap_*.sh`)

---

## 10. 購入リスト・見積もり

実機到着後・実装開始までに揃えたい機材一覧（2026-06-07 時点の価格）。

### 必須（本体到着済み前提・最小構成）

| # | 品目 | 数量 | 単価 (税込) | 小計 | 用途 |
|---|------|------|-----------|------|------|
| 1 | CardputerZero 標準版 (KS 出資済み) | 1 | (出資済) | — | 本体 |
| 2 | Cap LoRa-1262 (Cap A) | 1 | ¥2,838 | ¥2,838 | App 01 / 02 / 05 |
| 3 | Cap Hacker (Cap B) | 1 | 価格未確定 | ¥?,??? | App 03 / 04 / 08 / 09 |
| 4 | M5Stack Chain Encoder | 2 | ¥1,122 | ¥2,244 | 物理 UI (App 01 / 10 / 11) |
| 5 | M5Stack C6L Meshtastic Unit | 1 | ¥4,290 | ¥4,290 | 自宅 LoRa ゲートウェイ (App 02 / 05) |
| 6 | RTL-SDR Blog V4 (アンテナキット同梱版) | 1 | $30–40 (≒¥4,500–6,000) | ¥6,000 | App 10 SDR 受信 |
| 7 | USB-C 充電器 + ケーブル (C6L 常時給電用) | 1 | ¥1,000 | ¥1,000 | C6L 常時稼働 |
| | **必須小計** | | | **約 ¥16,400 + Cap B 価格** | |

### 推奨（あると便利）

| # | 品目 | 数量 | 単価 (税込) | 小計 | 用途 |
|---|------|------|-----------|------|------|
| 8 | 5dBi 920MHz SMA 外付けアンテナ | 1 | ¥1,500–3,000 | ¥2,500 | LoRa 到達距離向上 |
| 9 | RP-SMA → SMA 変換アダプタ | 1 | ¥500 | ¥500 | RTL-SDR と LoRa アンテナの共用検証 |
| 10 | HDMI ミニケーブル + 外部モニター (既存可) | 1 | — | — | App 10 GQRX / App 12 Sky Plot 詳細表示 |
| 11 | microSDXC カード (64GB 以上、標準版付属 32GB の予備) | 1 | ¥1,500 | ¥1,500 | ログ保存余裕用 |
| 12 | USB ハブ (セルフパワー型) | 1 | ¥2,000 | ¥2,000 | RTL-SDR + 他周辺機器の電力安定化 |
| | **推奨小計** | | | **約 ¥6,500** | |

### 将来検討（実装フェーズに応じて）

| # | 品目 | 想定価格 | 用途 |
|---|------|---------|------|
| - | アマチュア無線技士免許 (3 級以上) | 受験料 ¥5,400 | App 10 / App 04 で送信運用したい場合 |
| - | HackRF One | 約 ¥50,000 | RTL-SDR では受信できない用途 (要送信時) |
| - | NFC 検証用ダミーカード (NTAG215 等) | ¥500 × 数枚 | App 03 / 08 の安全な試験 |
| - | Sub-GHz 温湿度センサー (433MHz) | ¥1,000 | App 04 rtl_433 デコード検証用 |

### 合計目安

- **最低限スタート**: 約 ¥16,400 + Cap B 価格
- **標準構成**: 約 ¥22,900 + Cap B 価格
- **アマチュア無線免許取得込み**: +¥5,400

### 購入順序の推奨

1. **Phase 0 (Kickstarter 到着前)**: なし — 仕様書整備に集中
2. **Phase 1 (CardputerZero 到着直後)**: Cap A、Chain Encoder × 2、C6L
3. **Phase 2 (App 10 着手前)**: RTL-SDR Blog V4
4. **Phase 3 (Cap B 発売後)**: Cap Hacker
5. **Phase 4 (運用拡張時)**: 推奨群

> ⚠️ 価格・在庫はスイッチサイエンス・M5Stack 公式ストア・RTL-SDR Blog 等の
> 2026-06-07 時点の情報。実購入時に最新価格を確認すること。

---

## 11. Phase ロードマップ

実機到着前後の作業フェーズ整理。各 Phase 完了基準・想定期間も併記。

| Phase | 想定期間 | 主要作業 | 完了基準 |
|-------|---------|---------|---------|
| **Phase 0** | KS 到着前 (現在) | 仕様書整備・依存ライブラリ予習・Mac Mini 環境構築・買い物リスト確定 | HANDOFF 完成・Tailscale 開通 |
| **Phase 1** | KS 到着〜2週間 | ハードウェア検証 (§9.1)・Grove ピンアサイン確定・技適番号確認・czdev エミュレータ動作 | §9.1 ハードウェアチェックリストの 80% 消化 |
| **Phase 2** | Phase 1 完了後〜1ヶ月 | App 01 (GPS ロガー) 実装 + 共通ドライバ `gnss_at6668` / `input_encoder` 確立 | App 01 が microSD に GPX 記録できる |
| **Phase 3** | Phase 2 完了後〜1ヶ月 | App 10 (SDR 受信) 実装 + `setup_rtlsdr.sh` 完成 + 統合モニター UI | RTL-SDR V4 で FM ラジオ受信 + GQRX 表示 |
| **Phase 4** | Phase 3 完了後〜2ヶ月 | App 02 (LoRa Meshtastic) + C6L ゲートウェイ連携 + bsaf-jma-bot MQTT publish 機能追加 (外部プロジェクト) | 自宅 C6L → 外出先 CardputerZero で Meshtastic メッセージ到達 |
| **Phase 5** | Phase 4 完了後〜2ヶ月 | App 05 (BSAF 二系統受信) 実装 | Bluesky 投稿 → MQTT → LoRa → CardputerZero LCD 表示 |
| **Phase 6** | Cap B 入手後 | App 03 / 04 (NFC / Sub-GHz) 実装 | nfcpy で自己所有 Suica の UID 読取 + rtl_433 で温湿度センサーデコード |
| **Phase 7** | 業務利用前 | App 11 (LAN Scanner) 実装 + ISMS 規程との整合性確認 | 自宅 LAN を nmap でスキャンし JSON 保存 |
| **Phase 8** | 任意 | App 06 / 07 / 08 / 09 実装 | 個別に完了 |
| **Phase 9** | 各 App 完成時 | `czdev upload` で CardputerZeroRepository に投稿 | 公式 AppStore で `apt install` 可能になる |

### Phase 0 の具体的アクション

- [ ] Mac Mini に Tailscale 導入・Magic DNS 確認
- [ ] Mac Mini に Rust ツールチェーン + aarch64 ターゲット導入
- [ ] CardputerZero-AppBuilder を Mac Mini でビルドし `czdev run examples/` で動作確認
- [ ] LVGL の基本 API を予習 (公式チュートリアル)
- [ ] pynmea2 / pyrtlsdr / nfcpy の API ドキュメント熟読
- [ ] Bluesky で CardputerZero 関連情報をフォロー
- [ ] 購入リスト Phase 1 の発注タイミング検討

---

*このドキュメントは Kickstarter 到着・実機検証後に更新予定*  
*最終更新: 2026-06-07 by 総司 (osprey74)*
