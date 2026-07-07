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
#include <WiFiMulti.h> // 複数 AP 登録 (電波の強い既知 AP に自動接続)
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>   // INFO 天気: 気象庁 forecast JSON パース
#include <Preferences.h>   // NVS: INA226 ユニット種別などの永続設定
#include <time.h>
#include <math.h>
#include <string.h>
#include <limits.h>
#include <esp_heap_caps.h>   // PSRAM 確保 (ArduinoJson allocator)

// Wi-Fi 認証情報 (secrets.h は .gitignore 済み)。無ければ未設定として吸収しビルド可。
//   新形式: secrets.h で WIFI_APS を X("ssid","pass") の並びとして定義 (複数登録可)。
//   旧形式: WIFI_SSID / WIFI_PASS (単一) も後方互換でサポート。
#if __has_include("secrets.h")
  #include "secrets.h"
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

// ---- INA226 ユニット種別 (M5 公式仕様) -------------------------------------
// 10A番と1A番は同一 INA226 チップで、違いは基板シャント値のみ。この抵抗値を
// 読めるレジスタは存在せず、Mfg/Die ID・I2Cアドレスも同一なのでチップからの
// 自動判別は不可能。→ 種別を NVS に保持し、METER 画面のタッチで切り替える。
//
// M5 公式 Product Compare より:
//   10A版: シャント 5mΩ  / ±10A / 分解能 0.32mA
//   1A版 : シャント 80mΩ / ±1A  / 分解能 32µA
//   出典: https://shop.m5stack.com/products/ina226-1a-current-voltage-power-monitor-unit
//
// CAL = 0.00512 / (Current_LSB × R_shunt) はシャント値が異なるためユニット毎に別。
//   10A: 0.00512/(0.00032 ×0.005) = 3200
//   1A : 0.00512/(0.000032×0.08 ) = 2000
// 種別を切り替えたら CAL レジスタも書き直すこと (ina226ApplyCal)。
static constexpr uint16_t INA226_CONFIG = 0x4527;  // 連続(shunt+bus)/平均16/変換1.1ms

struct Ina226Unit {
  const char *name;
  uint16_t cal;        // Calibration register 値
  float current_lsb;   // A/bit
  float power_lsb;      // W/bit (= 25 × current_lsb)
};
static constexpr Ina226Unit INA226_UNITS[] = {
  { "10A", 3200, 0.00032f,  0.008f  },  // 5mΩ,  0.32mA/bit (広レンジ)
  { "1A",  2000, 0.000032f, 0.0008f },  // 80mΩ, 0.032mA/bit (高分解能)
};
static constexpr int INA226_UNIT_COUNT   = sizeof(INA226_UNITS) / sizeof(INA226_UNITS[0]);
static constexpr int INA226_UNIT_DEFAULT = 1;   // 初回起動時の既定 (1 = 1A番)

static int         g_ina_unit = INA226_UNIT_DEFAULT;  // 現在の種別 index (NVS から復元)
static Preferences g_prefs;                           // NVS 永続設定
// METER 画面のユニット種別トグルチップの描画矩形 (タッチ当たり判定に使用)。
static int16_t g_unit_btn_x = 0, g_unit_btn_y = 0, g_unit_btn_w = 0, g_unit_btn_h = 0;

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
  float mx, my, mz;            // 地磁気 [µT] (BMM150・未取得は NAN)。App16 星座盤の方位アライン用
  int   mag_ok;                // 1=getMag 成功 / 0=失敗
};
static Readings g_r;
static bool g_mag_available = false;   // 起動時プローブで BMM150 が使えると判定したか

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
static constexpr uint16_t COL_RED    = 0xF800;  // 赤 (タイマー僅少・超過)
static constexpr uint16_t COL_TRACK  = 0x2104;  // ドーナツの経過部 (暗い溝)

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

#define FW_VERSION "0.5.0"   // + セミナータイマー (TIMER) ページ / TIMER 中は Wi-Fi/I2C 停止

// ---- IMU 水準器・下げ振り (内蔵 BMI270) ------------------------------------
// 単体アプリ firmware/cores3-level と同じ角度ロジック。協働中も CoreS3 画面の
// スワイプで LEVEL / PLUMB を呼び出せるよう本フロントエンドにページとして統合。
// ⚠️ 軸符号は cores3-level で実機確定済み (ACC_SIGN_Y=-1 / EDGE_SIGN_*=+1)。
static constexpr float R2D           = 57.29578f;
static constexpr float ACCEL_ALPHA   = 0.20f;   // 加速度の指数移動平均係数
static constexpr float LEVEL_TOL_DEG = 0.5f;    // 「水平」判定の許容角 [deg]
static constexpr float BUBBLE_FS_DEG = 20.0f;   // 気泡が円の縁に達する傾き [deg]
static constexpr float ACC_SIGN_X = +1.0f;
static constexpr float ACC_SIGN_Y = -1.0f;      // 前後反転 (実機確定)
static constexpr float ACC_SIGN_Z = +1.0f;
static constexpr float EDGE_SIGN_A = +1.0f;     // EDGE/PLUMB 左右
static constexpr float EDGE_SIGN_B = +1.0f;     // EDGE 画面法線
static float g_fax = 0, g_fay = 0, g_faz = 1.0f;   // 平滑化済み加速度 (G)
static float g_angX = 0, g_angY = 0, g_tilt = 0;   // FLAT 左右/前後/合成傾斜 [deg]
static float g_edgeA = 0, g_edgeB = 0;             // EDGE(縦置き) 左右/法線 [deg]
static bool  g_relative = false;                   // タップでゼロ点トグル (LEVEL/PLUMB)
static float g_offX = 0, g_offY = 0, g_offA = 0, g_offB = 0;

