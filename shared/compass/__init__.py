"""compass — 地磁気から自機方位を得る機種非依存ロジック（App 16 星座盤・方式A）。

センサ実装（CoreS3 の BMM150 / CardputerZero 内蔵 BMM150）に依存せず、生 heading か
水平面磁気 x/y を受けて平滑化・偏角/取付オフセット補正済みの真北基準方位角を返す。
詳細は `compass.py` を参照。
"""
from __future__ import annotations

from .compass import (HeadingFilter, heading_from_xy,
                      tilt_compensated_heading, wrap180, wrap360)

__all__ = ["HeadingFilter", "heading_from_xy", "tilt_compensated_heading",
           "wrap180", "wrap360"]

__version__ = "0.1.0"
