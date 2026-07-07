#!/usr/bin/env python3
"""前処理済み HYG 星表 (stars.bin) を読み、320×170 の全天図に描画して PNG 出力する。

`build_star_catalog.py` の生成物を `shared/star_catalog` 経由でロードし、実データ
(約9千星) が正しく取り込めているかを可視検証する。惑星・月・星座線は含まない
(次段)。明るい固有名星を数個だけラベル表示して天文的な妥当性を確認する。

使い方:
  python render_catalog.py                       # 既定: 札幌 2026-07-07 21:30 JST
  python render_catalog.py --lat 35.68 --lon 139.77 --dt 2026-12-01T22:00
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from shared.star_catalog import (altaz_to_plot_xy, julian_date, lst_deg,  # noqa: E402
                                 load_catalog, mag_to_color, mag_to_radius,
                                 radec_to_altaz)

# osprey74 テーマ
COL_BG = (0, 0, 0)
COL_HORIZON = (60, 66, 70)
COL_ACCENT = (0, 220, 255)     # 星名ラベル (シアン)
COL_DIR = (255, 165, 0)        # 方位 N/E/S/W (オレンジ)
COL_TEXT = (235, 235, 235)     # 情報パネル本文
COL_LABEL = (150, 150, 150)
COL_OK = (0, 200, 80)

W, H = 320, 170
CX, CY, R = 85, 85, 80
PANEL_X = 170
SS = 4   # スーパーサンプリング倍率。高解像で描き→LANCZOS 縮小して小さな星も丸くする。

# ラベルを付ける代表的な明るい固有名星 (存在すれば表示)。
LABEL_STARS = ["Sirius", "Vega", "Arcturus", "Capella", "Rigel", "Betelgeuse",
               "Altair", "Deneb", "Aldebaran", "Antares", "Spica", "Pollux",
               "Regulus", "Polaris"]


# 四角ドットの一辺 [px] を等級クラスで決める (1等=3 / 2等=2 / 3等以下=1)。
def mag_to_square(mag: float) -> int:
    if mag <= 1.5:
        return 3
    if mag <= 2.5:
        return 2
    return 1


def _draw_square_native(d, x: float, y: float, side: int, col) -> None:
    """等倍・整数座標でピクセル正確な四角を描く (AA 無し)。side=1/2/3 px。"""
    ix, iy = round(x), round(y)
    if side <= 1:
        box = [ix, iy, ix, iy]                    # 1 ドット
    elif side == 2:
        box = [ix, iy, ix + 1, iy + 1]            # 2×2
    else:
        box = [ix - 1, iy - 1, ix + 1, iy + 1]    # 3×3 (中心そろえ)
    d.rectangle(box, fill=col)


def render(cat, dt_local: datetime, tz: float, lat: float, lon: float,
           mirror_ew: bool, mag_view: float,
           shape: str = "round", aa: bool = True) -> tuple[Image.Image, int]:
    """全天図を描く。

    aa=True: SS 倍で描画→LANCZOS 縮小 (丸を滑らかに)。
    aa=False: 等倍・AA 無し (文字は bilevel・四角はピクセル正確)。実機の見えに近い。
    shape: "round"=円 / "square"=四角ドット。
    """
    dt_utc = dt_local - timedelta(hours=tz)
    jd = julian_date(dt_utc.year, dt_utc.month, dt_utc.day,
                     dt_utc.hour, dt_utc.minute, dt_utc.second)
    lst = lst_deg(jd, lon)

    ss = SS if aa else 1
    img = Image.new("RGB", (W * ss, H * ss), COL_BG)
    d = ImageDraw.Draw(img)
    if not aa:
        d.fontmode = "1"          # 文字を AA 無し (bilevel) で描く = 実機の小文字に近い
    try:
        font = ImageFont.truetype("consola.ttf", 11 * ss)
        font_sm = ImageFont.truetype("consola.ttf", 9 * ss)
    except OSError:
        font = font_sm = ImageFont.load_default()

    cx, cy, rr0 = CX * ss, CY * ss, R * ss
    d.ellipse([cx - rr0, cy - rr0, cx + rr0, cy + rr0], outline=COL_HORIZON, width=ss)
    d.line([cx - rr0, cy, cx + rr0, cy], fill=COL_HORIZON, width=ss)
    d.line([cx, cy - rr0, cx, cy + rr0], fill=COL_HORIZON, width=ss)
    for lbl, (dx, dy) in {"N": (0, -1), "S": (0, 1),
                          "E": (1, 0) if not mirror_ew else (-1, 0),
                          "W": (-1, 0) if not mirror_ew else (1, 0)}.items():
        d.text(((CX + dx * (R + 3) - 3) * ss, (CY + dy * (R + 3) - 5) * ss),
               lbl, fill=COL_DIR, font=font_sm)

    visible = 0
    for st in cat.stars:
        if st.mag > mag_view:          # 小型 LCD 向けに暗い星を描画時に間引く
            continue
        alt, az = radec_to_altaz(st.ra_deg, st.dec_deg, lat, lst)
        if alt < 0:
            continue
        visible += 1
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew)
        col = mag_to_color(st.mag)
        if shape == "square":
            if aa:
                h = mag_to_square(st.mag) * ss / 2.0
                d.rectangle([x * ss - h, y * ss - h, x * ss + h, y * ss + h], fill=col)
            else:
                _draw_square_native(d, x, y, mag_to_square(st.mag), col)
        else:
            rr = mag_to_radius(st.mag) * ss
            d.ellipse([x * ss - rr, y * ss - rr, x * ss + rr, y * ss + rr], fill=col)

    # 代表星のラベル (地平線上のもののみ)。
    for name in LABEL_STARS:
        st = cat.by_name(name)
        if not st:
            continue
        alt, az = radec_to_altaz(st.ra_deg, st.dec_deg, lat, lst)
        if alt < 0:
            continue
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew)
        d.text(((x + 3) * ss, (y - 4) * ss), name, fill=COL_ACCENT, font=font_sm)

    # 情報パネル
    px = (PANEL_X + 4) * ss
    d.line([PANEL_X * ss, 0, PANEL_X * ss, H * ss], fill=COL_HORIZON, width=ss)
    d.text((px, 6 * ss), "HYG CATALOG", fill=COL_ACCENT, font=font)
    d.text((px, 24 * ss), dt_local.strftime("%Y-%m-%d %H:%M"), fill=COL_TEXT, font=font)
    d.text((px, 40 * ss), f"lat {lat:+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 54 * ss), f"lon {lon:+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 74 * ss), f"loaded: {len(cat)}", fill=COL_LABEL, font=font_sm)
    d.text((px, 88 * ss), f"up: {visible}", fill=COL_OK, font=font)
    d.text((px, 108 * ss), f"view mag<={mag_view:g}", fill=COL_LABEL, font=font_sm)
    mode = f"{shape}/{'AA' if aa else 'no-aa'}"
    d.text((px, 126 * ss), f"mode: {mode}", fill=COL_LABEL, font=font_sm)
    d.text((px, 148 * ss), "HYG v4.1 CC BY-SA", fill=COL_LABEL, font=font_sm)

    if aa:
        img = img.resize((W, H), Image.LANCZOS)
    return img, visible


def main() -> None:
    here = Path(__file__).resolve().parent
    app_root = here.parent
    ap = argparse.ArgumentParser(description="HYG 中間形式の可視検証レンダラ")
    ap.add_argument("--data", default=str(app_root / "data"), help="stars.bin のあるディレクトリ")
    ap.add_argument("--lat", type=float, default=43.06)
    ap.add_argument("--lon", type=float, default=141.35)
    ap.add_argument("--dt", default="2026-07-07T21:30")
    ap.add_argument("--tz", type=float, default=9.0)
    ap.add_argument("--mirror-ew", action="store_true")
    ap.add_argument("--mag-view", type=float, default=4.5,
                    help="描画する上限等級 (小型LCD向け・既定 4.5。カタログは全星保持)")
    ap.add_argument("--shape", choices=["round", "square"], default="round",
                    help="星の形。round=円 / square=四角ドット")
    ap.add_argument("--no-aa", action="store_true",
                    help="等倍・AA 無しで描く (文字 bilevel・四角ピクセル正確・実機に近い)")
    ap.add_argument("--out", default=None,
                    help="出力パス (未指定なら hyg_<shape>_<aa|noaa>.png)")
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()

    aa = not args.no_aa
    cat = load_catalog(args.data)
    img, visible = render(cat, datetime.fromisoformat(args.dt), args.tz,
                          args.lat, args.lon, args.mirror_ew, args.mag_view,
                          args.shape, aa)
    if args.out is None:
        tag = f"{args.shape}_{'aa' if aa else 'noaa'}"
        out = app_root / "poc" / "out" / f"hyg_{tag}.png"
    else:
        out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"[ok] loaded {len(cat)} stars, {visible} above horizon")
    print(f"[ok] saved {out}")
    if args.scale > 1:
        big = img.resize((W * args.scale, H * args.scale), Image.NEAREST)
        bp = out.with_name(out.stem + f"_{args.scale}x" + out.suffix)
        big.save(bp)
        print(f"[ok] saved {bp}")


if __name__ == "__main__":
    main()
