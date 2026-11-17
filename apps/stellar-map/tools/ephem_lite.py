"""App 16 星座盤 ― 惑星・月・月相の軽量計算（標準ライブラリのみ・暦ファイル不要）。

`ephem.py`（Skyfield＋JPL DE421）と同じ `sky_bodies()` インタフェースを、軌道要素と
主要な摂動項による解析式で実装する。CardputerZero 実機では Skyfield の導入が重い
（apt では 80 個超の依存・DE421 は 16MB）ため、追加パッケージ無しで惑星・月を出す用途。

方式は Paul Schlyter "How to compute planetary positions" の定式:
  - 太陽・月・水金火木土の軌道要素（日付の黄道・平均春分点基準）からケプラー方程式を解く
  - 月は主要な摂動 12 項（黄経）・5 項（黄緯）・2 項（距離）、木星・土星は相互摂動を加える
  - 月は地心視差（最大約 1°）を高度に反映する
精度の目安は惑星で数分角、月で 0.1〜0.3° 程度。320×170（全天図で 1 画素≒1°強）の表示には
十分で、`tools/compare_ephem.py` で Skyfield と突き合わせて確認している。

返り値の形式は `ephem.sky_bodies()` と同じ:
  {"planets": [{"name","alt","az","mag"}...], "moon": {"alt","az","frac","waxing","phase","mag"}}
"""
from __future__ import annotations

import math

_R = math.pi / 180.0


def _sin(d):
    return math.sin(d * _R)


def _cos(d):
    return math.cos(d * _R)


def _atan2(y, x):
    return math.atan2(y, x) / _R


def _rev(d):
    return d % 360.0


