// CardputerZero 入力フロントエンド (M5Stack CoreS3 / ESP32-S3)
// HANDOFF_cardputerzero.md §1.6.1 確定構成の雛形。
//
//   Port A (I2C, SDA=G1 / SCL=G2) : INA226-10A (0x41) + MLX90614 (0x5A)
//                                   ※Hub Unit U006 で 1→3 受動分岐し同居
//   Port C (UART, RX=G18 / TX=G17): Chain Encoder ×2 (デイジーチェーン)
//   USB CDC (Serial)              : 下記 JSON を 1 行/周期で CardputerZero へ送信
//
//   送信 JSON 例:
//   {"ina":{"v":5.01,"i":0.123,"p":0.616},"ncir":{"t_obj":36.5,"t_amb":24.1},
//    "enc":[{"id":0,"delta":1,"btn":0},{"id":1,"delta":0,"btn":1}]}
//
// ⚠️ 実機未確定 (HANDOFF §1.6.1 / §9): INA226 実アドレス・校正値、MLX90614 PEC、
//    Chain Encoder のデイジーチェーン UART プロトコル/baud、USB CDC の Host 認識。
//    本ファイルは「ビルドが通り、I2C スキャン + 生レジスタ読取 + JSON 送信の
//    骨格が動く」ことを目的とした雛形であり、各 TODO は実機検証後に確定する。

#include <M5Unified.h>
#include <Wire.h>
#include <M5Chain.h>   // Chain Encoder (Port C UART デイジーチェーン)

// ---- Port A (I2C) ----------------------------------------------------------
// ⚠️ 実機確定 (2026-06-24): Port A は SDA=G2 / SCL=G1。
//    §1.6.1 の表 (SDA=G1/SCL=G2) は誤りで、ESPHome 記述 (G2/G1) が正。
//    この順で INA226(0x41) と MLX90614(0x5A) を検出。
static constexpr int PORT_A_SDA = 2;   // G2
static constexpr int PORT_A_SCL = 1;   // G1

// ---- Port C (UART, Chain Encoder) ------------------------------------------
static constexpr int PORT_C_RX = 18;   // G18
static constexpr int PORT_C_TX = 17;   // G17
static constexpr uint32_t ENC_BAUD = 115200;  // TODO: 実機で確定

// ---- I2C アドレス (HANDOFF §1.6.1) -----------------------------------------
static constexpr uint8_t INA226_ADDR = 0x41;  // §2.x「0x41 固定」/ 0x40-0x4F 帯。要 i2cdetect
static constexpr uint8_t MLX_ADDR    = 0x5A;  // MLX90614 既定

// INA226 レジスタ
static constexpr uint8_t INA_REG_CONFIG = 0x00;
static constexpr uint8_t INA_REG_BUS_V  = 0x02;
static constexpr uint8_t INA_REG_POWER  = 0x03;
static constexpr uint8_t INA_REG_CURRENT= 0x04;
static constexpr uint8_t INA_REG_CAL    = 0x05;
static constexpr uint8_t INA_REG_MFG_ID = 0xFE;  // 期待値 0x5449 (TI)
static constexpr uint8_t INA_REG_DIE_ID = 0xFF;  // 期待値 0x2260

// INA226-10A 校正 (HANDOFF §3/§8: シャント 5mΩ・±10A・分解能 0.32mA)
//   Current_LSB = 0.32mA, CAL = 0.00512 / (Current_LSB × R_shunt)
//               = 0.00512 / (0.00032 × 0.005) = 3200
//   Power_LSB   = 25 × Current_LSB = 0.008 W/bit  (最大 ±10.49A)
static constexpr uint16_t INA226_CONFIG       = 0x4527;  // 連続(shunt+bus)/平均16/変換1.1ms
static constexpr uint16_t INA226_CAL          = 3200;
static constexpr float    INA226_CURRENT_LSB_A= 0.00032f;
static constexpr float    INA226_POWER_LSB_W  = 0.008f;

// MLX90614 RAM レジスタ
static constexpr uint8_t MLX_REG_T_AMB = 0x06;
static constexpr uint8_t MLX_REG_T_OBJ = 0x07;