// ---- セミナー・カウントダウンタイマー (TIMER ページ) -----------------------
// プリセット時間を選び、ドーナツ円グラフが 12 時から時計回りに減少。中央に
// 残り時間(大)+経過時間(小)を併記。0 到達後は超過を +MM:SS でカウントアップ。
// TIMER ページ表示中は省電力のため Wi-Fi/I2C を停止し、他ページへ戻すと再接続する
// (updateRadioForPage / netTask の g_radio_off を参照)。
static const int PRESET_MIN[]      = {5, 15, 30, 45, 60, 90, 100, 120};  // プリセット [分]
static constexpr int PRESET_COUNT   = sizeof(PRESET_MIN) / sizeof(PRESET_MIN[0]);
static constexpr int PRESET_DEFAULT = 5;   // 既定インデックス (= 90 分)
enum TimerState { TM_SETUP = 0, TM_RUNNING, TM_PAUSED, TM_DONE };
static int      g_tm_state   = TM_SETUP;
static int      g_tm_preset  = PRESET_DEFAULT;  // 選択中プリセットのインデックス
static uint32_t g_tm_total_ms  = 0;   // 設定総時間 [ms]
static uint32_t g_tm_start_ms  = 0;   // 計測開始時刻 (millis)
static uint32_t g_tm_paused_at = 0;   // 一時停止に入った時刻 (millis)
static uint32_t g_tm_paused_acc = 0;  // 累積の一時停止時間 [ms]

// ---- 画面ページ (左右スワイプで切替) ---------------------------------------
enum Page { PAGE_METER = 0, PAGE_INFO, PAGE_SYS, PAGE_LEVEL, PAGE_PLUMB, PAGE_TIMER, PAGE_COUNT };
static int  g_page = PAGE_METER;
static bool g_redraw = true;                 // ページ切替直後など即時再描画フラグ
static constexpr int SWIPE_THRESHOLD = 50;   // スワイプと判定する水平移動量 [px]
// セクション末尾テキストの下端から次セクション見出しまでの余白 [px]。
// METER (INA→NCIR / NCIR→ENC) が 12px なので全ページこれに揃える。
// 各セクション最終行の増分 = テキスト高(8×サイズ) + SEC_GAP とする。
static constexpr int SEC_GAP = 12;

// ---- Wi-Fi / NTP (INFO 画面) -----------------------------------------------
// WiFiMulti に登録された AP のうち電波の強い既知 AP へ自動接続。AP が 1 つも
// 無ければ Wi-Fi 機能は無効 (g_wifi_configured=false)。
static WiFiMulti wifiMulti;
static bool     g_wifi_configured = false;   // setup で登録 AP 数 > 0 なら true
enum WifiState { WIFI_OFF_STATE = 0, WIFI_CONNECTING, WIFI_CONNECTED_NO_NTP, WIFI_NTP_OK };
static int      g_wifi_state = WIFI_OFF_STATE;
static bool     g_ntp_started = false;
// TIMER ページ表示中は true。省電力のため Wi-Fi(core0/netTask)と I2C(core1/loop)を停止する。
// loop の updateRadioForPage が I2C を、netTask が Wi-Fi を、それぞれこのフラグを見て切替える。
static volatile bool g_radio_off = false;

// secrets.h の AP 群を WiFiMulti に登録し、登録数を返す。
// 新形式 WIFI_APS (X-macro) を優先、無ければ旧形式 WIFI_SSID を 1 件登録。
static int wifiRegisterAPs() {
  int n = 0;
#ifdef WIFI_APS
  #define X(ssid, pass) do { wifiMulti.addAP(ssid, pass); n++; } while (0);
  WIFI_APS
  #undef X
#elif defined(WIFI_SSID)
  if (sizeof(WIFI_SSID) > 1) { wifiMulti.addAP(WIFI_SSID, WIFI_PASS); n++; }
#endif
  return n;
}

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
  bool ok_cal = writeWord16(INA226_ADDR, INA_REG_CAL, INA226_UNITS[g_ina_unit].cal);
  Serial.printf("{\"log\":\"ina226_init\",\"unit\":\"%s\",\"mfg_id\":\"0x%04X\",\"die_id\":\"0x%04X\","
                "\"cfg_ok\":%d,\"cal_ok\":%d}\n",
                INA226_UNITS[g_ina_unit].name, mfg, die, ok_cfg ? 1 : 0, ok_cal ? 1 : 0);
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
// セミナータイマー ロジック (TIMER ページ)
// ---------------------------------------------------------------------------

// 経過時間 [ms] (一時停止分を除外)。RUNNING/PAUSED/DONE で有効。
static uint32_t tmElapsedMs() {
  uint32_t base = g_tm_start_ms + g_tm_paused_acc;
  uint32_t now  = (g_tm_state == TM_PAUSED) ? g_tm_paused_at : millis();
  return (now >= base) ? (now - base) : 0;
}

// 残り時間 [ms] (符号付き: 負なら超過)。
static long tmRemainingMs() {
  return (long)g_tm_total_ms - (long)tmElapsedMs();
}

// 秒数を "MM:SS" または 1 時間以上なら "H:MM:SS" に整形する。
static void tmFmt(long sec, char *buf, size_t n) {
  if (sec < 0) sec = 0;
  long h = sec / 3600, m = (sec % 3600) / 60, s = sec % 60;
  if (h > 0) snprintf(buf, n, "%ld:%02ld:%02ld", h, m, s);
  else       snprintf(buf, n, "%02ld:%02ld", m, s);
}

