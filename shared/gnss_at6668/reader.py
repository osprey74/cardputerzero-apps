"""CardputerZero＋Cap LoRa-1262 の GNSS を読む背景リーダ（標準ライブラリのみ）。

実機で確認した構成（2026-11-17・HANDOFF §9.1）:
  - GPS の NMEA は `/dev/serial0`（→ ttyS0）に **115200bps** で出る
  - Cap の電源は本体の EXT 5V 出力に依存する。`/sys/class/leds/ext_5v_out/brightness` に
    1 を書くと給電される（`gpio` グループで書込可・sudo 不要）。標準の GPS アプリも
    起動時に入れ、終了時に切っている
  - 標準の GPS アプリが動いている間は `/dev/serial0` が専有され、開けない

`GnssReader` は 5V を入れてシリアルを開き、背景スレッドで NMEA を読み続ける。一定時間
（既定 20 秒）NMEA が 1 文も来なければ「Cap が付いていない」とみなして 5V を元に戻し、停止する。

⚠️ 既知の問題（2026-11-17）: Cap と本体の間の接触が不安定で、NMEA が届かなくなることがある
   （Cap 上の IO エキスパンダは応答するのにシリアルは 0 バイト。通常は給電の約 0.4 秒後から
   出力が始まる）。実機では Cap を押し込んでいる間だけ NMEA が届いた。GPS モジュールは正常で、
   電源の入れ直しや命令の送信では直らない。この状態では本リーダは `nodata` で停止する。
   届いているかは、動作中に `grep ttyS0 /proc/interrupts` の数が増えるかで確かめられる。
終了時（`close()`）も 5V を起動前の状態へ戻す。pyserial は使わず termios で設定する。

Grove ポートに挿した GPS ユニット（Unit GPS v1.1＝ATGM336H／AT6668・115200bps）も同じ
`/dev/serial0` に出る（Grove と Cap-Bus は UART を共有。Grove の切替 `grove_fun` は 0＝UART）。
この場合は `GnssReader(power_path=GROVE_5V)` として Grove 側の 5V を入れる。2026-11-18 に実機で、
給電の 0.39 秒後から NMEA を途切れなく受信できることを確認した（Cap は外した状態）。
"""
from __future__ import annotations

import json
import os
import select
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from .nmea import NmeaParser

EXT_5V = "/sys/class/leds/ext_5v_out/brightness"        # Cap（EXT／Cap-Bus）への 5V
GROVE_5V = "/sys/class/leds/grove_5v_out/brightness"    # Grove ポートへの 5V
DEFAULT_PORT = "/dev/serial0"
LAST_FIX = os.path.expanduser("~/.cache/cardputerzero/last_fix.json")

# 状態: off=未起動・利用不可 / nodata=NMEA が来ない（Cap 無し等）/ search=受信中・未測位 / fix=測位中
STATES = ("off", "nodata", "search", "fix")


def available(port: str = DEFAULT_PORT, power_path: str = EXT_5V) -> bool:
    """この機体で GNSS を試せるか（CardputerZero 固有の 5V 制御とシリアルがあるか）。"""
    return os.path.exists(power_path) and os.path.exists(port)


