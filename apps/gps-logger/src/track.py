"""GPS ロガーの記録部（GPX 1.1 の書き出し・トラック統計・異常終了時の修復）。標準ライブラリのみ。

- GPX は 1 点ずつ追記する（1 点 1 行・毎回 flush、30 秒ごとに fsync）。電池切れや強制終了で
  閉じタグが無いまま残ったファイルは、次の起動時に `recover()` が閉じタグを補う。
- 一時停止で <trkseg> を閉じ、再開で新しい <trkseg> を始める（停止中の移動は距離に入れない）。
- GPX の時刻は GNSS の UTC。速度は GPX 1.1 の標準要素に無いため書かない（取り込み側で計算できる）。
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timezone

EARTH_R = 6371008.8
CREATOR = "CardputerZero gps-logger"
FOOTER_SEG = "    </trkseg>\n"
FOOTER = "  </trk>\n</gpx>\n"


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2 点間の距離 [m]。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Stats:
    """距離・移動時間・最高速度・累積標高。停止中の位置のふらつきは距離に入れない。"""

    STILL_KMH = 1.5          # これより遅く、
    STILL_M = 10.0           # かつ基準点からこれより近ければ停止中とみなす
    MOVING_KMH = 2.0         # 移動時間に数える速度
    ELE_STEP = 3.0           # 累積標高のヒステリシス [m]
    MAX_KMH = 200.0          # これを超える速度は誤測位として最高速度に入れない

    def __init__(self):
        self.distance_m = 0.0
        self.moving_s = 0.0
        self.max_kmh = 0.0
        self.gain_m = 0.0
        self.loss_m = 0.0
        self.points = 0
        self._anchor = None          # (lat, lon) 距離の基準点
        self._ele_ref = None
        self._last_t = None

    def break_segment(self) -> None:
        self._anchor = None
        self._last_t = None

    def add(self, lat: float, lon: float, ele, speed_kmh, hdop, mode: int, t: float) -> None:
        self.points += 1
        if self._last_t is not None and speed_kmh is not None and speed_kmh >= self.MOVING_KMH:
            self.moving_s += min(5.0, max(0.0, t - self._last_t))
        self._last_t = t
        if self._anchor is None:
            self._anchor = (lat, lon)
        else:
            d = haversine(self._anchor[0], self._anchor[1], lat, lon)
            still = (speed_kmh is not None and speed_kmh < self.STILL_KMH) and d < self.STILL_M
            if not still:
                self.distance_m += d
                self._anchor = (lat, lon)
        good = mode == 3 and (hdop is None or hdop <= 3.0)
        if good and speed_kmh is not None and speed_kmh <= self.MAX_KMH:
            self.max_kmh = max(self.max_kmh, speed_kmh)
        if ele is not None and good:
            if self._ele_ref is None:
                self._ele_ref = ele
            elif ele - self._ele_ref >= self.ELE_STEP:
                self.gain_m += ele - self._ele_ref
                self._ele_ref = ele
            elif self._ele_ref - ele >= self.ELE_STEP:
                self.loss_m += self._ele_ref - ele
                self._ele_ref = ele

    def avg_kmh(self) -> float:
        return self.distance_m / self.moving_s * 3.6 if self.moving_s > 0 else 0.0


class Recorder:
    """記録の状態（idle / rec / paused）と GPX ファイル。on_rmc から呼ばれるためスレッド安全。"""

    MAX_TRAIL = 4000          # 画面の軌跡用に残す点の上限（間引きながら保持）

    def __init__(self, directory: str):
        self.directory = directory
        self.lock = threading.Lock()
        self.state = "idle"
        self.path: str | None = None
        self.stats = Stats()
        self.trail: list[tuple[float, float]] = []
        self._f = None
        self._t_started = 0.0
        self._t_paused = 0.0
        self._paused_total = 0.0
        self._t_fsync = 0.0
        self._last_utc = None
        self._final_elapsed = 0.0

    # ---- 操作 ----
    def start(self, utc: datetime | None = None) -> str:
        with self.lock:
            if self.state != "idle":
                return self.path or ""
            os.makedirs(self.directory, exist_ok=True)
            now = utc or datetime.now(timezone.utc).replace(tzinfo=None)
            local = datetime.fromtimestamp(time.time())
            self.path = os.path.join(self.directory, local.strftime("track_%Y%m%d_%H%M%S.gpx"))
            self._f = open(self.path, "w", encoding="utf-8")
            self._f.write(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<gpx version="1.1" creator="{CREATOR}" xmlns="http://www.topografix.com/GPX/1/1"'
                ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
                ' xsi:schemaLocation="http://www.topografix.com/GPX/1/1'
                ' http://www.topografix.com/GPX/1/1/gpx.xsd">\n'
                f"  <metadata><time>{iso(now)}</time></metadata>\n"
                f"  <trk>\n    <name>{local.strftime('%Y-%m-%d %H:%M')}</name>\n"
                "    <trkseg>\n")
            self._f.flush()
            self.stats = Stats()
            self.trail = []
            self._t_started = time.monotonic()
            self._paused_total = 0.0
            self._last_utc = None
            self.state = "rec"
            return self.path

    def pause(self) -> None:
        with self.lock:
            if self.state == "rec":
                self._f.write(FOOTER_SEG)
                self._f.flush()
                self.stats.break_segment()
                self._t_paused = time.monotonic()
                self.state = "paused"

    def resume(self) -> None:
        with self.lock:
            if self.state == "paused":
                self._f.write("    <trkseg>\n")
                self._f.flush()
                self._paused_total += time.monotonic() - self._t_paused
                self.state = "rec"

    def stop(self) -> str | None:
        with self.lock:
            if self.state == "idle":
                return None
            end = self._t_paused if self.state == "paused" else time.monotonic()
            self._final_elapsed = end - self._t_started - self._paused_total
            if self.state == "rec":
                self._f.write(FOOTER_SEG)
            self._f.write(FOOTER)
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()
            self._f = None
            self.state = "idle"
            return self.path

    # ---- 点の追加（GNSS の読み取りスレッドから） ----
    def add(self, snap: dict) -> bool:
        if snap.get("state") != "fix" or snap.get("lat") is None:
            return False
        with self.lock:
            if self.state != "rec":
                return False
            utc = snap.get("utc")
            if utc is not None and utc == self._last_utc:
                return False                       # 同じ時刻の重複
            self._last_utc = utc
            lat, lon, ele = snap["lat"], snap["lon"], snap.get("alt")
            parts = [f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}">']
            if ele is not None:
                parts.append(f"<ele>{ele:.1f}</ele>")
            if utc is not None:
                parts.append(f"<time>{iso(utc)}</time>")
            mode = snap.get("mode") or 1
            if mode in (2, 3):
                parts.append(f"<fix>{mode}d</fix>")
            if snap.get("sats") is not None:
                parts.append(f"<sat>{snap['sats']}</sat>")
            if snap.get("hdop") is not None:
                parts.append(f"<hdop>{snap['hdop']:.1f}</hdop>")
            parts.append("</trkpt>\n")
            self._f.write("".join(parts))
            self._f.flush()
            now = time.monotonic()
            if now - self._t_fsync > 30.0:
                os.fsync(self._f.fileno())
                self._t_fsync = now
            # 移動時間は GNSS の時刻で数える（受信の遅れや処理の揺れに左右されない）
            t = (utc - datetime(2000, 1, 1)).total_seconds() if utc is not None else now
            self.stats.add(lat, lon, ele, snap.get("speed_kmh"), snap.get("hdop"), mode, t)
            if not self.trail or haversine(self.trail[-1][0], self.trail[-1][1], lat, lon) >= 5.0:
                self.trail.append((lat, lon))
                if len(self.trail) > self.MAX_TRAIL:
                    self.trail = self.trail[::2]
            return True

    def elapsed(self) -> float:
        """記録時間（一時停止を除く）[秒]。終了後は最後の記録の時間。"""
        with self.lock:
            if self.state == "idle":
                return self._final_elapsed
            end = self._t_paused if self.state == "paused" else time.monotonic()
            return end - self._t_started - self._paused_total


def recover(directory: str) -> list[str]:
    """閉じタグの無い GPX（電池切れ・強制終了）に閉じタグを補う。直したファイルの一覧を返す。"""
    fixed = []
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".gpx"))
    except OSError:
        return fixed
    for n in names:
        path = os.path.join(directory, n)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if text.rstrip().endswith("</gpx>") or "<trk>" not in text:
            continue
        if not text.endswith("\n"):
            text = text[: text.rfind("\n") + 1]            # 途中で切れた最後の行を捨てる
        tail = ""
        if text.rfind("<trkseg>") > text.rfind("</trkseg>"):
            tail += FOOTER_SEG
        tail += FOOTER
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + tail)
        fixed.append(path)
    return fixed
