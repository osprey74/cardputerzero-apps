"""前処理済み星表 (stars.bin / stars_meta.json / named_stars.json) のローダ。

生成は `apps/stellar-map/tools/build_star_catalog.py`。stars.bin は 1 星 20 バイトの
リトルエンディアン固定長レコード (hip:int32, ra_deg:f32, dec_deg:f32, mag:f32, ci:f32)、
等級昇順 (明るい順)。純 stdlib で読む。
"""
from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_RECORD = struct.Struct("<iffff")   # hip, ra_deg, dec_deg, mag, ci


@dataclass(frozen=True)
class Star:
    hip: int              # Hipparcos 番号 (星座線の参照キー・無しは -1)
    ra_deg: float         # 赤経 [deg] (J2000)
    dec_deg: float        # 赤緯 [deg]
    mag: float            # 実視等級
    ci: float             # 色指数 B-V (無しは NaN)


class StarCatalog:
    """読み込んだ星表。``stars`` は等級昇順。``named``/``by_hip`` で索引。"""

    def __init__(self, stars: list[Star], named: dict[str, int], meta: dict):
        self.stars = stars
        self.named = named                    # proper name -> index
        self.meta = meta
        self._by_hip = {s.hip: i for i, s in enumerate(stars) if s.hip >= 0}

    def __len__(self) -> int:
        return len(self.stars)

    def by_name(self, name: str) -> Optional[Star]:
        i = self.named.get(name)
        return self.stars[i] if i is not None else None

    def by_hip(self, hip: int) -> Optional[Star]:
        i = self._by_hip.get(hip)
        return self.stars[i] if i is not None else None


def load_catalog(data_dir: str | Path) -> StarCatalog:
    """data_dir 内の stars.bin (+ 任意の meta / named) を読み込む。"""
    d = Path(data_dir)
    raw = (d / "stars.bin").read_bytes()
    stars = [Star(hip, ra, dec, mag, ci)
             for hip, ra, dec, mag, ci in _RECORD.iter_unpack(raw)]
    named: dict[str, int] = {}
    named_path = d / "named_stars.json"
    if named_path.exists():
        named = json.loads(named_path.read_text(encoding="utf-8"))
    meta: dict = {}
    meta_path = d / "stars_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return StarCatalog(stars, named, meta)