def _day_number(dt_utc) -> float:
    """2000 Jan 0.0 UT からの日数（Schlyter の d。JD − 2451543.5）。"""
    y, m, dd = dt_utc.year, dt_utc.month, dt_utc.day
    d = 367 * y - (7 * (y + (m + 9) // 12)) // 4 + (275 * m) // 9 + dd - 730530
    return d + (dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0) / 24.0


# 軌道要素: (N0, N1, i0, i1, w0, w1, a, e0, e1, M0, M1)  ※ deg と deg/day、a は AU（月は地球半径）
_ELEMENTS = {
    "Sun":     (0.0, 0.0, 0.0, 0.0, 282.9404, 4.70935e-5, 1.0, 0.016709, -1.151e-9, 356.0470, 0.9856002585),
    "Moon":    (125.1228, -0.0529538083, 5.1454, 0.0, 318.0634, 0.1643573223, 60.2666, 0.054900, 0.0,
                115.3654, 13.0649929509),
    "Mercury": (48.3313, 3.24587e-5, 7.0047, 5.00e-8, 29.1241, 1.01444e-5, 0.387098, 0.205635, 5.59e-10,
                168.6562, 4.0923344368),
    "Venus":   (76.6799, 2.46590e-5, 3.3946, 2.75e-8, 54.8910, 1.38374e-5, 0.723330, 0.006773, -1.302e-9,
                48.0052, 1.6021302244),
    "Mars":    (49.5574, 2.11081e-5, 1.8497, -1.78e-8, 286.5016, 2.92961e-5, 1.523688, 0.093405, 2.516e-9,
                18.6021, 0.5240207766),
    "Jupiter": (100.4542, 2.76854e-5, 1.3030, -1.557e-7, 273.8777, 1.64505e-5, 5.20256, 0.048498, 4.469e-9,
                19.8950, 0.0830853001),
    "Saturn":  (113.6634, 2.38980e-5, 2.4886, -1.081e-7, 339.3939, 2.97661e-5, 9.55475, 0.055546, -9.499e-9,
                316.9670, 0.0334442282),
}

_PLANETS = ("Mercury", "Venus", "Mars", "Jupiter", "Saturn")


def _elements(name, d):
    N0, N1, i0, i1, w0, w1, a, e0, e1, M0, M1 = _ELEMENTS[name]
    return (_rev(N0 + N1 * d), i0 + i1 * d, _rev(w0 + w1 * d), a, e0 + e1 * d, _rev(M0 + M1 * d))


def _kepler(M, e):
    """離心近点角 E[deg]（ニュートン法）。"""
    E = M + e / _R * _sin(M) * (1.0 + e * _cos(M))
    for _ in range(12):
        dE = (E - e / _R * _sin(E) - M) / (1.0 - e * _cos(E))
        E -= dE
        if abs(dE) < 1e-7:
            break
    return E


def _orbit(name, d):
    """軌道面内の真近点角 v[deg]・動径 r と、黄道座標（黄経 lon・黄緯 lat）。"""
    N, i, w, a, e, M = _elements(name, d)
    E = _kepler(M, e)
    xv = a * (_cos(E) - e)
    yv = a * math.sqrt(1.0 - e * e) * _sin(E)
    v = _atan2(yv, xv)
    r = math.hypot(xv, yv)
    u = v + w
    xh = r * (_cos(N) * _cos(u) - _sin(N) * _sin(u) * _cos(i))
    yh = r * (_sin(N) * _cos(u) + _cos(N) * _sin(u) * _cos(i))
    zh = r * _sin(u) * _sin(i)
    lon = _rev(_atan2(yh, xh))
    lat = _atan2(zh, math.hypot(xh, yh))
    return lon, lat, r, M, w, N


def _lonlat_to_xyz(lon, lat, r):
    return (r * _cos(lon) * _cos(lat), r * _sin(lon) * _cos(lat), r * _sin(lat))


def _ecl_to_radec(x, y, z, ecl):
    xe = x
    ye = y * _cos(ecl) - z * _sin(ecl)
    ze = y * _sin(ecl) + z * _cos(ecl)
    ra = _rev(_atan2(ye, xe))
    dec = _atan2(ze, math.hypot(xe, ye))
    return ra, dec, math.sqrt(xe * xe + ye * ye + ze * ze)


def _altaz(ra, dec, lst, lat):
    """赤経・赤緯[deg]と地方恒星時[deg] → 高度・方位（北=0・東回り）[deg]。"""
    ha = lst - ra
    x = _cos(ha) * _cos(dec)
    y = _sin(ha) * _cos(dec)
    z = _sin(dec)
    xhor = x * _sin(lat) - z * _cos(lat)
    yhor = y
    zhor = x * _cos(lat) + z * _sin(lat)
    az = _rev(_atan2(yhor, xhor) + 180.0)
    alt = _atan2(zhor, math.hypot(xhor, yhor))
    return alt, az


def _phase_label(elong_deg: float) -> str:
    """太陽からの黄経離角 [deg] → 月相ラベル（ASCII）。`ephem._phase_label` と同じ区分。"""
    e = elong_deg % 360.0
    names = [(22.5, "New"), (67.5, "Waxing Cres"), (112.5, "First Qtr"),
             (157.5, "Waxing Gib"), (202.5, "Full"), (247.5, "Waning Gib"),
             (292.5, "Last Qtr"), (337.5, "Waning Cres")]
    for lim, name in names:
        if e < lim:
            return name
    return "New"


def sky_bodies(dt_utc, lat: float, lon: float, data_dir=None) -> dict:
    """指定 UTC(naive datetime)・観測地点の惑星・月を返す（`ephem.sky_bodies` 互換）。

    data_dir は互換のための引数で使わない（暦ファイル不要）。
    """
    d = _day_number(dt_utc)
    ecl = 23.4393 - 3.563e-7 * d

    # --- 太陽（地心黄経 lonsun・距離 rs）
    _, _, ws, _, es, Ms = _elements("Sun", d)
    Es = _kepler(Ms, es)
    xv = _cos(Es) - es
    yv = math.sqrt(1.0 - es * es) * _sin(Es)
    rs = math.hypot(xv, yv)
    lonsun = _rev(_atan2(yv, xv) + ws)
    xs, ys = rs * _cos(lonsun), rs * _sin(lonsun)
    Ls = _rev(Ms + ws)                         # 太陽の平均黄経

    # 地方恒星時[deg]
    ut_hours = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    lst = _rev(Ls + 180.0 + ut_hours * 15.0 + lon)

    # 木星・土星の平均近点角（相互摂動に使う）
    Mj = _elements("Jupiter", d)[5]
    Msat = _elements("Saturn", d)[5]

    planets = []
    for name in _PLANETS:
        plon, plat, r, _M, _w, _N = _orbit(name, d)
        if name == "Jupiter":
            plon += (-0.332 * _sin(2 * Mj - 5 * Msat - 67.6) - 0.056 * _sin(2 * Mj - 2 * Msat + 21)
                     + 0.042 * _sin(3 * Mj - 5 * Msat + 21) - 0.036 * _sin(Mj - 2 * Msat)
                     + 0.022 * _cos(Mj - Msat) + 0.023 * _sin(2 * Mj - 3 * Msat + 52)
                     - 0.016 * _sin(Mj - 5 * Msat - 69))
        elif name == "Saturn":
            plon += (0.812 * _sin(2 * Mj - 5 * Msat - 67.6) - 0.229 * _cos(2 * Mj - 4 * Msat - 2)
                     + 0.119 * _sin(Mj - 2 * Msat - 3) + 0.046 * _sin(2 * Mj - 6 * Msat - 69)
                     + 0.014 * _sin(Mj - 3 * Msat + 32))
            plat += -0.020 * _cos(2 * Mj - 4 * Msat - 2) + 0.018 * _sin(2 * Mj - 6 * Msat - 49)
        xh, yh, zh = _lonlat_to_xyz(plon, plat, r)
        xg, yg, zg = xh + xs, yh + ys, zh                      # 地心黄道座標
        ra, dec, dist = _ecl_to_radec(xg, yg, zg, ecl)
        alt, az = _altaz(ra, dec, lst, lat)

        # 見かけ等級（位相角 FV[deg]）
        c = (r * r + dist * dist - rs * rs) / (2.0 * r * dist)
        fv = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        base = 5.0 * math.log10(r * dist)
        if name == "Mercury":
            mag = -0.36 + base + 0.027 * fv + 2.2e-13 * fv ** 6
        elif name == "Venus":
            mag = -4.34 + base + 0.013 * fv + 4.2e-7 * fv ** 3
        elif name == "Mars":
            mag = -1.51 + base + 0.016 * fv
        elif name == "Jupiter":
            mag = -9.25 + base + 0.014 * fv
        else:                                                   # Saturn（環の傾きを含む）
            los = _atan2(yg, xg)
            las = _atan2(zg, math.hypot(xg, yg))
            ir, nr = 28.06, 169.51 + 3.82e-5 * d
            sb = _sin(las) * _cos(ir) - _cos(las) * _sin(ir) * _sin(los - nr)
            ring = -2.6 * abs(sb) + 1.2 * sb * sb
            mag = -9.0 + base + 0.044 * fv + ring
        planets.append({"name": name, "alt": alt, "az": az, "mag": mag})

    # --- 月（地心黄道座標に摂動を加える）
    mlon, mlat, mr, Mm, wm, Nm = _orbit("Moon", d)
    Lm = _rev(Nm + wm + Mm)
    D = _rev(Lm - Ls)
    F = _rev(Lm - Nm)
    mlon += (-1.274 * _sin(Mm - 2 * D) + 0.658 * _sin(2 * D) - 0.186 * _sin(Ms)
             - 0.059 * _sin(2 * Mm - 2 * D) - 0.057 * _sin(Mm - 2 * D + Ms)
             + 0.053 * _sin(Mm + 2 * D) + 0.046 * _sin(2 * D - Ms) + 0.041 * _sin(Mm - Ms)
             - 0.035 * _sin(D) - 0.031 * _sin(Mm + Ms) - 0.015 * _sin(2 * F - 2 * D)
             + 0.011 * _sin(Mm - 4 * D))
    mlat += (-0.173 * _sin(F - 2 * D) - 0.055 * _sin(Mm - F - 2 * D) - 0.046 * _sin(Mm + F - 2 * D)
             + 0.033 * _sin(F + 2 * D) + 0.017 * _sin(2 * Mm + F))
    mr += -0.58 * _cos(Mm - 2 * D) - 0.46 * _cos(2 * D)        # 地球半径
    xm, ym, zm = _lonlat_to_xyz(mlon, mlat, mr)
    ra, dec, _ = _ecl_to_radec(xm, ym, zm, ecl)
    m_alt, m_az = _altaz(ra, dec, lst, lat)
    # 地心視差: 観測者が地表にいるぶん、見かけの高度が下がる（地平線付近で最大約 1°）
    mpar = math.degrees(math.asin(1.0 / mr))
    m_alt -= mpar * _cos(m_alt)

    # 輝面比と満ち欠け
    cos_el = _cos(lonsun - mlon) * _cos(mlat)
    elong = math.degrees(math.acos(max(-1.0, min(1.0, cos_el))))
    frac = (1.0 + _cos(180.0 - elong)) / 2.0
    dlon = _rev(mlon - lonsun)
    moon = {"alt": m_alt, "az": m_az, "frac": frac, "waxing": bool(dlon < 180.0),
            "phase": _phase_label(dlon), "mag": -12.7}
    return {"planets": planets, "moon": moon}
