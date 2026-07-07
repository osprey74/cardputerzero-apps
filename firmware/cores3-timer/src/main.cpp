// CoreS3 セミナー・カウントダウンタイマー (M5Stack CoreS3 / ESP32-S3) ― 単体アプリ
//
// プリセット時間 (90/120 分など) を選んで開始すると、円グラフ (ドーナツ) が
// 12 時位置から時計回りに減少していく。中央に「残り時間」を大きく、その下に
// 「経過時間」を小さく併記する。0 到達後は赤点滅で TIME UP を表示し、超過時間を
// +MM:SS でカウントアップする (セミナーの延長把握用)。
//
//   画面遷移:
//     [SETUP  ] 左右スワイプでプリセット選択、タップで開始。
//     [RUNNING] タップ=一時停止 / 下スワイプ=リセット (SETUP へ)。
//     [PAUSED ] タップ=再開 / 下スワイプ=リセット。
//     [DONE   ] 超過カウント中。タップまたは下スワイプで SETUP へ戻る。
//
//   ちらつき防止に M5Canvas (PSRAM オフスクリーン) へ描画し一括転送する。
//   最後に選んだプリセットは NVS (Preferences) に保存し、次回起動時に復元する。

#include <M5Unified.h>
#include <Preferences.h>
#include <math.h>

#define FW_VERSION "0.1.0"

// ---- 表示の向き ------------------------------------------------------------
// 横向き (320×240)。ドーナツを中央に置き、内側に時刻を重ねるレイアウト。
static constexpr uint8_t DISPLAY_ROTATION = 1;

// ---- カラーテーマ (osprey74: ダーク基調 + シアン/グリーンのアクセント) -------
static constexpr uint16_t COL_BG      = 0x0000;  // 黒
static constexpr uint16_t COL_LABEL   = 0x8410;  // グレー
static constexpr uint16_t COL_VALUE   = 0xFFFF;  // 白
static constexpr uint16_t COL_ACCENT  = 0x07FF;  // シアン
static constexpr uint16_t COL_OK      = 0x07E0;  // グリーン (残り十分)
static constexpr uint16_t COL_WARN    = 0xFD20;  // オレンジ (残りわずか)
static constexpr uint16_t COL_RED     = 0xF800;  // 赤 (残り僅少・超過)
static constexpr uint16_t COL_TRACK   = 0x2104;  // ドーナツの経過部 (暗い溝)
static constexpr uint16_t COL_DIM     = 0x4208;  // 罫線・目盛

// ---- プリセット (分) -------------------------------------------------------
// セミナー標準の 90/120 分を中心に、休憩・LT 用の短時間も用意する。
static const int PRESET_MIN[] = {5, 15, 30, 45, 60, 90, 120};
static constexpr int PRESET_COUNT = sizeof(PRESET_MIN) / sizeof(PRESET_MIN[0]);
static constexpr int PRESET_DEFAULT = 5;  // = 90 分 (インデックス)

// ---- 状態機械 --------------------------------------------------------------
enum State { ST_SETUP = 0, ST_RUNNING, ST_PAUSED, ST_DONE };
static State g_state = ST_SETUP;
static int   g_preset = PRESET_DEFAULT;  // 選択中プリセットのインデックス

static uint32_t g_total_ms   = 0;  // 設定総時間 [ms]
static uint32_t g_start_ms   = 0;  // 計測開始時刻 (millis)
static uint32_t g_paused_at  = 0;  // 一時停止に入った時刻 (millis)
static uint32_t g_paused_acc = 0;  // 累積の一時停止時間 [ms]

// ---- タッチ判定パラメータ --------------------------------------------------
static constexpr int SWIPE_THRESHOLD = 50;  // スワイプと判定する移動量 [px]
static constexpr int TAP_MAX_MOVE    = 16;  // タップと判定する最大移動量 [px]

// ---- 描画バッファ / 永続化 -------------------------------------------------
static M5Canvas   g_canvas(&M5.Display);
static Preferences g_prefs;
static uint32_t   g_last_draw_ms = 0;

// ---------------------------------------------------------------------------
// 時刻ユーティリティ
// ---------------------------------------------------------------------------

