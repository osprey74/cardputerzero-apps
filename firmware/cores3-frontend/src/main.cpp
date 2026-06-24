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
//    "enc":[{"id":1,"role":"R","uid":"A1B2C3D4","cnt":12,"delta":1,"btn":0},
//           {"id":2,"role":"B","uid":"E5F6A7B8","cnt":-3,"delta":0,"btn":1}]}
//    ※ id=チェーン上の位置(1始まり)・role/uid=個体識別(配線順非依存・UID で確定)
//
//   液晶 (常時表示・左右スワイプで 3 ページ切替・下部にページドット):
//     [METER] バッテリ% / 充電 / 電圧 + INA226 V/I/P 大表示 + NCIR + エンコーダ
//     [INFO ] NTP 時計 (JST) + 室温 (NCIR amb) + 天気 (気象庁 forecast JSON)
//     [SYS  ] ネットワーク詳細 (SSID/RSSI/IP/GW/MAC) + システム (uptime/heap/psram/fw)
//   ちらつき防止に M5Canvas (オフスクリーン・スプライト) へ描画し一括転送する。
//   Wi-Fi 認証情報は src/secrets.h (gitignore 済み) に記入。未設定なら INFO/SYS は
//   "not configured" を表示し JSON 送信・METER は通常動作する。

#include <M5Unified.h>
#include <Wire.h>
#include <M5Chain.h>   // Chain Encoder (Port C UART デイジーチェーン)
#include <WiFi.h>      // INFO 画面: Wi-Fi 接続 + NTP 時計
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>   // INFO 天気: 気象庁 forecast JSON パース
#include <time.h>
#include <math.h>
#include <string.h>
#include <limits.h>
#include <esp_heap_caps.h>   // PSRAM 確保 (ArduinoJson allocator)

// Wi-Fi 認証情報 (secrets.h は .gitignore 済み)。無ければ空で吸収しビルド可。
#if __has_include("secrets.h")
  #include "secrets.h"
#endif
#ifndef WIFI_SSID
  #define WIFI_SSID ""
  #define WIFI_PASS ""
#endif

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

// ---- Chain Encoder 個体識別 (UID ベース・配線順非依存) ----------------------
// 各 Chain ノードは STM32 固有 UID を持つ。getUID(id, UID_TYPE_4_BYTE, ...) で
// 読み出し、下表の既知 UID と突き合わせて「役割(色)」を物理位置によらず固定する。
// ※ chain.getUID() のドキュメント上、id は「チェーン上の位置 (1 始まり)」を指す。
//    id だけだとケーブル接続順を入れ替えると赤/青が入れ替わるため UID で恒久固定する。
//
// 【UID 採取手順】初回はプレースホルダ(全ゼロ)。書込み後シリアルの
//    {"log":"chain_uid","id":..,"uid":"XXXXXXXX",..} を確認し、上流(赤)・下流(青)
//    の UID を下記 uid[] に記入して再ビルド・再書込みする。
//    ゼロのままのエントリは「未設定」として突合をスキップする (誤マッチ防止)。
struct EncoderIdentity {
  uint8_t     uid[4];   // STM32 固有 UID 先頭 4 バイト (全ゼロ = 未設定)
  const char *name;     // 表示名 (色の意味)
  uint16_t    color;    // 表示色
  char        role;     // JSON 用 役割コード
};
static const EncoderIdentity ENC_IDENTITY[] = {
  // 実機採取 (2026-06-24): id=1(上流) UID=4E001B00 / id=2(下流) UID=78001C00。
  // 以後この UID で色を固定するため、ケーブル接続順を入れ替えても赤/青は不変。
  {{0x4E, 0x00, 0x1B, 0x00}, "RED",  COL_E1, 'R'},   // 物理:赤 (採取時:上流)
  {{0x78, 0x00, 0x1C, 0x00}, "BLUE", COL_E2, 'B'},   // 物理:青 (採取時:下流)
};
static constexpr size_t ENC_IDENTITY_N = sizeof(ENC_IDENTITY) / sizeof(ENC_IDENTITY[0]);

// 位置 id(1始まり) ごとの UID 採取結果と解決済み identity インデックス。
static uint8_t g_enc_uid[ENC_MAX + 1][4] = {{0}};
static bool    g_enc_uid_ok[ENC_MAX + 1] = {false};
static int8_t  g_enc_ident[ENC_MAX + 1]  = {-1};  // ENC_IDENTITY index / -1=unknown

