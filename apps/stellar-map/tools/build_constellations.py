#!/usr/bin/env python3
"""App 16 星座盤 ― Stellarium 現代(西洋)星座線を取り込み、HIP ペア列に前処理する。

Stellarium の sky culture `western/index.json` から星座線（線分定義）を抽出し、
`constellation_lines.json`（HIP 番号ペアの列＋星座名）に変換する。描画側は各 HIP を
星表(`stars.bin`)の位置に解決して線を引く。

⚠️ ライセンス: 星座線（線分定義）は **MIT**（作者 Xalioth が Stellarium discussion #790 で
   MIT 再許諾。星座「絵」は別ライセンスのため本ツールは線のみ抽出）。生成物は非コミット。

index.json の構造:
  constellations[].lines = ポリラインの配列。各ポリラインは HIP 番号の並びで、
  隣接要素を結ぶ（例 [98036, 97649, 97278] = 98036-97649, 97649-97278 の 2 線分）。

使い方:
  python build_constellations.py            # 自動DL→ data/constellation_lines.json 生成
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

URL = ("https://raw.githubusercontent.com/Stellarium/stellarium-skycultures/"
       "master/western/index.json")
LICENSE = ("Constellation line definitions: Stellarium western sky culture, "
           "MIT (relicensed by Xalioth, Stellarium discussion #790)")


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] 既存: {dest} ({dest.stat().st_size:,} bytes)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[dl] {url}\n  -> {dest}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310
    print(f"[dl] 完了 ({dest.stat().st_size:,} bytes)")


def build(index_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(index_path.read_text(encoding="utf-8"))

    constellations = []
    all_pairs: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for c in data.get("constellations", []):
        iau = c.get("iau") or (c.get("id", "").split()[-1] if c.get("id") else "")
        cn = c.get("common_name") or {}
        name = cn.get("english") or cn.get("native") or iau
        pairs: list[list[int]] = []
        for poly in c.get("lines", []) or []:
            # 頂点は通常 HIP 整数だが、稀に文字列 ID が混じる。整数のみを頂点とし、
            # 非整数は「線の切れ目」として扱う（隣接ペアを跨いで結ばない）。
            verts = []
            for v in poly:
                if isinstance(v, bool):
                    verts.append(None)
                elif isinstance(v, int):
                    verts.append(v)
                elif isinstance(v, str) and v.lstrip("-").isdigit():
                    verts.append(int(v))
                else:
                    verts.append(None)   # 切れ目
            for a, b in zip(verts, verts[1:]):
                if a is None or b is None:
                    continue
                key = (a, b) if a <= b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append([a, b])
        if pairs:
            constellations.append({"iau": iau, "name": name, "pairs": pairs})
            all_pairs.extend(pairs)

    out = {
        "source": "Stellarium western sky culture (index.json)",
        "source_url": URL,
        "license": LICENSE,
        "count_constellations": len(constellations),
        "count_pairs": len(all_pairs),
        "pairs": all_pairs,                 # 描画用の平坦化 HIP ペア列
        "constellations": constellations,   # 星座名つきグループ（ラベル用）
    }
    (out_dir / "constellation_lines.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main() -> None:
    here = Path(__file__).resolve().parent
    app_root = here.parent
    ap = argparse.ArgumentParser(description="Stellarium 星座線 → HIP ペア前処理")
    ap.add_argument("--in", dest="inp",
                    default=str(app_root / "data" / "raw" / "western_index.json"))
    ap.add_argument("--out-dir", default=str(app_root / "data"))
    ap.add_argument("--url", default=URL)
    args = ap.parse_args()

    download(args.url, Path(args.inp))
    meta = build(Path(args.inp), Path(args.out_dir))
    print(f"[ok] {meta['count_constellations']} constellations / "
          f"{meta['count_pairs']} line segments (HIP pairs)")
    print(f"[ok] out: {args.out_dir}/constellation_lines.json")


if __name__ == "__main__":
    main()
