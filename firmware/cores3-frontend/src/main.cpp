// CardputerZero 入力フロントエンド (M5Stack CoreS3 / ESP32-S3)
// HANDOFF_cardputerzero.md §1.6.1 確定構成。
//
//   Port A (I2C, SDA=G2 / SCL=G1) : INA226-10A (0x41) + MLX90614 (0x5A)
//                                   ※Hub Unit U006 で 1→3 受動分岐し同居
//   Port C (UART, RX=G18 / TX=G17): Chain Encoder ×2 (デイジーチェーン)
//   USB CDC (Serial)              : 下記 JSON を 1 行/周期で CardputerZero へ送信
//
//   送信 JSON 例:
//   {"bat":{"pct":85,"chg":1,"v":4.05},
//    "ina":{"v":5.01,"i":0.123,"p":0.616},"ncir":{"t_obj":36.5,"t_amb":24.1},
//    "enc":[{"id":1,"cnt":12,"delta":1,"btn":0},{"id":2,"cnt":-3,"delta":0,"btn":1}]}
//
//   液晶 (常時表示ダッシュボード):
//     ・最上段  : バッテリー残量% + 充電状態 + バッテリ電圧 (M5.Power / AXP2101)
//     ・INA226  : V / I / P を大きく表示 (測定試験を実機目視で行うため)
//     ・NCIR    : t_obj / t_amb
//     ・ENC     : 各ノードの累積カウント + ボタン状態
//   ちらつき防止に M5Canvas (オフスクリーン・スプライト) へ描画し一括転送する。

#include <M5Unified.h>
#include <Wire.h>
#include <M5Chain.h>   // Chain Encoder (Port C UART デイジーチェーン)
#include <math.h>

// ---- Port A (I2C) ----------------------------------------------------------
// ⚠️ 実機確定 (2026-06-24): Port A は SDA=G2 / SCL=G1。
//    §1.6.1 の表 (SDA=G1/SCL=G2) は誤りで、ESPHome 記述 (G2/G1) が正。
//    この順で INA226(0x41) と MLX90614(0x5A) を検出。
static constexpr int PORT_A_SDA = 2;   // G2
static constexpr int PORT_A_SCL = 1;   // G1

// ---- Port C (UART, Chain Encoder) ------------------------------------------
static constexpr int PORT_C_RX = 18;   // G18
static constexpr int PORT_C_TX = 17;   // G17
static constexpr uint32_t ENC_BAUD = 115200;

// ---- I2C アドレス (HANDOFF §1.6.1) -----------------------------------------
static constexpr uint8_t INA226_ADDR = 0x41;
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
//   Current_LSB = 0.32mA, CAL = 0.00512 / (Current_LSB × R_shunt) = 3200
//   Power_LSB   = 25 × Current_LSB = 0.008 W/bit
static constexpr uint16_t INA226_CONFIG       = 0x4527;  // 連続(shunt+bus)/平均16/変換1.1ms
static constexpr uint16_t INA226_CAL          = 3200;
static constexpr float    INA226_CURRENT_LSB_A= 0.00032f;
static constexpr float    INA226_POWER_LSB_W  = 0.008f;

// MLX90614 RAM レジスタ
static constexpr uint8_t MLX_REG_T_AMB = 0x06;
static constexpr uint8_t MLX_REG_T_OBJ = 0x07;

// 表示の向き (M5GFX: 0/1/2/3 = 90°刻み)。既定1(横) から左90°で 0 (縦 240×320)。
static constexpr uint8_t DISPLAY_ROTATION = 0;

static uint32_t g_last_send_ms = 0;
static constexpr uint32_t SEND_INTERVAL_MS = 200;  // 5Hz

static uint32_t g_last_scan_ms = 0;
static constexpr uint32_t SCAN_INTERVAL_MS = 2000;  // 2s 毎に I2C/Chain 再列挙 (配線確認用)

