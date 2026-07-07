#!/usr/bin/env python3
"""App 16 星座盤 PoC ― 指定日時・観測地点の可視恒星＋星座線を 320×170 に投影して PNG 出力する。

目的（HANDOFF §9 App16 の先行 PoC）:
  実機・ネットワーク・天体暦ダウンロード無しで「投影パイプライン」を検証する。
  恒星と星座線だけなら惑星・月用の JPL 暦 (Skyfield) は不要で、古典的な
  「恒星時 → 地平座標 (Alt/Az)」変換で自己完結できる。惑星・月・高精度化は
  次段で Skyfield に差し替える想定（transform 部を独立関数にしてある）。

投影:
  HANDOFF App01「Sky Plot 天球図」の極座標変換を流用。
  左 170×170 = 円形全天図（中心=天頂 alt90° / 外周=地平線 alt0° / 北=上）、
  右 150×170 = 情報パネル。地平線下 (alt<0) の星・線は描かない。

データ:
  PoC 用に主要な明るい恒星（J2000 の RA/Dec は事実データ）を内蔵。
  本実装では HYG(CC BY-SA 4.0)/OpenNGC(CC BY-SA 4.0)/Stellarium 星座線(MIT) を
  取り込むが、PoC は依存とライセンス束縛を避けるため最小の自前サンプルを使う。

使い方:
  python star_poc.py                       # 既定: 札幌・2026-07-07 21:30 JST
  python star_poc.py --lat 35.68 --lon 139.77 --dt "2026-12-01T22:00" --tz 9
  python star_poc.py --mirror-ew           # 天頂を見上げる向き(planisphere)に東西反転
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---- osprey74 カラーテーマ (ダーク基調 + シアン/グリーンのアクセント) --------
COL_BG = (0, 0, 0)
COL_LINE = (32, 96, 110)      # 星座線 (暗いシアン)
COL_HORIZON = (60, 66, 70)    # 地平円・十字
COL_ACCENT = (0, 220, 255)    # シアン (タイトル・星名ラベル)
COL_DIR = (255, 165, 0)       # 方位 N/E/S/W (オレンジ)
COL_TEXT = (235, 235, 235)    # 情報パネル本文
COL_LABEL = (150, 150, 150)
COL_OK = (0, 200, 80)

# 等級クラス別の星の色 (1等星=白 / 2等星=シアン寄り / 3等以下=青灰)。
MAG_CLASS1, MAG_CLASS2 = 1.5, 2.5
COLOR_MAG1 = (255, 255, 255)
COLOR_MAG2 = (150, 220, 255)
COLOR_MAG3 = (110, 140, 180)


def mag_to_color(mag: float) -> tuple[int, int, int]:
    """実視等級 → 星の色。1等星=白 / 2等星=シアン寄り / 3等以下=青灰。"""
    if mag <= MAG_CLASS1:
        return COLOR_MAG1
    if mag <= MAG_CLASS2:
        return COLOR_MAG2
    return COLOR_MAG3

# ---- LCD レイアウト (320×170) ---------------------------------------------
W, H = 320, 170
PLOT_CX, PLOT_CY, PLOT_R = 85, 85, 80   # 左 170×170 円形全天図 (App01 Sky Plot 準拠)
PANEL_X = 170                            # 右 150×170 情報パネル開始 x
SS = 4                                   # スーパーサンプリング倍率 (小さな星を丸く AA)

# ---------------------------------------------------------------------------
# 明るい恒星サンプル (name, RA[deg, J2000], Dec[deg], 実視等級)
# ---------------------------------------------------------------------------
STARS: dict[str, tuple[float, float, float]] = {
    # おおぐま座 (北斗七星)
    "Dubhe":      (165.93, 61.75, 1.79),
    "Merak":      (165.46, 56.38, 2.37),
    "Phecda":     (178.46, 53.69, 2.44),
    "Megrez":     (183.86, 57.03, 3.31),
    "Alioth":     (193.51, 55.96, 1.77),
    "Mizar":      (200.98, 54.93, 2.27),
    "Alkaid":     (206.89, 49.31, 1.86),
    # オリオン座
    "Betelgeuse": (88.79, 7.41, 0.42),
    "Rigel":      (78.63, -8.20, 0.18),
    "Bellatrix":  (81.28, 6.35, 1.64),
    "Mintaka":    (83.00, -0.30, 2.23),
    "Alnilam":    (84.05, -1.20, 1.69),
    "Alnitak":    (85.19, -1.94, 1.74),
    "Saiph":      (86.94, -9.67, 2.07),
    # カシオペヤ座 (W)
    "Segin":      (28.60, 63.67, 3.35),
    "Ruchbah":    (21.45, 60.24, 2.68),
    "GammaCas":   (14.18, 60.72, 2.47),
    "Schedar":    (10.13, 56.54, 2.24),
    "Caph":       (2.29, 59.15, 2.28),
    # はくちょう座 (北十字) + こと + わし (夏の大三角)
    "Deneb":      (310.36, 45.28, 1.25),
    "Sadr":       (305.56, 40.26, 2.23),
    "Gienah":     (311.55, 33.97, 2.48),
    "DeltaCyg":   (296.24, 45.13, 2.87),
    "Albireo":    (292.68, 27.96, 3.05),
    "Vega":       (279.23, 38.78, 0.03),
    "Altair":     (297.70, 8.87, 0.77),
    # 単体の明るい星 (文脈用)
    "Sirius":     (101.29, -16.72, -1.46),
    "Arcturus":   (213.92, 19.18, -0.05),
    "Capella":    (79.17, 46.00, 0.08),
    "Aldebaran":  (68.98, 16.51, 0.87),
    "Antares":    (247.35, -26.43, 1.06),
    "Spica":      (201.30, -11.16, 0.98),
    "Pollux":     (116.33, 28.03, 1.14),
    "Regulus":    (152.09, 11.97, 1.35),
    "Polaris":    (37.95, 89.26, 1.98),
}

# 星座線 (名前ペアの連なり)。両端が地平線上のときだけ描画する。
CONSTELLATION_LINES: list[list[str]] = [
    # 北斗七星: 柄 (Alkaid〜Megrez) + ます (Megrez-Dubhe-Merak-Phecda-Megrez)
    ["Alkaid", "Mizar", "Alioth", "Megrez", "Dubhe", "Merak", "Phecda", "Megrez"],
    # オリオン: 肩・ベルト・脚
    ["Betelgeuse", "Bellatrix", "Mintaka", "Alnilam", "Alnitak", "Betelgeuse"],
    ["Bellatrix", "Rigel"], ["Alnitak", "Saiph"], ["Mintaka", "Rigel"], ["Saiph", "Rigel"],
    # カシオペヤ W
    ["Segin", "Ruchbah", "GammaCas", "Schedar", "Caph"],
    # はくちょう (北十字): 長軸 + 横木
    ["Deneb", "Sadr", "Albireo"], ["Gienah", "Sadr", "DeltaCyg"],
]


# ---------------------------------------------------------------------------
# 時刻・座標変換 (惑星・月なしの恒星専用。次段で Skyfield に差し替え可能)
# ---------------------------------------------------------------------------
def julian_date(dt_utc: datetime) -> float:
    """UTC datetime → ユリウス日 (JD)。"""
    y, m = dt_utc.year, dt_utc.month
    d = (dt_utc.day + (dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600) / 24)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def gmst_deg(jd: float) -> float:
    """JD → グリニッジ平均恒星時 [deg]。"""
    t = (jd - 2451545.0) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
         + 0.000387933 * t * t - (t ** 3) / 38710000.0)
    return g % 360.0


def radec_to_altaz(ra_deg: float, dec_deg: float, lat_deg: float,
                   lst_deg: float) -> tuple[float, float]:
    """赤道座標 (RA/Dec) → 地平座標 (alt, az)。az は北=0・東回り [deg]。"""
    ha = math.radians((lst_deg - ra_deg) % 360.0)   # 時角
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)
    cos_az = (math.sin(dec) - math.sin(lat) * sin_alt) / (math.cos(lat) * math.cos(alt) + 1e-12)
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha) > 0:
        az = 360.0 - az
    return math.degrees(alt), az


def altaz_to_xy(alt: float, az: float, mirror_ew: bool) -> tuple[float, float]:
    """地平座標 → 左 170×170 円形全天図のピクセル (App01 Sky Plot 準拠)。

    中心=天頂(alt90°)/外周=地平線(alt0°)/北=上。既定は東=右 (Sky Plot 準拠)。
    mirror_ew=True で天頂を見上げる向き (planisphere) に東西反転。
    """
    r = PLOT_R * (1.0 - alt / 90.0)
    a = (360.0 - az) if mirror_ew else az
    theta = math.radians(a - 90.0)   # 北を 12 時方向へ
    x = PLOT_CX + r * math.cos(theta)
    y = PLOT_CY + r * math.sin(theta)
    return x, y


def mag_to_radius(mag: float) -> float:
    """実視等級 → ドット半径 [px] (等級クラス別)。1等=2.0 / 2等=1.5 / 3等以下=1.0。

    小さな円は Pillow の ellipse では「＋」に欠けるため、描画側はスーパーサンプリング
    (高解像描画→縮小) で丸くする前提のサイズ。
    """
    if mag <= MAG_CLASS1:
        return 2.0
    if mag <= MAG_CLASS2:
        return 1.5
    return 1.0


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------
def render(dt_local: datetime, tz_hours: float, lat: float, lon: float,
           mirror_ew: bool) -> Image.Image:
    dt_utc = (dt_local - timedelta(hours=tz_hours)).replace(tzinfo=timezone.utc)
    jd = julian_date(dt_utc)
    lst = (gmst_deg(jd) + lon) % 360.0   # 地方恒星時 (東経 +)

    # 高解像 (SS 倍) で描画してから LANCZOS で 320×170 に縮小する（星を丸く AA）。
    ss = SS
    img = Image.new("RGB", (W * ss, H * ss), COL_BG)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("consola.ttf", 11 * ss)
        font_sm = ImageFont.truetype("consola.ttf", 9 * ss)
    except OSError:
        font = ImageFont.load_default()
        font_sm = font

    # --- 全天円・十字・方位 ---
    cx, cy, pr = PLOT_CX * ss, PLOT_CY * ss, PLOT_R * ss
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], outline=COL_HORIZON, width=ss)
    d.line([cx - pr, cy, cx + pr, cy], fill=COL_HORIZON, width=ss)
    d.line([cx, cy - pr, cx, cy + pr], fill=COL_HORIZON, width=ss)
    for lbl, (dx, dy) in {"N": (0, -1), "S": (0, 1),
                          "E": (1, 0) if not mirror_ew else (-1, 0),
                          "W": (-1, 0) if not mirror_ew else (1, 0)}.items():
        d.text(((PLOT_CX + dx * (PLOT_R + 3) - 3) * ss, (PLOT_CY + dy * (PLOT_R + 3) - 5) * ss),
               lbl, fill=COL_DIR, font=font_sm)

    # --- 恒星の地平座標を先に計算 ---
    pos: dict[str, tuple[float, float, float]] = {}   # name -> (alt, x, y)  ※x,y は最終座標
    for name, (ra, dec, _mag) in STARS.items():
        alt, az = radec_to_altaz(ra, dec, lat, lst)
        x, y = altaz_to_xy(alt, az, mirror_ew)
        pos[name] = (alt, x, y)

    # --- 星座線 (両端が地平線上のときだけ) ---
    for chain in CONSTELLATION_LINES:
        for a, b in zip(chain, chain[1:]):
            if a in pos and b in pos and pos[a][0] >= 0 and pos[b][0] >= 0:
                d.line([pos[a][1] * ss, pos[a][2] * ss, pos[b][1] * ss, pos[b][2] * ss],
                       fill=COL_LINE, width=ss)

    # --- 恒星ドット ---
    visible = 0
    for name, (ra, dec, mag) in STARS.items():
        alt, x, y = pos[name]
        if alt < 0:
            continue
        visible += 1
        rr = mag_to_radius(mag) * ss
        d.ellipse([x * ss - rr, y * ss - rr, x * ss + rr, y * ss + rr], fill=mag_to_color(mag))

    # --- 右 情報パネル ---
    px = (PANEL_X + 4) * ss
    d.line([PANEL_X * ss, 0, PANEL_X * ss, H * ss], fill=COL_HORIZON, width=ss)
    d.text((px, 6 * ss), "STELLAR MAP  PoC", fill=COL_ACCENT, font=font)
    d.text((px, 24 * ss), dt_local.strftime("%Y-%m-%d %H:%M"), fill=COL_TEXT, font=font)
    d.text((px, 38 * ss), f"TZ +{tz_hours:g}  (local)", fill=COL_LABEL, font=font_sm)
    d.text((px, 54 * ss), f"lat {lat:+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 68 * ss), f"lon {lon:+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 84 * ss), f"LST {lst / 15:05.2f}h", fill=COL_LABEL, font=font_sm)
    d.text((px, 104 * ss), f"stars up: {visible}/{len(STARS)}", fill=COL_OK, font=font)
    d.text((px, 122 * ss), "N up / " + ("look-up" if mirror_ew else "E=right"),
           fill=COL_LABEL, font=font_sm)
    d.text((px, 148 * ss), "zenith=center", fill=COL_LABEL, font=font_sm)

    return img.resize((W, H), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser(description="App16 星座盤 PoC (320x170 投影)")
    ap.add_argument("--lat", type=float, default=43.06, help="観測地 緯度 [deg] (既定: 札幌)")
    ap.add_argument("--lon", type=float, default=141.35, help="観測地 経度 [deg] 東経+ (既定: 札幌)")
    ap.add_argument("--dt", default="2026-07-07T21:30", help="ローカル日時 ISO (既定 2026-07-07 21:30)")
    ap.add_argument("--tz", type=float, default=9.0, help="タイムゾーン時差 [h] (既定 +9 JST)")
    ap.add_argument("--mirror-ew", action="store_true", help="見上げる向き(planisphere)に東西反転")
    ap.add_argument("--out", default=str(Path(__file__).parent / "out" / "skychart.png"))
    ap.add_argument("--scale", type=int, default=4, help="拡大版の倍率 (0 で無効)")
    args = ap.parse_args()

    dt_local = datetime.fromisoformat(args.dt)
    img = render(dt_local, args.tz, args.lat, args.lon, args.mirror_ew)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"saved {out} ({img.width}x{img.height})")
    if args.scale > 1:
        big = img.resize((W * args.scale, H * args.scale), Image.NEAREST)
        big_path = out.with_name(out.stem + f"_{args.scale}x" + out.suffix)
        big.save(big_path)
        print(f"saved {big_path} ({big.width}x{big.height})")


if __name__ == "__main__":
    main()
