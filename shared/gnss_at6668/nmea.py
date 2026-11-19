"""NMEA 0183 の最小パーサ（RMC・GGA・GSA・GSV）。外部依存なし。

Cap LoRa-1262 の GP-02（ATGM336H／AT6668）や Grove の Unit GPS v1.1 は 115200bps で
GN/GP/GL/GA/BD/GQ 各トーカーの文を出す。位置・時刻・測位状態（RMC・GGA）と、
衛星の情報（GSA＝測位に使っている衛星と 2D/3D、GSV＝見えている衛星の仰角・方位・SNR）を
解釈し、それ以外は無視する。

実機の出力（2026-11-19・Unit GPS v1.1）は NMEA 4.1 形式で、GSV の末尾に信号 ID、
GSA の末尾に衛星系 ID（1=GPS 2=GLONASS 3=Galileo 4=BeiDou 5=QZSS）が付く。
GSA は衛星系ごとに 1 秒 5 本、GSV のトーカーは GP/GL/GA/BD/GQ（GQ＝みちびき）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# 衛星系の 1 文字記号（G=GPS Q=QZSS R=GLONASS E=Galileo B=BeiDou S=SBAS）
TALKER_SYS = {"GP": "G", "GQ": "Q", "QZ": "Q", "GL": "R", "GA": "E", "GB": "B", "BD": "B"}
GSA_SYSID = {1: "G", 2: "R", 3: "E", 4: "B", 5: "Q"}
SAT_TTL = 5.0                         # これより長く GSV/GSA に出てこない衛星は捨てる[秒]


def sat_system(talker: str, prn: int) -> str:
    """トーカーと PRN から衛星系の記号を決める（GP の 33〜64 は SBAS、193〜202 は QZSS）。"""
    s = TALKER_SYS.get(talker)
    if s == "G" or s is None:
        if 193 <= prn <= 202:
            return "Q"
        if 33 <= prn <= 64:
            return "S"
        if s is None and 65 <= prn <= 96:
            return "R"
        return "G"
    return s


@dataclass
class Sat:
    """見えている衛星 1 機。"""
    sys: str                          # G/Q/R/E/B/S
    prn: int
    elev: Optional[int]               # 仰角 [度]
    azim: Optional[int]               # 方位 [度]（北=0・東=90）
    snr: Optional[int]                # C/N0 [dBHz]（追尾していなければ None）
    seen: float = 0.0                 # 最後に GSV で見た時刻（monotonic）

    @property
    def key(self) -> str:
        return f"{self.sys}{self.prn:02d}"


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
    speed_kmh: Optional[float] = None # 対地速度 [km/h]（RMC）
    course: Optional[float] = None    # 進行方向 [度]（RMC・止まっているときは不定）
    mode: int = 1                     # 1=未測位 2=2D 3=3D（GSA）


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
        self.sats: dict[str, Sat] = {}       # 見えている衛星（キー "G07" など）
        self.used: dict[str, float] = {}     # 測位に使っている衛星のキー → 最後に GSA で見た時刻
        self._mode_seen: dict[str, tuple[int, float]] = {}   # 衛星系ごとの GSA の 2D/3D

    def feed(self, line: str, now: Optional[float] = None) -> Optional[str]:
        """1 行を解釈する。解釈した文の種別（"RMC"／"GGA"／"GSA"／"GSV"）か、それ以外は None を返す。"""
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
        if kind == "GSA" and len(f) >= 18:
            self._gsa(f, time.monotonic() if now is None else now)
            return "GSA"
        if kind == "GSV" and len(f) >= 4:
            self._gsv(f, time.monotonic() if now is None else now)
            return "GSV"
        return None

    def satellites(self, now: Optional[float] = None) -> list[Sat]:
        """見えている衛星（古いものは除く）。"""
        now = time.monotonic() if now is None else now
        for k in [k for k, s in self.sats.items() if now - s.seen > SAT_TTL]:
            del self.sats[k]
        for k in [k for k, t in self.used.items() if now - t > SAT_TTL]:
            del self.used[k]
        return list(self.sats.values())

    def _gsa(self, f, now: float) -> None:
        # $xxGSA,A,mode,prn×12,pdop,hdop,vdop[,sysid]
        try:
            mode = int(f[2] or 1)
        except ValueError:
            mode = 1
        sysid = None
        if len(f) >= 19 and f[18]:
            try:
                sysid = GSA_SYSID.get(int(f[18], 16))
            except ValueError:
                sysid = None
        talker = f[0][:2]
        tag = sysid or talker
        self._mode_seen[tag] = (mode, now)
        self.fix.mode = max((m for m, t in self._mode_seen.values() if now - t <= SAT_TTL), default=1)
        for p in f[3:15]:
            if not p:
                continue
            try:
                prn = int(p)
            except ValueError:
                continue
            self.used[f"{sysid or sat_system(talker, prn)}{prn:02d}"] = now

    def _gsv(self, f, now: float) -> None:
        # $xxGSV,総数,番号,衛星数,{prn,仰角,方位,snr}×最大4[,信号 ID]
        talker = f[0][:2]
        body = f[4:]
        if len(body) % 4 == 1:            # NMEA 4.1 の信号 ID
            body = body[:-1]
        for i in range(0, len(body) - 3, 4):
            prn_s, el, az, snr = body[i:i + 4]
            try:
                prn = int(prn_s)
            except ValueError:
                continue
            def num(v):
                try:
                    return int(float(v)) if v != "" else None
                except ValueError:
                    return None
            s = Sat(sat_system(talker, prn), prn, num(el), num(az), num(snr), now)
            old = self.sats.get(s.key)
            if old is not None and s.snr is None and old.snr is not None and now - old.seen < 1.5:
                s.snr = old.snr               # 同じ周期内の別信号（L5 等）で SNR が空なら前の値を残す
            self.sats[s.key] = s

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
            try:
                self.fix.speed_kmh = float(f[7]) * 1.852 if f[7] else None
            except ValueError:
                self.fix.speed_kmh = None
            try:
                self.fix.course = float(f[8]) if f[8] else None
            except ValueError:
                self.fix.course = None
        else:
            self.fix.speed_kmh = self.fix.course = None
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
