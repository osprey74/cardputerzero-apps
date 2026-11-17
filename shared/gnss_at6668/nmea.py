"""NMEA 0183 の最小パーサ（RMC・GGA）。外部依存なし。

Cap LoRa-1262 の GP-02（ATGM336H／AT6668）は 115200bps で GN/GP/GL/GA/BD/GQ 各トーカーの
文を出す。位置・時刻・測位状態に必要な RMC と GGA だけを解釈し、それ以外は無視する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Fix:
    """直近の測位状態。未取得の項目は None。"""
    valid: bool = False               # RMC が有効（A）か、GGA の品質が 1 以上
    lat: Optional[float] = None       # 度（北が正）
    lon: Optional[float] = None       # 度（東が正）
    alt: Optional[float] = None       # 海抜高度 [m]（GGA）
    sats: Optional[int] = None        # 測位に使っている衛星数（GGA）
    hdop: Optional[float] = None
    utc: Optional[datetime] = None    # UTC（naive）。日付は RMC から


def checksum_ok(line: str) -> bool:
    """`$....*HH` の XOR チェックサムを検証する。"""
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, tail = line[1:].partition("*")
    try:
        want = int(tail[:2], 16)
    except ValueError:
        return False
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def _deg(value: str, hemi: str) -> Optional[float]:
    """`ddmm.mmmm`／`dddmm.mmmm` と半球文字 → 度。"""
    if not value or not hemi:
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    d = int(v // 100)
    out = d + (v - d * 100) / 60.0
    return -out if hemi in ("S", "W") else out


class NmeaParser:
    """NMEA 文を 1 行ずつ与えると `fix` を更新する。"""

    def __init__(self):
        self.fix = Fix()
        self.sentences = 0            # チェックサムが通った文の数（「データが来ている」判定用）

    def feed(self, line: str) -> Optional[str]:
        """1 行を解釈する。解釈した文の種別（"RMC"／"GGA"）か、それ以外は None を返す。"""
        line = line.strip()
        if not checksum_ok(line):
            return None
        self.sentences += 1
        f = line[1:line.index("*")].split(",")
        kind = f[0][2:] if len(f[0]) >= 5 else ""
        if kind == "RMC" and len(f) >= 10:
            self._rmc(f)
            return "RMC"
        if kind == "GGA" and len(f) >= 10:
            self._gga(f)
            return "GGA"
        return None

    def _rmc(self, f) -> None:
        # $xxRMC,hhmmss.sss,A,ddmm.mmmm,N,dddmm.mmmm,E,speed,course,ddmmyy,...
        valid = f[2] == "A"
        t, date = f[1], f[9]
        if len(t) >= 6 and len(date) == 6:
            try:
                utc = datetime(2000 + int(date[4:6]), int(date[2:4]), int(date[0:2]),
                               int(t[0:2]), int(t[2:4]), int(t[4:6]))
                # 未同期時の既定日付は捨てる（年 2 桁が 80 以上＝1980 年代の既定値、2000 年代初頭など）
                if 2024 <= utc.year < 2080:
                    self.fix.utc = utc
            except ValueError:
                pass
        if valid:
            lat, lon = _deg(f[3], f[4]), _deg(f[5], f[6])
            if lat is not None and lon is not None:
                self.fix.lat, self.fix.lon = lat, lon
        self.fix.valid = valid and self.fix.lat is not None

    def _gga(self, f) -> None:
        # $xxGGA,hhmmss.sss,ddmm.mmmm,N,dddmm.mmmm,E,quality,sats,hdop,alt,M,...
        try:
            quality = int(f[6] or 0)
        except ValueError:
            quality = 0
        try:
            self.fix.sats = int(f[7]) if f[7] else None
        except ValueError:
            pass
        try:
            self.fix.hdop = float(f[8]) if f[8] else None
        except ValueError:
            pass
        if quality > 0:
            lat, lon = _deg(f[2], f[3]), _deg(f[4], f[5])
            if lat is not None and lon is not None:
                self.fix.lat, self.fix.lon = lat, lon
            try:
                self.fix.alt = float(f[9]) if f[9] else self.fix.alt
            except ValueError:
                pass
        else:
            self.fix.valid = False