static void tmStart() {
  g_tm_total_ms   = (uint32_t)PRESET_MIN[g_tm_preset] * 60u * 1000u;
  g_tm_start_ms   = millis();
  g_tm_paused_acc = 0;
  g_tm_state      = TM_RUNNING;
}
static void tmPause()  { g_tm_paused_at = millis(); g_tm_state = TM_PAUSED; }
static void tmResume() { g_tm_paused_acc += (millis() - g_tm_paused_at); g_tm_state = TM_RUNNING; }
static void tmReset()  { g_tm_state = TM_SETUP; }
static void tmSavePreset() { g_prefs.putInt("tm_preset", g_tm_preset); }

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
  int ina_hdr_y = y;
  y = drawSection(x, y, W - 12, "INA226  DC METER");
  // ユニット種別トグルチップ (右上)。タップで 1A/10A を切替し NVS 保存。
  {
    const char *un = INA226_UNITS[g_ina_unit].name;
    int cw = (int)strlen(un) * 12 + 16;  // 文字幅(size2=12px) + 左右パディング
    int ch = 20;                         // タップしやすいよう拡大
    int cx = W - 6 - cw;
    int cy = ina_hdr_y - 5;
    g_canvas.fillRoundRect(cx, cy, cw, ch, 4, COL_ACCENT);
    g_canvas.setTextSize(2);
    g_canvas.setTextColor(COL_BG, COL_ACCENT);
    g_canvas.setCursor(cx + 8, cy + 3);
    g_canvas.print(un);
    g_unit_btn_x = cx; g_unit_btn_y = cy; g_unit_btn_w = cw; g_unit_btn_h = ch;
  }
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
      // 名前を 4 桁左詰めで揃え、回転値の桁を縦に揃える ("RED  +0" / "BLUE +0")。
      if (nm) snprintf(line, sizeof(line), "%-4s %+ld", nm, (long)g_enc_count[id]);
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
                   g_wifi_configured ? "no time yet" : "no wifi cfg");
    y += 28;
  }

  // ---- 室温 (NCIR amb) ----
  // CLOCK セクションの最終行 → 次の WEATHER 見出しまでを METER と同じ余白に揃える。
  if (!isnan(g_r.t_amb)) {
    snprintf(buf, sizeof(buf), "%.1fC", g_r.t_amb);
    drawField(x + 4, y, "room ", buf, COL_ACCENT, 2, 2);
    y += 16 + SEC_GAP;   // size2 テキスト(16px) + セクション余白
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
      !g_wifi_configured                ? "not configured" :
      g_wifi_state == WIFI_CONNECTING ? "connecting..." :
      (g_wifi_state >= WIFI_CONNECTED_NO_NTP) ? "connected" : "down";
  uint16_t stcol = (g_wifi_state >= WIFI_CONNECTED_NO_NTP) ? COL_OK :
                   g_wifi_configured ? COL_WARN : COL_LABEL;
  // 項目名は最長ラベル+2 で左詰めし、値との間に半角 2 空き以上を確保して揃える。
  drawField(x + 4, y, "stat ", st, stcol, 2, 2); y += 24;
  if (g_wifi_state >= WIFI_CONNECTED_NO_NTP) {
    snprintf(buf, sizeof(buf), "%.18s", WiFi.SSID().c_str());
    drawField(x + 4, y, "ssid   ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%d dBm", WiFi.RSSI());
    drawField(x + 4, y, "rssi   ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%s", WiFi.localIP().toString().c_str());
    drawField(x + 4, y, "ip     ", buf, COL_VALUE, 1, 2); y += 20;
    snprintf(buf, sizeof(buf), "%s", WiFi.gatewayIP().toString().c_str());
    drawField(x + 4, y, "gw     ", buf, COL_LABEL, 1, 2); y += 20;
  }
  snprintf(buf, sizeof(buf), "%s", WiFi.macAddress().c_str());
  // NETWORK セクションの最終行 → 次の SYSTEM 見出しまでを METER と同じ余白に揃える。
  drawField(x + 4, y, "mac    ", buf, COL_LABEL, 1, 1); y += 8 + SEC_GAP;  // size1(8px)+余白

  // ---- システム ----
  y = drawSection(x, y, W - 12, "SYSTEM");
  uint32_t s = millis() / 1000;
  snprintf(buf, sizeof(buf), "%02u:%02u:%02u", (unsigned)(s / 3600), (unsigned)((s / 60) % 60), (unsigned)(s % 60));
  drawField(x + 4, y, "up     ", buf, COL_VALUE, 1, 2); y += 20;
  // heap/psram は「空き / 合計」で表示 (getFreeHeap=現在の空き・getHeapSize=合計)。
  snprintf(buf, sizeof(buf), "%u/%u KB",
           (unsigned)(ESP.getFreeHeap() / 1024), (unsigned)(ESP.getHeapSize() / 1024));
  drawField(x + 4, y, "heap   ", buf, COL_VALUE, 1, 2); y += 20;
  snprintf(buf, sizeof(buf), "%.1f/%.1f MB",
           ESP.getFreePsram() / 1048576.0, ESP.getPsramSize() / 1048576.0);
  drawField(x + 4, y, "psram  ", buf, COL_VALUE, 1, 2); y += 20;
  drawField(x + 4, y, "fw     ", FW_VERSION, COL_ACCENT, 1, 2); y += 20;
}

// ---------------------------------------------------------------------------
// IMU 水準器・下げ振り (内蔵 BMI270)
// ---------------------------------------------------------------------------