// 経過時間 [ms] を返す (一時停止分を除外)。RUNNING/PAUSED/DONE で有効。
static uint32_t elapsedMs() {
  uint32_t base = g_start_ms + g_paused_acc;
  uint32_t now  = (g_state == ST_PAUSED) ? g_paused_at : millis();
  return (now >= base) ? (now - base) : 0;
}

// 秒数を "MM:SS" または 1 時間以上なら "H:MM:SS" に整形する。
static void fmtTime(long sec, char *buf, size_t n) {
  if (sec < 0) sec = 0;
  long h = sec / 3600, m = (sec % 3600) / 60, s = sec % 60;
  if (h > 0) snprintf(buf, n, "%ld:%02ld:%02ld", h, m, s);
  else       snprintf(buf, n, "%02ld:%02ld", m, s);
}

// 現在の残り時間 [ms] (符号付き: 負なら超過)。
static long remainingMs() {
  return (long)g_total_ms - (long)elapsedMs();
}

// ---------------------------------------------------------------------------
// 状態遷移
// ---------------------------------------------------------------------------

static void startTimer() {
  g_total_ms   = (uint32_t)PRESET_MIN[g_preset] * 60u * 1000u;
  g_start_ms   = millis();
  g_paused_acc = 0;
  g_state      = ST_RUNNING;
}

static void pauseTimer() {
  g_paused_at = millis();
  g_state     = ST_PAUSED;
}

static void resumeTimer() {
  g_paused_acc += (millis() - g_paused_at);  // 停止していた分を差し引く
  g_state       = ST_RUNNING;
}

static void resetToSetup() {
  g_state = ST_SETUP;
}

// 選択プリセットを NVS に保存する。
static void savePreset() {
  g_prefs.putInt("preset", g_preset);
}

// ---------------------------------------------------------------------------
// 描画
// ---------------------------------------------------------------------------

// 右上に小さくバッテリー残量 (%) を描く。
static void drawBatteryCorner() {
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
}

// 残り割合に応じた色を返す (超過は赤)。
static uint16_t phaseColor(float frac) {
  if (frac <= 0.0f)  return COL_RED;
  if (frac <= 0.10f) return COL_RED;
  if (frac <= 0.25f) return COL_WARN;
  return COL_OK;
}

// 円周に 12 個の目盛 (時計の時位置) を短い線で描く。
static void drawTicks(int cx, int cy, int rOut) {
  for (int i = 0; i < 12; i++) {
    float th = (i * 30 - 90) * 0.017453293f;  // 12 時を上に、時計回り
    float c = cosf(th), s = sinf(th);
    int x1 = cx + (int)((rOut + 3) * c);
    int y1 = cy + (int)((rOut + 3) * s);
    int x2 = cx + (int)((rOut + 8) * c);
    int y2 = cy + (int)((rOut + 8) * s);
    g_canvas.drawLine(x1, y1, x2, y2, COL_DIM);
  }
}

