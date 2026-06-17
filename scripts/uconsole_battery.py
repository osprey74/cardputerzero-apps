#!/usr/bin/env python3
"""uconsole_battery — ClockworkPi uConsole の正確なバッテリ状態を表示する CLI。

AXP20x ドライバが提供する `capacity` は電圧→容量変換テーブルの粗さで
高電圧帯が 99-100% に張り付くため参考にならない。本ツールは sysfs から
電圧・電流・状態を直接読み、Li-Po 標準 OCV カーブで再計算する。

用途:
    uconsole_battery                # 人間向け 1 行表示
    uconsole_battery --json         # JSON 出力（自動化・他ツール連携）
    uconsole_battery --compare      # sysfs 表示 vs 再計算 の差分確認
    uconsole_battery --watch 5      # 5 秒間隔で連続表示（Ctrl-C で終了）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional


PSU_DIR = Path("/sys/class/power_supply/axp20x-battery")

# 開回路電圧 (Open-Circuit Voltage) → SoC (State of Charge) 変換表
# 典型的な Li-Po 4.2V セルの放電カーブ。uConsole の低負荷状況 (1-2W) に概ね適合。
# 実機放電ログを採取後、総司様のセル個体に合わせて再校正可能。
OCV_TABLE = [
    (4.200, 100), (4.150, 95), (4.110, 90), (4.080, 85),
    (4.020, 80),  (3.980, 75), (3.950, 70), (3.910, 65),
    (3.870, 60),  (3.840, 55), (3.820, 50), (3.800, 45),
    (3.790, 40),  (3.770, 35), (3.750, 30), (3.730, 25),
    (3.710, 20),  (3.690, 15), (3.610, 10), (3.270, 5),
    (3.000, 0),
]

DESIGN_ENERGY_WH = 8.0  # sysfs energy_full_design より (8 Wh)


def _read_int(name: str) -> int:
    return int((PSU_DIR / name).read_text().strip())


def _read_str(name: str) -> str:
    return (PSU_DIR / name).read_text().strip()


def voltage_to_percent(voltage_v: float) -> float:
    if voltage_v >= OCV_TABLE[0][0]:
        return 100.0
    if voltage_v <= OCV_TABLE[-1][0]:
        return 0.0
    for (v_hi, p_hi), (v_lo, p_lo) in zip(OCV_TABLE, OCV_TABLE[1:]):
        if v_lo <= voltage_v <= v_hi:
            frac = (voltage_v - v_lo) / (v_hi - v_lo)
            return p_lo + frac * (p_hi - p_lo)
    return 0.0


def _format_duration(minutes: float) -> str:
    if minutes < 0:
        return "—"
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def gather() -> dict:
    voltage_uv = _read_int("voltage_now")
    current_ua = _read_int("current_now")
    status = _read_str("status")
    sysfs_capacity = _read_int("capacity")

    voltage_v = voltage_uv / 1_000_000.0
    current_a_abs = abs(current_ua) / 1_000_000.0
    power_w_abs = voltage_v * current_a_abs

    # 電力符号は status に従う (current_now の符号規約はドライバ依存のため信用しない)
    if status == "Discharging":
        power_w = -power_w_abs
    elif status == "Charging":
        power_w = power_w_abs
    else:
        power_w = 0.0

    percent = voltage_to_percent(voltage_v)

    eta_min: Optional[float] = None
    if status == "Discharging" and power_w_abs > 0.01:
        remaining_wh = (percent / 100.0) * DESIGN_ENERGY_WH
        eta_min = (remaining_wh / power_w_abs) * 60

    return {
        "percent": round(percent, 1),
        "voltage_v": round(voltage_v, 3),
        "current_ma": round(current_ua / 1000.0, 0),
        "power_w": round(power_w, 2),
        "status": status,
        "eta_min": round(eta_min, 1) if eta_min is not None else None,
        "sysfs_capacity": sysfs_capacity,
    }


def _format_text(d: dict) -> str:
    parts = [
        f"{d['percent']:5.1f}%",
        f"{d['voltage_v']:.3f} V",
        f"{d['power_w']:+.2f} W",
        d["status"],
    ]
    if d["eta_min"] is not None:
        parts.append(f"~{_format_duration(d['eta_min'])} remaining")
    return "  ".join(parts)


def _format_compare(d: dict) -> str:
    diff = d["sysfs_capacity"] - d["percent"]
    return (
        f"sysfs reports : {d['sysfs_capacity']:5d}%\n"
        f"computed (OCV): {_format_text(d)}\n"
        f"discrepancy   : {diff:+.1f}%"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="uconsole_battery",
        description="ClockworkPi uConsole accurate battery monitor",
    )
    parser.add_argument("--json", action="store_true", help="JSON 形式で出力")
    parser.add_argument("--compare", action="store_true",
                        help="sysfs 値と OCV 再計算値の差分を表示")
    parser.add_argument("--watch", metavar="SEC", type=float, default=None,
                        help="SEC 秒間隔で連続表示 (Ctrl-C で終了)")
    args = parser.parse_args(argv)

    if not PSU_DIR.exists():
        print(f"Error: {PSU_DIR} not found. Is this a uConsole?", file=sys.stderr)
        return 1

    def emit() -> None:
        data = gather()
        if args.json:
            print(json.dumps(data, ensure_ascii=False))
        elif args.compare:
            print(_format_compare(data))
        else:
            print(_format_text(data))

    if args.watch is not None:
        try:
            while True:
                if args.compare or args.json:
                    emit()
                    print()
                else:
                    print(_format_text(gather()))
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 130
    else:
        emit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
