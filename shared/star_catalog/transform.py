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
                     mirror_ew: bool = False, heading: float = 0.0) -> tuple[float, float]:
    """地平座標 → 円形全天図ピクセル (中心=天頂/外周=地平線)。

    星座早見盤と同じ「見上げ式」＝**向いている方位を画面下(正面の地平線)に置く**。
    mirror_ew=True で見上げ向き(北向き時 東=右/西=左・実際の星座形)、False で鏡像(地図向き)。

    heading[deg] は「自機が向いている方位角」(北=0・東回り)。既定 0 なら北を向いた状態で、
    N=下・S=上・E=右・W=左 (mirror_ew=True)。値を与えると全天図を回転し、その方位が
    6 時方向 (画面下＝正面の地平線) に来る (App16 方式A)。方位ソースは実機では
    CardputerZero 内蔵 BMM150、先行検証では CoreS3 の BMM150 (USB CDC)。
    """
    r = radius * (1.0 - alt / 90.0)
    az_rel = (az - heading) % 360.0        # 自機の向き基準へ回転
    a = (360.0 - az_rel) if mirror_ew else az_rel
    theta = math.radians(a + 90.0)   # 向いている方位を 6 時方向(画面下＝正面の地平線)へ
    return cx + r * math.cos(theta), cy + r * math.sin(theta)


# 等級クラス別のドット半径 [px] (1等星 / 2等星 / 3等以下)。直径 ≈ 4 / 3 / 2 px。
# 小さな円は Pillow の ellipse では角が欠けて「＋」に見えるため、描画側は
# スーパーサンプリング (高解像描画→縮小) で丸くする前提のサイズ。
RADIUS_MAG1 = 2.0
RADIUS_MAG2 = 1.5
RADIUS_MAG3 = 1.0


def mag_to_radius(mag: float) -> float:
    """実視等級 → ドット半径 [px] (等級クラス別)。1等=2.0 / 2等=1.5 / 3等以下=1.0。"""
    if mag <= MAG_CLASS1:
        return RADIUS_MAG1
    if mag <= MAG_CLASS2:
        return RADIUS_MAG2
    return RADIUS_MAG3


# 等級クラスの境界と色 (1等星 / 2等星 / 3等以下)。調整しやすいよう定数化。
MAG_CLASS1 = 1.5    # これ以下 = 1 等星 (最も明るい)
MAG_CLASS2 = 2.5    # これ以下 = 2 等星
COLOR_MAG1 = (255, 255, 255)    # 1 等星: 白
COLOR_MAG2 = (150, 220, 255)    # 2 等星: 明るいシアン寄り
COLOR_MAG3 = (110, 140, 180)    # 3 等以下: くすんだ青灰 (奥行き感)


def mag_to_color(mag: float) -> tuple[int, int, int]:
    """実視等級 → 星の色 (RGB)。1 等星=白 / 2 等星=シアン寄り / 3 等以下=青灰。"""
    if mag <= MAG_CLASS1:
        return COLOR_MAG1
    if mag <= MAG_CLASS2:
        return COLOR_MAG2
    return COLOR_MAG3