#define FW_VERSION "0.3.0"

// ---- 画面ページ (左右スワイプで切替) ---------------------------------------
enum Page { PAGE_METER = 0, PAGE_INFO, PAGE_SYS, PAGE_COUNT };
static int  g_page = PAGE_METER;
static bool g_redraw = true;                 // ページ切替直後など即時再描画フラグ
static constexpr int SWIPE_THRESHOLD = 50;   // スワイプと判定する水平移動量 [px]

// ---- Wi-Fi / NTP (INFO 画面) -----------------------------------------------
// secrets.h 未設定 (空 SSID) なら Wi-Fi 機能は無効。
static const bool WIFI_CONFIGURED = (sizeof(WIFI_SSID) > 1);  // "" は 1 byte
enum WifiState { WIFI_OFF_STATE = 0, WIFI_CONNECTING, WIFI_CONNECTED_NO_NTP, WIFI_NTP_OK };
static int      g_wifi_state = WIFI_OFF_STATE;
static uint32_t g_wifi_last_try_ms = 0;
static bool     g_ntp_started = false;
static constexpr uint32_t WIFI_RETRY_MS = 10000;  // 切断時の再接続間隔

// ---- 天気 (気象庁 forecast JSON・INFO 画面) --------------------------------
// area=016000 (石狩・空知・後志 / 札幌管区)。API キー不要・HTTPS。
#define WX_AREA "016000"
#define WX_PLACE "Sapporo"
static constexpr uint32_t WX_INTERVAL_MS = 30UL * 60 * 1000;  // 30 分毎に更新
struct WeatherDay {
  char cat[8];   // "Sunny"/"Cloudy"/"Rain"/"Snow"/"-"
  int  tmax, tmin;   // ℃ (INT_MIN = 無し)
  int  pop;          // 降水確率 % (-1 = 無し)
};
static bool        g_wx_ok = false;
static WeatherDay  g_wx_today = {"-", INT_MIN, INT_MIN, -1};
static WeatherDay  g_wx_tom   = {"-", INT_MIN, INT_MIN, -1};
static int         g_wx_now_temp = INT_MIN;   // 直近気温
static uint32_t    g_wx_last_ms = 0;
static char        g_wx_upd[6] = "--:--";     // 取得時刻 HH:MM

// ArduinoJson を PSRAM に確保する Allocator (本体ヒープを圧迫しない)。
struct PsramAllocator : ArduinoJson::Allocator {
  void *allocate(size_t n) override { return heap_caps_malloc(n, MALLOC_CAP_SPIRAM); }
  void  deallocate(void *p) override { heap_caps_free(p); }
  void *reallocate(void *p, size_t n) override {
    return heap_caps_realloc(p, n, MALLOC_CAP_SPIRAM);
  }
};

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

// 指定位置 id の Chain ノードから 4 バイト UID を読み出す。成功時 true。
static bool getEncoderUID4(uint16_t id, uint8_t out[4]) {
  uint8_t op = 0;
  return chain.getUID(id, UID_TYPE_4_BYTE, out, 4, &op) == CHAIN_OK && op == 1;
}

// UID を既知テーブルと突合し identity インデックスを返す。未設定(全ゼロ)entry は無視。
static int8_t resolveIdentity(const uint8_t uid[4]) {
  for (size_t i = 0; i < ENC_IDENTITY_N; i++) {
    const uint8_t *u = ENC_IDENTITY[i].uid;
    if ((u[0] | u[1] | u[2] | u[3]) == 0) continue;  // 未設定 (プレースホルダ)
    if (memcmp(u, uid, 4) == 0) return (int8_t)i;
  }
  return -1;
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

// 下部ページインジケータ (現在ページを塗り円・他は輪郭)。
static void drawPageDots() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  const int r = 3, gap = 12;
  int total = PAGE_COUNT * gap;
  int x0 = (W - total) / 2 + gap / 2;
  for (int i = 0; i < PAGE_COUNT; i++) {
    int cx = x0 + i * gap;
    if (i == g_page) g_canvas.fillCircle(cx, H - 6, r, COL_ACCENT);
    else             g_canvas.drawCircle(cx, H - 6, r, COL_DIM);
  }
}

