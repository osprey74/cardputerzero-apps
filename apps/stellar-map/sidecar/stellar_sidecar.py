#!/usr/bin/env python3
"""App 16 星座盤 ― Python サイドカー（Scene JSON 出力）。

天体計算・投影・色/サイズ決定を Python 側で行い、320×170 のデバイス座標プリミティブ
（Scene）を JSON 1 行で stdout に出す。Rust/LVGL UI はこれを読んで四角・線・文字を
描くだけ（薄い実装）。

CardputerZero 実機では: 時刻=RTC(RX8130CE)/NTP/GNSS、位置=AT6668 GNSS、方位=内蔵
BMM150 を入力にして本サイドカーが Scene を吐き、Rust UI が描画する構成。実機到着前は
方位を CoreS3 の BMM150（USB CDC）で先行検証する（--mag-port）。

方式A（自機の向きを画面上=12 時方向に固定して全天図を回転）:
  --heading D   固定方位 D[deg] で回転（回転の見え方を PC 確認）
  --mag-port P  CoreS3 の BMM150 をライブ読取して回転（未指定なら OS 既定ポート）

使い方:
  python stellar_sidecar.py                      # 現在時刻・札幌の Scene を 1 行 JSON 出力
  python stellar_sidecar.py --dt 2026-07-08T03:30 --lat 35.68 --lon 139.77
  python stellar_sidecar.py --interval 30        # 30 秒ごとに 1 行ずつ出力（JSON Lines）
  python stellar_sidecar.py --heading 120        # 方位 120° を上に固定して静止描画
  python stellar_sidecar.py --interval 1 --mag-port COM5 --declination -9  # CoreS3 実方位で回転
  python stellar_sidecar.py --interval 0.2       # 較正/取付は ~/.config/cardputerzero/stellar_map.json から
  python stellar_sidecar.py --no-planets --mag-view 4.0

個体・取付依存の設定（ハードアイアン較正・姿勢オフセット・観測地・ポート）は
JSON 設定ファイル（既定 ~/.config/cardputerzero/stellar_map.json）に置ける。
CLI 引数が設定ファイルを上書きする。例は config/stellar_map.json.example。

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


# 個体・取付依存の永続設定（ハードアイアン較正・姿勢オフセット・観測地など）の既定パス。
# HANDOFF §3 App16 の想定に合わせた per-device 設定。CLI 引数が設定ファイルを上書きする。
_DEFAULT_CFG = os.path.expanduser("~/.config/cardputerzero/stellar_map.json")

# 設定ファイルで指定できるキー（argparse の dest 名と一致させる）。
_CFG_KEYS = {"lat", "lon", "tz", "mag_view", "mag_port", "declination",
             "heading_offset", "heading_alpha", "heading_invert", "no_tilt",
             "mag_offset_x", "mag_offset_y", "mag_offset_z",
             "mag_span_x", "mag_span_y", "mag_span_z"}


def _load_config(argv) -> tuple[dict, str]:
    """`--config <path>`（無ければ既定パス）から JSON 設定を読む。無ければ空 dict。"""
    path = _DEFAULT_CFG
    if "--config" in argv:
        i = argv.index("--config")
        if i + 1 < len(argv):
            path = os.path.expanduser(argv[i + 1])
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return {k: v for k, v in data.items() if k in _CFG_KEYS}, path
        except Exception as ex:  # noqa: BLE001
            print(f"# config load failed {path}: {ex}", file=sys.stderr)
    return {}, path


def build_once(args, cat, lines, dsos, hsrc=None) -> dict:
    dt_local = datetime.fromisoformat(args.dt) if args.dt else _now_local()
    bodies = None
    if not args.no_planets:
        try:
            from ephem import sky_bodies
            dt_utc = dt_local - timedelta(hours=args.tz)
            bodies = sky_bodies(dt_utc, args.lat, args.lon, args.data)
        except Exception as ex:  # noqa: BLE001
            print(f"# planets/moon disabled (skyfield?): {ex}", file=sys.stderr)
    # 方位: ライブソース優先 → 無ければ None（未ロック時は 0=北上にフォールバック）。
    heading = hsrc.heading() if hsrc is not None else None
    if heading is None:
        heading = 0.0
    return build_scene(dt_local, args.tz, args.lat, args.lon, cat=cat,
                       lines=lines, dsos=dsos, bodies=bodies,
                       mag_view=args.mag_view, mirror_ew=args.mirror_ew,
                       heading=heading)


def make_heading_source(args):
    """--mag-port / --heading から方位ソースを組む（無ければ None）。"""
    from heading_source import CoreS3HeadingSource, FixedHeadingSource
    if args.mag_port is not None:
        port = args.mag_port or None      # 空文字なら OS 既定ポート
        return CoreS3HeadingSource(port, alpha=args.heading_alpha,
                                   declination=args.declination,
                                   zero_offset=args.heading_offset,
                                   invert=args.heading_invert,
                                   use_tilt=not args.no_tilt,
                                   offset_x=args.mag_offset_x,
                                   offset_y=args.mag_offset_y,
                                   offset_z=args.mag_offset_z,
                                   span_x=args.mag_span_x,
                                   span_y=args.mag_span_y,
                                   span_z=args.mag_span_z)
    if args.heading is not None:
        return FixedHeadingSource(args.heading + args.heading_offset + args.declination)
    return None


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
    # 方式A: 自機の向きを画面上に固定する方位入力。
    ap.add_argument("--heading", type=float, default=None,
                    help="固定方位[deg]で回転（北=0・東回り）。--mag-port 未指定時に有効")
    ap.add_argument("--mag-port", nargs="?", const="", default=None,
                    help="CoreS3 BMM150 をライブ読取して回転。値省略で OS 既定ポート")
    ap.add_argument("--declination", type=float, default=0.0,
                    help="磁気偏角[deg]（磁北→真北。西偏はマイナス。例 札幌 -9）")
    ap.add_argument("--heading-offset", type=float, default=0.0,
                    help="センサ取付角オフセット[deg]")
    ap.add_argument("--heading-alpha", type=float, default=0.2,
                    help="方位 EMA 係数（大きいほど追従速・雑音増）")
    ap.add_argument("--heading-invert", action="store_true",
                    help="方位の回転向きを反転")
    ap.add_argument("--no-tilt", action="store_true",
                    help="傾き補正を無効化（加速度があっても水平前提で heading を出す）")
    # ハード/ソフトアイアン較正（calib_probe.py の推定値。両 offset 指定で x/y 補正が有効）。
    ap.add_argument("--mag-offset-x", type=float, default=None, help="ハードアイアン中心 x")
    ap.add_argument("--mag-offset-y", type=float, default=None, help="ハードアイアン中心 y")
    ap.add_argument("--mag-span-x", type=float, default=1.0, help="360deg x 半スパン(soft-iron)")
    ap.add_argument("--mag-span-y", type=float, default=1.0, help="360deg y 半スパン(soft-iron)")
    ap.add_argument("--mag-offset-z", type=float, default=0.0, help="ハードアイアン中心 z（傾き補正用・3D較正）")
    ap.add_argument("--mag-span-z", type=float, default=None, help="3D z 半スパン（未指定は x/y 平均）")
    ap.add_argument("--config", default=_DEFAULT_CFG,
                    help=f"個体設定 JSON（既定 {_DEFAULT_CFG}）。CLI 引数がこれを上書き")
    # 設定ファイルの値を argparse の既定に流し込む（＝CLI 未指定なら設定値、指定あれば CLI 優先）。
    cfg, cfg_path = _load_config(sys.argv)
    if cfg:
        ap.set_defaults(**cfg)
        print(f"# config loaded: {cfg_path} ({', '.join(sorted(cfg))})", file=sys.stderr)
    args = ap.parse_args()

    # カタログ類は一度だけロード（惑星・月は毎フレーム再計算）。
    cat = load_catalog(args.data)
    lines = load_constellation_lines(args.data)
    dsos, _n, _m = load_dso(args.data)

    hsrc = make_heading_source(args)
    try:
        if args.interval and args.interval > 0:
            while True:
                sys.stdout.write(json.dumps(build_once(args, cat, lines, dsos, hsrc),
                                            separators=(",", ":")) + "\n")
                sys.stdout.flush()
                time.sleep(args.interval)
        else:
            sys.stdout.write(json.dumps(build_once(args, cat, lines, dsos, hsrc),
                                        separators=(",", ":")) + "\n")
    finally:
        if hsrc is not None:
            hsrc.close()


if __name__ == "__main__":
    main()