static uint16_t g_enc_num = 0;  // Chain バス上の Encoder ノード数 (デイジーチェーン)
static Chain chain;             // M5Chain バスマスタ (Port C UART)

// エンコーダ累積カウント (getEncoderIncValue は前回読取からの増分のみ返すため自前で積算)。
// device id は 1 始まり。十分な余裕を持って 16 ノードまで対応。
static constexpr uint16_t ENC_MAX = 16;
static int32_t g_enc_count[ENC_MAX + 1] = {0};

// 直近の計測値 (描画と JSON で共用)。
struct Readings {
  float ina_v, ina_i, ina_p;   // V / A / W (未取得は NAN)
  float t_obj, t_amb;          // ℃ (未取得は NAN)
  int   bat_pct;               // 0-100 (-1 unknown)
  int   bat_chg;               // -1 unknown / 0 放電 / 1 充電
  float bat_v;                 // V
};
static Readings g_r;

// オフスクリーン描画用スプライト (ちらつき防止)。
static M5Canvas g_canvas(&M5.Display);

// ---- カラーテーマ (osprey74: ダーク基調 + シアン/グリーンのアクセント) -------
static constexpr uint16_t COL_BG     = 0x0000;  // 黒
static constexpr uint16_t COL_LABEL  = 0x8410;  // グレー (ラベル)
static constexpr uint16_t COL_VALUE  = 0xFFFF;  // 白 (値)
static constexpr uint16_t COL_ACCENT = 0x07FF;  // シアン (セクション見出し)
static constexpr uint16_t COL_OK     = 0x07E0;  // グリーン (充電/良好)
static constexpr uint16_t COL_WARN   = 0xFD20;  // オレンジ (低残量)
static constexpr uint16_t COL_DIM    = 0x4208;  // 罫線
static constexpr uint16_t COL_E1     = 0xF800;  // 赤 (Encoder 1)
static constexpr uint16_t COL_E2     = 0x349F;  // 青 (Encoder 2)

// ---------------------------------------------------------------------------
// I2C 低レベル
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// 描画ヘルパ
// ---------------------------------------------------------------------------

// バッテリーアイコン (端子付き) + 残量塗り。x,y は左上。w×h は本体サイズ。
static void drawBatteryIcon(int x, int y, int w, int h, int pct, bool charging) {
  uint16_t border = charging ? COL_OK : (pct >= 0 && pct < 20 ? COL_WARN : COL_VALUE);
  g_canvas.drawRect(x, y, w, h, border);
  g_canvas.fillRect(x + w, y + h / 3, 3, h / 3, border);  // +端子
  if (pct >= 0) {
    int fillw = (w - 4) * pct / 100;
    if (fillw < 0) fillw = 0;
    uint16_t fill = charging ? COL_OK : (pct < 20 ? COL_WARN : COL_ACCENT);
    g_canvas.fillRect(x + 2, y + 2, fillw, h - 4, fill);
  }
}

// 値を右寄せ無しの簡易行で描画: ラベル(グレー) + 値(色)。size 指定。
static void drawField(int x, int y, const char *label, const char *value,
                      uint16_t valColor, uint8_t labelSize, uint8_t valSize) {
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(labelSize);
  g_canvas.setCursor(x, y);
  g_canvas.print(label);
  g_canvas.setTextColor(valColor, COL_BG);
  g_canvas.setTextSize(valSize);
  g_canvas.print(value);
}

// セクション見出し (アクセント色 + 下線)。
static int drawSection(int x, int y, int w, const char *title) {
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setCursor(x, y);
  g_canvas.print(title);
  g_canvas.drawFastHLine(x, y + 11, w, COL_DIM);
  return y + 16;
}