// METER ページ: バッテリ + INA226 + NCIR + エンコーダ (従来ダッシュボード)。
static void drawMeter() {
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
      // UID で解決した役割があれば色・名前を個体固定 (配線順非依存)。
      // 未解決時は従来の位置ベース (id1=赤 / id2=青) にフォールバック。
      int8_t idn = g_enc_ident[id];
      uint16_t encColor = (idn >= 0) ? ENC_IDENTITY[idn].color
                        : (id == 1) ? COL_E1 : (id == 2) ? COL_E2 : COL_VALUE;
      const char *nm = (idn >= 0) ? ENC_IDENTITY[idn].name : nullptr;
      char line[24];
      if (nm) snprintf(line, sizeof(line), "%s %+ld", nm, (long)g_enc_count[id]);
      else    snprintf(line, sizeof(line), "E%u %+ld", id, (long)g_enc_count[id]);
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
}

// INFO ページ: NTP 時計 (JST) + 室温 (NCIR amb) + 天気 (気象庁)。
static void drawInfo() {
  const int W = g_canvas.width();
  char buf[40], line[40];

  g_canvas.fillScreen(COL_BG);
  int x = 6, y = 4;

  // ---- 時計 (NTP 同期時のみ・曜日 日=赤/土=青) ----
  y = drawSection(x, y, W - 12, "CLOCK  (JST)");
  if (g_wifi_state == WIFI_NTP_OK) {
    struct tm t;
    if (getLocalTime(&t, 0)) {
      static const char *wd[] = {"Sun","Mon","Tue","Wed","Thu","Fri","Sat"};
      snprintf(buf, sizeof(buf), "%04d-%02d-%02d ", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday);
      g_canvas.setTextSize(2);
      g_canvas.setTextColor(COL_LABEL, COL_BG);
      g_canvas.setCursor(x + 4, y);
      g_canvas.print(buf);
      uint16_t wcol = (t.tm_wday == 0) ? COL_E1 : (t.tm_wday == 6) ? COL_E2 : COL_LABEL;
      g_canvas.setTextColor(wcol, COL_BG);
      g_canvas.print(wd[t.tm_wday % 7]);
      y += 26;
      snprintf(buf, sizeof(buf), "%02d:%02d:%02d", t.tm_hour, t.tm_min, t.tm_sec);
      g_canvas.setTextSize(4);
      g_canvas.setTextColor(COL_VALUE, COL_BG);
      g_canvas.setCursor(x + 4, y);
      g_canvas.print(buf);
      y += 42;
    }
  } else {
    g_canvas.setTextSize(2);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setCursor(x + 4, y);
    g_canvas.print(g_wifi_state == WIFI_CONNECTED_NO_NTP ? "NTP sync..." :
                   WIFI_CONFIGURED ? "no time yet" : "no wifi cfg");
    y += 28;
  }

  // ---- 室温 (NCIR amb) ----
  if (!isnan(g_r.t_amb)) {
    snprintf(buf, sizeof(buf), "%.1fC", g_r.t_amb);
    drawField(x + 4, y, "room ", buf, COL_ACCENT, 2, 2);
    y += 26;
  }

  // ---- 天気 (気象庁) ----
  snprintf(buf, sizeof(buf), "WEATHER  %s", WX_PLACE);
  y = drawSection(x, y, W - 12, buf);
  if (g_wx_ok) {
    // 今日 (カテゴリ + 直近気温)
    if (g_wx_now_temp != INT_MIN) snprintf(line, sizeof(line), "%s %dC", g_wx_today.cat, g_wx_now_temp);
    else                         snprintf(line, sizeof(line), "%s", g_wx_today.cat);
    drawField(x + 4, y, "now ", line, COL_VALUE, 2, 2); y += 22;
    if (g_wx_today.pop >= 0) {
      snprintf(line, sizeof(line), "%d%%", g_wx_today.pop);
      drawField(x + 4, y, "pop ", line, COL_LABEL, 2, 2); y += 22;
    }
    // 明日 (カテゴリ + 最高/最低)
    if (g_wx_tom.tmax != INT_MIN || g_wx_tom.tmin != INT_MIN) {
      char hi[8] = "--", lo[8] = "--";
      if (g_wx_tom.tmax != INT_MIN) snprintf(hi, sizeof(hi), "%d", g_wx_tom.tmax);
      if (g_wx_tom.tmin != INT_MIN) snprintf(lo, sizeof(lo), "%d", g_wx_tom.tmin);
      snprintf(line, sizeof(line), "%s %s/%s", g_wx_tom.cat, hi, lo);
    } else {
      snprintf(line, sizeof(line), "%s", g_wx_tom.cat);
    }
    drawField(x + 4, y, "tom ", line, COL_VALUE, 2, 2); y += 22;
    // 取得時刻
    snprintf(line, sizeof(line), "upd %s", g_wx_upd);
    g_canvas.setTextSize(1);
    g_canvas.setTextColor(COL_DIM, COL_BG);
    g_canvas.setCursor(x + 4, y);
    g_canvas.print(line); y += 14;
  } else {
    g_canvas.setTextSize(1);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setCursor(x + 4, y);
    g_canvas.print(g_wifi_state >= WIFI_CONNECTED_NO_NTP ? "fetching..." : "(needs wifi)");
    y += 14;
  }
}

