# CoreS3 Input Frontend (firmware)

M5Stack CoreS3 (ESP32-S3) 用ファームウェア。CardputerZero の**入力・計測フロントエンド**として、
センサ/エンコーダの値を読み取り、JSON 1 行/周期で USB CDC 経由で CardputerZero(USB Host / Linux) へ流す。

> 設計の一次資料: [`../../HANDOFF_cardputerzero.md`](../../HANDOFF_cardputerzero.md) **§1.6 / §1.6.1**

## 確定構成 (§1.6.1)

| CoreS3 ポート | 接続 | 通信 | GPIO |
| --- | --- | --- | --- |
| Port A (赤) | INA226-10A + MLX90614 (Hub Unit U006 で 1→3 分岐し同居) | I2C | SDA=G2 / SCL=G1 |
| Port C (青) | Chain Encoder ×2 (デイジーチェーン) | UART | RX=G18 / TX=G17 |
| Port B | App13 導通チェック 5V/GND | 電源のみ | — |
| USB-C | CardputerZero へ JSON 送信 | USB CDC | — |

INA226 (0x41) と MLX90614 (0x5A) はアドレス非衝突のため MUX 不要。CoreS3 は内蔵/モバイルバッテリ自己給電、USB はデータ専用。

> 🔬 **実機確定 (2026-06-24)**: Port A の I2C ピン順は **SDA=G2 / SCL=G1**（HANDOFF §1.6.1 当初表記の G1/G2 は誤りで訂正済み）。この順で INA226=0x41 / MLX90614=0x5A を検出し、MLX90614 は実温度の読取を確認。INA226 は通信成立（測定端子未接続時 v=0V）。

## 送信フォーマット

```json
{"bat":{"pct":85,"chg":1,"v":4.05},
 "ina":{"v":5.01,"i":0.123,"p":0.616},"ncir":{"t_obj":36.5,"t_amb":24.1},
 "mag":{"ok":1,"x":-1520.4,"y":623.8,"z":-9.0,"heading":157.7},
 "enc":[{"id":1,"cnt":12,"delta":1,"btn":0},{"id":2,"cnt":-3,"delta":0,"btn":1}]}
```

| キー | 内容 |
| --- | --- |
| `bat.pct` | CoreS3 バッテリー残量 % (AXP2101 / `-1`=不明) |
| `bat.chg` | 充電状態 `1`=充電 / `0`=放電 / `-1`=不明 |
| `bat.v` | バッテリー電圧 V |
| `ina.v/i/p` | INA226 電圧 V / 電流 A (符号付き双方向) / 電力 W |
| `ncir.t_obj/t_amb` | MLX90614 物体温度 / 周囲温度 ℃ |
| `mag.ok` | BMM150 地磁気取得可否 (`1`=取得成功)。CoreS3 の BMM150 は BMI270 補助 I2C 配下で `i2cdetect` に出ないが `M5.Imu.getMag()` で取得可 |
| `mag.x/y/z` | 地磁気 [µT]（App 16 星座盤の方位アライン用・要ハード/ソフトアイアン補正） |
| `mag.heading` | 水平面 方位角 [deg]（傾き補正なし・未キャリブレーションの目安値） |
| `enc[].cnt` | エンコーダ累積カウント (CoreS3 起動からの積算) |
| `enc[].delta` | 直近周期の増分 / `btn` ノブ押下 (`1`=押下) |

CardputerZero 側は `shared/cores3_bridge/`(Python/pyserial) で `/dev/ttyACM*` を開いてパースする。

## 液晶ダッシュボード (常時表示)

CoreS3 液晶 (rotation=0 / 縦 240×320) に全計測値を常時表示する。`M5Canvas`
(PSRAM オフスクリーン) へ描画し一括転送するためちらつきは無い。

```text
[▮85% CHG]          4.05V     ← バッテリー残量/充電状態/電圧
─────────────────────────
INA226  DC METER
  V 5.012 V                   ← INA226 を大きく表示 (測定試験を実機目視)
  I 123.4 mA                     (電流は mA/A・電力は mW/W を自動レンジ)
  P 0.617 W
NCIR  MLX90614
  obj 36.5C / amb 24.1C
ENCODER  x2
  E1 +12   ●                  ← 累積カウント + 押下インジケータ
  E2 -3    ○
```

> 💡 **INA226 測定試験**: 既知負荷を測定端子に直列接続し、画面の `V / I / P` を直読する。
> 無負荷では 0、負荷接続で電流・電力が表示される。USB CDC の JSON でも同値を確認可能。

### ページ構成 (左右スワイプで切替・下部ドット)

`METER → INFO → SYS → LEVEL → PLUMB → TIMER` の 6 ページ。

| ページ | 内容 |
| --- | --- |
| **METER** | バッテリ + INA226 V/I/P + NCIR + エンコーダ (上記ダッシュボード) |
| **INFO** | NTP 時計 (JST) + 室温 (NCIR amb) + 天気 (気象庁) |
| **SYS** | ネットワーク詳細 + システム (uptime/heap/psram/fw) |
| **LEVEL** | 内蔵 IMU (BMI270) の円形気泡水準器。タップでゼロ点トグル (相対測定・右上 `REL`) |
| **PLUMB** | 「下げ振り分銅」。支点 (上部水平線×中央垂直線の交点・y=60) から重力方向へ赤い糸＋分銅が垂れ、本体の左右傾きで振れる |
| **TIMER** | セミナー用カウントダウン／経過時間計。ドーナツ円グラフが 12 時から時計回りに減少し、中央に残り時間(大)+経過時間(小)を併記 |

