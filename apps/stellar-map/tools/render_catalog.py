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
                                 load_catalog, mag_to_radius, radec_to_altaz)

# osprey74 テーマ
COL_BG = (0, 0, 0)
COL_STAR = (255, 255, 255)
COL_HORIZON = (60, 66, 70)
COL_ACCENT = (0, 220, 255)
COL_LABEL = (150, 150, 150)
COL_OK = (0, 200, 80)

W, H = 320, 170
CX, CY, R = 85, 85, 80
PANEL_X = 170

# ラベルを付ける代表的な明るい固有名星 (存在すれば表示)。
LABEL_STARS = ["Sirius", "Vega", "Arcturus", "Capella", "Rigel", "Betelgeuse",
               "Altair", "Deneb", "Aldebaran", "Antares", "Spica", "Pollux",
               "Regulus", "Polaris"]


def render(cat, dt_local: datetime, tz: float, lat: float, lon: float,
           mirror_ew: bool, mag_view: float) -> tuple[Image.Image, int]:
    dt_utc = dt_local - timedelta(hours=tz)
    jd = julian_date(dt_utc.year, dt_utc.month, dt_utc.day,
                     dt_utc.hour, dt_utc.minute, dt_utc.second)
    lst = lst_deg(jd, lon)

    img = Image.new("RGB", (W, H), COL_BG)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("consola.ttf", 11)
        font_sm = ImageFont.truetype("consola.ttf", 9)
    except OSError:
        font = font_sm = ImageFont.load_default()

    d.ellipse([CX - R, CY - R, CX + R, CY + R], outline=COL_HORIZON)
    d.line([CX - R, CY, CX + R, CY], fill=COL_HORIZON)
    d.line([CX, CY - R, CX, CY + R], fill=COL_HORIZON)
    for lbl, (dx, dy) in {"N": (0, -1), "S": (0, 1),
                          "E": (1, 0) if not mirror_ew else (-1, 0),
                          "W": (-1, 0) if not mirror_ew else (1, 0)}.items():
        d.text((CX + dx * (R + 3) - 3, CY + dy * (R + 3) - 5), lbl, fill=COL_ACCENT, font=font_sm)

    visible = 0
    for s in cat.stars:
        if s.mag > mag_view:          # 小型 LCD 向けに暗い星を描画時に間引く
            continue
        alt, az = radec_to_altaz(s.ra_deg, s.dec_deg, lat, lst)
        if alt < 0:
            continue
        visible += 1
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew)
        rr = mag_to_radius(s.mag)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=COL_STAR)

    # 代表星のラベル (地平線上のもののみ)。
    for name in LABEL_STARS:
        s = cat.by_name(name)
        if not s:
            continue
        alt, az = radec_to_altaz(s.ra_deg, s.dec_deg, lat, lst)
        if alt < 0:
            continue
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew)
        d.text((x + 3, y - 4), name, fill=COL_ACCENT, font=font_sm)

    # 情報パネル
    px = PANEL_X + 4
    d.line([PANEL_X, 0, PANEL_X, H], fill=COL_HORIZON)
    d.text((px, 6), "HYG CATALOG", fill=COL_ACCENT, font=font)
    d.text((px, 24), dt_local.strftime("%Y-%m-%d %H:%M"), fill=COL_STAR, font=font)
    d.text((px, 40), f"lat {lat:+.2f}", fill=COL_STAR, font=font)
    d.text((px, 54), f"lon {lon:+.2f}", fill=COL_STAR, font=font)
    d.text((px, 74), f"loaded: {len(cat)}", fill=COL_LABEL, font=font_sm)
    d.text((px, 88), f"up: {visible}", fill=COL_OK, font=font)
    d.text((px, 108), f"view mag<={mag_view:g}", fill=COL_LABEL, font=font_sm)
    d.text((px, 148), "HYG v4.1 CC BY-SA", fill=COL_LABEL, font=font_sm)
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
    ap.add_argument("--out", default=str(app_root / "poc" / "out" / "hyg_real.png"))
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()

    cat = load_catalog(args.data)
    img, visible = render(cat, datetime.fromisoformat(args.dt), args.tz,
                          args.lat, args.lon, args.mirror_ew, args.mag_view)
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
