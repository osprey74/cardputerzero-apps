"""赤道座標 → 地平座標 → LCD ピクセルの変換 (恒星専用・惑星/月は Skyfield 側)。

PoC (`apps/stellar-map/poc/star_poc.py`) の変換関数を共通コアへ昇格したもの。
古典的な「ユリウス日 → グリニッジ恒星時 → 地方恒星時 → 地平座標」で自己完結し、
天体暦ダウンロード不要。恒星の年周視差・固有運動は裸眼精度では無視できる。
"""
from __future__ import annotations

import math

R2D = 57.295779513082323


def julian_date(year: int, month: int, day: int,
                hour: float = 0.0, minute: float = 0.0, second: float = 0.0) -> float:
    """UTC の暦日時 → ユリウス日 (JD)。"""
    d = day + (hour + minute / 60.0 + second / 3600.0) / 24.0
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def gmst_deg(jd: float) -> float:
    """JD → グリニッジ平均恒星時 [deg] (0-360)。"""
    t = (jd - 2451545.0) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
         + 0.000387933 * t * t - (t ** 3) / 38710000.0)
    return g % 360.0


def lst_deg(jd: float, lon_deg: float) -> float:
    """JD と東経経度 → 地方恒星時 [deg] (0-360)。"""
    return (gmst_deg(jd) + lon_deg) % 360.0


def radec_to_altaz(ra_deg: float, dec_deg: float, lat_deg: float,
                   lst_deg_: float) -> tuple[float, float]:
    """赤道座標 (RA/Dec) → 地平座標。返り値 (alt[deg], az[deg])。az は北=0・東回り。"""
    ha = math.radians((lst_deg_ - ra_deg) % 360.0)
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)
    denom = math.cos(lat) * math.cos(alt)
    cos_az = 1.0 if abs(denom) < 1e-12 else (math.sin(dec) - math.sin(lat) * sin_alt) / denom
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha) > 0.0:
        az = 360.0 - az
    return math.degrees(alt), az


def altaz_to_plot_xy(alt: float, az: float, cx: float, cy: float, radius: float,
                     mirror_ew: bool = False) -> tuple[float, float]:
    """地平座標 → 円形全天図ピクセル (中心=天頂/外周=地平線/北=上)。

    既定は東=右 (App01 Sky Plot 準拠)。mirror_ew=True で見上げる向き (planisphere)。
    """
    r = radius * (1.0 - alt / 90.0)
    a = (360.0 - az) if mirror_ew else az
    theta = math.radians(a - 90.0)   # 北を 12 時方向へ
    return cx + r * math.cos(theta), cy + r * math.sin(theta)


def mag_to_radius(mag: float, r_min: int = 1, r_max: int = 5) -> int:
    """実視等級 → ドット半径 [px]。明るい (等級小) ほど大きい。"""
    r = round(3.4 - 0.55 * mag)
    return max(r_min, min(r_max, r))