// 表示の向き (M5GFX: 0/1/2/3 = 90°刻み・時計回り)。0 から 180°回転で 2。
static constexpr uint8_t DISPLAY_ROTATION = 2;

static uint32_t g_last_send_ms = 0;
static constexpr uint32_t SEND_INTERVAL_MS = 200;  // 5Hz

static uint32_t g_last_scan_ms = 0;
static constexpr uint32_t SCAN_INTERVAL_MS = 2000;  // 2s 毎に I2C バス再列挙 + Chain 列挙 (配線確認用)

static uint16_t g_enc_num = 0;  // Chain バス上の Encoder ノード数 (デイジーチェーン)
static Chain chain;             // M5Chain バスマスタ (Port C UART)

// 16bit ワード読み出し (MSB first / INA226 等)。成功時 true。
static bool readWord16(uint8_t addr, uint8_t reg, uint16_t &out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;  // repeated start
  if (Wire.requestFrom((int)addr, 2) != 2) return false;
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  out = (uint16_t(hi) << 8) | lo;
  return true;
}

// MLX90614 は SMBus (LSB first, PEC 付き)。ここでは PEC 未検証の簡易読み。
static bool readWordLE(uint8_t addr, uint8_t reg, uint16_t &out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, 3) != 3) return false;  // lo, hi, pec
  uint8_t lo = Wire.read();
  uint8_t hi = Wire.read();
  (void)Wire.read();  // PEC (TODO: 検証)
  out = (uint16_t(hi) << 8) | lo;
  return true;
}

// 16bit ワード書込み (MSB first / INA226 等)。成功時 true。
static bool writeWord16(uint8_t addr, uint8_t reg, uint16_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(uint8_t(val >> 8));
  Wire.write(uint8_t(val & 0xFF));
  return Wire.endTransmission() == 0;
}

// INA226 を初期化 (Config + Calibration 書込み)。Mfg/Die ID を確認ログ出力。
static void ina226Init() {
  uint16_t mfg = 0, die = 0;
  readWord16(INA226_ADDR, INA_REG_MFG_ID, mfg);
  readWord16(INA226_ADDR, INA_REG_DIE_ID, die);
  bool ok_cfg = writeWord16(INA226_ADDR, INA_REG_CONFIG, INA226_CONFIG);
  bool ok_cal = writeWord16(INA226_ADDR, INA_REG_CAL, INA226_CAL);
  Serial.printf("{\"log\":\"ina226_init\",\"mfg_id\":\"0x%04X\",\"die_id\":\"0x%04X\","
                "\"cfg_ok\":%d,\"cal_ok\":%d}\n",
                mfg, die, ok_cfg ? 1 : 0, ok_cal ? 1 : 0);
}

// 指定ピンで I2C を初期化しバスを列挙。検出数を返す。
// ⚠️ Port A の SDA/SCL 順は設計書内で矛盾（§1.6.1=G1/G2 vs ESPHome=G2/G1）。
//    両順を試して、どちらで応答するかを実機で確定する。
static int i2cScanOn(int sda, int scl) {
  Wire.end();
  delay(5);
  Wire.begin(sda, scl, 100000);
  Serial.printf("{\"log\":\"i2c_scan\",\"sda\":%d,\"scl\":%d,\"found\":[", sda, scl);
  int n = 0;
  for (uint8_t a = 0x08; a < 0x78; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      if (n) Serial.print(",");
      Serial.printf("\"0x%02X\"", a);
      n++;
    }
  }
  Serial.printf("],\"count\":%d}\n", n);
  return n;
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.setRotation(DISPLAY_ROTATION);  // 左 90° 回転 (既定1 → 0)
  M5.Display.setTextSize(2);
  M5.Display.println("CoreS3 frontend");

  Serial.begin(115200);   // USB CDC
  chain.begin(&Serial2, ENC_BAUD, PORT_C_RX, PORT_C_TX);  // Chain Encoder (Port C)

  delay(300);
  Wire.begin(PORT_A_SDA, PORT_A_SCL, 100000);  // 実機確定: SDA=G2 / SCL=G1
  ina226Init();  // Config + Calibration 書込み (電流/電力読取の前提)
}

