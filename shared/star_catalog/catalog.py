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
_DSO = struct.Struct("<fffi")       # ra_deg, dec_deg, mag, type


@dataclass(frozen=True)
class Star:
    hip: int              # Hipparcos 番号 (星座線の参照キー・無しは -1)
    ra_deg: float         # 赤経 [deg] (J2000)
    dec_deg: float        # 赤緯 [deg]
    mag: float            # 実視等級
    ci: float             # 色指数 B-V (無しは NaN)


@dataclass(frozen=True)
class Dso:
    """深宇宙天体 (OpenNGC)。type: 0=other/1=galaxy/2=nebula/3=open cluster/4=globular。"""
    ra_deg: float
    dec_deg: float
    mag: float            # 等級 (不明は 99.0)
    type: int


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


def load_dso(data_dir: str | Path) -> tuple[list[Dso], dict, dict]:
    """dso.bin (+ 任意の names/meta) を読み込む。無ければ ([], {}, {})。"""
    d = Path(data_dir)
    p = d / "dso.bin"
    if not p.exists():
        return [], {}, {}
    dsos = [Dso(ra, dec, mag, typ) for ra, dec, mag, typ in _DSO.iter_unpack(p.read_bytes())]
    names: dict = {}
    if (d / "dso_names.json").exists():
        names = json.loads((d / "dso_names.json").read_text(encoding="utf-8"))
    meta: dict = {}
    if (d / "dso_meta.json").exists():
        meta = json.loads((d / "dso_meta.json").read_text(encoding="utf-8"))
    return dsos, names, meta


def load_constellation_names(data_dir: str | Path,
                             cat: "StarCatalog") -> list[tuple[str, float, float]]:
    """星座名ラベルを ``[(label, ra_deg, dec_deg)]`` で返す。無ければ []。

    `constellation_lines.json` の ``constellations`` グループ（iau/name/pairs）から、
    各星座の構成星（HIP）の位置を単位ベクトル平均して**重心 RA/Dec**を求める
    （RA 0/360 のまたぎや極でも破綻しない球面重心）。ラベルは IAU 3 文字略号
    （Ori / UMa …）を優先＝低解像度 LCD でも収まる。星表に無い HIP は無視。
    """
    d = Path(data_dir)
    p = d / "constellation_lines.json"
    if not p.exists():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    out: list[tuple[str, float, float]] = []
    for c in obj.get("constellations", []):
        hips: set[int] = set()
        for a, b in c.get("pairs", []):
            hips.add(int(a))
            hips.add(int(b))
        x = y = z = 0.0
        n = 0
        for h in hips:
            st = cat.by_hip(h)
            if st is None:
                continue
            ra = math.radians(st.ra_deg)
            dec = math.radians(st.dec_deg)
            x += math.cos(dec) * math.cos(ra)
            y += math.cos(dec) * math.sin(ra)
            z += math.sin(dec)
            n += 1
        if n == 0:
            continue
        ra_c = math.degrees(math.atan2(y, x)) % 360.0
        dec_c = math.degrees(math.atan2(z, math.hypot(x, y)))
        label = c.get("iau") or c.get("name") or ""
        if label:
            out.append((label, ra_c, dec_c))
    return out


def load_constellation_lines(data_dir: str | Path) -> list[tuple[int, int]]:
    """constellation_lines.json の HIP ペア列を読み込む。無ければ []。"""
    d = Path(data_dir)
    p = d / "constellation_lines.json"
    if not p.exists():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    return [(int(a), int(b)) for a, b in obj.get("pairs", [])]
