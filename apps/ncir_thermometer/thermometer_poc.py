#!/usr/bin/env python3
"""App 15 ncir-thermometer PoC — MLX90614 非接触温度の閾値監視 + Min/Max。

CoreS3 firmware が USB CDC で送る {"...","ncir":{"t_obj":..,"t_amb":..}} を
shared/cores3_bridge 経由で受け、NORMAL/WARN/ALERT を色分け表示する。
医療用途ではない（電子工作・IoT デバッグ用）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_APP = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_APP))       # apps/ncir_thermometer → repo root
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from shared.cores3_bridge import Frame, Temp
from shared.cores3_bridge.parse import parse_line

# Windows の既定コンソール(cp932)だと °/— 等が化ける・落ちるため UTF-8 を強制。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — 非対応ストリーム(パイプ等)は無視
        pass

# legacy_windows=False: Win32 レガシー描画を切って ANSI 出力に統一（cp932 例外回避）。
_out = Console(legacy_windows=False)
_err = Console(stderr=True, legacy_windows=False)

NORMAL, WARN, ALERT = "NORMAL", "WARN", "ALERT"
_STYLE = {NORMAL: "green", WARN: "yellow", ALERT: "bold red"}


def classify(t_obj, warn: float, alert: float) -> str:
    """t_obj[℃] を閾値で分類。None は NORMAL（呼び出し側で除外済みの前提）。"""
    if t_obj is None:
        return NORMAL
    if t_obj >= alert:
        return ALERT
    if t_obj >= warn:
        return WARN
    return NORMAL


def _fmt(v) -> str:
    return f"{v:6.1f}" if v is not None else "  --.-"


class Stats:
    """t_obj / t_amb の min/max/avg/count をセッション保持（テスト対象）。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.n = 0
        self.sum_obj = 0.0
        self.mn = {"obj": None, "amb": None}
        self.mx = {"obj": None, "amb": None}

    def update(self, t_obj: float, t_amb):
        self.n += 1
        self.sum_obj += t_obj
        for k, v in (("obj", t_obj), ("amb", t_amb)):
            if v is None:
                continue
            self.mn[k] = v if self.mn[k] is None else min(self.mn[k], v)
            self.mx[k] = v if self.mx[k] is None else max(self.mx[k], v)

    @property
    def avg_obj(self) -> float:
        return self.sum_obj / self.n if self.n else 0.0


def _render(t: Temp, status: str, s: Stats, warn, alert, interval) -> Panel:
    st = _STYLE[status]
    tbl = Table.grid(padding=(0, 2))
    tbl.add_row("t_obj", f"[{st}]{_fmt(t.t_obj)} °C   {status}[/]")
    tbl.add_row("t_amb", f"{_fmt(t.t_amb)} °C")
    tbl.add_row("", "")
    tbl.add_row("obj min/max", f"{_fmt(s.mn['obj'])} / {_fmt(s.mx['obj'])} °C")
    tbl.add_row("amb min/max", f"{_fmt(s.mn['amb'])} / {_fmt(s.mx['amb'])} °C")
    tbl.add_row("samples", f"{s.n:,}   warn≥{warn:g} alert≥{alert:g}  every {interval:g}s")
    tbl.add_row("keys", "[dim]r = reset min/max   Ctrl+C = quit[/]")
    return Panel(tbl, title="NCIR Thermometer PoC — NOT for medical use",
                 border_style=st)


def _reset_pressed() -> bool:
    """非ブロッキングで 'r' 押下を検出（Win=msvcrt / POSIX=select）。不可なら False。"""
    try:
        if os.name == "nt":
            import msvcrt
            hit = False
            while msvcrt.kbhit():
                hit = msvcrt.getwch().lower() == "r" or hit
            return hit
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.readline().strip().lower().startswith("r")
    except Exception:  # noqa: BLE001 — キー入力不可環境（パイプ等）は静かに無効化
        return False
    return False


def _mock_frames(path: str):
    """jsonl をループ再生して Frame を yield（PC 単独テスト用）。"""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    while True:
        for ln in lines:
            p = parse_line(ln)
            if isinstance(p, Frame):
                yield p
            time.sleep(0.2)


def _serial_frames(port: str):
    """実機 USB CDC から Frame を yield。切断時は 5 秒待って自動再接続。"""
    from shared.cores3_bridge import CoreS3Reader  # pyserial はここでのみ必要
    while True:
        try:
            with CoreS3Reader(port) as rd:
                yield from rd.frames()
        except Exception as ex:  # noqa: BLE001
            _err.print(f"[yellow]serial 切断: {ex} — 5s 後に再接続[/]")
            time.sleep(5.0)


def _report(s: Stats):
    _err.print(f"avg={s.avg_obj:.1f} min={_fmt(s.mn['obj']).strip()} "
               f"max={_fmt(s.mx['obj']).strip()} samples={s.n}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NCIR MLX90614 threshold monitor (NOT medical).")
    ap.add_argument("--port", default=None, help="serial port (既定: default_port())")
    ap.add_argument("--warn-threshold", type=float, default=80.0)
    ap.add_argument("--alert-threshold", type=float, default=100.0)
    ap.add_argument("--report-interval", type=float, default=5.0)
    ap.add_argument("--mock-file", help="jsonl をループ再生（PC 単独テスト）")
    ap.add_argument("--max-frames", type=int, default=0, help="0=無制限（テスト用に有限化）")
    a = ap.parse_args(argv)

    _err.print("[bold]WARNING:[/] hobby/dev tool — NOT for medical use.")
    if a.mock_file:
        src = _mock_frames(a.mock_file)
    else:
        from shared.cores3_bridge import default_port
        src = _serial_frames(a.port or default_port())

    s, status, last = Stats(), NORMAL, time.monotonic()
    seen = 0
    try:
        with Live(console=_out, refresh_per_second=4, screen=False) as live:
            for fr in src:
                if _reset_pressed():
                    s.reset()
                t = fr.ncir
                if t is None or t.t_obj is None:      # ncir 欠落・nan(None化) はスキップ
                    continue
                status = classify(t.t_obj, a.warn_threshold, a.alert_threshold)
                s.update(t.t_obj, t.t_amb)
                live.update(_render(t, status, s, a.warn_threshold,
                                    a.alert_threshold, a.report_interval))
                now = time.monotonic()
                if now - last >= a.report_interval:
                    _report(s)
                    last = now
                seen += 1
                if a.max_frames and seen >= a.max_frames:
                    break
    except KeyboardInterrupt:
        pass
    _err.print(f"[bold]Summary[/] samples={s.n} obj avg={s.avg_obj:.1f} "
               f"min={_fmt(s.mn['obj']).strip()} max={_fmt(s.mx['obj']).strip()} °C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