void loop() {
  M5.update();

  const uint32_t now = millis();

  // 配線確認用: 2s 毎に I2C バスを再列挙 + INA226 ID を読取 (リセット不要でライブ観測)。
  if (now - g_last_scan_ms >= SCAN_INTERVAL_MS) {
    g_last_scan_ms = now;
    i2cScanOn(PORT_A_SDA, PORT_A_SCL);  // 実機確定: SDA=G2 / SCL=G1
    uint16_t mfg = 0, die = 0;
    readWord16(INA226_ADDR, INA_REG_MFG_ID, mfg);  // 期待 0x5449 (TI)
    readWord16(INA226_ADDR, INA_REG_DIE_ID, die);  // 期待 0x2260
    Serial.printf("{\"log\":\"ina226_id\",\"mfg_id\":\"0x%04X\",\"die_id\":\"0x%04X\"}\n", mfg, die);

    // Chain バス上の Encoder ノード数を列挙 (繋げばここに反映される)
    uint16_t n = 0;
    chain_status_t st = chain.getDeviceNum(&n);
    if (st == CHAIN_OK) g_enc_num = n;
    Serial.printf("{\"log\":\"chain_enum\",\"status\":%d,\"enc_num\":%u}\n", (int)st, g_enc_num);
  }

  if (now - g_last_send_ms < SEND_INTERVAL_MS) return;
  g_last_send_ms = now;

  // ---- INA226 (校正済み: 電圧/電流/電力) ----
  float v = NAN, i = NAN, p = NAN;
  uint16_t raw;
  if (readWord16(INA226_ADDR, INA_REG_BUS_V, raw)) {
    v = raw * 0.00125f;  // Bus Voltage LSB = 1.25mV
  }
  if (readWord16(INA226_ADDR, INA_REG_CURRENT, raw)) {
    i = int16_t(raw) * INA226_CURRENT_LSB_A;  // 符号付き (双方向)
  }
  if (readWord16(INA226_ADDR, INA_REG_POWER, raw)) {
    p = raw * INA226_POWER_LSB_W;  // Power は符号なし
  }

  // ---- MLX90614 ----
  float t_obj = NAN, t_amb = NAN;
  if (readWordLE(MLX_ADDR, MLX_REG_T_OBJ, raw)) t_obj = raw * 0.02f - 273.15f;
  if (readWordLE(MLX_ADDR, MLX_REG_T_AMB, raw)) t_amb = raw * 0.02f - 273.15f;

  // ---- Chain Encoder (Port C UART・デイジーチェーン) ----
  // M5Chain ライブラリで各ノードの増分(delta)と押下状態を読取り JSON 配列化。
  // device id は 1 始まり (id=1 が Master 直近のノード)。
  char encbuf[160];
  int off = snprintf(encbuf, sizeof(encbuf), "[");
  for (uint16_t id = 1; id <= g_enc_num && off < (int)sizeof(encbuf) - 40; id++) {
    int16_t inc = 0;
    uint8_t btn = 0;
    chain.getEncoderIncValue(id, &inc);     // 前回読取からの増分
    chain.getEncoderButtonStatus(id, &btn); // ノブ押下状態 (生値)
    off += snprintf(encbuf + off, sizeof(encbuf) - off,
                    "%s{\"id\":%u,\"delta\":%d,\"btn\":%u}", id > 1 ? "," : "", id, inc, btn);
  }
  snprintf(encbuf + off, sizeof(encbuf) - off, "]");

  // ---- JSON 1 行送信 ----
  char buf[320];
  snprintf(buf, sizeof(buf),
           "{\"ina\":{\"v\":%.3f,\"i\":%.4f,\"p\":%.4f},"
           "\"ncir\":{\"t_obj\":%.2f,\"t_amb\":%.2f},\"enc\":%s}",
           v, i, p, t_obj, t_amb, encbuf);
  Serial.println(buf);

  // ---- タッチ液晶 (簡易表示) ----
  M5.Display.fillRect(0, 40, M5.Display.width(), 90, TFT_BLACK);
  M5.Display.setCursor(0, 40);
  M5.Display.printf("V: %.3f V\n", v);
  M5.Display.printf("I: %.1f mA\n", i * 1000.0f);
  M5.Display.printf("T: %.2f C\n", t_obj);
}