// ドーナツ円グラフ + 中央の残り/経過時刻を描く (RUNNING/PAUSED/DONE 共通)。
//   frac  : 残り割合 [0..1] (0 で空・超過)
//   col   : 残り弧の色
//   flash : true のとき残り弧を点滅で消す (DONE/僅少時)
static void drawDial(float frac, uint16_t col, bool flash) {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  const int cx = W / 2;
  const int cy = H / 2 + 6;   // 上部ステータス行のぶん少し下げる
  const int rOut = 92;
  const int rIn  = 70;        // ドーナツ内径 (中央に時刻を重ねる)

  // 経過部の溝 (暗いリング) を全周に敷く。
  g_canvas.fillArc(cx, cy, rIn, rOut, 0, 360, COL_TRACK);

  // 残り弧: 12 時 (このライブラリでは 270°) から時計回りに frac*360 度。
  if (frac > 0.0f && !flash) {
    float sweep = frac * 360.0f;
    if (sweep > 359.9f) sweep = 359.9f;  // 完全一周は 360 弱にして境界を残す
    g_canvas.fillArc(cx, cy, rIn, rOut, 270.0f, 270.0f + sweep, col);
  }

  drawTicks(cx, cy, rOut);

  // ---- 中央: 残り時間 (大) ----
  long remMs = remainingMs();
  char buf[16];
  bool over = (remMs < 0);
  long remSec = (over ? -remMs : remMs) / 1000;

  g_canvas.setTextDatum(textdatum_t::middle_center);
  // 残り (超過時は +MM:SS を赤で)。
  if (over) {
    fmtTime(remSec, buf, sizeof(buf));
    char ob[20];
    snprintf(ob, sizeof(ob), "+%s", buf);
    g_canvas.setTextColor(COL_RED, COL_BG);
    g_canvas.setTextSize(4);
    g_canvas.drawString(ob, cx, cy - 8);
  } else {
    fmtTime(remSec, buf, sizeof(buf));
    g_canvas.setTextColor(COL_VALUE, COL_BG);
    g_canvas.setTextSize(4);
    g_canvas.drawString(buf, cx, cy - 8);
  }

  // ---- 中央下: 経過時間 (小) ----
  long elSec = elapsedMs() / 1000;
  fmtTime(elSec, buf, sizeof(buf));
  char eb[24];
  snprintf(eb, sizeof(eb), "elapsed %s", buf);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(1);
  g_canvas.drawString(eb, cx, cy + 24);
}

// 上部ステータス行 (プリセット名 + 状態)。
static void drawStatusLine(const char *label, uint16_t col) {
  g_canvas.setTextDatum(textdatum_t::top_center);
  g_canvas.setTextColor(col, COL_BG);
  g_canvas.setTextSize(2);
  g_canvas.drawString(label, g_canvas.width() / 2, 6);
}

// SETUP 画面: プリセット選択。
static void drawSetup() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  g_canvas.fillScreen(COL_BG);

  g_canvas.setTextDatum(textdatum_t::top_center);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setTextSize(2);
  g_canvas.drawString("SELECT TIME", W / 2, 10);

  // 大きなプリセット値 + 単位。
  char buf[8];
  snprintf(buf, sizeof(buf), "%d", PRESET_MIN[g_preset]);
  g_canvas.setTextDatum(textdatum_t::middle_center);
  g_canvas.setTextColor(COL_VALUE, COL_BG);
  g_canvas.setTextSize(7);
  g_canvas.drawString(buf, W / 2, H / 2 - 8);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(2);
  g_canvas.drawString("MIN", W / 2, H / 2 + 44);

  // 左右の送りインジケータ (< >)。
  g_canvas.setTextDatum(textdatum_t::middle_center);
  g_canvas.setTextColor(g_preset > 0 ? COL_ACCENT : COL_DIM, COL_BG);
  g_canvas.setTextSize(3);
  g_canvas.drawString("<", 20, H / 2 - 4);
  g_canvas.setTextColor(g_preset < PRESET_COUNT - 1 ? COL_ACCENT : COL_DIM, COL_BG);
  g_canvas.drawString(">", W - 20, H / 2 - 4);

  // プリセット位置ドット。
  const int gap = 14;
  int x0 = (W - PRESET_COUNT * gap) / 2 + gap / 2;
  for (int i = 0; i < PRESET_COUNT; i++) {
    int px = x0 + i * gap;
    if (i == g_preset) g_canvas.fillCircle(px, H - 34, 3, COL_ACCENT);
    else               g_canvas.drawCircle(px, H - 34, 3, COL_DIM);
  }

  g_canvas.setTextDatum(textdatum_t::bottom_center);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(1);
  g_canvas.drawString("swipe to change  /  tap to start", W / 2, H - 8);
}

