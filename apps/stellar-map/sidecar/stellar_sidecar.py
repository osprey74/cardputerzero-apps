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
import threading
import time
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_APP))
for p in (_REPO, os.path.join(_APP, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.star_catalog import (build_list_scene, build_plist_scene,  # noqa: E402
                                 build_pzoom_scene, build_scene, build_zoom_scene,
                                 compute_sky, julian_date, load_catalog,
                                 load_constellation_groups, load_constellation_lines,
                                 load_constellation_names, load_dso, lst_deg,
                                 radec_to_altaz)


def _now_local():
    # サイドカーは実時間で動く（デバイスでは RTC 相当）。
    return datetime.now().replace(microsecond=0)


# 個体・取付依存の永続設定（ハードアイアン較正・姿勢オフセット・観測地など）の既定パス。
# HANDOFF §3 App16 の想定に合わせた per-device 設定。CLI 引数が設定ファイルを上書きする。
_DEFAULT_CFG = os.path.expanduser("~/.config/cardputerzero/stellar_map.json")

# 設定ファイルで指定できるキー（argparse の dest 名と一致させる）。
_CFG_KEYS = {"lat", "lon", "tz", "mag_view", "mag_port", "declination",
             "heading_offset", "heading_alpha", "heading_invert", "no_tilt", "accel_gate",
             "enc_sensitivity",
             "mag_offset_x", "mag_offset_y", "mag_offset_z",
             "mag_span_x", "mag_span_y", "mag_span_z",
             "mag_ellipsoid_offset", "mag_ellipsoid_matrix"}


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


def _get_bodies(args, bcache, dt_local):
    """惑星・月を返す（bodies-interval 秒キャッシュ）。skyfield 無/--no-planets は None。"""
    if args.no_planets:
        return None
    now = time.monotonic()
    if (bcache is not None and bcache.get("bodies") is not None
            and bcache.get("t") is not None
            and now - bcache["t"] < args.bodies_interval):
        return bcache["bodies"]
    try:
        from ephem import sky_bodies
        dt_utc = dt_local - timedelta(hours=args.tz)
        bodies = sky_bodies(dt_utc, args.lat, args.lon, args.data)
        if bcache is not None:
            bcache["bodies"] = bodies
            bcache["t"] = now
        return bodies
    except Exception as ex:  # noqa: BLE001
        print(f"# planets/moon disabled (skyfield?): {ex}", file=sys.stderr)
        return None


def _bright_star_catalog(cat, groups, mag_cut=1.5):
    """1 等星（mag<=1.5 の命名星）を [{name,hip,ra,dec,mag,group}] で返す（明るい順）。

    group=その星が構成星に含まれる星座グループ（拡大時に星座線/名を出すため）。無ければ None。
    """
    hip2grp = {}
    for g in groups:
        for a, b in g["pairs"]:
            hip2grp.setdefault(a, g)
            hip2grp.setdefault(b, g)
    out, seen = [], set()
    for name, idx in getattr(cat, "named", {}).items():
        st = cat.stars[idx]
        if st.mag > mag_cut or st.hip in seen:
            continue
        seen.add(st.hip)
        out.append({"name": name, "hip": st.hip, "ra": st.ra_deg, "dec": st.dec_deg,
                    "mag": st.mag, "group": hip2grp.get(st.hip)})
    out.sort(key=lambda s: s["mag"])
    return out


def _lst_now(args, dt_local):
    dt_utc = dt_local - timedelta(hours=args.tz)
    return lst_deg(julian_date(dt_utc.year, dt_utc.month, dt_utc.day,
                               dt_utc.hour, dt_utc.minute, dt_utc.second), args.lon)


def _bodies_list(bodies):
    """bodies dict → 惑星/月リスト [{name,alt,az,mag,kind}]（PLIST/PZOOM 用）。"""
    out = []
    if not bodies:
        return out
    for p in bodies.get("planets", []):
        out.append({"name": p["name"], "alt": p["alt"], "az": p["az"],
                    "mag": p.get("mag", 0.0), "kind": "planet"})
    mo = bodies.get("moon")
    if mo:
        out.append({"name": "Moon", "alt": mo["alt"], "az": mo["az"],
                    "mag": mo.get("mag", -12.7), "kind": "moon"})
    return out


def build_once(args, cat, lines, dsos, hsrc=None, bcache=None, scache=None,
               cnames=None) -> dict:
    dt_local = datetime.fromisoformat(args.dt) if args.dt else _now_local()

    # 恒星・星座線・DSO・星座名の alt/az は heading 非依存で重い→sky-interval 秒キャッシュ。
    # 毎フレームは build_scene が alt/az→画素の投影（heading 回転）だけ回す。
    now = time.monotonic()
    if (scache is not None and scache.get("sky") is not None
            and scache.get("t") is not None
            and now - scache["t"] < args.sky_interval):
        sky = scache["sky"]
    else:
        sky = compute_sky(dt_local, args.tz, args.lat, args.lon, cat=cat,
                          lines=lines, dsos=dsos, cnames=cnames, mag_view=args.mag_view)
        if scache is not None:
            scache["sky"] = sky
            scache["t"] = now

    bodies = _get_bodies(args, bcache, dt_local)
    # 方位: ライブソース優先 → 無ければ None（未ロック時は 0=北上にフォールバック）。
    heading = hsrc.heading() if hsrc is not None else None
    if heading is None:
        heading = 0.0
    return build_scene(dt_local, args.tz, args.lat, args.lon, cat=cat,
                       lines=lines, dsos=dsos, bodies=bodies,
                       mag_view=args.mag_view, mirror_ew=args.mirror_ew,
                       heading=heading, sky=sky)


_NO_INPUT = {"red_rot": 0, "blue_rot": 0, "red_press": 0, "blue_press": 0}


class StdinNav:
    """UI（キーボード）からの操作を標準入力の行で受ける（CZ 単体・エンコーダ無し用）。

    UI がサイドカーを子プロセス起動し、キー名（enter/tab/up/down/esc）を 1 行ずつ
    stdin へ書く。パイプ運用（stdin=/dev/null）では即 EOF でスレッド終了＝無害。
    """

    def __init__(self):
        import collections
        self._q = collections.deque()
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._run, name="stdin-nav", daemon=True)
        self._t.start()

    def _run(self):
        try:
            while True:
                line = sys.stdin.readline()
                if line == "":
                    break                       # EOF
                ev = line.strip().lower()
                if ev:
                    with self._lock:
                        self._q.append(ev)
        except Exception:  # noqa: BLE001
            pass

    def drain(self):
        with self._lock:
            out = list(self._q)
            self._q.clear()
        return out


def _apply_nav(state, ev, n, m):
    """キーボードのナビ操作イベント ev で状態機械を遷移させる（エンコーダと並行）。

    enter=深く / tab=惑星リスト / up,down=カーソルor拡縮 / esc=一段戻る。
    """
    mode = state["mode"]
    if ev == "enter":
        if mode == "MAP":
            state["mode"] = "LIST"
        elif mode == "LIST" and n:
            state["selected"] = state["cursor"]
            state["czoom"] = 1.0
            state["zrot"] = 0
            state["mode"] = "ZOOM"
        elif mode == "PLIST" and m:
            state["pselected"] = state["pcursor"]
            state["pzoom"] = 1.0
            state["pzrot"] = 0
            state["mode"] = "PZOOM"
    elif ev == "tab":
        # 2 つのリストを切替（MAP/星座リスト→惑星リスト、惑星リスト→星座リスト）。
        if mode in ("MAP", "LIST"):
            state["mode"] = "PLIST"
        elif mode == "PLIST":
            state["mode"] = "LIST"
    elif ev in ("up", "down"):
        d = -1 if ev == "up" else 1
        if mode == "LIST" and n:
            state["cursor"] = (state["cursor"] + d) % n
        elif mode == "PLIST" and m:
            state["pcursor"] = (state["pcursor"] + d) % m
        elif mode == "ZOOM":
            f = 1.15 if ev == "up" else 1.0 / 1.15
            state["czoom"] = min(8.0, max(0.3, state["czoom"] * f))
        elif mode == "PZOOM":
            f = 1.15 if ev == "up" else 1.0 / 1.15
            state["pzoom"] = min(8.0, max(0.3, state["pzoom"] * f))
    elif ev == "esc":
        state["mode"] = {"ZOOM": "LIST", "LIST": "MAP",
                         "PZOOM": "PLIST", "PLIST": "MAP"}.get(mode, mode)


def build_frame(args, cat, lines, dsos, cnames, groups, bstars, hsrc, bcache, scache,
                state, nav=None):
    """Chain Encoder 入力で 5 モード遷移し、モードに応じた Scene を返す。

    星座（赤起点）: MAP --赤--> LIST（赤回転=カーソル/青=選択→ZOOM/赤=MAP）、ZOOM --青--> LIST。
    惑星（青起点・逆操作）: MAP --青--> PLIST（青回転=カーソル/赤=選択→PZOOM/青=MAP）、PZOOM --赤--> PLIST。
    """
    inp = hsrc.drain_input() if (hsrc is not None and hasattr(hsrc, "drain_input")) else _NO_INPUT
    dt_local = datetime.fromisoformat(args.dt) if args.dt else _now_local()
    n = len(groups)
    # 惑星/月 ＋ 1 等星（現在の alt/az を毎フレーム計算）を 1 つのリストに。
    blist = _bodies_list(_get_bodies(args, bcache, dt_local))
    if bstars:
        lst = _lst_now(args, dt_local)
        for bs in bstars:
            alt, az = radec_to_altaz(bs["ra"], bs["dec"], args.lat, lst)
            blist.append({"name": bs["name"], "alt": alt, "az": az, "mag": bs["mag"],
                          "kind": "star", "hip": bs["hip"], "group": bs["group"]})
    m = len(blist)
    sens = max(1, int(args.enc_sensitivity))

    # キーボード（stdin）ナビ＝エンコーダと並行に状態機械を動かす（CZ 単体対応）。
    if nav is not None:
        for ev in nav.drain():
            _apply_nav(state, ev, n, m)

    mode = state["mode"]
    if mode == "MAP":
        if inp["red_press"]:
            state["mode"] = "LIST"
        elif inp["blue_press"]:
            state["mode"] = "PLIST"
    elif mode == "LIST":
        if n:
            state["rot"] += inp["red_rot"]
            steps = int(state["rot"] / sens)
            if steps:
                state["cursor"] = (state["cursor"] + steps) % n
                state["rot"] -= steps * sens
        if inp["blue_press"] and n:
            state["selected"] = state["cursor"]
            state["czoom"] = 1.0            # 拡縮倍率リセット（画面フィットから）
            state["zrot"] = 0
            state["mode"] = "ZOOM"
        elif inp["red_press"]:
            state["mode"] = "MAP"
    elif mode == "ZOOM":
        # 青回転で拡大/縮小（目印星も同倍率）。青押下でリストへ戻る。
        state["zrot"] += inp["blue_rot"]
        zsteps = int(state["zrot"] / sens)
        if zsteps:
            state["czoom"] = min(8.0, max(0.3, state["czoom"] * (1.15 ** zsteps)))
            state["zrot"] -= zsteps * sens
        if inp["blue_press"]:
            state["mode"] = "LIST"
    elif mode == "PLIST":
        if m:
            state["prot"] += inp["blue_rot"]
            steps = int(state["prot"] / sens)
            if steps:
                state["pcursor"] = (state["pcursor"] + steps) % m
                state["prot"] -= steps * sens
        if inp["red_press"] and m:
            state["pselected"] = state["pcursor"]
            state["pzoom"] = 1.0            # 拡縮倍率リセット
            state["pzrot"] = 0
            state["mode"] = "PZOOM"
        elif inp["blue_press"]:
            state["mode"] = "MAP"
    elif mode == "PZOOM":
        # 赤回転で拡大/縮小（目印星も同倍率）。赤押下でリストへ戻る。
        state["pzrot"] += inp["red_rot"]
        psteps = int(state["pzrot"] / sens)
        if psteps:
            state["pzoom"] = min(8.0, max(0.3, state["pzoom"] * (1.15 ** psteps)))
            state["pzrot"] -= psteps * sens
        if inp["red_press"]:
            state["mode"] = "PLIST"

    mode = state["mode"]
    heading = hsrc.heading() if hsrc is not None else None
    heading = heading if heading is not None else 0.0
    if mode == "LIST":
        return build_list_scene(groups, state["cursor"], dt_local, args.tz,
                                args.lat, args.lon)
    if mode == "ZOOM" and n:
        return build_zoom_scene(groups[state["selected"]], cat, dt_local, args.tz,
                                args.lat, args.lon, heading=heading,
                                mirror_ew=args.mirror_ew, zoom_mult=state["czoom"])
    if mode == "PLIST":
        return build_plist_scene(blist, state["pcursor"], dt_local, args.tz,
                                 args.lat, args.lon)
    if mode == "PZOOM" and m:
        entry = blist[state["pselected"] % m]
        return build_pzoom_scene(entry, cat, dt_local, args.tz, args.lat, args.lon,
                                 heading=heading, mirror_ew=args.mirror_ew,
                                 zoom=6.0 * state["pzoom"], group=entry.get("group"))
    return build_once(args, cat, lines, dsos, hsrc, bcache, scache, cnames)


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
                                   span_z=args.mag_span_z,
                                   ell_offset=getattr(args, "mag_ellipsoid_offset", None),
                                   ell_matrix=getattr(args, "mag_ellipsoid_matrix", None),
                                   accel_gate=args.accel_gate)
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
    ap.add_argument("--bodies-interval", type=float, default=10.0,
                    help="惑星・月の再計算間隔[秒]（Skyfield は重いので低頻度キャッシュ）")
    ap.add_argument("--sky-interval", type=float, default=10.0,
                    help="恒星・星座線・DSO の alt/az 再計算間隔[秒]（heading 回転を軽くする）")
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
    ap.add_argument("--accel-gate", type=float, default=0.12,
                    help="動作中(|a|が1gからこの幅[g]超で外れる)は heading 更新を止める。0で無効")
    ap.add_argument("--enc-sensitivity", type=float, default=2.0,
                    help="星座リストのカーソル移動感度（この回転カウントで1行進む）")
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
    cnames = load_constellation_names(args.data, cat)
    groups = load_constellation_groups(args.data, cat)
    bstars = _bright_star_catalog(cat, groups)   # 1 等星（リストに追加・星座所属付き）
    dsos, _n, _m = load_dso(args.data)

    hsrc = make_heading_source(args)
    bcache: dict = {"bodies": None, "t": None}   # 惑星・月の低頻度キャッシュ
    scache: dict = {"sky": None, "t": None}      # 恒星・星座線・DSO の alt/az キャッシュ
    state = {"mode": "MAP", "cursor": 0, "selected": 0, "rot": 0,   # 星座（赤）
             "czoom": 1.0, "zrot": 0,                               # 星座拡大の拡縮
             "pcursor": 0, "pselected": 0, "prot": 0,               # 惑星/月（青）
             "pzoom": 1.0, "pzrot": 0}                              # 惑星拡大の拡縮
    nav = StdinNav()   # UI（キーボード）からの操作を stdin で受ける（CZ 単体対応）
    try:
        if args.interval and args.interval > 0:
            while True:
                sys.stdout.write(json.dumps(
                    build_frame(args, cat, lines, dsos, cnames, groups, bstars,
                                hsrc, bcache, scache, state, nav),
                    separators=(",", ":")) + "\n")
                sys.stdout.flush()
                time.sleep(args.interval)
        else:
            sys.stdout.write(json.dumps(
                build_frame(args, cat, lines, dsos, cnames, groups, bstars,
                            hsrc, bcache, scache, state, nav),
                separators=(",", ":")) + "\n")
    finally:
        if hsrc is not None:
            hsrc.close()


if __name__ == "__main__":
    main()
