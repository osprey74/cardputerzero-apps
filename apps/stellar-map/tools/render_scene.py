#!/usr/bin/env python3
"""App 16 星座盤 ― Scene JSON を PNG に描く（サイドカー↔UI プロトコルの PC 検証）。

`sidecar/stellar_sidecar.py` が出す Scene JSON を**天体計算を一切せず**プリミティブだけから
描画する。これが成立すれば「Python サイドカーが Scene を吐き、UI は描くだけ」という
Rust/LVGL 側の実装が妥当だと確認できる。描画は実機方針どおり **等倍・AA 無し・四角**。

使い方:
  python ../sidecar/stellar_sidecar.py --dt 2026-07-08T03:30 | python render_scene.py
  python render_scene.py --in scene.json --out ../poc/out/scene.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COL_BG = (0, 0, 0)
COL_ACCENT = (0, 220, 255)
COL_TEXT = (235, 235, 235)
COL_LABEL = (150, 150, 150)


def draw_square(d, x, y, side, col):
    ix, iy = int(x), int(y)
    if side <= 1:
        box = [ix, iy, ix, iy]
    elif side == 2:
        box = [ix, iy, ix + 1, iy + 1]
    else:
        box = [ix - 1, iy - 1, ix + 1, iy + 1]
    d.rectangle(box, fill=col)


def render_scene(scene: dict) -> Image.Image:
    w, h = scene.get("w", 320), scene.get("h", 170)
    img = Image.new("RGB", (w, h), COL_BG)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"          # 実機同様 AA 無し（bilevel）文字
    try:
        font = ImageFont.truetype("consola.ttf", 11)
        font_sm = ImageFont.truetype("consola.ttf", 9)
    except OSError:
        font = font_sm = ImageFont.load_default()

    ch = scene.get("chrome", {})
    if ch.get("circle"):
        cx, cy, r = ch["circle"]
        cc = tuple(ch.get("circle_color", [60, 66, 70]))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cc)
        d.line([cx - r, cy, cx + r, cy], fill=cc)
        d.line([cx, cy - r, cx, cy + r], fill=cc)
        dc = tuple(ch.get("dir_color", [255, 165, 0]))
        for x, y, t in ch.get("dirs", []):
            d.text((x, y), t, fill=dc, font=font_sm)

    lc = tuple(scene.get("line_color", [40, 90, 110]))
    for x1, y1, x2, y2 in scene.get("lines", []):
        d.line([x1, y1, x2, y2], fill=lc)

    for x, y, side, r, g, b in scene.get("dso", []):     # DSO（恒星の下に）
        draw_square(d, x, y, side, (r, g, b))
    for x, y, side, r, g, b in scene.get("points", []):
        draw_square(d, x, y, side, (r, g, b))

    for x, y, t, r, g, b in scene.get("labels", []):
        d.text((x, y), t, fill=(r, g, b), font=font_sm)

    # 情報パネル（meta から）。UI 側の描画例。
    meta = scene.get("meta", {})
    px = 174
    d.line([170, 0, 170, h], fill=(60, 66, 70))
    d.text((px, 6), "STELLAR MAP", fill=COL_ACCENT, font=font)
    d.text((px, 24), meta.get("time_local", ""), fill=COL_TEXT, font=font)
    d.text((px, 40), f"lat {meta.get('lat', 0):+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 54), f"lon {meta.get('lon', 0):+.2f}", fill=COL_TEXT, font=font)
    d.text((px, 138), f"heading {meta.get('heading', 0):.0f}", fill=COL_ACCENT, font=font_sm)
    c = meta.get("counts", {})
    d.text((px, 72), f"stars: {c.get('stars', 0)}", fill=(0, 200, 80), font=font_sm)
    d.text((px, 84), f"lines: {c.get('lines', 0)}  dso: {c.get('dso', 0)}",
           fill=COL_LABEL, font=font_sm)
    d.text((px, 96), f"planets up: {c.get('planets', 0)}", fill=(255, 215, 120), font=font_sm)
    mo = meta.get("moon")
    if mo:
        wax = "wax" if mo.get("waxing") else "wan"
        d.text((px, 108), f"Moon {mo.get('frac', 0) * 100:.0f}% {wax}",
               fill=(225, 225, 205), font=font_sm)
    d.text((px, 126), "from Scene JSON", fill=COL_LABEL, font=font_sm)
    d.text((px, 150), "HYG/OpenNGC/Stel/JPL", fill=COL_LABEL, font=font_sm)
    return img


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Scene JSON → PNG (プロトコル検証)")
    ap.add_argument("--in", dest="inp", default=None, help="Scene JSON パス（既定は stdin）")
    ap.add_argument("--out", default=str(here.parent / "poc" / "out" / "scene.png"))
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()

    raw = Path(args.inp).read_text(encoding="utf-8") if args.inp else sys.stdin.read()
    scene = json.loads(raw.strip().splitlines()[-1])   # JSON Lines の最新行
    img = render_scene(scene)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"[ok] saved {out}")
    if args.scale > 1:
        big = img.resize((img.width * args.scale, img.height * args.scale), Image.NEAREST)
        bp = out.with_name(out.stem + f"_{args.scale}x" + out.suffix)
        big.save(bp)
        print(f"[ok] saved {bp}")


if __name__ == "__main__":
    main()
