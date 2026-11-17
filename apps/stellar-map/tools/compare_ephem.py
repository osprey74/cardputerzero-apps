#!/usr/bin/env python3
"""App 16 星座盤 ― 軽量計算 `ephem_lite` を Skyfield（`ephem`）と突き合わせる検証ツール（PC 用）。

多数の日時について、惑星・月の地平座標の角距離の差、等級の差、月の輝面比の差を集計する。
Skyfield と DE421（`data/raw/de421.bsp`）が必要。

使い方:
  python compare_ephem.py                      # 2020〜2035 年の 600 サンプル・札幌
  python compare_ephem.py --samples 2000 --lat 35.68 --lon 139.77
"""
from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import ephem
import ephem_lite


def sep(alt1, az1, alt2, az2):
    """2 方向の角距離 [deg]。"""
    a1, z1, a2, z2 = map(math.radians, (alt1, az1, alt2, az2))
    c = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(z1 - z2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=600)
    ap.add_argument("--lat", type=float, default=43.06)
    ap.add_argument("--lon", type=float, default=141.35)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2036-01-01")
    ap.add_argument("--data", default=str(here.parent / "data"))
    ap.add_argument("--seed", type=int, default=16)
    args = ap.parse_args()

    t0 = datetime.fromisoformat(args.start)
    span = (datetime.fromisoformat(args.end) - t0).total_seconds()
    rnd = random.Random(args.seed)
    pos = {}     # name -> [sep deg]
    mag = {}     # name -> [abs mag diff]
    frac, wax_mismatch, phase_mismatch = [], 0, 0
    for _ in range(args.samples):
        dt = t0 + timedelta(seconds=rnd.uniform(0, span))
        dt = dt.replace(microsecond=0)
        a = ephem.sky_bodies(dt, args.lat, args.lon, args.data)
        b = ephem_lite.sky_bodies(dt, args.lat, args.lon)
        for pa, pb in zip(a["planets"], b["planets"]):
            assert pa["name"] == pb["name"]
            pos.setdefault(pa["name"], []).append(sep(pa["alt"], pa["az"], pb["alt"], pb["az"]))
            mag.setdefault(pa["name"], []).append(abs(pa["mag"] - pb["mag"]))
        ma, mb = a["moon"], b["moon"]
        pos.setdefault("Moon", []).append(sep(ma["alt"], ma["az"], mb["alt"], mb["az"]))
        frac.append(abs(ma["frac"] - mb["frac"]))
        wax_mismatch += ma["waxing"] != mb["waxing"]
        phase_mismatch += ma["phase"] != mb["phase"]

    print(f"samples {args.samples}  {args.start}..{args.end}  lat {args.lat} lon {args.lon}")
    print(f"{'body':8s} {'pos mean':>9s} {'pos p95':>9s} {'pos max':>9s}   {'mag mean':>8s} {'mag max':>8s}")
    for name in ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Moon"):
        v = sorted(pos[name])
        line = f"{name:8s} {sum(v) / len(v):8.3f}° {v[int(len(v) * 0.95)]:8.3f}° {v[-1]:8.3f}°"
        if name in mag:
            m = mag[name]
            line += f"   {sum(m) / len(m):8.2f} {max(m):8.2f}"
        print(line)
    print(f"moon illuminated fraction: mean diff {sum(frac) / len(frac):.4f}  max {max(frac):.4f}")
    print(f"moon waxing flag mismatches: {wax_mismatch}/{args.samples}   phase label mismatches: {phase_mismatch}/{args.samples}")


if __name__ == "__main__":
    main()
