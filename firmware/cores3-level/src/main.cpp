// CoreS3 IMU 水準器・傾斜計 (M5Stack CoreS3 / ESP32-S3) ― 単体アプリ
//
// 内蔵 6 軸 IMU (BMI270・実機確定 2026-06-24) の加速度ベクトル (重力方向) から
// 傾き角を計算し、2 モードで表示する。CardputerZero とは独立した自己完結アプリ。
//
//   [BUBBLE] 円形の気泡水準器。机に水平置きし、傾きで気泡が中心からずれる。
//            X/Y とも許容範囲内なら気泡が緑になり "LEVEL" を表示。
//   [ANGLE ] 傾斜計。pitch / roll を大きく数値表示し、合成傾斜角と、
//            roll で回転する水平線 (簡易アティテュード) を描く。
//
//   操作: 画面タップ      = 現在の姿勢をゼロ点に設定 (相対測定 / 再タップで解除)
//         左右スワイプ    = モード切替 (BUBBLE ⇔ ANGLE)
//
//   ちらつき防止に M5Canvas (PSRAM オフスクリーン) へ描画し一括転送する。
//
// ⚠️ BMI270 の軸の向き・符号は基板実装に依存する。実機で液晶とシリアルログ
//    ({"log":"imu",...}) を見ながら ACC_SIGN_* / 軸の割当を確認すること。
//    傾けた向きと気泡/角度の動きが逆なら、対応する ACC_SIGN_* を -1 にする。

#include <M5Unified.h>
#include <math.h>

// ---- 表示の向き ------------------------------------------------------------
// 横向き (320×240)。気泡円を左に大きく、数値を右に置くレイアウト。
static constexpr uint8_t DISPLAY_ROTATION = 1;

// ---- 軸の割当と符号 (実機で要確認) -----------------------------------------
// M5.Imu.getAccel() が返す (ax, ay, az) を、画面の傾き計算に使う前に符号補正する。
// 水平置きで az≈+1.0G になり、右へ傾けると X 角が +、手前へ傾けると Y 角が + に
// なる向きを基準とする。逆に動く場合は該当する符号を -1 にする。
static constexpr float ACC_SIGN_X = +1.0f;
static constexpr float ACC_SIGN_Y = -1.0f;  // 実機確定(2026-06-30): 前後が逆だったため反転
static constexpr float ACC_SIGN_Z = +1.0f;

// EDGE モード (手前側面を下=水平面とする縦置き水準器) の平面 2 軸の符号。
// 基準「下」は前後軸 (|ay|)。A=左右 / B=画面法線方向。傾けた向きと気泡が逆なら -1 に。
static constexpr float EDGE_SIGN_A = +1.0f;  // 左右
static constexpr float EDGE_SIGN_B = +1.0f;  // 画面法線 (手前/奥への倒れ)

// ---- 角度パラメータ --------------------------------------------------------
static constexpr float R2D            = 57.29578f;  // rad → deg
static constexpr float ACCEL_ALPHA    = 0.20f;      // 加速度の指数移動平均係数 (小さいほど安定)
static constexpr float LEVEL_TOL_DEG  = 0.5f;       // この範囲内を「水平」と判定 [deg]
static constexpr float BUBBLE_FS_DEG  = 20.0f;      // 気泡が円の縁に達する傾き [deg] (フルスケール)

// ---- カラーテーマ (osprey74: ダーク基調 + シアン/グリーンのアクセント) -------
static constexpr uint16_t COL_BG     = 0x0000;  // 黒
static constexpr uint16_t COL_LABEL  = 0x8410;  // グレー
static constexpr uint16_t COL_VALUE  = 0xFFFF;  // 白
static constexpr uint16_t COL_ACCENT = 0x07FF;  // シアン
static constexpr uint16_t COL_OK     = 0x07E0;  // グリーン (水平・良好)
static constexpr uint16_t COL_WARN   = 0xFD20;  // オレンジ
static constexpr uint16_t COL_DIM    = 0x4208;  // 罫線
static constexpr uint16_t COL_REL    = 0xFFE0;  // 黄 (相対測定中インジケータ)
static constexpr uint16_t COL_RED    = 0xF800;  // 赤 (下げ振りの糸・分銅)

#define FW_VERSION "0.1.0"

// ---- モード (左右スワイプで切替) -------------------------------------------
enum Mode { MODE_BUBBLE = 0, MODE_ANGLE, MODE_EDGE, MODE_COUNT };
static int  g_mode   = MODE_BUBBLE;
static bool g_redraw = true;