// SYS ページ: ネットワーク詳細 + システム情報。
static void drawSys() {
  const int W = g_canvas.width();
  char buf[48];

  g_canvas.fillScreen(COL_BG);
  int x = 6, y = 4;

  // ---- ネットワーク ----
  y = drawSection(x, y, W - 12, "NETWORK");
  const char *st =
      !WIFI_CONFIGURED                ? "not configured" :
      g_wifi_state == WIFI_CONNECTING ? "connecting..." :
      (g_wifi_state >= WIFI_CONNECTED_NO_NTP) ? "connected" : "down";
  uint16_t stcol = (g_wifi_state >= WIFI_CONNECTED_NO_NTP) ? COL_OK :
                   WIFI_CONFIGURED ? COL_WARN : COL_LABEL;
  drawField(x + 4, y, "stat ", st, stcol, 2, 2); y += 24;
  if (g_wifi_state >= WIFI_CONNECTED_NO_NTP) {
    snprintf(buf, sizeof(buf), "%.18s", WiFi.SSID().c_str());
    drawField(x + 4, y, "ssid ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%d dBm", WiFi.RSSI());
    drawField(x + 4, y, "rssi ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%s", WiFi.localIP().toString().c_str());
    drawField(x + 4, y, "ip   ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%s", WiFi.gatewayIP().toString().c_str());
    drawField(x + 4, y, "gw   ", buf, COL_LABEL, 1, 2); y += 20;
  }
  snprintf(buf, sizeof(buf), "%s", WiFi.macAddress().c_str());
  drawField(x + 4, y, "mac  ", buf, COL_LABEL, 1, 1); y += 18;

  // ---- システム ----
  y = drawSection(x, y, W - 12, "SYSTEM");
  uint32_t s = millis() / 1000;
  snprintf(buf, sizeof(buf), "%02u:%02u:%02u", (unsigned)(s / 3600), (unsigned)((s / 60) % 60), (unsigned)(s % 60));
  drawField(x + 4, y, "up   ", buf, COL_VALUE, 1, 2); y += 20;
  snprintf(buf, sizeof(buf), "%u KB", (unsigned)(ESP.getFreeHeap() / 1024));
  drawField(x + 4, y, "heap ", buf, COL_VALUE, 1, 2); y += 20;
  snprintf(buf, sizeof(buf), "%.1f MB", ESP.getFreePsram() / 1048576.0);
  drawField(x + 4, y, "psram", buf, COL_VALUE, 1, 2); y += 20;
  drawField(x + 4, y, "fw   ", FW_VERSION, COL_ACCENT, 1, 2); y += 20;
}

// 現在ページを描画 → ページドット → 一括転送。
static void drawCurrentPage() {
  switch (g_page) {
    case PAGE_INFO:  drawInfo();  break;
    case PAGE_SYS:   drawSys();   break;
    case PAGE_METER:
    default:         drawMeter(); break;
  }
  drawPageDots();
  g_canvas.pushSprite(0, 0);
}

