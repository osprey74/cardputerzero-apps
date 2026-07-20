"""星座盤の「シーン」ビルダー ― 時刻・地点から 320×170 のデバイス座標プリミティブを組む。

App 16 のアーキテクチャ（Python サイドカー ＋ Rust/LVGL UI）の中核。天体計算・投影・
色/サイズ決定は**すべて Python 側（本モジュール）**で行い、320×170 のデバイス画素座標に
落とした「描画プリミティブの集合（Scene）」を返す。UI（Rust/LVGL）は Scene を受け取って
四角・線・文字を描くだけの薄い実装になる。

Scene は JSON 化して stdout でサイドカーが吐き、UI が読む（`sidecar/stellar_sidecar.py`）。
PC 検証は `tools/render_scene.py`（Pillow で同じ Scene を描く）。

座標系: 左 170×170 が円形全天図（中心=天頂 / 外周=地平線 / 北=上）、右 150×170 は UI が
`meta` から情報パネルを描く。地平線下の星・線・天体は Scene に含めない（UI は描くだけ）。
"""
from __future__ import annotations

from .transform import altaz_to_plot_xy, julian_date, lst_deg, radec_to_altaz

# デバイス寸法・レイアウト（実機 LCD と同一）。
W, H = 320, 170
CX, CY, R = 85, 85, 80

# 配色（osprey74・[r,g,b]）。実機描画は四角＋AA無しが最良（HANDOFF §App16 決定）。
COL_DIR = [255, 165, 0]
COL_HORIZON = [60, 66, 70]
COL_LINE = [40, 90, 110]
COL_CNAME = [120, 130, 110]     # 星座名ラベル（くすんだ黄緑灰・控えめ）
COL_DSO = [200, 120, 200]
COL_PLANET = [255, 215, 120]
COL_MOON = [225, 225, 205]
COL_STAR1 = [255, 255, 255]     # 1 等星
COL_STAR2 = [150, 220, 255]     # 2 等星
COL_STAR3 = [110, 140, 180]     # 3 等以下


def _star_color(mag: float):
    return COL_STAR1 if mag <= 1.5 else COL_STAR2 if mag <= 2.5 else COL_STAR3


def _star_side(mag: float) -> int:
    return 3 if mag <= 1.5 else 2 if mag <= 2.5 else 1


def compute_sky(dt_local, tz: float, lat: float, lon: float, *,
                cat, lines=None, dsos=None, cnames=None, mag_view: float = 4.5) -> dict:
    """時刻・地点から可視天体の地平座標 (alt/az) を計算する（**heading 非依存**）。

    赤道→地平座標変換は全恒星ぶんで重い一方、alt/az は heading に依らず時刻・地点だけで
    決まる（地平線下の除外も heading 非依存）。そこで本関数の結果を数秒キャッシュし、
    毎フレームの `build_scene` は安価な「alt/az → 画素」投影だけを回す（App16 方式A の
    heading 回転を軽くする）。恒星は日周運動で ~0.25°/分 と遅く、キャッシュ間隔での
    ずれは表示画素以下。
    """
    from datetime import timedelta
    dt_utc = dt_local - timedelta(hours=tz)
    jd = julian_date(dt_utc.year, dt_utc.month, dt_utc.day,
                     dt_utc.hour, dt_utc.minute, dt_utc.second)
    lst = lst_deg(jd, lon)

    sky_lines = []
    if lines:
        for ha, hb in lines:
            sa, sb = cat.by_hip(ha), cat.by_hip(hb)
            if not sa or not sb:
                continue
            aa, za = radec_to_altaz(sa.ra_deg, sa.dec_deg, lat, lst)
            ab, zb = radec_to_altaz(sb.ra_deg, sb.dec_deg, lat, lst)
            if aa < 0 or ab < 0:
                continue
            sky_lines.append((aa, za, ab, zb))

    sky_stars = []
    for st in cat.stars:
        if st.mag > mag_view:
            continue
        alt, az = radec_to_altaz(st.ra_deg, st.dec_deg, lat, lst)
        if alt < 0:
            continue
        sky_stars.append((alt, az, _star_side(st.mag), _star_color(st.mag)))

    sky_dso = []
    if dsos:
        for o in dsos:
            alt, az = radec_to_altaz(o.ra_deg, o.dec_deg, lat, lst)
            if alt < 0:
                continue
            sky_dso.append((alt, az))

    sky_cnames = []
    if cnames:
        for label, ra, dec in cnames:
            alt, az = radec_to_altaz(ra, dec, lat, lst)
            if alt < 0:
                continue
            sky_cnames.append((alt, az, label))

    return {"lines": sky_lines, "stars": sky_stars, "dso": sky_dso,
            "cnames": sky_cnames}