static constexpr int SWIPE_THRESHOLD = 50;  // スワイプと判定する水平移動量 [px]
static constexpr int TAP_MAX_MOVE    = 16;  // タップと判定する最大移動量 [px]

// ---- 計測状態 --------------------------------------------------------------
static float g_fax = 0, g_fay = 0, g_faz = 1.0f;  // 平滑化済み加速度 (G)
static float g_angX = 0, g_angY = 0;              // 左右/前後 傾き [deg] (オフセット適用後)
static float g_tilt = 0;                          // 合成傾斜角 (鉛直からの角度) [deg]
static float g_edgeA = 0, g_edgeB = 0;            // EDGE モード 左右/画面法線 傾き [deg]

// 相対測定 (ゼロ点) 用オフセット。タップで現在角を控え、以後その差分を表示する。
static bool  g_relative = false;
static float g_offX = 0, g_offY = 0;              // FLAT/ANGLE 用
static float g_offA = 0, g_offB = 0;              // EDGE 用

// オフスクリーン描画用スプライト (ちらつき防止)。
static M5Canvas g_canvas(&M5.Display);

static uint32_t g_last_log_ms = 0;
static constexpr uint32_t LOG_INTERVAL_MS = 500;  // 軸検証ログ 2Hz

// ---------------------------------------------------------------------------
// IMU 読取 → 角度計算
// ---------------------------------------------------------------------------

// 内蔵 IMU から加速度を読み、平滑化して傾き角 (g_angX/g_angY/g_tilt) を更新する。
static void updateAngles() {
  float ax, ay, az;
  if (!M5.Imu.getAccel(&ax, &ay, &az)) return;  // 新データ無しなら前回値を維持

  ax *= ACC_SIGN_X;
  ay *= ACC_SIGN_Y;
  az *= ACC_SIGN_Z;

  // 指数移動平均でノイズを抑える。
  g_fax += ACCEL_ALPHA * (ax - g_fax);
  g_fay += ACCEL_ALPHA * (ay - g_fay);
  g_faz += ACCEL_ALPHA * (az - g_faz);

  // 各軸まわりの傾き (水平置きで 0)。気泡水準器はこの 2 軸で表す。
  float rawX = atan2f(g_fax, g_faz) * R2D;   // 左右の傾き
  float rawY = atan2f(g_fay, g_faz) * R2D;   // 前後の傾き

  // 相対測定: タップ時の姿勢を基準に差分を取る。
  g_angX = rawX - (g_relative ? g_offX : 0.0f);
  g_angY = rawY - (g_relative ? g_offY : 0.0f);

  // 合成傾斜角 = 重力ベクトルと Z 軸 (画面法線) のなす角。鉛直からの倒れ具合。
  float g_mag = sqrtf(g_fax * g_fax + g_fay * g_fay + g_faz * g_faz);
  if (g_mag > 0.01f) g_tilt = acosf(fabsf(g_faz) / g_mag) * R2D;

  // EDGE モード: 手前側面を下とみなす。前後軸 |ay| を「下」の基準にし、
  // 左右(ax)・画面法線(az) を平面 2 軸として傾きを取る (水平で 0)。
  float vdown = fabsf(g_fay);
  float rawA = atan2f(EDGE_SIGN_A * g_fax, vdown) * R2D;
  float rawB = atan2f(EDGE_SIGN_B * g_faz, vdown) * R2D;
  g_edgeA = rawA - (g_relative ? g_offA : 0.0f);
  g_edgeB = rawB - (g_relative ? g_offB : 0.0f);
}

// 現在の生角度をゼロ点として控える (相対測定の基準)。FLAT/ANGLE/EDGE 全モード分。
static void captureZero() {
  g_offX = atan2f(g_fax, g_faz) * R2D;
  g_offY = atan2f(g_fay, g_faz) * R2D;
  float vdown = fabsf(g_fay);
  g_offA = atan2f(EDGE_SIGN_A * g_fax, vdown) * R2D;
  g_offB = atan2f(EDGE_SIGN_B * g_faz, vdown) * R2D;
}

// ---------------------------------------------------------------------------
// 描画
// ---------------------------------------------------------------------------

// 右上に小さくバッテリー残量 (%) を描く。
static void drawBatteryCorner() {
  int pct = M5.Power.getBatteryLevel();   // 0-100 (-1 unknown)
  bool chg = M5.Power.isCharging() == 1;
  char buf[8];
  if (pct >= 0) snprintf(buf, sizeof(buf), "%d%%", pct);
  else          snprintf(buf, sizeof(buf), "--%%");
  uint16_t col = chg ? COL_OK : (pct >= 0 && pct < 20 ? COL_WARN : COL_LABEL);
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(col, COL_BG);
  g_canvas.setCursor(g_canvas.width() - (int)strlen(buf) * 6 - 4, 4);
  g_canvas.print(buf);
}