// 電流を自動レンジ整形 ("%.1f mA" / "%.3f A")。NAN は "---"。
static void fmtCurrent(char *out, size_t n, float a) {
  if (isnan(a)) { snprintf(out, n, "---"); return; }
  if (fabsf(a) < 1.0f) snprintf(out, n, "%.1f mA", a * 1000.0f);
  else                 snprintf(out, n, "%.3f A", a);
}

// 電力を自動レンジ整形 ("%.0f mW" / "%.3f W")。NAN は "---"。
static void fmtPower(char *out, size_t n, float w) {
  if (isnan(w)) { snprintf(out, n, "---"); return; }
  if (w < 1.0f) snprintf(out, n, "%.0f mW", w * 1000.0f);
  else          snprintf(out, n, "%.3f W", w);
}

// 温度整形。NAN は "---"。
static void fmtTemp(char *out, size_t n, float c) {
  if (isnan(c)) snprintf(out, n, "---");
  else          snprintf(out, n, "%.1fC", c);
}

// ダッシュボード全体を描画 (スプライトへ → pushSprite で一括転送)。
static void drawDashboard() {
  const int W = g_canvas.width();
  char val[24];

  g_canvas.fillScreen(COL_BG);

  int x = 6;
  int y = 4;

  // ---- バッテリー (最上段) --------------------------------------------------
  drawBatteryIcon(x, y, 30, 16, g_r.bat_pct, g_r.bat_chg == 1);
  g_canvas.setTextSize(2);
  if (g_r.bat_pct >= 0) snprintf(val, sizeof(val), "%d%%", g_r.bat_pct);
  else                  snprintf(val, sizeof(val), "--%%");
  g_canvas.setTextColor(g_r.bat_pct >= 0 && g_r.bat_pct < 20 ? COL_WARN : COL_VALUE, COL_BG);
  g_canvas.setCursor(x + 40, y);
  g_canvas.print(val);
  // 充電状態
  g_canvas.setTextSize(1);
  if (g_r.bat_chg == 1) { g_canvas.setTextColor(COL_OK, COL_BG);  g_canvas.setCursor(x + 40, y + 18); g_canvas.print("CHG"); }
  else if (g_r.bat_chg == 0) { g_canvas.setTextColor(COL_LABEL, COL_BG); g_canvas.setCursor(x + 40, y + 18); g_canvas.print("BAT"); }
  // バッテリ電圧 (右側)
  if (!isnan(g_r.bat_v)) {
    snprintf(val, sizeof(val), "%.2fV", g_r.bat_v);
    g_canvas.setTextSize(2);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setCursor(W - 6 - (int)strlen(val) * 12, y);
    g_canvas.print(val);
  }
  g_canvas.drawFastHLine(0, y + 30, W, COL_DIM);
  y += 38;

  // ---- INA226 (測定試験のメイン: 大きく表示) --------------------------------
  y = drawSection(x, y, W - 12, "INA226  DC METER");
  // V (先頭に "V:" ラベル)
  if (isnan(g_r.ina_v)) snprintf(val, sizeof(val), "---");
  else                  snprintf(val, sizeof(val), "%.3f V", g_r.ina_v);
  g_canvas.setTextSize(3);
  g_canvas.setTextColor(COL_VALUE, COL_BG);
  g_canvas.setCursor(x + 4, y);
  g_canvas.print("V "); g_canvas.print(val);
  y += 30;
  // I (先頭に "I:" ラベル)
  fmtCurrent(val, sizeof(val), g_r.ina_i);
  g_canvas.setTextSize(3);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setCursor(x + 4, y);
  g_canvas.print("I "); g_canvas.print(val);
  y += 30;
  // P (先頭に "P:" ラベル)
  fmtPower(val, sizeof(val), g_r.ina_p);
  g_canvas.setTextSize(3);
  g_canvas.setTextColor(COL_OK, COL_BG);
  g_canvas.setCursor(x + 4, y);
  g_canvas.print("P "); g_canvas.print(val);
  y += 36;

  // ---- NCIR -----------------------------------------------------------------
  y = drawSection(x, y, W - 12, "NCIR  MLX90614");
  fmtTemp(val, sizeof(val), g_r.t_obj);
  drawField(x + 4, y, "obj ", val, COL_VALUE, 2, 2);
  y += 22;
  fmtTemp(val, sizeof(val), g_r.t_amb);
  drawField(x + 4, y, "amb ", val, COL_LABEL, 2, 2);
  y += 28;

  // ---- ENC ------------------------------------------------------------------
  char title[24];
  snprintf(title, sizeof(title), "ENCODER  x%u", g_enc_num);
  y = drawSection(x, y, W - 12, title);
  if (g_enc_num == 0) {
    g_canvas.setTextSize(1);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setCursor(x + 4, y);
    g_canvas.print("(no node)");
    y += 14;
  } else {
    for (uint16_t id = 1; id <= g_enc_num && id <= ENC_MAX && y < g_canvas.height() - 18; id++) {
      uint8_t btn = 0;
      chain.getEncoderButtonStatus(id, &btn);
      char line[24];
      snprintf(line, sizeof(line), "E%u %+ld", id, (long)g_enc_count[id]);
      // E1=赤 / E2=青 / それ以降は白
      uint16_t encColor = (id == 1) ? COL_E1 : (id == 2) ? COL_E2 : COL_VALUE;
      g_canvas.setTextSize(2);
      g_canvas.setTextColor(encColor, COL_BG);
      g_canvas.setCursor(x + 4, y);
      g_canvas.print(line);
      // ボタン状態インジケータ (押下=塗り円)
      int cy = y + 7;
      int cx = W - 18;
      if (btn) g_canvas.fillCircle(cx, cy, 6, COL_OK);
      else     g_canvas.drawCircle(cx, cy, 6, COL_LABEL);
      y += 22;
    }
  }

  g_canvas.pushSprite(0, 0);
}