#### TIMER ページ (セミナータイマー)

プリセット時間 (既定 90 分) を選んで開始すると、ドーナツ円グラフが減少していく。
残り >25% 緑 → 25% 橙 → 10% 赤、残り 10 秒以内は弧が点滅。0 到達後は `TIME UP` 点滅＋
超過時間を `+MM:SS` でカウントアップ（延長把握用）。プリセットは NVS に保存し次回復元。

| 状態 | 操作 |
| --- | --- |
| **SETUP** | **上下スワイプ**=プリセット選択 (5/15/30/45/60/90/100/120 分) / **タップ**=開始 |
| **RUNNING** | **タップ**=一時停止 / **上下スワイプ**=リセット |
| **PAUSED** | **タップ**=再開 / **上下スワイプ**=リセット |
| **DONE** | **タップ / 上下スワイプ**=SETUP へ戻る |

> ⚡ **省電力: TIMER 表示中は Wi-Fi/I2C を停止**。TIMER ページに入ると Wi-Fi(netTask) を
> `WIFI_OFF` に、Port A の I2C(`Wire.end()`) を止め、JSON 送信も停止する。他ページへ戻すと
> Wi-Fi(`WIFI_STA`) を再開し、I2C を `Wire.begin()`＋`ina226Init()` で再初期化する
> (シリアルに `{"log":"radio",...}`)。セミナー中は無線・センサを切って電池を節約できる。
> **左右スワイプ**でページを離れても計測は `millis()` 基準で継続し、戻れば正しい残り時間を表示する。
>
> 🕐 **TIMER 中はセンサ非送信**: TIMER ページ表示中は INA226/MLX/エンコーダを読まず JSON も
> 送らない。CardputerZero へ計測値を流したい場合は TIMER 以外のページに切り替えること。

> 🧭 **IMU 水準器/下げ振りの統合**: 単体アプリ [`../cores3-level`](../cores3-level) と同じ角度ロジックを
> 本フロントエンドにページとして統合し、CardputerZero と協働中も CoreS3 画面のスワイプで呼び出せる。
> 表示は rotation=0 (縦) のため、本体固定の IMU 軸を画面の水平/垂直へ入れ替えてマッピングしている
> (気泡は高い側=重力の逆、下げ振りは重力方向)。軸符号は実機確定済み。

## ツールチェーン (PlatformIO)

```bash
pip install platformio          # 初回のみ (Python 3.x)
pio run                         # ビルド
pio run -t upload               # CoreS3 へ書込み
pio device monitor              # シリアルモニタ (115200)
```

`platform = espressif32` / `board = m5stack-cores3` / `framework = arduino`。依存は `M5Unified` を固定。

## 実機検証 (HANDOFF §1.6.1 / §9)

### 確定済み (2026-06-24)

- [x] **Port A I2C ピン順 = SDA=G2 / SCL=G1**（設計書の G1/G2 は誤り・訂正済み）
- [x] **INA226 = 0x41**、Mfg ID=`0x5449`/Die ID=`0x2260`（TI INA226 同定）
- [x] **INA226 校正**（CAL=3200 / Current_LSB=0.32mA / Power_LSB=8mW）→ 電圧/電流/電力 読取（無負荷で 0）
- [x] **MLX90614 = 0x5A**、Hub Unit U006 同居で衝突なし、実温度の読取確認 (t_obj/t_amb)
- [x] **Chain Encoder ×2** = M5Chain ライブラリ連携（115200bps・device id 1 始まり・`getEncoderIncValue`/`getEncoderButtonStatus`）。**ライブ検証済み**: デイジーチェーン列挙 enc_num=2(CHAIN_OK)、上流 id=1／下流 id=2 の回転増分(delta)・押下(btn) を正しく取得。未接続時は CHAIN_TIMEOUT で `enc:[]` に degrade
- [x] PlatformIO ビルド → USB-C 書込み (COM5) → USB CDC で JSON 送信まで動作
- [x] **INA226 実負荷精度**: 1kΩ + 3.6V Li-ion を OUT 端子に直列接続し検証。V=4.289V / I≈4.29mA（理論 4.289V÷1kΩ）/ P≈16mW（理論 ~19mW を Power_LSB=8mW で量子化）と一致。CAL=3200 校正を実負荷で確定（※10A 用シャントを数 mA で使うため低電流域は量子化が粗い）

> ⚠️ **Hub Unit U006 は受動 Grove スプリッタ**（PaHUB のような I2C MUX ではない）。3 分岐は同一バス共有のため、アドレス非衝突の I2C デバイス同居専用。UART と I2C は混在不可。

### 残 TODO

- [ ] MLX90614 PEC 検証
- [ ] CoreS3 が CardputerZero(USB Host) に CDC(`/dev/ttyACM*`) として認識されること (本体到着後)