// 相対測定中インジケータ (左上の "REL")。
static void drawRelFlag() {
  if (!g_relative) return;
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(COL_REL, COL_BG);
  g_canvas.setCursor(4, 4);
  g_canvas.print("REL");
}

// 下部モードインジケータ (現在モードを塗り円・他は輪郭)。
static void drawModeDots() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  const int r = 3, gap = 12;
  int x0 = (W - MODE_COUNT * gap) / 2 + gap / 2;
  for (int i = 0; i < MODE_COUNT; i++) {
    int cx = x0 + i * gap;
    if (i == g_mode) g_canvas.fillCircle(cx, H - 7, r, COL_ACCENT);
    else             g_canvas.drawCircle(cx, H - 7, r, COL_DIM);
  }
}

// 円形気泡水準器の共通描画 (基準軸の違いは呼び出し側が angX/angY で渡す)。
// title は画面上部中央に表示し、どのモードか分かるようにする。
static void drawBubbleCore(float angX, float angY, const char *title) {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  g_canvas.fillScreen(COL_BG);

  const int R  = H / 2 - 20;     // 外周半径 (=100)
  const int cx = R + 8;          // 円を左に寄せ、右に数値パネル用の幅を確保
  const int cy = H / 2;

  // モードタイトル (上部中央)。
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setCursor(W / 2 - (int)strlen(title) * 3, 4);
  g_canvas.print(title);

  bool level = (fabsf(angX) <= LEVEL_TOL_DEG && fabsf(angY) <= LEVEL_TOL_DEG);
  uint16_t ringCol  = level ? COL_OK : COL_DIM;
  uint16_t crossCol = level ? COL_OK : COL_DIM;

  // 外周 + 中間リング + 中心許容円。
  g_canvas.drawCircle(cx, cy, R, ringCol);
  g_canvas.drawCircle(cx, cy, R / 2, COL_DIM);
  int tolR = (int)(LEVEL_TOL_DEG / BUBBLE_FS_DEG * (R - 18));
  if (tolR < 10) tolR = 10;
  g_canvas.drawCircle(cx, cy, tolR, COL_ACCENT);
  // 十字線。
  g_canvas.drawFastHLine(cx - R, cy, 2 * R, crossCol);
  g_canvas.drawFastVLine(cx, cy - R, 2 * R, crossCol);

  // 気泡位置: 傾き角をフルスケールで正規化し、円内にクランプ。
  float nx = angX / BUBBLE_FS_DEG;  if (nx > 1) nx = 1; if (nx < -1) nx = -1;
  float ny = angY / BUBBLE_FS_DEG;  if (ny > 1) ny = 1; if (ny < -1) ny = -1;
  const int bR = 18;
  int bx = cx + (int)(nx * (R - bR));
  int by = cy + (int)(ny * (R - bR));
  uint16_t bubCol = level ? COL_OK : COL_ACCENT;
  g_canvas.fillCircle(bx, by, bR, bubCol);
  g_canvas.drawCircle(bx, by, bR, COL_VALUE);

  // ---- 右パネル: X/Y 角度 + 状態 (ラベルの下に値を積む縦並び) ----
  // 開始 X は円の右端基準。値は size3 でも残り幅 (~100px) に収まる桁数。
  const int px = cx + R + 10;
  char buf[16];

  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setCursor(px, 30); g_canvas.print("X");
  g_canvas.setTextSize(3);
  g_canvas.setTextColor(COL_VALUE, COL_BG);
  snprintf(buf, sizeof(buf), "%+.1f", angX);
  g_canvas.setCursor(px, 48); g_canvas.print(buf);

  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setCursor(px, 92); g_canvas.print("Y");
  g_canvas.setTextSize(3);
  g_canvas.setTextColor(COL_VALUE, COL_BG);
  snprintf(buf, sizeof(buf), "%+.1f", angY);
  g_canvas.setCursor(px, 110); g_canvas.print(buf);

  // 状態表示 (size2 で右パネル幅に収める)。
  g_canvas.setTextSize(2);
  if (level) { g_canvas.setTextColor(COL_OK, COL_BG);   g_canvas.setCursor(px, 160); g_canvas.print("LEVEL"); }
  else       { g_canvas.setTextColor(COL_WARN, COL_BG); g_canvas.setCursor(px, 160); g_canvas.print("..."); }
}