def load_last_fix(path: str = LAST_FIX) -> Optional[dict]:
    """前回の測位結果 {"lat","lon","alt","utc"} を返す（無ければ None）。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d.get("lat"), (int, float)) and isinstance(d.get("lon"), (int, float)):
            return d
    except (OSError, ValueError):
        pass
    return None


def save_last_fix(lat: float, lon: float, alt: Optional[float] = None,
                  utc: Optional[datetime] = None, path: str = LAST_FIX) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"lat": round(lat, 5), "lon": round(lon, 5), "alt": alt,
                   "utc": utc.isoformat() if utc else None}, f)
    os.replace(tmp, path)


def _open_serial(port: str, baud: int) -> int:
    import termios
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        speed = getattr(termios, f"B{baud}")
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0                                           # iflag: 変換なし
        attrs[1] = 0                                           # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # cflag: 8N1
        attrs[3] = 0                                           # lflag: raw
        attrs[4] = speed
        attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


class GnssReader:
    """GNSS の位置・時刻を背景で読み続ける。`snapshot()` で最新の状態を得る。"""

    def __init__(self, port: str = DEFAULT_PORT, baud: int = 115200,
                 power_path: Optional[str] = EXT_5V, probe_timeout: float = 20.0,
                 save_interval: float = 300.0, last_fix_path: str = LAST_FIX, on_rmc=None):
        """on_rmc: RMC を受けるたびに読み取りスレッドから呼ぶ関数（引数は snapshot() と同じ辞書）。"""
        self._on_rmc = on_rmc
        self._port, self._baud = port, baud
        self._power_path = power_path
        self._probe_timeout = probe_timeout
        self._save_interval = save_interval
        self._last_fix_path = last_fix_path
        self._lock = threading.Lock()
        self._state = "off"
        self._fix: dict = {}
        self._utc: Optional[datetime] = None      # 直近に受けた UTC
        self._utc_mono: float = 0.0               # それを受けた time.monotonic()
        self._error: Optional[str] = None
        self._power_before: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- 電源 ----
    def _power(self, on: bool) -> None:
        if not self._power_path:
            return
        try:
            if self._power_before is None:
                self._power_before = open(self._power_path).read().strip()
            with open(self._power_path, "w") as f:
                f.write("1" if on else "0")
        except OSError as ex:
            self._error = f"5V 出力を操作できない: {ex}"

    def _power_restore(self) -> None:
        if self._power_path and self._power_before is not None:
            try:
                with open(self._power_path, "w") as f:
                    f.write(self._power_before)
            except OSError:
                pass
            self._power_before = None

    # ---- スレッド ----
    def start(self) -> "GnssReader":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="gnss", daemon=True)
            self._thread.start()
        return self

    def _set(self, state: str) -> None:
        with self._lock:
            self._state = state

    def _run(self) -> None:
        self._power(True)
        time.sleep(0.4)                           # Cap の 3.3V が立ち上がるのを待つ
        try:
            fd = _open_serial(self._port, self._baud)
        except Exception as ex:  # noqa: BLE001
            self._error = f"{self._port} を開けない（標準の GPS アプリが使用中？）: {ex}"
            self._power_restore()
            self._set("off")
            return
        parser = NmeaParser()
        buf = b""
        t_start = time.monotonic()
        t_last_data = None
        t_saved = 0.0
        self._set("nodata")
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([fd], [], [], 0.5)
                now = time.monotonic()
                if r:
                    try:
                        chunk = os.read(fd, 4096)
                    except BlockingIOError:
                        chunk = b""
                    if chunk:
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        if len(buf) > 4096:
                            buf = b""
                        for raw in lines:
                            kind = parser.feed(raw.decode("ascii", "replace"))
                            if parser.sentences:
                                t_last_data = now
                            if kind:
                                self._publish(parser, now)
                                if kind == "RMC" and self._on_rmc is not None:
                                    try:
                                        self._on_rmc(self.snapshot())
                                    except Exception as ex:  # noqa: BLE001
                                        self._error = f"on_rmc: {ex}"
                if t_last_data is None:
                    if now - t_start > self._probe_timeout:
                        self._error = "NMEA が来ない（Cap LoRa-1262 が付いていない？）"
                        break                      # Cap 無し → 5V を戻して終了
                    continue
                if now - t_last_data > 5.0:
                    self._set("nodata")
                fx = parser.fix
                if fx.valid and now - t_saved > self._save_interval:
                    try:
                        save_last_fix(fx.lat, fx.lon, fx.alt, fx.utc, self._last_fix_path)
                        t_saved = now
                    except OSError:
                        pass
        finally:
            os.close(fd)
            self._power_restore()
            if self._stop.is_set() or t_last_data is None:
                self._set("off" if self._stop.is_set() else "nodata")

    def _publish(self, parser: NmeaParser, now: float) -> None:
        fx = parser.fix
        sky = parser.satellites(now)
        used = set(parser.used)
        with self._lock:
            self._state = "fix" if fx.valid else "search"
            self._fix = {"lat": fx.lat, "lon": fx.lon, "alt": fx.alt,
                         "sats": fx.sats, "hdop": fx.hdop, "speed_kmh": fx.speed_kmh,
                         "course": fx.course, "mode": fx.mode, "utc": fx.utc,
                         "sky": [{"key": s.key, "sys": s.sys, "prn": s.prn, "elev": s.elev,
                                  "azim": s.azim, "snr": s.snr, "used": s.key in used} for s in sky]}
            if fx.utc is not None and fx.utc != self._utc:
                self._utc, self._utc_mono = fx.utc, now

    # ---- 取得 ----
    def snapshot(self) -> dict:
        """{"state","lat","lon","alt","sats","hdop","speed_kmh","course","mode","utc","sky","error"}
        （位置は測位中のみ有効。sky は見えている衛星の辞書のリスト）。"""
        with self._lock:
            d = dict(self._fix)
            d["state"] = self._state
            d["error"] = self._error
            return d

    def utc_now(self) -> Optional[datetime]:
        """GNSS の UTC を現在時刻へ進めた値（一度も受けていなければ None）。"""
        with self._lock:
            if self._utc is None:
                return None
            return self._utc + timedelta(seconds=time.monotonic() - self._utc_mono)

    def alive(self) -> bool:
        """読み取りスレッドが動いているか（NMEA が来ずに諦めた場合は False）。"""
        return self._thread is not None and self._thread.is_alive()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