// ---------------------------------------------------------------------------
// タッチ: 左右スワイプでページ送り。
// ---------------------------------------------------------------------------
static void handleTouch() {
  if (M5.Touch.getCount() == 0) return;
  auto d = M5.Touch.getDetail();
  // フリック確定 or 指離し時に、始点からの水平移動量で判定。
  if (d.wasFlicked() || d.wasReleased()) {
    int dx = d.distanceX();
    if (dx <= -SWIPE_THRESHOLD) {          // 左へスワイプ → 次ページ
      g_page = (g_page + 1) % PAGE_COUNT;
      g_redraw = true;
    } else if (dx >= SWIPE_THRESHOLD) {    // 右へスワイプ → 前ページ
      g_page = (g_page + PAGE_COUNT - 1) % PAGE_COUNT;
      g_redraw = true;
    }
  }
}

// ---------------------------------------------------------------------------
// Wi-Fi / NTP の状態遷移 (非ブロッキング)。loop から毎回呼ぶ。
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// 天気: 気象庁 forecast JSON を取得・パース (INFO 画面)。
// ---------------------------------------------------------------------------

// 天気コード先頭桁 → カテゴリ (1=晴/2=曇/3=雨/4=雪)。日本語フォント不要。
static const char *wxCat(const char *code) {
  if (!code || !code[0]) return "-";
  switch (code[0]) {
    case '1': return "Sunny";
    case '2': return "Cloudy";
    case '3': return "Rain";
    case '4': return "Snow";
    default:  return "-";
  }
}

// 気象庁 forecast JSON を取得して g_wx_* を更新。NTP 同期後に呼ぶ (日付計算に必要)。
static void fetchWeather() {
  WiFiClientSecure client;
  client.setInsecure();   // 証明書検証スキップ (公開天気データの表示用途)
  HTTPClient http;
  http.setTimeout(8000);
  const char *url = "https://www.jma.go.jp/bosai/forecast/data/forecast/" WX_AREA ".json";
  if (!http.begin(client, url)) {
    Serial.println("{\"log\":\"wx\",\"ok\":0,\"err\":\"begin\"}");
    return;
  }
  int code = http.GET();
  if (code != 200) {
    Serial.printf("{\"log\":\"wx\",\"ok\":0,\"http\":%d}\n", code);
    http.end();
    return;
  }

  static PsramAllocator psramAlloc;
  JsonDocument doc(&psramAlloc);
  DeserializationError err = deserializeJson(doc, http.getStream());
  http.end();
  if (err) {
    Serial.printf("{\"log\":\"wx\",\"ok\":0,\"json\":\"%s\"}\n", err.c_str());
    return;
  }

  JsonArray root = doc.as<JsonArray>();
  if (root.isNull() || root.size() < 1) {
    Serial.println("{\"log\":\"wx\",\"ok\":0,\"err\":\"shape\"}");
    return;
  }
  JsonArray ts = root[0]["timeSeries"].as<JsonArray>();
  if (ts.isNull() || ts.size() < 3) {
    Serial.println("{\"log\":\"wx\",\"ok\":0,\"err\":\"ts\"}");
    return;
  }

  // ---- 今日/明日の日付文字列 (NTP 時刻から) ----
  char todayStr[11] = "", tomStr[11] = "";
  struct tm t;
  if (getLocalTime(&t, 0)) {
    strftime(todayStr, sizeof(todayStr), "%Y-%m-%d", &t);
    time_t tt = mktime(&t) + 86400;
    struct tm t2;
    localtime_r(&tt, &t2);
    strftime(tomStr, sizeof(tomStr), "%Y-%m-%d", &t2);
  }

  // ---- 天気コード (ts[0]: 今日/明日/明後日) ----
  auto wxReset = [](WeatherDay &d) {
    d.cat[0] = '-'; d.cat[1] = '\0'; d.tmax = INT_MIN; d.tmin = INT_MIN; d.pop = -1;
  };
  wxReset(g_wx_today);
  wxReset(g_wx_tom);
  g_wx_now_temp = INT_MIN;
  JsonObject wxArea = ts[0]["areas"][0];
  strncpy(g_wx_today.cat, wxCat(wxArea["weatherCodes"][0]), sizeof(g_wx_today.cat) - 1);
  strncpy(g_wx_tom.cat,   wxCat(wxArea["weatherCodes"][1]), sizeof(g_wx_tom.cat) - 1);

  // ---- 気温 (ts[2]: 札幌・00:00=最低 / 09:00=最高) ----
  JsonArray tDefs = ts[2]["timeDefines"].as<JsonArray>();
  JsonArray temps = ts[2]["areas"][0]["temps"].as<JsonArray>();
  for (size_t i = 0; i < tDefs.size(); i++) {
    const char *td = tDefs[i];
    const char *tv = temps[i];
    if (!td || !tv || !tv[0]) continue;
    int val = atoi(tv);
    int hh = atoi(td + 11);  // "....T HH:.." の時
    if (todayStr[0] && strncmp(td, todayStr, 10) == 0) g_wx_now_temp = val;  // 今日の直近
    if (tomStr[0]   && strncmp(td, tomStr, 10) == 0) {
      if (hh < 6) g_wx_tom.tmin = val; else g_wx_tom.tmax = val;
    }
  }

  // ---- 降水確率 (ts[1]: 今日/明日の最大) ----
  JsonArray pDefs = ts[1]["timeDefines"].as<JsonArray>();
  JsonArray pops  = ts[1]["areas"][0]["pops"].as<JsonArray>();
  for (size_t i = 0; i < pDefs.size(); i++) {
    const char *pd = pDefs[i];
    const char *pv = pops[i];
    if (!pd || !pv || !pv[0]) continue;
    int v = atoi(pv);
    if (todayStr[0] && strncmp(pd, todayStr, 10) == 0 && v > g_wx_today.pop) g_wx_today.pop = v;
    if (tomStr[0]   && strncmp(pd, tomStr, 10) == 0 && v > g_wx_tom.pop)     g_wx_tom.pop = v;
  }

  if (getLocalTime(&t, 0)) snprintf(g_wx_upd, sizeof(g_wx_upd), "%02d:%02d", t.tm_hour, t.tm_min);
  g_wx_ok = true;
  Serial.printf("{\"log\":\"wx\",\"ok\":1,\"today\":\"%s\",\"tom\":\"%s\","
                "\"tom_max\":%d,\"tom_min\":%d,\"now\":%d,\"today_pop\":%d,\"tom_pop\":%d}\n",
                g_wx_today.cat, g_wx_tom.cat, g_wx_tom.tmax, g_wx_tom.tmin,
                g_wx_now_temp, g_wx_today.pop, g_wx_tom.pop);
}

