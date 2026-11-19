"""周辺 AP のスキャン（nmcli）と接続中リンクの電波強度（/proc/net/wireless）。

- 周辺 AP: NetworkManager の `nmcli dev wifi list` を使う。`pi` ユーザーのまま再スキャンでき、
  iw や root 権限は要らない（2026-11-19 実機確認）。受信するのは AP が出しているビーコン
  （どの端末の Wi-Fi 一覧にも出る情報）だけで、他者のネットワークへは接続しない。
- 信号の強さ: nmcli は 0〜100 の相対値（%）しか出さない。接続中の AP だけは
  /proc/net/wireless の level（dBm）を 1 秒ごとに読める。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field

FIELDS = ["IN-USE", "BSSID", "SSID", "CHAN", "FREQ", "RATE", "SIGNAL", "SECURITY", "BANDWIDTH"]
HISTORY = 400                 # AP ごとに保持する信号履歴の点数
STALE_SEC = 60.0              # これより長く見えない AP は一覧から外す


def split_terse(line: str) -> list[str]:
    """nmcli -t の 1 行を区切る（値の中の ':' は '\\:'、'\\' は '\\\\' でエスケープされる）。"""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _int(s: str) -> int:
    digits = "".join(ch for ch in s.split(" ")[0] if ch.isdigit())
    return int(digits) if digits else 0


@dataclass
class AP:
    bssid: str
    ssid: str
    chan: int
    freq: int                 # MHz
    rate: int                 # Mbit/s
    signal: int               # 0〜100（%）
    security: str
    width: int                # MHz（不明なら 20）
    in_use: bool
    last_seen: float = 0.0
    hist: deque = field(default_factory=lambda: deque(maxlen=HISTORY))   # (t, signal%)

    @property
    def band(self) -> str:
        return "5G" if self.freq >= 4900 else "2.4G"

    @property
    def sec_short(self) -> str:
        s = self.security.upper()
        if not s or s == "--":
            return "OPEN"
        for k in ("WPA3", "WPA2", "WPA1", "WEP"):
            if k in s:
                return "WPA" if k == "WPA1" else k
        return s.split()[0]


def parse_list(text: str, fields: list[str] = FIELDS) -> list[dict]:
    """nmcli -t -f <fields> dev wifi list の出力を辞書のリストにする。"""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        vals = split_terse(line)
        if len(vals) != len(fields):
            continue
        r = dict(zip(fields, vals))
        rows.append({
            "in_use": r.get("IN-USE", "").strip() == "*",
            "bssid": r.get("BSSID", "").upper(),
            "ssid": r.get("SSID", ""),
            "chan": _int(r.get("CHAN", "0")),
            "freq": _int(r.get("FREQ", "0")),
            "rate": _int(r.get("RATE", "0")),
            "signal": _int(r.get("SIGNAL", "0")),
            "security": r.get("SECURITY", ""),
            "width": _int(r.get("BANDWIDTH", "20")) or 20,
        })
    return rows


def parse_proc_wireless(text: str, ifname: str = "wlan0") -> float | None:
    """/proc/net/wireless から level（dBm）を返す。"""
    for line in text.splitlines():
        if line.strip().startswith(ifname + ":"):
            parts = line.split(":", 1)[1].split()
            try:
                return float(parts[2].rstrip("."))
            except (IndexError, ValueError):
                return None
    return None


class Scanner:
    """nmcli による周期スキャンと 1 秒ごとのリンク強度の読み取りを背景スレッドで行う。"""

    def __init__(self, interval: float = 10.0, ifname: str = "wlan0", runner=None):
        self.interval = interval
        self.ifname = ifname
        self.lock = threading.Lock()
        self.aps: dict[str, AP] = {}
        self.link_hist: deque = deque(maxlen=HISTORY)      # (t, dBm) 接続中 AP のみ
        self.version = 0
        self.scanning = False
        self.last_scan = 0.0
        self.scans = 0
        self.error = ""
        self.log_path: str | None = None
        self._fields = list(FIELDS)
        self._runner = runner or self._run_nmcli
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []

    # ---- nmcli ----
    def _run_nmcli(self, rescan: str) -> tuple[int, str, str]:
        cmd = ["nmcli", "-t", "-e", "yes", "-f", ",".join(self._fields),
               "dev", "wifi", "list", "--rescan", rescan]
        env = dict(os.environ, LC_ALL="C")
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return p.returncode, p.stdout, p.stderr

    def scan_once(self) -> None:
        self.scanning = True
        self.version += 1
        try:
            rc, out, err = self._runner("yes")
            if rc != 0 and "BANDWIDTH" in self._fields and "BANDWIDTH" in err:
                self._fields.remove("BANDWIDTH")              # 古い nmcli 向け
                rc, out, err = self._runner("yes")
            if rc != 0:                                        # 再スキャンの間隔制限など
                rc, out, err = self._runner("no")
            if rc != 0:
                self.error = (err.strip() or f"nmcli rc={rc}").splitlines()[-1][:60]
                return
            self.error = ""
            self.ingest(parse_list(out, self._fields), time.time())
        except (OSError, subprocess.SubprocessError) as e:
            self.error = str(e)[:60]
        finally:
            self.scanning = False
            self.version += 1

    def ingest(self, rows: list[dict], now: float) -> None:
        with self.lock:
            for r in rows:
                if not r["bssid"]:
                    continue
                ap = self.aps.get(r["bssid"])
                if ap is None:
                    ap = AP(**r)
                    self.aps[r["bssid"]] = ap
                else:
                    for k, v in r.items():
                        setattr(ap, k, v)
                ap.last_seen = now
                ap.hist.append((now, r["signal"]))
            for b in [b for b, a in self.aps.items() if now - a.last_seen > STALE_SEC]:
                del self.aps[b]
            self.last_scan = now
            self.scans += 1
        if self.log_path:
            self._append_log(rows, now)

    # ---- CSV 記録 ----
    def start_log(self, directory: str) -> str:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, time.strftime("wifi_%Y%m%d_%H%M%S.csv"))
        with open(path, "w", encoding="utf-8") as f:
            f.write("time,bssid,ssid,chan,freq_mhz,signal_pct,security,in_use\n")
        self.log_path = path
        return path

    def stop_log(self) -> None:
        self.log_path = None

    def _append_log(self, rows: list[dict], now: float) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                for r in rows:
                    ssid = r["ssid"].replace('"', '""')
                    f.write(f'{ts},{r["bssid"]},"{ssid}",{r["chan"]},{r["freq"]},'
                            f'{r["signal"]},{r["security"]},{int(r["in_use"])}\n')
        except OSError as e:
            self.error = f"log: {e}"[:60]
            self.log_path = None

    # ---- スレッド ----
    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            self._wake.wait(self.interval)
            self._wake.clear()

    def _link_loop(self) -> None:
        while not self._stop.is_set():
            try:
                lvl = parse_proc_wireless(open("/proc/net/wireless").read(), self.ifname)
            except OSError:
                lvl = None
            if lvl is not None:
                with self.lock:
                    self.link_hist.append((time.time(), lvl))
                self.version += 1
            self._stop.wait(1.0)

    def start(self) -> None:
        for fn in (self._scan_loop, self._link_loop):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)

    def rescan_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def snapshot(self) -> list[AP]:
        with self.lock:
            return list(self.aps.values())