def build_scene(dt_local, tz: float, lat: float, lon: float, *,
                cat=None, lines=None, dsos=None, cnames=None, bodies=None,
                mag_view: float = 4.5, mirror_ew: bool = False,
                heading: float = 0.0, sky=None) -> dict:
    """Scene 辞書を返す。座標は 320×170 の整数デバイス画素。

    ``sky`` に `compute_sky()` の結果を渡すと再計算を省く（毎フレームの heading 回転を
    軽くするキャッシュ経路）。未指定なら内部で `compute_sky()` を呼ぶ（後方互換）。
    heading[deg]（自機の向く方位角・北=0・東回り）でその方位を画面上（12 時）に固定。

    恒星・星座線・DSO は `sky`（alt/az・地平線下除外済み）から投影。惑星・月は `bodies`
    （ephem.sky_bodies の alt/az）から投影。DSO は UI 側で ON/OFF 切替できるよう
    ``points`` とは別の ``dso`` 配列に出す（恒星/惑星/月は ``points``）。
    """
    if sky is None:
        sky = compute_sky(dt_local, tz, lat, lon, cat=cat, lines=lines,
                          dsos=dsos, cnames=cnames, mag_view=mag_view)

    def proj_altaz(alt, az):
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew, heading)
        return round(x), round(y)

    out_lines = []
    for aa, za, ab, zb in sky["lines"]:
        xa, ya = proj_altaz(aa, za)
        xb, yb = proj_altaz(ab, zb)
        out_lines.append([xa, ya, xb, yb])

    # DSO は独立配列（UI トグル用）。[x, y, side, r, g, b]。
    dso_pts = []
    for alt, az in sky["dso"]:
        x, y = proj_altaz(alt, az)
        dso_pts.append([x, y, 2, *COL_DSO])

    # 星座名ラベル（UI トグル用・独立配列）。[x, y, text]。
    clabels = []
    for alt, az, label in sky.get("cnames", []):
        x, y = proj_altaz(alt, az)
        clabels.append([x, y, label])

    # points: [x, y, side, r, g, b]。恒星→惑星→月（後ほど上に載る）。
    points = []
    for alt, az, side, col in sky["stars"]:
        x, y = proj_altaz(alt, az)
        points.append([x, y, side, *col])

    labels = []
    planets_n = 0
    moon_meta = None
    if bodies:
        for p in bodies.get("planets", []):
            if p["alt"] < 0:
                continue
            planets_n += 1
            x, y = proj_altaz(p["alt"], p["az"])
            side = max(2, _star_side(p["mag"]))
            points.append([x, y, side, *COL_PLANET])
            labels.append([x + 3, y - 4, p["name"], *COL_PLANET])
        mo = bodies.get("moon")
        if mo:
            moon_meta = {"frac": mo["frac"], "waxing": mo["waxing"], "phase": mo["phase"]}
            if mo["alt"] >= 0:
                x, y = proj_altaz(mo["alt"], mo["az"])
                points.append([x, y, 3, *COL_MOON])
                labels.append([x + 3, y - 4, "Moon", *COL_MOON])

    # 方位ラベルは地平線 (alt=0) 上の各基本方位を投影して置く。こうすると
    # heading 回転・mirror_ew を投影側と同一ロジックで自動追従できる。
    chrome_dirs = []
    for t, az in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
        x, y = altaz_to_plot_xy(0.0, az, CX, CY, R + 3, mirror_ew, heading)
        chrome_dirs.append([round(x) - 3, round(y) - 5, t])

    return {
        "w": W, "h": H,
        "chrome": {"circle": [CX, CY, R], "circle_color": COL_HORIZON,
                   "dir_color": COL_DIR, "dirs": chrome_dirs},
        "lines": out_lines, "line_color": COL_LINE,
        "dso": dso_pts,
        "cnames": clabels, "cname_color": COL_CNAME,
        "points": points,
        "crosses": [],
        "labels": labels,
        "rects": [],
        "meta": {
            "time_local": dt_local.strftime("%Y-%m-%d %H:%M"),
            "tz": tz, "lat": lat, "lon": lon, "mag_view": mag_view,
            "mirror_ew": mirror_ew, "heading": round(heading % 360.0, 1),
            "mode": "MAP", "moon": moon_meta,
            "counts": {"stars": len(sky["stars"]), "lines": len(out_lines),
                       "dso": len(dso_pts), "planets": planets_n},
        },
    }


