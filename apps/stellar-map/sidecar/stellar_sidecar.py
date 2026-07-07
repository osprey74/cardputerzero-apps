#!/usr/bin/env python3
"""App 16 星座盤 ― Python サイドカー（Scene JSON 出力）。

天体計算・投影・色/サイズ決定を Python 側で行い、320×170 のデバイス座標プリミティブ
（Scene）を JSON 1 行で stdout に出す。Rust/LVGL UI はこれを読んで四角・線・文字を
描くだけ（薄い実装）。

CardputerZero 実機では: 時刻=RTC(RX8130CE)/NTP/GNSS、位置=AT6668 GNSS、方位=CoreS3 の
BMM150（USB CDC）を入力にして本サイドカーが Scene を吐き、Rust UI が描画する構成。

使い方:
  python stellar_sidecar.py                      # 現在時刻・札幌の Scene を 1 行 JSON 出力
  python stellar_sidecar.py --dt 2026-07-08T03:30 --lat 35.68 --lon 139.77
  python stellar_sidecar.py --interval 30        # 30 秒ごとに 1 行ずつ出力（JSON Lines）
  python stellar_sidecar.py --no-planets --mag-view 4.0

出力は JSON Lines（1 フレーム=1 行）。UI 側は行単位で読み最新フレームを描く。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_APP))
for p in (_REPO, os.path.join(_APP, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.star_catalog import (build_scene, load_catalog,  # noqa: E402
                                 load_constellation_lines, load_dso)


def _now_local():
    # サイドカーは実時間で動く（デバイスでは RTC 相当）。
    return datetime.now().replace(microsecond=0)


def build_once(args, cat, lines, dsos) -> dict:
    dt_local = datetime.fromisoformat(args.dt) if args.dt else _now_local()
    bodies = None
    if not args.no_planets:
        try:
            from ephem import sky_bodies
            dt_utc = dt_local - timedelta(hours=args.tz)
            bodies = sky_bodies(dt_utc, args.lat, args.lon, args.data)
        except Exception as ex:  # noqa: BLE001
            print(f"# planets/moon disabled (skyfield?): {ex}", file=sys.stderr)
    return build_scene(dt_local, args.tz, args.lat, args.lon, cat=cat,
                       lines=lines, dsos=dsos, bodies=bodies,
                       mag_view=args.mag_view, mirror_ew=args.mirror_ew)


def main() -> None:
    ap = argparse.ArgumentParser(description="App16 星座盤 サイドカー (Scene JSON)")
    ap.add_argument("--data", default=os.path.join(_APP, "data"),
                    help="stars.bin 等のあるディレクトリ")
    ap.add_argument("--lat", type=float, default=43.06)
    ap.add_argument("--lon", type=float, default=141.35)
    ap.add_argument("--dt", default=None, help="ローカル日時 ISO（未指定なら現在時刻）")
    ap.add_argument("--tz", type=float, default=9.0)
    ap.add_argument("--mag-view", type=float, default=4.5)
    ap.add_argument("--mirror-ew", action="store_true")
    ap.add_argument("--no-planets", action="store_true")
    ap.add_argument("--interval", type=float, default=0.0,
                    help="秒。>0 でこの間隔でフレームを繰り返し出力（JSON Lines）")
    args = ap.parse_args()

    # カタログ類は一度だけロード（惑星・月は毎フレーム再計算）。
    cat = load_catalog(args.data)
    lines = load_constellation_lines(args.data)
    dsos, _n, _m = load_dso(args.data)

    if args.interval and args.interval > 0:
        while True:
            sys.stdout.write(json.dumps(build_once(args, cat, lines, dsos),
                                        separators=(",", ":")) + "\n")
            sys.stdout.flush()
            time.sleep(args.interval)
    else:
        sys.stdout.write(json.dumps(build_once(args, cat, lines, dsos),
                                    separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
