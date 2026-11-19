#!/usr/bin/env python3
"""IEEE の OUI 一覧（MA-L）から data/oui.tsv.gz（"AABBCC<TAB>ベンダー名"）を作る。

  python3 tools/build_oui.py                 # IEEE から取得して生成
  python3 tools/build_oui.py --csv oui.csv   # 手元の CSV から生成

出典: https://standards-oui.ieee.org/oui/oui.csv（IEEE Registration Authority の公開一覧）
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import os
import urllib.request

URL = "https://standards-oui.ieee.org/oui/oui.csv"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "oui.tsv.gz")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="取得済みの oui.csv")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if args.csv:
        text = open(args.csv, encoding="utf-8", errors="replace").read()
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (oui table builder)"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

    rows = {}
    for r in csv.DictReader(io.StringIO(text)):
        k = (r.get("Assignment") or "").strip().upper()
        v = " ".join((r.get("Organization Name") or "").split())
        if len(k) == 6 and v:
            rows[k] = v
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8", compresslevel=9) as f:
        for k in sorted(rows):
            f.write(f"{k}\t{rows[k]}\n")
    print(f"{len(rows)} entries -> {os.path.abspath(args.out)} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