// 状態遷移を 1 回だけログ出力 (NTP 同期確認・Wi-Fi デバッグ用)。
static void logWifiTransition(int from, int to) {
  if (from == to) return;
  if (to == WIFI_NTP_OK) {
    struct tm t;
    char ts[24] = "?";
    if (getLocalTime(&t, 0))
      snprintf(ts, sizeof(ts), "%04d-%02d-%02d %02d:%02d:%02d",
               t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec);
    Serial.printf("{\"log\":\"wifi\",\"state\":%d,\"ssid\":\"%s\",\"rssi\":%d,"
                  "\"ip\":\"%s\",\"ntp_time\":\"%s\"}\n",
                  to, WiFi.SSID().c_str(), WiFi.RSSI(),
                  WiFi.localIP().toString().c_str(), ts);
  } else {
    Serial.printf("{\"log\":\"wifi\",\"state\":%d}\n", to);
  }
}

static void wifiTask() {
  if (!WIFI_CONFIGURED) { g_wifi_state = WIFI_OFF_STATE; return; }

  const int prev_state = g_wifi_state;
  const uint32_t now = millis();
  wl_status_t ws = WiFi.status();

  if (ws == WL_CONNECTED) {
    if (!g_ntp_started) {
      // JST (UTC+9)。NTP は NICT + pool を指定。
      configTzTime("JST-9", "ntp.nict.jp", "pool.ntp.org");
      g_ntp_started = true;
    }
    if (g_wifi_state < WIFI_CONNECTED_NO_NTP) g_wifi_state = WIFI_CONNECTED_NO_NTP;
    // NTP 同期判定: 年が 2020 以降なら同期済みとみなす。
    struct tm t;
    if (getLocalTime(&t, 0) && (t.tm_year + 1900) >= 2020) g_wifi_state = WIFI_NTP_OK;
  } else {
    g_ntp_started = false;
    if (g_wifi_state == WIFI_NTP_OK || g_wifi_state == WIFI_CONNECTED_NO_NTP)
      g_wifi_state = WIFI_CONNECTING;  // 切断 → 再接続待ち
    // 初回 or リトライ間隔ごとに begin。
    if (g_wifi_state == WIFI_OFF_STATE ||
        (now - g_wifi_last_try_ms >= WIFI_RETRY_MS)) {
      g_wifi_last_try_ms = now;
      g_wifi_state = WIFI_CONNECTING;
      WiFi.mode(WIFI_STA);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
  }

  logWifiTransition(prev_state, g_wifi_state);  // 状態が変わった時のみログ出力
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

  // タッチ (左右スワイプでページ送り) と Wi-Fi/NTP は毎ループ処理し応答性を確保。
  handleTouch();
  wifiTask();

  // 天気: NTP 同期後、初回 + 30 分毎に取得 (HTTPS なので数秒ブロックする)。
  if (g_wifi_state == WIFI_NTP_OK &&
      (g_wx_last_ms == 0 || now - g_wx_last_ms >= WX_INTERVAL_MS)) {
    g_wx_last_ms = now;
    fetchWeather();
    g_redraw = true;
  }

  if (g_redraw) {           // ページ切替直後は即時再描画してキビキビ動かす。
    g_redraw = false;
    drawCurrentPage();
  }

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

    // 各ノードの UID を採取 → 既知テーブルと突合し役割(色)を配線順非依存で確定。
    for (uint16_t id = 1; id <= g_enc_num && id <= ENC_MAX; id++) {
      uint8_t uid[4] = {0};
      bool ok = getEncoderUID4(id, uid);
      g_enc_uid_ok[id] = ok;
      if (ok) { memcpy(g_enc_uid[id], uid, 4); g_enc_ident[id] = resolveIdentity(uid); }
      else    { g_enc_ident[id] = -1; }
      Serial.printf("{\"log\":\"chain_uid\",\"id\":%u,\"ok\":%d,\"uid\":\"%02X%02X%02X%02X\","
                    "\"ident\":%d,\"name\":\"%s\"}\n",
                    id, ok ? 1 : 0, uid[0], uid[1], uid[2], uid[3], (int)g_enc_ident[id],
                    g_enc_ident[id] >= 0 ? ENC_IDENTITY[g_enc_ident[id]].name : "?");
    }
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
  char encbuf[360];
  int off = snprintf(encbuf, sizeof(encbuf), "[");
  for (uint16_t id = 1; id <= g_enc_num && id <= ENC_MAX && off < (int)sizeof(encbuf) - 96; id++) {
    int16_t inc = 0;
    uint8_t btn = 0;
    chain.getEncoderIncValue(id, &inc);     // 前回読取からの増分
    chain.getEncoderButtonStatus(id, &btn); // ノブ押下状態 (生値)
    g_enc_count[id] += inc;
    // 個体識別: role(R/B/…) と uid を併記 (受信側が配線順によらず個体を束ねられる)。
    char role = (g_enc_ident[id] >= 0) ? ENC_IDENTITY[g_enc_ident[id]].role : '?';
    off += snprintf(encbuf + off, sizeof(encbuf) - off,
                    "%s{\"id\":%u,\"role\":\"%c\",\"uid\":\"%02X%02X%02X%02X\","
                    "\"cnt\":%ld,\"delta\":%d,\"btn\":%u}",
                    id > 1 ? "," : "", id, role,
                    g_enc_uid[id][0], g_enc_uid[id][1], g_enc_uid[id][2], g_enc_uid[id][3],
                    (long)g_enc_count[id], inc, btn);
  }
  snprintf(encbuf + off, sizeof(encbuf) - off, "]");

  // ---- JSON 1 行送信 ----
  char buf[600];
  snprintf(buf, sizeof(buf),
           "{\"bat\":{\"pct\":%d,\"chg\":%d,\"v\":%.2f},"
           "\"ina\":{\"v\":%.3f,\"i\":%.4f,\"p\":%.4f},"
           "\"ncir\":{\"t_obj\":%.2f,\"t_amb\":%.2f},\"enc\":%s}",
           g_r.bat_pct, g_r.bat_chg, g_r.bat_v,
           g_r.ina_v, g_r.ina_i, g_r.ina_p, g_r.t_obj, g_r.t_amb, encbuf);
  Serial.println(buf);

  // ---- 液晶 (現在ページを描画) ----
  drawCurrentPage();
}
