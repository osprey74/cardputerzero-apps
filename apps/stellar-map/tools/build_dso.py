#!/usr/bin/env python3
"""App 16 星座盤 ― OpenNGC 深宇宙天体(DSO)を取り込み、軽量な中間形式に前処理する。

OpenNGC の `NGC.csv`(`;` 区切り) から、小型 LCD で意味のある明るい DSO
（Messier 天体、または V/B 等級 ≤ 既定 8.0）を抽出し、`dso.bin` ＋ `dso_meta.json`
＋ `dso_names.json` を生成する。

⚠️ ライセンス: OpenNGC は **CC BY-SA 4.0**（表示＋継承・© Mattia Verga）。生成物を
   再配布する場合は同ライセンス維持＋クレジット。生データ・生成物とも非コミット。

出力 `dso.bin` の 1 レコード(LE・16 バイト): ra_deg:f32, dec_deg:f32, mag:f32, type:int32
  type: 0=other / 1=galaxy / 2=nebula / 3=open cluster / 4=globular cluster
  (等級昇順=明るい順。等級不明は 99.0 として末尾寄りに)

使い方:
  python build_dso.py                 # 自動DL→ 既定 mag≤8.0 で data/ に生成
  python build_dso.py --mag-limit 7
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"
LICENSE = "OpenNGC, © Mattia Verga, CC BY-SA 4.0"
RECORD = struct.Struct("<fffi")   # ra_deg, dec_deg, mag, type (16 bytes)

# OpenNGC Type コード → 種別 enum。
TYPE_MAP = {
    "G": 1, "GPair": 1, "GTrpl": 1, "GGroup": 1,
    "PN": 2, "HII": 2, "EmN": 2, "Neb": 2, "RfN": 2, "SNR": 2, "Cl+N": 2, "DrkN": 2,
    "OCl": 3,
    "GCl": 4,
}
SKIP_TYPES = {"NonEx", "Dup"}   # 非実在・重複は除外


def _ra_to_deg(s: str):
    """"HH:MM:SS.ss" → 度。空なら None。"""
    s = s.strip()
    if not s:
        return None
    try:
        h, m, sec = s.split(":")
        return (int(h) + int(m) / 60.0 + float(sec) / 3600.0) * 15.0
    except ValueError:
        return None


def _dec_to_deg(s: str):
    """"±DD:MM:SS.s" → 度。空なら None。"""
    s = s.strip()
    if not s:
        return None
    try:
        sign = -1.0 if s[0] == "-" else 1.0
        d, m, sec = s.lstrip("+-").split(":")
        return sign * (int(d) + int(m) / 60.0 + float(sec) / 3600.0)
    except ValueError:
        return None


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] exists: {dest} ({dest.stat().st_size:,} bytes)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[dl] {url}\n  -> {dest}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310
    print(f"[dl] done ({dest.stat().st_size:,} bytes)")


def build(csv_path: Path, out_dir: Path, mag_limit: float) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    recs: list[tuple[float, float, float, int]] = []
    names_pending: list[tuple[str, int]] = []   # (name, recs のインデックス)

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            typ = (r.get("Type") or "").strip()
            if typ in SKIP_TYPES:
                continue
            ra = _ra_to_deg(r.get("RA", ""))
            dec = _dec_to_deg(r.get("Dec", ""))
            if ra is None or dec is None:
                continue
            # 等級: V-Mag 優先、無ければ B-Mag。両方無ければ 99。
            def _f(key):
                v = (r.get(key) or "").strip()
                try:
                    return float(v) if v else None
                except ValueError:
                    return None
            mag = _f("V-Mag")
            if mag is None:
                mag = _f("B-Mag")
            messier = (r.get("M") or "").strip()
            # 採用条件: Messier 天体、または 等級 ≤ mag_limit。
            if not messier and (mag is None or mag > mag_limit):
                continue
            recs.append((ra, dec, mag if mag is not None else 99.0,
                         TYPE_MAP.get(typ, 0)))
            idx = len(recs) - 1
            common = (r.get("Common names") or "").strip()
            if messier:
                names_pending.append((f"M{int(messier)}", idx))
            elif common:
                names_pending.append((common.split(",")[0], idx))

    # 等級昇順に並べ、index を確定。
    order = sorted(range(len(recs)), key=lambda i: recs[i][2])
    remap = {old: new for new, old in enumerate(order)}
    recs_sorted = [recs[i] for i in order]
    names = {str(remap[i]): nm for nm, i in names_pending}

    with (out_dir / "dso.bin").open("wb") as fh:
        for ra, dec, mag, typ in recs_sorted:
            fh.write(RECORD.pack(ra, dec, mag, typ))
    (out_dir / "dso_names.json").write_text(
        json.dumps(names, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    meta = {
        "source": "OpenNGC (database_files/NGC.csv)",
        "source_url": URL,
        "license": LICENSE,
        "mag_limit": mag_limit,
        "count": len(recs_sorted),
        "named_count": len(names),
        "record_struct": "<fffi",
        "record_fields": ["ra_deg_f32", "dec_deg_f32", "mag_f32", "type_int32"],
        "record_bytes": RECORD.size,
        "type_map": {"0": "other", "1": "galaxy", "2": "nebula",
                     "3": "open cluster", "4": "globular cluster"},
        "note": "Messier 天体または 等級≤mag_limit を採用。等級不明は 99.0。",
    }
    (out_dir / "dso_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    here = Path(__file__).resolve().parent
    app_root = here.parent
    ap = argparse.ArgumentParser(description="OpenNGC DSO → 星座盤用 中間形式 前処理")
    ap.add_argument("--in", dest="inp",
                    default=str(app_root / "data" / "raw" / "NGC.csv"))
    ap.add_argument("--out-dir", default=str(app_root / "data"))
    ap.add_argument("--mag-limit", type=float, default=8.0,
                    help="Messier 以外を採用する上限等級 (既定 8.0)")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args()

    download(args.url, Path(args.inp))
    meta = build(Path(args.inp), Path(args.out_dir), args.mag_limit)
    print(f"[ok] {meta['count']:,} DSO (Messier or mag<={meta['mag_limit']}) / "
          f"{meta['named_count']} named")
    print(f"[ok] out: {args.out_dir}/dso.bin "
          f"({meta['count'] * meta['record_bytes']:,} bytes), dso_meta.json, dso_names.json")


if __name__ == "__main__":
    main()