// BUBBLE: 底面を水平面とする気泡水準器。
static void drawBubble() { drawBubbleCore(g_angX, g_angY, "FLAT"); }

// EDGE: 手前側面を水平面とする縦置きモード。測量/建築の「下げ振り分銅」を再現する。
//   固定 UI: 画面上部に白 1px 水平線 + 左右中央に白 1px 垂直線 (上下全体)。
//   下げ振り: 上記の交点 (cx, 0) を固定点とし、そこから重力方向 (真の鉛直) へ
//             赤 1px の糸を引き、下端に分銅 (直径 4px の赤丸) を描く。糸は本体の
//             左右傾き (edgeA) につれて固定点から振れ、低い側へ垂れる。
//             本体が鉛直なら糸は中央の白垂直線に重なる。
static void drawEdge() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  g_canvas.fillScreen(COL_BG);

  const int cx   = W / 2;
  const int topY = 0;

  // 固定の基準線 (白 1px)。
  g_canvas.drawFastHLine(0, topY, W, COL_VALUE);   // 上部水平線
  g_canvas.drawFastVLine(cx, 0, H, COL_VALUE);     // 左右中央の垂直線

  // 下げ振り (赤)。固定点 (cx, topY) から重力方向へ糸を垂らす。
  // 糸長 L は中央〜画面端 (cx) より短くし、真横 (±90°) まで振れても画面内に
  // 収まる円弧を描かせる (端で止まらない)。
  const int L = 150;                  // 糸の長さ [px] (< cx=160)
  float a = g_edgeA;                  // 左右傾き [deg]
  if (a >  90.0f) a =  90.0f;         // 真横を超えると固定点より上に出るため制限
  if (a < -90.0f) a = -90.0f;
  float ar = a / R2D;
  // 分銅は低い側へ垂れる (気泡=高い側 とは逆向き)。
  int bx = cx - (int)(L * sinf(ar));
  int by = topY + (int)(L * cosf(ar));
  g_canvas.drawLine(cx, topY, bx, by, COL_RED);    // 糸 (赤 1px)
  g_canvas.fillCircle(bx, by, 6, COL_RED);         // 分銅 (直径 約12px)

  // 左右傾き角の読み (鉛直なら緑)。
  char buf[24];
  snprintf(buf, sizeof(buf), "PLUMB %+.1f", g_edgeA);
  g_canvas.setTextSize(2);
  g_canvas.setTextColor(fabsf(g_edgeA) <= LEVEL_TOL_DEG ? COL_OK : COL_ACCENT, COL_BG);
  g_canvas.setCursor(4, H - 26);
  g_canvas.print(buf);
}

// ANGLE: 傾斜計。pitch/roll 大表示 + 合成傾斜 + roll で回転する水平線。
static void drawAngle() {
  const int W = g_canvas.width();
  const int H = g_canvas.height();
  g_canvas.fillScreen(COL_BG);

  char buf[16];

  // モードタイトル (上部中央)。
  g_canvas.setTextSize(1);
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  g_canvas.setCursor(W / 2 - 15, 4);
  g_canvas.print("ANGLE");

  // ---- 大きな数値 (左: roll=X / 右: pitch=Y) ----
  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setCursor(20, 28);      g_canvas.print("ROLL");
  g_canvas.setCursor(W / 2 + 20, 28); g_canvas.print("PITCH");

  g_canvas.setTextSize(4);
  bool levX = fabsf(g_angX) <= LEVEL_TOL_DEG;
  bool levY = fabsf(g_angY) <= LEVEL_TOL_DEG;
  g_canvas.setTextColor(levX ? COL_OK : COL_VALUE, COL_BG);
  snprintf(buf, sizeof(buf), "%+.1f", g_angX);
  g_canvas.setCursor(14, 52); g_canvas.print(buf);
  g_canvas.setTextColor(levY ? COL_OK : COL_VALUE, COL_BG);
  snprintf(buf, sizeof(buf), "%+.1f", g_angY);
  g_canvas.setCursor(W / 2 + 14, 52); g_canvas.print(buf);

  // ---- 合成傾斜角 ----
  g_canvas.setTextSize(2);
  g_canvas.setTextColor(COL_LABEL, COL_BG);
  g_canvas.setCursor(20, 104); g_canvas.print("TILT");
  g_canvas.setTextColor(COL_ACCENT, COL_BG);
  snprintf(buf, sizeof(buf), "%.1f deg", g_tilt);
  g_canvas.setCursor(80, 104); g_canvas.print(buf);

  // ---- 水平線 (roll で回転・pitch で上下) ----
  const int hy = 178;            // 水平線エリアの中心 y
  const int hcx = W / 2;
  const int len = 120;
  float rollRad = g_angX / R2D;
  float dyShift = g_angY * 1.5f;  // pitch を画面 px に変換 (見やすさ優先の係数)
  if (dyShift > 30) dyShift = 30; if (dyShift < -30) dyShift = -30;
  int x1 = hcx - (int)(len / 2 * cosf(rollRad));
  int y1 = hy  - (int)(len / 2 * sinf(rollRad)) + (int)dyShift;
  int x2 = hcx + (int)(len / 2 * cosf(rollRad));
  int y2 = hy  + (int)(len / 2 * sinf(rollRad)) + (int)dyShift;
  uint16_t hCol = (levX && levY) ? COL_OK : COL_ACCENT;
  g_canvas.drawLine(x1, y1, x2, y2, hCol);
  g_canvas.drawLine(x1, y1 + 1, x2, y2 + 1, hCol);   // 太め
  // 中心基準マーク (固定の機体マーク)。
  g_canvas.drawFastHLine(hcx - 20, hy, 12, COL_WARN);
  g_canvas.drawFastHLine(hcx + 8,  hy, 12, COL_WARN);
  g_canvas.fillCircle(hcx, hy, 2, COL_WARN);
}