// RUNNING / PAUSED / DONE 画面。
static void drawTimer() {
  g_canvas.fillScreen(COL_BG);

  long remMs = remainingMs();
  float frac = (g_total_ms > 0) ? (float)remMs / (float)g_total_ms : 0.0f;
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;

  // 状態ごとの色と点滅。0.5 秒周期で点滅する位相。
  bool blink = ((millis() / 500) & 1) != 0;

  char label[24];
  if (g_state == ST_DONE) {
    drawStatusLine("TIME UP", blink ? COL_RED : COL_LABEL);
    drawDial(0.0f, COL_RED, true);           // 弧は空、超過を中央に赤で
  } else if (g_state == ST_PAUSED) {
    snprintf(label, sizeof(label), "%d MIN  PAUSED", PRESET_MIN[g_preset]);
    drawStatusLine(label, blink ? COL_WARN : COL_LABEL);  // PAUSED を点滅
    drawDial(frac, phaseColor(frac), false);
  } else {  // ST_RUNNING
    snprintf(label, sizeof(label), "%d MIN", PRESET_MIN[g_preset]);
    drawStatusLine(label, COL_ACCENT);
    // 残り 10 秒以内は残り弧も点滅させて注意喚起。
    bool urgent = (remMs > 0 && remMs <= 10000);
    drawDial(frac, phaseColor(frac), urgent && blink);
  }

  // 操作ヒント (下端)。
  g_canvas.setTextDatum(textdatum_t::bottom_center);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setTextSize(1);
  const char *hint = (g_state == ST_DONE)   ? "tap: back to menu"
                   : (g_state == ST_PAUSED) ? "tap: resume  /  swipe down: reset"
                                            : "tap: pause  /  swipe down: reset";
  g_canvas.drawString(hint, g_canvas.width() / 2, g_canvas.height() - 6);
}

// 現在状態を描画し一括転送する。
static void drawCurrent() {
  if (g_state == ST_SETUP) drawSetup();
  else                     drawTimer();
  drawBatteryCorner();
  g_canvas.pushSprite(0, 0);
}

// ---------------------------------------------------------------------------
// タッチ処理
// ---------------------------------------------------------------------------
static void handleTouch() {
  if (M5.Touch.getCount() == 0) return;
  auto d = M5.Touch.getDetail();
  if (!(d.wasFlicked() || d.wasReleased())) return;

  int dx = d.distanceX();
  int dy = d.distanceY();
  bool isTap   = (abs(dx) < TAP_MAX_MOVE && abs(dy) < TAP_MAX_MOVE);
  bool isHoriz = (abs(dx) >= SWIPE_THRESHOLD && abs(dx) > abs(dy));
  bool isDown  = (dy >= SWIPE_THRESHOLD && abs(dy) > abs(dx));

  switch (g_state) {
    case ST_SETUP:
      if (isHoriz) {
        if (dx < 0 && g_preset < PRESET_COUNT - 1) g_preset++;
        else if (dx > 0 && g_preset > 0)           g_preset--;
        savePreset();
      } else if (isTap) {
        startTimer();
      }
      break;

    case ST_RUNNING:
      if (isDown)     resetToSetup();
      else if (isTap) pauseTimer();
      break;

    case ST_PAUSED:
      if (isDown)     resetToSetup();
      else if (isTap) resumeTimer();
      break;

    case ST_DONE:
      if (isTap || isDown) resetToSetup();
      break;
  }
}

// ---------------------------------------------------------------------------

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.setRotation(DISPLAY_ROTATION);

  g_canvas.setColorDepth(16);
  g_canvas.setPsram(true);
  g_canvas.createSprite(M5.Display.width(), M5.Display.height());

  Serial.begin(115200);

  // NVS から前回のプリセットを復元 (範囲外なら既定)。
  g_prefs.begin("seminar", false);
  int p = g_prefs.getInt("preset", PRESET_DEFAULT);
  g_preset = (p >= 0 && p < PRESET_COUNT) ? p : PRESET_DEFAULT;

  Serial.printf("{\"log\":\"init\",\"fw\":\"%s\",\"preset\":%d}\n",
                FW_VERSION, PRESET_MIN[g_preset]);
}

void loop() {
  M5.update();
  handleTouch();

  // RUNNING で残り 0 到達 → DONE (超過カウントへ)。
  if (g_state == ST_RUNNING && remainingMs() <= 0) {
    g_state = ST_DONE;
  }

  // 約 10fps で再描画 (秒送り・点滅・弧の変化を滑らかに見せつつ省電力)。
  const uint32_t now = millis();
  if (now - g_last_draw_ms >= 100) {
    g_last_draw_ms = now;
    drawCurrent();
  }
}
