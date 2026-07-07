"""App 16 星座盤 ― 惑星・月・月相の計算サイドカー (Skyfield)。

恒星は静的カタログ (HYG) で足りるが、惑星・月は時刻依存のため JPL 天体暦が要る。
本モジュールは Skyfield ＋ DE 暦で、指定 UTC・観測地点の惑星/月の地平座標 (Alt/Az)、
惑星の見かけ等級、月の輝面比 (満ち欠け) を返す。

⚠️ 依存: `skyfield`（MIT）。DE 暦 `de421.bsp`（NASA/JPL・実質パブリックドメイン）は
   初回のみ `data/raw/` にダウンロード・キャッシュ（gitignore）。

Skyfield の `.altaz()` は地心視差を含む地平座標を直接返すため、月のように近い天体も
正確。恒星側の自前変換 (shared/star_catalog/transform) とは別経路。
"""
from __future__ import annotations

from pathlib import Path

# de421 に含まれる天体名（外惑星は重心で十分＝裸眼精度）。
_PLANETS = [
    ("Mercury", "mercury"),
    ("Venus", "venus"),
    ("Mars", "mars"),
    ("Jupiter", "jupiter barycenter"),
    ("Saturn", "saturn barycenter"),
]

_cache: dict = {}


def _load(data_dir: Path):
    """timescale と DE 暦をロード（プロセス内キャッシュ）。"""
    key = str(data_dir)
    if key in _cache:
        return _cache[key]
    from skyfield.api import Loader
    loader = Loader(str(Path(data_dir) / "raw"))   # de421.bsp をここにキャッシュ
    ts = loader.timescale()
    eph = loader("de421.bsp")
    _cache[key] = (ts, eph)
    return ts, eph


def _phase_label(elong_deg: float) -> str:
    """太陽からの黄経離角 [deg] → 月相ラベル（ASCII）。"""
    e = elong_deg % 360.0
    names = [(22.5, "New"), (67.5, "Waxing Cres"), (112.5, "First Qtr"),
             (157.5, "Waxing Gib"), (202.5, "Full"), (247.5, "Waning Gib"),
             (292.5, "Last Qtr"), (337.5, "Waning Cres")]
    for lim, name in names:
        if e < lim:
            return name
    return "New"


def sky_bodies(dt_utc, lat: float, lon: float, data_dir) -> dict:
    """指定 UTC(naive datetime)・観測地点の惑星・月を返す。

    返り値: {
      "planets": [{"name","alt","az","mag"}...（地平線下含む・呼び側で間引く）],
      "moon": {"alt","az","frac","waxing","phase","mag"},
    }
    """
    from skyfield.api import wgs84
    from skyfield.framelib import ecliptic_frame
    ts, eph = _load(Path(data_dir))
    t = ts.utc(dt_utc.year, dt_utc.month, dt_utc.day,
               dt_utc.hour, dt_utc.minute, dt_utc.second)
    observer = eph["earth"] + wgs84.latlon(lat, lon)
    at = observer.at(t)

    try:
        from skyfield.magnitudelib import planetary_magnitude
    except ImportError:
        planetary_magnitude = None

    planets = []
    for name, target in _PLANETS:
        try:
            app = at.observe(eph[target]).apparent()
        except (KeyError, ValueError):
            continue
        alt, az, _ = app.altaz()
        mag = None
        if planetary_magnitude is not None:
            try:
                mag = float(planetary_magnitude(app))
            except (ValueError, KeyError):
                mag = None
        planets.append({"name": name, "alt": alt.degrees, "az": az.degrees,
                        "mag": mag if mag is not None else 0.0})

    moon_app = at.observe(eph["moon"]).apparent()
    m_alt, m_az, _ = moon_app.altaz()
    frac = float(moon_app.fraction_illuminated(eph["sun"]))
    _, m_lon, _ = moon_app.frame_latlon(ecliptic_frame)
    sun_app = at.observe(eph["sun"]).apparent()
    _, s_lon, _ = sun_app.frame_latlon(ecliptic_frame)
    elong = (m_lon.degrees - s_lon.degrees) % 360.0
    moon = {"alt": m_alt.degrees, "az": m_az.degrees, "frac": frac,
            "waxing": elong < 180.0, "phase": _phase_label(elong), "mag": -12.7}
    return {"planets": planets, "moon": moon}