// 加速度を読み、平滑化して FLAT(g_angX/g_angY/g_tilt) と EDGE(g_edgeA/g_edgeB) を更新。
static void updateAngles() {
  float ax, ay, az;
  if (!M5.Imu.getAccel(&ax, &ay, &az)) return;  // 新データ無しなら前回値を維持
  ax *= ACC_SIGN_X; ay *= ACC_SIGN_Y; az *= ACC_SIGN_Z;
  g_fax += ACCEL_ALPHA * (ax - g_fax);
  g_fay += ACCEL_ALPHA * (ay - g_fay);
  g_faz += ACCEL_ALPHA * (az - g_faz);

  // FLAT: 底面 (Z 軸) を下とみなす 2 軸の傾き。
  float rawX = atan2f(g_fax, g_faz) * R2D;
  float rawY = atan2f(g_fay, g_faz) * R2D;
  g_angX = rawX - (g_relative ? g_offX : 0.0f);
  g_angY = rawY - (g_relative ? g_offY : 0.0f);
  float mag = sqrtf(g_fax * g_fax + g_fay * g_fay + g_faz * g_faz);
  if (mag > 0.01f) g_tilt = acosf(fabsf(g_faz) / mag) * R2D;

  // EDGE: 手前側面 (前後 Y 軸 |ay|) を下とみなす 2 軸の傾き。
  float vdown = fabsf(g_fay);
  float rawA = atan2f(EDGE_SIGN_A * g_fax, vdown) * R2D;
  float rawB = atan2f(EDGE_SIGN_B * g_faz, vdown) * R2D;
  g_edgeA = rawA - (g_relative ? g_offA : 0.0f);
  g_edgeB = rawB - (g_relative ? g_offB : 0.0f);
}

// 現在の生角度をゼロ点として控える (相対測定の基準)。
static void captureZero() {
  g_offX = atan2f(g_fax, g_faz) * R2D;
  g_offY = atan2f(g_fay, g_faz) * R2D;
  float vdown = fabsf(g_fay);
  g_offA = atan2f(EDGE_SIGN_A * g_fax, vdown) * R2D;
  g_offB = atan2f(EDGE_SIGN_B * g_faz, vdown) * R2D;
}

// 相対測定中インジケータ (右上の "REL")。
static void drawRelFlag() {
  if (!g_relative) return;
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(COL_WARN, COL_BG);
  g_canvas.setCursor(g_canvas.width() - 22, 4);
  g_canvas.print("REL");
}

// LEVEL ページ: 底面を水平面とする円形気泡水準器 (縦 240×320 用レイアウト)。
static void drawLevel() {
  const int W = g_canvas.width();
  g_canvas.fillScreen(COL_BG);

  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setCursor(6, 6);
  g_canvas.print("LEVEL");

  const int cx = W / 2;
  const int cy = 150;
  const int R  = W / 2 - 14;
  bool level = (fabsf(g_angX) <= LEVEL_TOL_DEG && fabsf(g_angY) <= LEVEL_TOL_DEG);
  uint16_t ring = level ? COL_OK : COL_DIM;

  g_canvas.drawCircle(cx, cy, R, ring);
  g_canvas.drawCircle(cx, cy, R / 2, COL_DIM);
  int tolR = (int)(LEVEL_TOL_DEG / BUBBLE_FS_DEG * (R - 18));
  if (tolR < 10) tolR = 10;
  g_canvas.drawCircle(cx, cy, tolR, COL_ACCENT);
  g_canvas.drawFastHLine(cx - R, cy, 2 * R, ring);
  g_canvas.drawFastVLine(cx, cy - R, 2 * R, ring);

  // 表示は rotation=0 (既定の横向きから左 90° 回転)。IMU 軸は本体固定なので canvas の
  // 水平/垂直へ入れ替える。気泡は「高い側」へ動く = 重力方向 (PLUMB の向き) の逆のため、
  // PLUMB の射影 (gx=g_fay / gy=-g_fax) に対し符号を反転した割当にする。
  //   画面水平 ← -本体Y(g_angY) / 画面垂直 ← +本体X(g_angX)。
  float pH = -g_angY;   // 画面水平方向の傾き [deg]
  float pV =  g_angX;   // 画面垂直方向の傾き [deg]
  float nx = pH / BUBBLE_FS_DEG; if (nx > 1) nx = 1; if (nx < -1) nx = -1;
  float ny = pV / BUBBLE_FS_DEG; if (ny > 1) ny = 1; if (ny < -1) ny = -1;
  const int bR = 18;
  int bx = cx + (int)(nx * (R - bR));
  int by = cy + (int)(ny * (R - bR));
  g_canvas.fillCircle(bx, by, bR, level ? COL_OK : COL_ACCENT);
  g_canvas.drawCircle(bx, by, bR, COL_VALUE);

  // 数値は画面軸に合わせて表示 (X=画面水平 / Y=画面垂直)。
  char buf[16];
  int ty = cy + R + 14;
  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_LABEL, COL_BG); g_canvas.setCursor(18, ty); g_canvas.print("X");
  g_canvas.setTextColor(COL_VALUE, COL_BG); snprintf(buf, sizeof(buf), "%+.1f", pH);
  g_canvas.setCursor(38, ty); g_canvas.print(buf);
  g_canvas.setTextColor(COL_LABEL, COL_BG); g_canvas.setCursor(W / 2 + 8, ty); g_canvas.print("Y");
  g_canvas.setTextColor(COL_VALUE, COL_BG); snprintf(buf, sizeof(buf), "%+.1f", pV);
  g_canvas.setCursor(W / 2 + 28, ty); g_canvas.print(buf);
  if (level) {
    g_canvas.setTextColor(COL_OK, COL_BG);
    g_canvas.setCursor(cx - 30, ty + 24); g_canvas.print("LEVEL");
  }
  drawRelFlag();
}

