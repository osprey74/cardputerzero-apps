#!/usr/bin/env python3
"""App 16 星座盤 ― HYG 星表を取り込み、軽量な中間形式に前処理するツール。

HYG Database v4.1 (CC BY-SA 4.0) の巨大 CSV (約 34MB / 約12万星) から、
裸眼可視 (既定 等級 ≤ 6.5・約 9,000 星) だけを抜き出し、実行時に高速ロードできる
コンパクトなバイナリ ``stars.bin`` ＋メタ ``stars_meta.json`` ＋固有名 ``named_stars.json``
に変換する。生成物は CardputerZero では ``/mnt/sdcard/stellar_map/data/`` に置く想定。

⚠️ ライセンス: HYG は CC BY-SA 4.0 (表示＋継承)。生成データを再配布する場合は
   同ライセンスを維持し出典を明記すること。本リポジトリには生データ・生成物とも
   コミットしない (data/.gitignore)。本ツールが都度ダウンロード・生成する。

使い方:
  python build_star_catalog.py                 # 既定: 等級≤6.5・data/ に出力・無ければ自動DL
  python build_star_catalog.py --mag-limit 5.0
  python build_star_catalog.py --in path/to/hygdata_v41.csv --out-dir /mnt/sdcard/stellar_map/data

出力バイナリ ``stars.bin`` の 1 レコード (リトルエンディアン・20 バイト):
  hip:int32, ra_deg:float32, dec_deg:float32, mag:float32, ci:float32
  (等級昇順=明るい順に並ぶ。hip 無しは -1。ci=色指数、無しは NaN)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
import urllib.request
from pathlib import Path

HYG_URL = ("https://raw.githubusercontent.com/astronexus/HYG-Database/"
           "main/hyg/CURRENT/hygdata_v41.csv")
LICENSE = "HYG Database v4.1, © astronexus, CC BY-SA 4.0"
RECORD = struct.Struct("<iffff")   # hip, ra_deg, dec_deg, mag, ci  (20 bytes)


def download(url: str, dest: Path) -> None:
    """HYG CSV を dest へダウンロード (既にあれば何もしない)。"""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] 既存: {dest} ({dest.stat().st_size:,} bytes)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[dl] {url}\n  -> {dest}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310 (信頼できる HTTPS 一次ソース)
    print(f"[dl] 完了 ({dest.stat().st_size:,} bytes)")


def build(csv_path: Path, out_dir: Path, mag_limit: float) -> dict:
    """HYG CSV を読み、等級 ≤ mag_limit の星を中間形式に変換して out_dir に書く。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[int, float, float, float, float]] = []
    named: dict[str, int] = {}          # proper -> (後で確定する index)
    named_pending: list[tuple[str, int]] = []  # (proper, rows のインデックス)

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            # 太陽 (id=0・ra/dec=0 のプレースホルダ) は星図に載せない。
            if r.get("id") == "0":
                continue
            mag_s = r.get("mag", "").strip()
            if not mag_s:
                continue
            try:
                mag = float(mag_s)
            except ValueError:
                continue
            if mag > mag_limit:
                continue
            try:
                ra_deg = float(r["ra"]) * 15.0   # HYG の ra は「時」なので度へ
                dec_deg = float(r["dec"])
            except (KeyError, ValueError):
                continue
            hip_s = (r.get("hip") or "").strip()
            hip = int(hip_s) if hip_s.isdigit() else -1
            ci_s = (r.get("ci") or "").strip()
            try:
                ci = float(ci_s) if ci_s else math.nan
            except ValueError:
                ci = math.nan
            idx = len(rows)
            rows.append((hip, ra_deg, dec_deg, mag, ci))
            proper = (r.get("proper") or "").strip()
            if proper:
                named_pending.append((proper, idx))

    # 明るい順 (等級昇順) に並べ替え、index を確定。
    order = sorted(range(len(rows)), key=lambda i: rows[i][3])
    remap = {old: new for new, old in enumerate(order)}
    rows_sorted = [rows[i] for i in order]
    for proper, old_idx in named_pending:
        named[proper] = remap[old_idx]

    # stars.bin
    bin_path = out_dir / "stars.bin"
    with bin_path.open("wb") as fh:
        for hip, ra, dec, mag, ci in rows_sorted:
            fh.write(RECORD.pack(hip, ra, dec, mag, ci))

    # named_stars.json (固有名 -> index)
    (out_dir / "named_stars.json").write_text(
        json.dumps(named, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

    # stars_meta.json
    meta = {
        "source": "HYG Database v4.1",
        "source_url": HYG_URL,
        "license": LICENSE,
        "mag_limit": mag_limit,
        "count": len(rows_sorted),
        "named_count": len(named),
        "record_struct": "<iffff",
        "record_fields": ["hip_int32", "ra_deg_f32", "dec_deg_f32", "mag_f32", "ci_f32"],
        "record_bytes": RECORD.size,
        "order": "magnitude ascending (brightest first)",
        "note": "ra は度 (HYG の時 ×15)。hip 無しは -1、ci 無しは NaN。太陽(id0)は除外。",
    }
    (out_dir / "stars_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    here = Path(__file__).resolve().parent
    app_root = here.parent
    ap = argparse.ArgumentParser(description="HYG 星表 → 星座盤用 中間形式 前処理")
    ap.add_argument("--in", dest="inp", default=str(app_root / "data" / "raw" / "hygdata_v41.csv"),
                    help="HYG CSV パス (無ければ --url から自動DL)")
    ap.add_argument("--out-dir", default=str(app_root / "data"), help="中間形式の出力先")
    ap.add_argument("--mag-limit", type=float, default=6.5, help="取り込む上限等級 (既定 6.5=裸眼)")
    ap.add_argument("--url", default=HYG_URL, help="HYG CSV ダウンロード URL")
    args = ap.parse_args()

    csv_path = Path(args.inp)
    try:
        download(args.url, csv_path)
    except Exception as e:  # noqa: BLE001
        print(f"[err] ダウンロード失敗: {e}", file=sys.stderr)
        sys.exit(1)

    meta = build(csv_path, Path(args.out_dir), args.mag_limit)
    # Windows コンソール (cp932) は一部記号 (≤ 等) を出せないため出力は ASCII に限定する。
    print(f"[ok] {meta['count']:,} stars (mag<={meta['mag_limit']}) / "
          f"{meta['named_count']} named")
    print(f"[ok] out: {args.out_dir}/stars.bin "
          f"({meta['count'] * meta['record_bytes']:,} bytes), "
          "stars_meta.json, named_stars.json")


if __name__ == "__main__":
    main()