// 現在モードを描画 → 各種インジケータ → 一括転送。
static void drawCurrent() {
  switch (g_mode) {
    case MODE_ANGLE:  drawAngle();  break;
    case MODE_EDGE:   drawEdge();   break;
    case MODE_BUBBLE:
    default:          drawBubble(); break;
  }
  drawBatteryCorner();
  drawRelFlag();
  drawModeDots();
  g_canvas.pushSprite(0, 0);
}

// ---------------------------------------------------------------------------
// タッチ: タップ=ゼロ点トグル / 左右スワイプ=モード切替。
// ---------------------------------------------------------------------------
static void handleTouch() {
  if (M5.Touch.getCount() == 0) return;
  auto d = M5.Touch.getDetail();
  if (!(d.wasFlicked() || d.wasReleased())) return;

  int dx = d.distanceX();
  int dy = d.distanceY();
  if (abs(dx) >= SWIPE_THRESHOLD && abs(dx) > abs(dy)) {
    // 左右スワイプ → モード送り。
    if (dx < 0) g_mode = (g_mode + 1) % MODE_COUNT;
    else        g_mode = (g_mode + MODE_COUNT - 1) % MODE_COUNT;
    g_redraw = true;
  } else if (abs(dx) < TAP_MAX_MOVE && abs(dy) < TAP_MAX_MOVE) {
    // タップ → 相対測定のゼロ点をトグル。
    if (g_relative) {
      g_relative = false;
    } else {
      captureZero();
      g_relative = true;
    }
    g_redraw = true;
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

  Serial.begin(115200);   // USB CDC (軸検証ログ用)

  // 内蔵 IMU (BMI270) の有無を確認しログ出力。
  bool imu_ok = (M5.Imu.getType() != m5::imu_none);
  Serial.printf("{\"log\":\"imu_init\",\"ok\":%d,\"type\":%d,\"fw\":\"%s\"}\n",
                imu_ok ? 1 : 0, (int)M5.Imu.getType(), FW_VERSION);

  if (!imu_ok) {
    g_canvas.fillScreen(COL_BG);
    g_canvas.setTextColor(COL_WARN, COL_BG);
    g_canvas.setTextSize(2);
    g_canvas.setCursor(10, 100);
    g_canvas.print("No IMU detected");
    g_canvas.pushSprite(0, 0);
  }
}

void loop() {
  M5.update();
  handleTouch();
  updateAngles();

  // 軸検証用ログ (2Hz)。傾けた向きと符号の対応を実機で確認する。
  const uint32_t now = millis();
  if (now - g_last_log_ms >= LOG_INTERVAL_MS) {
    g_last_log_ms = now;
    Serial.printf("{\"log\":\"imu\",\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,"
                  "\"angX\":%.2f,\"angY\":%.2f,\"tilt\":%.2f,"
                  "\"edgeA\":%.2f,\"edgeB\":%.2f,\"rel\":%d}\n",
                  g_fax, g_fay, g_faz, g_angX, g_angY, g_tilt,
                  g_edgeA, g_edgeB, g_relative ? 1 : 0);
  }

  // 常時再描画 (角度は連続変化するため毎ループ描く・~60fps)。
  drawCurrent();
  g_redraw = false;
}