// PLUMB ページ: 手前側面を下とする縦置きの「下げ振り分銅」(縦 240×320 用)。
static void drawPlumb() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  g_canvas.fillScreen(COL_BG);

  const int cx = W / 2;
  const int topY = 60;                             // 固定点 (糸の支点) の y
  g_canvas.drawFastHLine(0, topY, W, COL_VALUE);   // 上部水平線 (白 1px・y=60)
  g_canvas.drawFastVLine(cx, 0, H, COL_VALUE);     // 左右中央の垂直線 (白 1px)

  // 重力を canvas 平面へ射影し、その方向 (=真の鉛直) へ糸を垂らす (rotation=0 対応)。
  // 画面水平成分 ← 本体Y(g_fay) / 画面垂直成分(下+) ← -本体X(g_fax)。
  // ⚠️ 縦持ちで分銅が下へ垂れず横/上へ向く場合は gx/gy の符号を調整する。
  const int L = 110;                  // 糸長 (< cx=120 で端に触れず自由円弧)
  float gx = g_fay;                   // 画面水平方向の重力成分 [G]
  float gy = -g_fax;                  // 画面垂直方向の重力成分 [G]
  int bx = cx + (int)(L * gx);
  int by = topY + (int)(L * gy);
  if (by < topY) by = topY;           // 上下逆さ時に固定点より上へ出ないよう抑える
  if (bx < 6) bx = 6; if (bx > W - 6) bx = W - 6;
  g_canvas.drawLine(cx, topY, bx, by, COL_E1);     // 糸 (赤 1px)
  g_canvas.fillCircle(bx, by, 6, COL_E1);          // 分銅 (直径 約12px)

  float ang = atan2f(gx, gy) * R2D;   // 鉛直からの左右ズレ角
  char buf[24];
  snprintf(buf, sizeof(buf), "PLUMB %+.1f", ang);
  g_canvas.setTextSize(2);
  g_canvas.setTextColor(fabsf(ang) <= LEVEL_TOL_DEG ? COL_OK : COL_ACCENT, COL_BG);
  g_canvas.setCursor(4, H - 28);
  g_canvas.print(buf);
}

// 残り時間の右上に小さくバッテリー残量を描く (TIMER ページ用)。
static void drawTimerBattery() {
  int pct = M5.Power.getBatteryLevel();
  bool chg = M5.Power.isCharging() == 1;
  char buf[8];
  if (pct >= 0) snprintf(buf, sizeof(buf), "%d%%", pct);
  else          snprintf(buf, sizeof(buf), "--%%");
  uint16_t col = chg ? COL_OK : (pct >= 0 && pct < 20 ? COL_WARN : COL_LABEL);
  g_canvas.setTextDatum(textdatum_t::top_right);
  g_canvas.setTextColor(col, COL_BG);
  g_canvas.setTextSize(1);
  g_canvas.drawString(buf, g_canvas.width() - 4, 4);
  g_canvas.setTextDatum(textdatum_t::top_left);  // 既定に戻す
}

// TIMER ページ: プリセット選択 (SETUP) / カウントダウン (RUNNING/PAUSED/DONE)。
// 縦向き 240×320。ドーナツを中央に置き、内側に残り/経過時刻を重ねる。
static void drawTimer() {
  const int W = g_canvas.width();    // 240
  const int H = g_canvas.height();   // 320
  g_canvas.fillScreen(COL_BG);

  const int cx = W / 2;
  bool blink = ((millis() / 500) & 1) != 0;   // 0.5s 周期の点滅位相
  char buf[16], line[24];

  // ---- SETUP: プリセット選択 ----
  if (g_tm_state == TM_SETUP) {
    g_canvas.setTextDatum(textdatum_t::top_center);
    g_canvas.setTextColor(COL_ACCENT, COL_BG);
    g_canvas.setTextSize(2);
    g_canvas.drawString("SET TIME", cx, 20);

    snprintf(buf, sizeof(buf), "%d", PRESET_MIN[g_tm_preset]);
    g_canvas.setTextDatum(textdatum_t::middle_center);
    g_canvas.setTextColor(COL_VALUE, COL_BG);
    g_canvas.setTextSize(8);
    g_canvas.drawString(buf, cx, H / 2 - 10);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setTextSize(2);
    g_canvas.drawString("MIN", cx, H / 2 + 48);

    // 上下送りインジケータ。
    g_canvas.setTextColor(g_tm_preset < PRESET_COUNT - 1 ? COL_ACCENT : COL_DIM, COL_BG);
    g_canvas.setTextSize(3);
    g_canvas.drawString("^", cx, 70);
    g_canvas.setTextColor(g_tm_preset > 0 ? COL_ACCENT : COL_DIM, COL_BG);
    g_canvas.drawString("v", cx, H - 78);

    // プリセット位置ドット。
    const int gap = 16;
    int x0 = (W - PRESET_COUNT * gap) / 2 + gap / 2;
    for (int i = 0; i < PRESET_COUNT; i++) {
      int px = x0 + i * gap;
      if (i == g_tm_preset) g_canvas.fillCircle(px, H - 44, 3, COL_ACCENT);
      else                  g_canvas.drawCircle(px, H - 44, 3, COL_DIM);
    }

    g_canvas.setTextDatum(textdatum_t::bottom_center);
    g_canvas.setTextColor(COL_LABEL, COL_BG);
    g_canvas.setTextSize(1);
    g_canvas.drawString("swipe up/down  /  tap: start", cx, H - 24);
    drawTimerBattery();
    return;
  }

  // ---- RUNNING / PAUSED / DONE: ドーナツ + 時刻 ----
  const int cy   = H / 2 - 6;
  const int rOut = 108;
  const int rIn  = 82;

  long remMs = tmRemainingMs();
  bool over  = (remMs < 0);
  float frac = (g_tm_total_ms > 0) ? (float)remMs / (float)g_tm_total_ms : 0.0f;
  if (frac < 0) frac = 0; if (frac > 1) frac = 1;

  // 残り割合 → 色。
  uint16_t arcCol = (frac <= 0.10f) ? COL_RED : (frac <= 0.25f) ? COL_WARN : COL_OK;
  bool urgent = (g_tm_state == TM_RUNNING && remMs > 0 && remMs <= 10000);  // 残り10秒
  bool hideArc = over || (urgent && blink);

  // 経過部の溝 (全周) → 残り弧 (12時=270°から時計回り)。
  g_canvas.fillArc(cx, cy, rIn, rOut, 0, 360, COL_TRACK);
  if (frac > 0.0f && !hideArc) {
    float sweep = frac * 360.0f; if (sweep > 359.9f) sweep = 359.9f;
    g_canvas.fillArc(cx, cy, rIn, rOut, 270.0f, 270.0f + sweep, arcCol);
  }

  // 上部ステータス行。
  g_canvas.setTextDatum(textdatum_t::top_center);
  g_canvas.setTextSize(2);
  if (g_tm_state == TM_DONE) {
    g_canvas.setTextColor(blink ? COL_RED : COL_LABEL, COL_BG);
    g_canvas.drawString("TIME UP", cx, 12);
  } else if (g_tm_state == TM_PAUSED) {
    snprintf(line, sizeof(line), "%d MIN  PAUSED", PRESET_MIN[g_tm_preset]);
    g_canvas.setTextColor(blink ? COL_WARN : COL_LABEL, COL_BG);
    g_canvas.drawString(line, cx, 12);
  } else {
    snprintf(line, sizeof(line), "%d MIN", PRESET_MIN[g_tm_preset]);
    g_canvas.setTextColor(COL_ACCENT, COL_BG);
    g_canvas.drawString(line, cx, 12);
  }

  // 中央: 残り時間 (超過時は +MM:SS を赤)。桁数に応じてサイズを落とす (内径に収める)。
  long remSec = (over ? -remMs : remMs) / 1000;
  tmFmt(remSec, buf, sizeof(buf));
  g_canvas.setTextDatum(textdatum_t::middle_center);
  if (over) {
    snprintf(line, sizeof(line), "+%s", buf);
    g_canvas.setTextColor(COL_RED, COL_BG);
    g_canvas.setTextSize(strlen(line) > 6 ? 3 : 4);
    g_canvas.drawString(line, cx, cy - 8);
  } else {
    g_canvas.setTextColor(COL_VALUE, COL_BG);
    g_canvas.setTextSize(strlen(buf) > 5 ? 3 : 4);  // H:MM:SS は size3
    g_canvas.drawString(buf, cx, cy - 8);
  }

  // 中央下: 経過時間 (小)。
  long elSec = tmElapsedMs() / 1000;
  tmFmt(elSec, buf, sizeof(buf));
  snprintf(line, sizeof(line), "elapsed %s", buf);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(1);
  g_canvas.drawString(line, cx, cy + 26);

  // 操作ヒント。
  g_canvas.setTextDatum(textdatum_t::bottom_center);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(1);
  const char *hint = (g_tm_state == TM_DONE)   ? "tap: back to setup"
                   : (g_tm_state == TM_PAUSED) ? "tap: resume / swipe: reset"
                                               : "tap: pause / swipe: reset";
  g_canvas.drawString(hint, cx, H - 24);
  drawTimerBattery();
}

