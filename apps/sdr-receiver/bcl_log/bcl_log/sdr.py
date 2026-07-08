"""RTL-SDR 受信コントローラ（rtl_fm → 音声再生 + S メータ）。

App 10 の SDR 受信統合。UI から周波数/バンドを選んで `rtl_fm` を起動し、復調音声を
`aplay` で再生する。復調音声ストリームを Python で tee して **RMS レベル**を算出し、
簡易 S メータ（相対レベル・0..1）を出す。RTL-SDR は 1 プロセス占有のため rtl_power 等の
別測定は同時不可＝復調音声ベースのレベルを採用（校正 dBm ではない）。

RTL-SDR は 1 プロセス占有。再同調は rtl_fm 再起動で行う。エンコーダ(cores3_bridge)とは
デバイスが別（SDR=USB RTL2838 / エンコーダ=USB CDC ttyACM）なので同時動作可。

⚠️ 停止は必ず SIGTERM（`kill -9`/SIGKILL は USB 未解放で RTL-SDR V4 がバス脱落する）。
"""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import threading
import time

try:
    import audioop  # S16 RMS を C で高速算出（3.9 標準・3.13 で撤去）

    def _rms(buf: bytes) -> int:
        try:
            return audioop.rms(buf, 2)
        except Exception:  # noqa: BLE001
            return 0
except Exception:  # noqa: BLE001 — audioop が無い環境のフォールバック
    import array

    def _rms(buf: bytes) -> int:
        n = len(buf) // 2
        if not n:
            return 0
        a = array.array("h")
        a.frombytes(buf[: n * 2])
        return int(math.sqrt(sum(x * x for x in a) / n))


# (name, default_khz, ui_mode, step_khz, rtl_mode, samp_rate, audio_rate)
BANDS = [
    ("FM", 80400, "WFM", 100, "wbfm", 200000, 48000),   # 例: AIR-G' 80.4MHz(札幌)
    ("MW", 594, "AM", 9, "am", 1000000, 32000),          # 例: NHK札幌第1 594kHz
    ("SW", 6055, "AM", 5, "am", 1000000, 32000),         # 例: ラジオNIKKEI 6055kHz
]


def available() -> bool:
    return shutil.which("rtl_fm") is not None and shutil.which("aplay") is not None


class Receiver:
    def __init__(self):
        self.band_idx = 0
        self.freq_khz = BANDS[0][1]
        self.level = 0.0            # 0..1 平滑化レベル（復調音声 RMS ベース・簡易 S メータ）
        self._rtl = None            # type: ignore
        self._aplay = None          # type: ignore
        self._pump = None           # type: ignore
        self._stop = False
        self._pending = False       # 再同調要求（回転が落ち着いてから 1 回だけ実行）
        self._pending_t = 0.0
        self._all = []              # 生成した全プロセス（非ブロッキングで reap する追跡用）

    # --- 状態 ---
    @property
    def band(self):
        return BANDS[self.band_idx]

    @property
    def mode(self) -> str:
        return self.band[2]

    @property
    def step_khz(self) -> int:
        return self.band[3]

    @property
    def running(self) -> bool:
        return self._rtl is not None and self._rtl.poll() is None

    def freq_label(self) -> str:
        if self.band[0] == "FM":
            return "%.1f MHz" % (self.freq_khz / 1000.0)
        return "%d kHz" % self.freq_khz

    # --- 操作 ---
    def set_band(self, delta: int):
        self.band_idx = (self.band_idx + delta) % len(BANDS)
        self.freq_khz = self.band[1]
        self._mark_retune()

    def tune(self, steps: int):
        if steps == 0:
            return
        self.freq_khz = max(1, self.freq_khz + steps * self.step_khz)
        self._mark_retune()

    def _mark_retune(self):
        # 受信中は再同調を予約するだけ（回転が落ち着いてから service() が 1 回実行）。
        if self.running:
            self._pending = True
            self._pending_t = time.monotonic()

    def service(self):
        """UI ループから毎フレーム呼ぶ。終了プロセスを reap し、予約された再同調を実行。"""
        self._reap_finished()
        if self._pending and self.running and time.monotonic() - self._pending_t > 0.4:
            self._pending = False
            self.start()   # 現在の freq/band で受信し直す

    def _reap_finished(self):
        """追跡中プロセスのうち終了したものを poll() で reap（ゾンビ回収・非ブロッキング）。"""
        self._all = [p for p in self._all if p.poll() is None]

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        self.stop()
        if not available():
            return
        _n, _d, _u, _s, rtl_mode, samp, audio = self.band
        hz = int(self.freq_khz * 1000)
        dev = os.environ.get("BCL_APLAY_DEVICE", "pulse")  # 既定 PulseAudio
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
        self._stop = False
        self.level = 0.0
        # rtl_fm(raw S16LE mono) → Python(tee/RMS) → aplay。各々 setsid で個別に SIGTERM 可。
        self._rtl = subprocess.Popen(
            ["rtl_fm", "-f", str(hz), "-M", rtl_mode, "-s", str(samp),
             "-r", str(audio), "-l", "0", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, preexec_fn=os.setsid,
        )
        self._aplay = subprocess.Popen(
            ["aplay", "-D", dev, "-r", str(audio), "-f", "S16_LE",
             "-t", "raw", "-c", "1", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, preexec_fn=os.setsid, env=env,
        )
        # ポンプは自分の rtl/aplay ハンドルに束ねる（再同調で start() が呼ばれても
        # 旧ポンプは旧プロセスを見て終了し、新ポンプと同一パイプを奪い合わない）。
        self._all += [self._rtl, self._aplay]   # reap 追跡
        self._pump = threading.Thread(
            target=self._run_pump, args=(self._rtl, self._aplay), daemon=True)
        self._pump.start()

    def _run_pump(self, rtl, aplay):
        """rtl_fm 出力を読み、RMS→レベル更新しつつ aplay へ転送する。"""
        full = 32767.0
        while not self._stop and rtl.poll() is None:
            buf = rtl.stdout.read(4096)
            if not buf:
                break
            r = _rms(buf) / full
            db = -50.0 if r <= 1e-4 else max(-50.0, 20.0 * math.log10(r))
            lvl = (db + 50.0) / 50.0            # -50..0 dBFS → 0..1
            self.level = 0.7 * self.level + 0.3 * lvl  # EMA 平滑
            try:
                if aplay.stdin is not None:
                    aplay.stdin.write(buf)
            except (BrokenPipeError, ValueError, OSError):
                break
        # aplay の stdin を閉じて自然終了を促す（reap は _reap_finished が非ブロッキングで行う）。
        try:
            if aplay.stdin is not None:
                aplay.stdin.close()
        except OSError:
            pass

    def stop(self):
        self._stop = True
        self._pending = False
        procs = [p for p in (self._aplay, self._rtl) if p is not None]
        for p in procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)  # ※ SIGKILL 厳禁
            except (ProcessLookupError, PermissionError):
                pass
        # 実際に終了するまで待つ（次の start が RTL-SDR を掴む前にデバイスを解放させる）。
        # 再同調はコアレス済み＝この待ちは同調が落ち着いた 1 回だけなので UI 停止は許容範囲。
        for p in procs:
            try:
                p.wait(timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
        self._rtl = None
        self._aplay = None
        self.level = 0.0
        self._reap_finished()