# 星座リスト/拡大表示 UI（App16・Chain Encoder 操作）の配色。
COL_LIST_HI = [38, 66, 104]      # カーソル行のハイライト背景
COL_LIST_TXT = [205, 215, 230]   # カーソル行の文字
COL_LIST_DIM = [120, 132, 148]   # 非カーソル行の文字
COL_LIST_HDR = [79, 195, 247]    # 見出し（アクセント）
COL_HINT = [130, 132, 110]       # 操作ヒント


def _meta(dt_local, tz, lat, lon, mode, **extra):
    m = {"time_local": dt_local.strftime("%Y-%m-%d %H:%M"), "tz": tz,
         "lat": lat, "lon": lon, "mag_view": 0.0, "mirror_ew": False,
         "heading": 0.0, "mode": mode, "moon": None,
         "counts": {"stars": 0, "lines": 0, "dso": 0, "planets": 0}}
    m.update(extra)
    return m


def _empty_chrome():
    # 円・方位を描かない（LIST/ZOOM 用）。UI は circle 半径<=0 で地平線円を省く。
    return {"circle": [CX, CY, 0], "circle_color": COL_HORIZON,
            "dir_color": COL_DIR, "dirs": []}


def build_list_scene(groups, cursor, dt_local, tz, lat, lon, *,
                     visible: int = 11, row_h: int = 12, top: int = 18) -> dict:
    """星座リスト画面の Scene。cursor 行をハイライトしスクロール表示。

    各星座の重心が地平線上なら "up"、下なら "--" を行頭に表示（惑星リストと同様）。
    """
    labels = [[6, 3, "CONSTELLATIONS", *COL_LIST_HDR]]
    rects = []
    lst = _lst_for(dt_local, tz, lon)
    n = len(groups)
    if n:
        cursor %= n
        start = max(0, min(cursor - visible // 2, max(0, n - visible)))
        for i in range(min(visible, n - start)):
            idx = start + i
            g = groups[idx]
            y = top + i * row_h
            up = "  "
            if g.get("ra") is not None:
                alt, _az = radec_to_altaz(g["ra"], g["dec"], lat, lst)
                up = "up" if alt >= 0 else "--"
            text = ("%s %s %s" % (up, g["iau"], g.get("latin") or g["name"]))[:36]
            if idx == cursor:
                rects.append([2, y - 1, 316, row_h, *COL_LIST_HI])
                labels.append([6, y, text, *COL_LIST_TXT])
            else:
                labels.append([6, y, text, *COL_LIST_DIM])
        sel = groups[cursor].get("latin") or groups[cursor]["iau"]
    else:
        labels.append([6, top, "(no data)", *COL_LIST_DIM])
        sel = ""
    labels.append([6, H - 10, "RED:back  turn:move  BLUE:zoom", *COL_HINT])
    return {"w": W, "h": H, "chrome": _empty_chrome(),
            "lines": [], "line_color": COL_LINE, "dso": [],
            "cnames": [], "cname_color": COL_CNAME, "points": [], "crosses": [],
            "labels": labels, "rects": rects,
            "meta": _meta(dt_local, tz, lat, lon, "LIST",
                          cursor=cursor + 1 if n else 0, total=n, sel=sel)}


def _lst_for(dt_local, tz, lon):
    from datetime import timedelta
    dt_utc = dt_local - timedelta(hours=tz)
    jd = julian_date(dt_utc.year, dt_utc.month, dt_utc.day,
                     dt_utc.hour, dt_utc.minute, dt_utc.second)
    return lst_deg(jd, lon)


def _bright_landmarks(cat, lst, lat, heading, mirror_ew, tf, exclude=None,
                      mag_cut: float = 2.5):
    """明るい星(mag<=mag_cut)を投影→tf で画面座標化→画面内のものを目印として返す。

    返り値 (crosses, dots): crosses=1等星(<=1.5) の [x,y,r,g,b]（UI が 3×3 十字を描く）、
    dots=2等星(<=2.5) の [x,y,side=1,r,g,b]（1 ドット）。exclude=除外 HIP 集合（星座の
    構成星など）。cat.stars は等級昇順なので mag_cut 超で打ち切り。
    """
    exclude = exclude or set()
    crosses, dots = [], []
    for st in cat.stars:
        if st.mag > mag_cut:
            break
        if st.hip in exclude:
            continue
        alt, az = radec_to_altaz(st.ra_deg, st.dec_deg, lat, lst)
        if alt < 0:
            continue
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew, heading)
        nx, ny = tf(x, y)
        if 0 <= nx < W and 0 <= ny < H:
            col = _star_color(st.mag)
            if st.mag <= 1.5:
                crosses.append([nx, ny, *col])      # 1 等星 = 3×3 十字
            else:
                dots.append([nx, ny, 1, *col])       # 2 等星 = 1 ドット
    return crosses, dots


def build_zoom_scene(group, cat, dt_local, tz, lat, lon, *,
                     heading: float = 0.0, mirror_ew: bool = False) -> dict:
    """選択星座を「今見えている角度で」拡大した Scene（＋目印の明るい星）。

    構成星を地平投影→bbox を画面いっぱいへ拡大平行移動（回転は保持）。さらに星座に
    含まれない 1・2 等星を同じ変換で投影し、探す目安として 1等=十字/2等=点で重ねる。
    """
    lst = _lst_for(dt_local, tz, lon)
    pts = {}
    for hip in {h for pair in group["pairs"] for h in pair}:
        st = cat.by_hip(hip)
        if st is None:
            continue
        alt, az = radec_to_altaz(st.ra_deg, st.dec_deg, lat, lst)
        x, y = altaz_to_plot_xy(alt, az, CX, CY, R, mirror_ew, heading)
        pts[hip] = (x, y, st.mag)

    name = group.get("latin") or group["name"] or group["iau"]
    labels = [[6, 3, "%s %s" % (group["iau"], name), *COL_LIST_HDR],
              [6, H - 10, "BLUE:back to list", *COL_HINT]]
    if len(pts) < 2:
        return {"w": W, "h": H, "chrome": _empty_chrome(),
                "lines": [], "line_color": COL_LINE, "dso": [],
                "cnames": [], "cname_color": COL_CNAME, "points": [], "crosses": [],
                "labels": labels, "rects": [],
                "meta": _meta(dt_local, tz, lat, lon, "ZOOM", sel=name)}

    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    cx0, cy0 = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    bw, bh = max(maxx - minx, 1e-3), max(maxy - miny, 1e-3)
    scale = max(0.5, min(min(300.0 / bw, 148.0 / bh), 24.0))
    tcx, tcy = 160.0, 88.0

    def tf(x, y):
        return round(tcx + scale * (x - cx0)), round(tcy + scale * (y - cy0))

    tp = {h: tf(x, y) for h, (x, y, _m) in pts.items()}
    out_lines = []
    for a, b in group["pairs"]:
        if a in tp and b in tp:
            out_lines.append([tp[a][0], tp[a][1], tp[b][0], tp[b][1]])
    # 目印星（構成星は除外）。dots は points に、crosses は crosses 配列に。
    crosses, dots = _bright_landmarks(cat, lst, lat, heading, mirror_ew, tf,
                                      exclude=set(pts.keys()))
    points = list(dots)
    for h, (x, y, mag) in pts.items():
        nx, ny = tp[h]
        points.append([nx, ny, max(2, _star_side(mag) + 1), *_star_color(mag)])
    return {"w": W, "h": H, "chrome": _empty_chrome(),
            "lines": out_lines, "line_color": COL_LINE, "dso": [],
            "cnames": [], "cname_color": COL_CNAME, "points": points,
            "crosses": crosses, "labels": labels, "rects": [],
            "meta": _meta(dt_local, tz, lat, lon, "ZOOM", sel=name)}


def build_plist_scene(bodies_list, cursor, dt_local, tz, lat, lon, *,
                      visible: int = 11, row_h: int = 12, top: int = 18) -> dict:
    """惑星・月リスト画面の Scene。bodies_list=[{"name","alt","az","mag","kind"}...]。"""
    labels = [[6, 3, "PLANETS & MOON", *COL_LIST_HDR]]
    rects = []
    n = len(bodies_list)
    if n:
        cursor %= n
        start = max(0, min(cursor - visible // 2, max(0, n - visible)))
        for i in range(min(visible, n - start)):
            idx = start + i
            b = bodies_list[idx]
            y = top + i * row_h
            up = "up" if b["alt"] >= 0 else "--"
            text = ("%-8s %s" % (b["name"], up))[:36]
            if idx == cursor:
                rects.append([2, y - 1, 316, row_h, *COL_LIST_HI])
                labels.append([6, y, text, *COL_LIST_TXT])
            else:
                labels.append([6, y, text, *COL_LIST_DIM])
        sel = bodies_list[cursor]["name"]
    else:
        labels.append([6, top, "(planets unavailable)", *COL_LIST_DIM])
        sel = ""
    labels.append([6, H - 10, "BLUE:back  turn:move  RED:zoom", *COL_HINT])
    return {"w": W, "h": H, "chrome": _empty_chrome(),
            "lines": [], "line_color": COL_LINE, "dso": [],
            "cnames": [], "cname_color": COL_CNAME, "points": [], "crosses": [],
            "labels": labels, "rects": rects,
            "meta": _meta(dt_local, tz, lat, lon, "PLIST",
                          cursor=cursor + 1 if n else 0, total=n, sel=sel)}


def build_pzoom_scene(body, cat, dt_local, tz, lat, lon, *,
                      heading: float = 0.0, mirror_ew: bool = False,
                      zoom: float = 6.0) -> dict:
    """選択した惑星/月を中心に据えた拡大 Scene（＋目印の明るい星）。

    body={"name","alt","az","kind"}。天体を画面中央に置き固定倍率 zoom で拡大、
    周囲の 1・2 等星を目印として 1等=十字/2等=点で描く（探す目安）。
    """
    lst = _lst_for(dt_local, tz, lon)
    name = body["name"]
    labels = [[6, 3, name, *COL_LIST_HDR],
              [6, H - 10, "RED:back to list", *COL_HINT]]
    bx, by = altaz_to_plot_xy(body["alt"], body["az"], CX, CY, R, mirror_ew, heading)
    tcx, tcy = 160.0, 88.0

    def tf(x, y):
        return round(tcx + zoom * (x - bx)), round(tcy + zoom * (y - by))

    crosses, dots = _bright_landmarks(cat, lst, lat, heading, mirror_ew, tf)
    points = list(dots)
    # 天体本体（惑星=ゴールド/月=淡白）を中央に大きめで。
    col = COL_MOON if body.get("kind") == "moon" else COL_PLANET
    points.append([160, 88, 3, *col])
    labels.insert(1, [166, 84, name, *col])
    return {"w": W, "h": H, "chrome": _empty_chrome(),
            "lines": [], "line_color": COL_LINE, "dso": [],
            "cnames": [], "cname_color": COL_CNAME, "points": points,
            "crosses": crosses, "labels": labels, "rects": [],
            "meta": _meta(dt_local, tz, lat, lon, "PZOOM", sel=name)}