// 現在ページを描画 → ページドット → 一括転送。
static void drawCurrentPage() {
  switch (g_page) {
    case PAGE_INFO:  drawInfo();  break;
    case PAGE_SYS:   drawSys();   break;
    case PAGE_LEVEL: drawLevel(); break;
    case PAGE_PLUMB: drawPlumb(); break;
    case PAGE_TIMER: drawTimer(); break;
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
  // フリック確定 or 指離し時に、始点からの移動量で判定。
  if (d.wasFlicked() || d.wasReleased()) {
    int dx = d.distanceX();
    int dy = d.distanceY();
    if (dx <= -SWIPE_THRESHOLD && abs(dx) > abs(dy)) {        // 左へスワイプ → 次ページ
      g_page = (g_page + 1) % PAGE_COUNT;
      g_redraw = true;
    } else if (dx >= SWIPE_THRESHOLD && abs(dx) > abs(dy)) {  // 右へスワイプ → 前ページ
      g_page = (g_page + PAGE_COUNT - 1) % PAGE_COUNT;
      g_redraw = true;
    } else if (g_page == PAGE_TIMER) {
      // TIMER ページ: 左右はページ送り(上で処理済)、上下スワイプ=プリセット/リセット、タップ=開始/停止。
      bool tap    = (abs(dx) < 16 && abs(dy) < 16);
      bool vSwipe = (abs(dy) >= SWIPE_THRESHOLD && abs(dy) > abs(dx));
      switch (g_tm_state) {
        case TM_SETUP:
          if (vSwipe) {
            if (dy < 0 && g_tm_preset < PRESET_COUNT - 1) g_tm_preset++;  // 上=長く
            else if (dy > 0 && g_tm_preset > 0)           g_tm_preset--;  // 下=短く
            tmSavePreset(); g_redraw = true;
          } else if (tap) { tmStart(); g_redraw = true; }
          break;
        case TM_RUNNING:
          if (vSwipe)     { tmReset();  g_redraw = true; }
          else if (tap)   { tmPause();  g_redraw = true; }
          break;
        case TM_PAUSED:
          if (vSwipe)     { tmReset();  g_redraw = true; }
          else if (tap)   { tmResume(); g_redraw = true; }
          break;
        case TM_DONE:
          if (tap || vSwipe) { tmReset(); g_redraw = true; }
          break;
      }
    } else if (abs(dx) < 16 && abs(dy) < 16 && g_page == PAGE_LEVEL) {
      // タップ: 水準器ページのみゼロ点をトグル (相対測定)。下げ振りは絶対鉛直のため対象外。
      if (g_relative) g_relative = false;
      else { captureZero(); g_relative = true; }
      g_redraw = true;
    } else if (abs(dx) < 16 && abs(dy) < 16 && g_page == PAGE_METER) {
      // タップ: INA226 ユニット種別チップ (右上) を押したら 1A/10A をトグルし NVS 保存。
      const int pad = 16;   // チップ周囲に余裕を持たせ押しやすくする
      if (d.x >= g_unit_btn_x - pad && d.x <= g_unit_btn_x + g_unit_btn_w + pad &&
          d.y >= g_unit_btn_y - pad && d.y <= g_unit_btn_y + g_unit_btn_h + pad) {
        g_ina_unit = (g_ina_unit + 1) % INA226_UNIT_COUNT;
        g_prefs.putInt("ina_unit", g_ina_unit);
        // シャント値が異なるため CAL レジスタも書き直す (LSB だけの切替では不足)。
        writeWord16(INA226_ADDR, INA_REG_CAL, INA226_UNITS[g_ina_unit].cal);
        Serial.printf("{\"log\":\"ina226_unit\",\"unit\":\"%s\",\"cal\":%u}\n",
                      INA226_UNITS[g_ina_unit].name, INA226_UNITS[g_ina_unit].cal);
        g_redraw = true;
      }
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

// ネットワークタスク (core 0 常駐)。Wi-Fi 接続・NTP・天気取得をここで行い、
// メインループ (core 1: 表示・センサ・JSON) をブロックしない。wifiMulti.run() や
// HTTPS は数秒ブロックするが core 0 内に閉じるためダッシュボードは滑らかなまま。
static void netTask(void *) {
  bool radio_was_off = false;   // 直近に Wi-Fi を落とした状態か (エッジ検出)
  for (;;) {
    // TIMER ページ表示中は Wi-Fi を落として省電力化。ページを戻すと再接続する。
    if (g_radio_off) {
      if (!radio_was_off) {
        WiFi.disconnect(true, false);   // 切断 + STA 停止
        WiFi.mode(WIFI_OFF);
        g_ntp_started = false;
        g_wifi_state  = WIFI_OFF_STATE;
        radio_was_off = true;
        Serial.println("{\"log\":\"radio\",\"iface\":\"wifi\",\"state\":\"off\"}");
      }
      vTaskDelay(pdMS_TO_TICKS(300));
      continue;
    }
    if (radio_was_off) {                 // TIMER ページを離れた → STA 再開
      radio_was_off = false;
      if (g_wifi_configured) WiFi.mode(WIFI_STA);
      Serial.println("{\"log\":\"radio\",\"iface\":\"wifi\",\"state\":\"on\"}");
    }

    if (!g_wifi_configured) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }

    const int prev_state = g_wifi_state;
    if (WiFi.status() == WL_CONNECTED) {
      if (!g_ntp_started) {
        configTzTime("JST-9", "ntp.nict.jp", "pool.ntp.org");  // JST (UTC+9)
        g_ntp_started = true;
      }
      if (g_wifi_state < WIFI_CONNECTED_NO_NTP) g_wifi_state = WIFI_CONNECTED_NO_NTP;
      struct tm t;
      if (getLocalTime(&t, 0) && (t.tm_year + 1900) >= 2020) g_wifi_state = WIFI_NTP_OK;
      logWifiTransition(prev_state, g_wifi_state);

      // 天気: NTP 同期後、初回 + 30 分毎に取得 (HTTPS は数秒ブロック・core 0 内)。
      if (g_wifi_state == WIFI_NTP_OK &&
          (g_wx_last_ms == 0 || millis() - g_wx_last_ms >= WX_INTERVAL_MS)) {
        g_wx_last_ms = millis();
        fetchWeather();
        g_redraw = true;
      }
      vTaskDelay(pdMS_TO_TICKS(500));
    } else {
      g_ntp_started = false;
      if (g_wifi_state != WIFI_CONNECTING) {
        g_wifi_state = WIFI_CONNECTING;
        logWifiTransition(prev_state, g_wifi_state);
      }
      wifiMulti.run(8000);  // スキャン + 接続 (ブロックするが core 0 内に閉じる)
      vTaskDelay(pdMS_TO_TICKS(500));
    }
  }
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
  Serial.printf("{\"log\":\"imu_init\",\"type\":%d}\n", (int)M5.Imu.getType());  // BMI270 確認

  // 地磁気 (BMM150) プローブ。CoreS3 の BMM150 は BMI270 の補助 I2C 配下のため
  // メインバスの i2cdetect には出ないが、M5Unified の getMag() 経由なら取得できる想定。
  // App16 星座盤の方位アライン用に、使えるかどうかをここで一度確定してログ出力する。
  {
    float mx = NAN, my = NAN, mz = NAN;
    M5.update();
    bool ok = M5.Imu.getMag(&mx, &my, &mz);
    // 全ゼロや NaN は「実データなし」とみなす (未初期化時に 0 が返ることがある)。
    bool has_data = ok && (isfinite(mx) && isfinite(my) && isfinite(mz)) &&
                    (mx != 0.0f || my != 0.0f || mz != 0.0f);
    g_mag_available = has_data;
    Serial.printf("{\"log\":\"mag_probe\",\"getmag_ok\":%d,\"has_data\":%d,"
                  "\"mx\":%.2f,\"my\":%.2f,\"mz\":%.2f}\n",
                  ok ? 1 : 0, has_data ? 1 : 0, mx, my, mz);
  }

  // 初期値
  g_r = { NAN, NAN, NAN, NAN, NAN, -1, -1, NAN };

  // INA226 ユニット種別を NVS から復元 (無ければ既定=1A番)。以降タッチで切替可能。
  g_prefs.begin("cores3", false);
  g_ina_unit = g_prefs.getInt("ina_unit", INA226_UNIT_DEFAULT);
  if (g_ina_unit < 0 || g_ina_unit >= INA226_UNIT_COUNT) g_ina_unit = INA226_UNIT_DEFAULT;

  // タイマーの最終プリセットを NVS から復元 (範囲外なら既定=90 分)。
  g_tm_preset = g_prefs.getInt("tm_preset", PRESET_DEFAULT);
  if (g_tm_preset < 0 || g_tm_preset >= PRESET_COUNT) g_tm_preset = PRESET_DEFAULT;

  delay(300);
  Wire.begin(PORT_A_SDA, PORT_A_SCL, 100000);  // 実機確定: SDA=G2 / SCL=G1
  ina226Init();  // Config + Calibration 書込み (電流/電力読取の前提)

  // Wi-Fi: secrets.h の AP 群を WiFiMulti に登録 (1 件でもあれば有効)。
  int aps = wifiRegisterAPs();
  g_wifi_configured = (aps > 0);
  if (g_wifi_configured) WiFi.mode(WIFI_STA);
  Serial.printf("{\"log\":\"wifi_cfg\",\"ap_count\":%d}\n", aps);

  // ネットワーク処理は core 0 のバックグラウンドタスクへ (メインループを止めない)。
  // HTTPS/TLS でスタックを使うため余裕を持って 20KB 確保。
  xTaskCreatePinnedToCore(netTask, "net", 20480, nullptr, 1, nullptr, 0);
}

// TIMER ページの出入りに合わせて I2C を停止/再開する (Wi-Fi は netTask が g_radio_off で切替)。
// TIMER 表示中は INA226/MLX などの I2C を止め、他ページへ戻すとバスを再初期化する。
static void updateRadioForPage() {
  bool want_off = (g_page == PAGE_TIMER);
  if (want_off == g_radio_off) return;   // 状態変化なし
  g_radio_off = want_off;                // netTask (Wi-Fi 側) もこのフラグを見る
  if (want_off) {
    Wire.end();                          // I2C バス解放 (Port A センサ停止)
    Serial.println("{\"log\":\"radio\",\"iface\":\"i2c\",\"state\":\"off\"}");
  } else {
    Wire.begin(PORT_A_SDA, PORT_A_SCL, 100000);
    ina226Init();                        // Config + 現ユニットの CAL を再書込み
    g_last_scan_ms = 0;                  // 復帰直後に配線再列挙を促す
    Serial.println("{\"log\":\"radio\",\"iface\":\"i2c\",\"state\":\"on\"}");
  }
}

void loop() {
  M5.update();

  const uint32_t now = millis();

  // タッチ (左右スワイプでページ送り) を毎ループ処理し応答性を確保。
  // Wi-Fi 接続・NTP・天気取得は netTask (core 0) が担当しメインループを止めない。
  handleTouch();

  // TIMER ページ表示中は Wi-Fi/I2C を停止、他ページへ戻すと再接続 (省電力)。
  updateRadioForPage();

  // TIMER: RUNNING で残り 0 到達 → DONE (超過カウントへ)。
  if (g_page == PAGE_TIMER && g_tm_state == TM_RUNNING && tmRemainingMs() <= 0) {
    g_tm_state = TM_DONE;
  }

  // IMU 角度を毎ループ更新。水準器/下げ振りページは毎ループ描画で滑らかに動かす。
  updateAngles();
  if (g_redraw) {           // ページ切替・天気更新時は即時再描画してキビキビ動かす。
    g_redraw = false;
    drawCurrentPage();
  } else if (g_page == PAGE_LEVEL || g_page == PAGE_PLUMB || g_page == PAGE_TIMER) {
    drawCurrentPage();      // TIMER は秒送り/点滅のため毎ループ描画
  }

  // TIMER ページ中は I2C スキャン・センサ読取・JSON 送信を停止 (省電力)。表示は上で完了済み。
  if (g_radio_off) return;

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
  if (readWord16(INA226_ADDR, INA_REG_CURRENT, raw)) g_r.ina_i = int16_t(raw) * INA226_UNITS[g_ina_unit].current_lsb;  // 符号付き
  if (readWord16(INA226_ADDR, INA_REG_POWER, raw))   g_r.ina_p = raw * INA226_UNITS[g_ina_unit].power_lsb;   // 符号なし

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

  // ---- 地磁気 (BMM150) ---- App16 星座盤の方位アライン用に CardputerZero へ流す。
  g_r.mx = g_r.my = g_r.mz = NAN;
  g_r.mag_ok = 0;
  if (g_mag_available) {
    float mx, my, mz;
    if (M5.Imu.getMag(&mx, &my, &mz)) {
      g_r.mx = mx; g_r.my = my; g_r.mz = mz; g_r.mag_ok = 1;
    }
  }
  // 水平面の簡易方位 (deg)。傾き補正なし・要キャリブレーション。受信側で使う目安。
  // 軸割当と符号は実機で要確認 (BMM150 の実装向きに依存)。
  float heading = NAN;
  if (g_r.mag_ok) {
    heading = atan2f(g_r.my, g_r.mx) * 57.29578f;
    if (heading < 0) heading += 360.0f;
  }

  // ---- JSON 1 行送信 ----
  char buf[680];
  snprintf(buf, sizeof(buf),
           "{\"bat\":{\"pct\":%d,\"chg\":%d,\"v\":%.2f},"
           "\"ina\":{\"v\":%.3f,\"i\":%.4f,\"p\":%.4f},"
           "\"ncir\":{\"t_obj\":%.2f,\"t_amb\":%.2f},"
           "\"mag\":{\"ok\":%d,\"x\":%.2f,\"y\":%.2f,\"z\":%.2f,\"heading\":%.1f},"
           "\"enc\":%s}",
           g_r.bat_pct, g_r.bat_chg, g_r.bat_v,
           g_r.ina_v, g_r.ina_i, g_r.ina_p, g_r.t_obj, g_r.t_amb,
           g_r.mag_ok, g_r.mx, g_r.my, g_r.mz, heading, encbuf);
  Serial.println(buf);

  // ---- 液晶 (現在ページを描画) ----
  drawCurrentPage();
}
