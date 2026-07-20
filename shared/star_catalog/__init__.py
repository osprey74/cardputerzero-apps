"""star_catalog — 星座盤 (App 16) 共通コア。

前処理ツール (`apps/stellar-map/tools/build_star_catalog.py`) が生成した中間形式
``stars.bin`` を読み込み、赤道座標 (RA/Dec) を観測時刻・地点の地平座標 (Alt/Az) へ
変換し、LCD の円形全天図ピクセルへ投影する純 stdlib ライブラリ。

依存は Python 標準ライブラリのみ (描画は呼び出し側)。惑星・月・高精度化は将来
Skyfield を併用する想定で、変換関数は独立している。
"""
from __future__ import annotations

from .catalog import (Dso, Star, StarCatalog, load_catalog,
                      load_constellation_lines, load_dso)
from .scene import build_scene, compute_sky
from .transform import (altaz_to_plot_xy, gmst_deg, julian_date, lst_deg,
                        mag_to_color, mag_to_radius, radec_to_altaz)

__all__ = [
    "Star", "Dso", "StarCatalog", "load_catalog", "load_dso",
    "load_constellation_lines", "build_scene", "compute_sky",
    "julian_date", "gmst_deg", "lst_deg", "radec_to_altaz",
    "altaz_to_plot_xy", "mag_to_radius", "mag_to_color",
]

__version__ = "0.1.0"
