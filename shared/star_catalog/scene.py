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
        "labels": labels,
        "meta": {
            "time_local": dt_local.strftime("%Y-%m-%d %H:%M"),
            "tz": tz, "lat": lat, "lon": lon, "mag_view": mag_view,
            "mirror_ew": mirror_ew, "heading": round(heading % 360.0, 1),
            "moon": moon_meta,
            "counts": {"stars": len(sky["stars"]), "lines": len(out_lines),
                       "dso": len(dso_pts), "planets": planets_n},
        },
    }
