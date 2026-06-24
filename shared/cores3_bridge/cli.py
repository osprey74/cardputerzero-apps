"""cores3_bridge CLI — CoreS3 テレメトリの表示・JSON 中継・ライブ監視。

使い方::

    python -m cores3_bridge.cli                 # 1 行サマリを流す
    python -m cores3_bridge.cli --json          # 正規化 JSON を 1 行ずつ
    python -m cores3_bridge.cli --watch         # 1 画面ライブ更新
    python -m cores3_bridge.cli --port COM5     # ポート指定

shared/ をパッケージ親に持たない実行環境では、リポジトリ直下から
``python -m shared.cores3_bridge.cli`` でも起動できる。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .models import Frame
from .reader import CoreS3Reader, default_port


def _fmt_opt(v, suffix="", nd=3):
    return "---" if v is None else f"{v:.{nd}f}{suffix}"


def _summary(f: Frame) -> str:
    parts = []
    if f.bat:
        chg = {1: "CHG", 0: "BAT", -1: "?"}.get(f.bat.chg, "?")
        parts.append(f"bat {f.bat.pct}% {chg} {_fmt_opt(f.bat.v, 'V', 2)}")
    if f.ina:
        parts.append(f"V {_fmt_opt(f.ina.v, 'V')} I {_fmt_opt(f.ina.i, 'A', 4)} "
                     f"P {_fmt_opt(f.ina.p, 'W', 4)}")
    if f.ncir:
        parts.append(f"obj {_fmt_opt(f.ncir.t_obj, 'C', 1)} "
                     f"amb {_fmt_opt(f.ncir.t_amb, 'C', 1)}")
    for e in f.encoders:
        press = "*" if e.pressed else " "
        parts.append(f"[{e.role}:{e.uid} {e.cnt:+d}{press}]")
    return " | ".join(parts)


def _frame_to_dict(f: Frame) -> dict:
    return {
        "bat": dataclasses.asdict(f.bat) if f.bat else None,
        "ina": dataclasses.asdict(f.ina) if f.ina else None,
        "ncir": dataclasses.asdict(f.ncir) if f.ncir else None,
        "enc": [dataclasses.asdict(e) for e in f.encoders],
    }


def _watch_render(f: Frame) -> str:
    lines = ["CoreS3 frontend - live (Ctrl-C to quit)", "-" * 44]
    if f.bat:
        chg = {1: "charging", 0: "discharge", -1: "unknown"}.get(f.bat.chg, "?")
        lines.append(f"  BAT  {f.bat.pct:>3}%  {chg:<9} {_fmt_opt(f.bat.v, ' V', 2)}")
    if f.ina:
        lines.append(f"  INA  V={_fmt_opt(f.ina.v, ' V')}  "
                     f"I={_fmt_opt(f.ina.i, ' A', 4)}  P={_fmt_opt(f.ina.p, ' W', 4)}")
    if f.ncir:
        lines.append(f"  NCIR obj={_fmt_opt(f.ncir.t_obj, ' C', 1)}  "
                     f"amb={_fmt_opt(f.ncir.t_amb, ' C', 1)}")
    lines.append("  ENC")
    for e in f.encoders:
        press = "PRESS" if e.pressed else "     "
        lines.append(f"    {e.role}  uid={e.uid}  cnt={e.cnt:+d}  "
                     f"d={e.delta:+d}  {press}  (pos id={e.id})")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cores3_bridge",
                                 description="CoreS3 入力フロントエンド受信ブリッジ")
    ap.add_argument("--port", default=None,
                    help=f"シリアルポート（既定: {default_port()}）")
    ap.add_argument("--baud", type=int, default=115200)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true",
                   help="正規化した JSON を 1 行ずつ出力（nan/inf は null 化済み）")
    g.add_argument("--watch", action="store_true",
                   help="1 画面をライブ更新表示")
    args = ap.parse_args(argv)

    try:
        reader = CoreS3Reader(port=args.port, baud=args.baud)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        with reader as rd:
            print(f"# reading {rd.port} @ {rd.baud}", file=sys.stderr)
            for f in rd.frames():
                if args.json:
                    print(json.dumps(_frame_to_dict(f), ensure_ascii=False), flush=True)
                elif args.watch:
                    sys.stdout.write("\x1b[2J\x1b[H")  # clear + home
                    sys.stdout.write(_watch_render(f) + "\n")
                    sys.stdout.flush()
                else:
                    print(_summary(f), flush=True)
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # noqa: BLE001 - シリアル切断等を素直に通知
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