// ---------------------------------------------------------------------------

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.setRotation(DISPLAY_ROTATION);  // 左 90° 回転 (既定1 → 0 / 縦 240×320)

  // オフスクリーン・スプライトを画面サイズで確保 (PSRAM)。
  g_canvas.setColorDepth(16);
  g_canvas.setPsram(true);
  g_canvas.createSprite(M5.Display.width(), M5.Display.height());
  g_canvas.fillScreen(COL_BG);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setTextSize(2);
  g_canvas.setCursor(6, 6);
  g_canvas.print("CoreS3 frontend");
  g_canvas.pushSprite(0, 0);

  Serial.begin(115200);   // USB CDC
  chain.begin(&Serial2, ENC_BAUD, PORT_C_RX, PORT_C_TX);  // Chain Encoder (Port C)

  // 初期値
  g_r = { NAN, NAN, NAN, NAN, NAN, -1, -1, NAN };

  delay(300);
  Wire.begin(PORT_A_SDA, PORT_A_SCL, 100000);  // 実機確定: SDA=G2 / SCL=G1
  ina226Init();  // Config + Calibration 書込み (電流/電力読取の前提)
}

void loop() {
  M5.update();

  const uint32_t now = millis();

  // 配線確認用: 2s 毎に I2C バスを再列挙 + INA226 ID を読取 + Chain ノード列挙。
  if (now - g_last_scan_ms >= SCAN_INTERVAL_MS) {
    g_last_scan_ms = now;
    i2cScanOn(PORT_A_SDA, PORT_A_SCL);
    uint16_t mfg = 0, die = 0;
    readWord16(INA226_ADDR, INA_REG_MFG_ID, mfg);  // 期待 0x5449 (TI)
    readWord16(INA226_ADDR, INA_REG_DIE_ID, die);  // 期待 0x2260
    Serial.printf("{\"log\":\"ina226_id\",\"mfg_id\":\"0x%04X\",\"die_id\":\"0x%04X\"}\n", mfg, die);

    uint16_t n = 0;
    chain_status_t st = chain.getDeviceNum(&n);
    if (st == CHAIN_OK) g_enc_num = (n <= ENC_MAX) ? n : ENC_MAX;
    Serial.printf("{\"log\":\"chain_enum\",\"status\":%d,\"enc_num\":%u}\n", (int)st, g_enc_num);
  }

  if (now - g_last_send_ms < SEND_INTERVAL_MS) return;
  g_last_send_ms = now;

  // ---- バッテリー (AXP2101 / M5.Power) ----
  g_r.bat_pct = M5.Power.getBatteryLevel();             // 0-100 (-1 unknown)
  g_r.bat_chg = (int)M5.Power.isCharging();             // -1 / 0 / 1
  {
    int mv = M5.Power.getBatteryVoltage();              // mV (0=unknown)
    g_r.bat_v = (mv > 0) ? mv / 1000.0f : NAN;
  }

  // ---- INA226 (校正済み: 電圧/電流/電力) ----
  g_r.ina_v = g_r.ina_i = g_r.ina_p = NAN;
  uint16_t raw;
  if (readWord16(INA226_ADDR, INA_REG_BUS_V, raw))   g_r.ina_v = raw * 0.00125f;             // 1.25mV/bit
  if (readWord16(INA226_ADDR, INA_REG_CURRENT, raw)) g_r.ina_i = int16_t(raw) * INA226_CURRENT_LSB_A;  // 符号付き
  if (readWord16(INA226_ADDR, INA_REG_POWER, raw))   g_r.ina_p = raw * INA226_POWER_LSB_W;   // 符号なし

  // ---- MLX90614 ----
  g_r.t_obj = g_r.t_amb = NAN;
  if (readWordLE(MLX_ADDR, MLX_REG_T_OBJ, raw)) g_r.t_obj = raw * 0.02f - 273.15f;
  if (readWordLE(MLX_ADDR, MLX_REG_T_AMB, raw)) g_r.t_amb = raw * 0.02f - 273.15f;

  // ---- Chain Encoder (Port C UART・デイジーチェーン) ----
  // delta を積算して累積カウント(g_enc_count)を更新しつつ JSON 配列化。
  // device id は 1 始まり (id=1 が Master 直近のノード)。
  char encbuf[200];
  int off = snprintf(encbuf, sizeof(encbuf), "[");
  for (uint16_t id = 1; id <= g_enc_num && id <= ENC_MAX && off < (int)sizeof(encbuf) - 56; id++) {
    int16_t inc = 0;
    uint8_t btn = 0;
    chain.getEncoderIncValue(id, &inc);     // 前回読取からの増分
    chain.getEncoderButtonStatus(id, &btn); // ノブ押下状態 (生値)
    g_enc_count[id] += inc;
    off += snprintf(encbuf + off, sizeof(encbuf) - off,
                    "%s{\"id\":%u,\"cnt\":%ld,\"delta\":%d,\"btn\":%u}",
                    id > 1 ? "," : "", id, (long)g_enc_count[id], inc, btn);
  }
  snprintf(encbuf + off, sizeof(encbuf) - off, "]");

  // ---- JSON 1 行送信 ----
  char buf[420];
  snprintf(buf, sizeof(buf),
           "{\"bat\":{\"pct\":%d,\"chg\":%d,\"v\":%.2f},"
           "\"ina\":{\"v\":%.3f,\"i\":%.4f,\"p\":%.4f},"
           "\"ncir\":{\"t_obj\":%.2f,\"t_amb\":%.2f},\"enc\":%s}",
           g_r.bat_pct, g_r.bat_chg, g_r.bat_v,
           g_r.ina_v, g_r.ina_i, g_r.ina_p, g_r.t_obj, g_r.t_amb, encbuf);
  Serial.println(buf);

  // ---- 液晶ダッシュボード (常時表示) ----
  drawDashboard();
}
