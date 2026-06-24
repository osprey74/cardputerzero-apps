# CoreS3 Input Frontend (firmware)

M5Stack CoreS3 (ESP32-S3) 用ファームウェア。CardputerZero の**入力・計測フロントエンド**として、
センサ/エンコーダの値を読み取り、JSON 1 行/周期で USB CDC 経由で CardputerZero(USB Host / Linux) へ流す。

> 設計の一次資料: [`../../HANDOFF_cardputerzero.md`](../../HANDOFF_cardputerzero.md) **§1.6 / §1.6.1**

## 確定構成 (§1.6.1)

| CoreS3 ポート | 接続 | 通信 | GPIO |
|---|---|---|---|
| Port A (赤) | INA226-10A + MLX90614 (Hub Unit U006 で 1→3 分岐し同居) | I2C | SDA=G1 / SCL=G2 |
| Port C (青) | Chain Encoder ×2 (デイジーチェーン) | UART | RX=G18 / TX=G17 |
| Port B | App13 導通チェック 5V/GND | 電源のみ | — |
| USB-C | CardputerZero へ JSON 送信 | USB CDC | — |

INA226 (0x41) と MLX90614 (0x5A) はアドレス非衝突のため MUX 不要。CoreS3 は内蔵/モバイルバッテリ自己給電、USB はデータ専用。

> 🔬 **実機確定 (2026-06-24)**: Port A の I2C ピン順は **SDA=G2 / SCL=G1**（HANDOFF §1.6.1 当初表記の G1/G2 は誤りで訂正済み）。この順で INA226=0x41 / MLX90614=0x5A を検出し、MLX90614 は実温度の読取を確認。INA226 は通信成立（測定端子未接続時 v=0V）。

## 送信フォーマット

```json
{"ina":{"v":5.01},"ncir":{"t_obj":36.5,"t_amb":24.1},"enc":[]}
```

CardputerZero 側は `shared/cores3_bridge/`(Python/pyserial) で `/dev/ttyACM*` を開いてパースする。

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
- [x] **INA226 検出 = 0x41**（i2c_scan）。通信成立、測定端子未接続時 v=0V
- [x] **MLX90614 検出 = 0x5A**、Hub Unit U006 同居で衝突なし、実温度の読取確認 (t_obj/t_amb)
- [x] PlatformIO ビルド → USB-C 書込み (COM5) → USB CDC で JSON 送信まで動作

### 残 TODO

- [ ] INA226 Mfg ID=`0x5449`/Die ID=`0x2260` の読出し確認 (デバイス同定の最終確証)
- [ ] INA226 校正レジスタ設定 → 電流/電力の確定 (現状は電圧のみ)
- [ ] MLX90614 PEC 検証
- [ ] Chain Encoder デイジーチェーン UART プロトコル/baud の確定、delta/btn 抽出
- [ ] CoreS3 が CardputerZero(USB Host) に CDC(`/dev/ttyACM*`) として認識されること (本体到着後)
