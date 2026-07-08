"""RTL-SDR 受信コントローラ（pyrtlsdr ライブ同調 + numpy 復調 + aplay 音声）。

App 10 の SDR 受信。**デバイスをセッション中 1 回だけ open** し、`center_freq` を
ライブ変更して同調する（rtl_fm を張り替える旧方式は、RTL-SDR V4 が close→reopen で
ストリーム停止する不具合を招いたため廃止）。IQ を numpy で AM/FM 復調して 48kHz int16 に
し `aplay` へ流す。S メータは **IQ 電力**（`10·log10(mean|IQ|²)`）ベースの相対 RF レベル。

デバイスは 1 回開くだけ＝再オープンによる V4 ハングを誘発しない（＝デバイスに優しい）。
依存: pyrtlsdr(0.2.93) / numpy / aplay。エンコーダ(cores3_bridge)とはデバイスが別。
"""
from __future__ import annotations

import gc
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
import time

import numpy as np
import scipy.signal as sig

try:
    from rtlsdr import RtlSdr
    _HAVE_RTL = True
except Exception:  # noqa: BLE001
    RtlSdr = None
    _HAVE_RTL = False

SAMPLE_RATE = 960000      # RTL サンプルレート（960k：AM/FM とも dec=20 で 48k 音声へ）
AUDIO_RATE = 48000
DEC = SAMPLE_RATE // AUDIO_RATE     # = 20
BLOCK = 102400            # 非同期コールバック 1 回のサンプル数（512 と 20 の倍数・約0.107s）

# (name, default_khz, ui_mode, step_khz, demod)
BANDS = [
    ("FM", 80400, "WFM", 100, "fm"),    # 例: AIR-G' 80.4MHz(札幌)
    ("MW", 594, "AM", 9, "am"),          # 例: NHK札幌第1 594kHz（V4 の HF 受信）
    ("SW", 6055, "AM", 5, "am"),         # 例: ラジオNIKKEI 6055kHz
]

# S メータのマッピング（IQ 電力 dB → 0..1）。実測で調整（空き帯≈-21dB / 強局≈+1dB）。
SIG_DB_LO, SIG_DB_HI = -24.0, 2.0


def available() -> bool:
    return _HAVE_RTL and shutil.which("aplay") is not None


# FM デエンファシス（75µs・1-pole IIR @ AUDIO_RATE）。lfilter で状態保持して適用。
_DEEMPH_D = math.exp(-1.0 / (AUDIO_RATE * 75e-6))
_DEEMPH_B = np.array([1.0 - _DEEMPH_D])
_DEEMPH_A = np.array([1.0, -_DEEMPH_D])


class Receiver:
    def __init__(self):
        self.band_idx = 0
        self.freq_khz = BANDS[0][1]
        self.level = 0.0                # 0..1（IQ 電力ベースの相対 RF レベル）
        self.level_db = -99.0           # 生 dB（校正/デバッグ用）
        self._sdr = None                # type: ignore
        self._aplay = None              # type: ignore
        self._reader = None             # type: ignore
        self._proc = None               # type: ignore
        self._q = None                  # type: ignore
        self._stop = False
        self._mode = BANDS[0][4]
        self._pending_freq = None       # Hz（reader スレッドが読みの合間に適用）
        self._pending_mode = None
        self._zi = None                 # デエンファシス lfilter 状態（ブロック間で保持）
        self._demod_mode = None         # 直近の復調モード（変わったら _zi リセット）

    # --- 状態 ---
    @property
    def band(self):
        return BANDS[self.band_idx]

    @property
    def mode(self):
        return self.band[2]

    @property
    def step_khz(self):
        return self.band[3]

    @property
    def running(self):
        return self._reader is not None and self._reader.is_alive()

    def freq_label(self):
        if self.band[0] == "FM":
            return "%.1f MHz" % (self.freq_khz / 1000.0)
        return "%d kHz" % self.freq_khz

    # --- 操作（ライブ：デバイスは開いたまま） ---
    def set_band(self, delta):
        self.band_idx = (self.band_idx + delta) % len(BANDS)
        self.freq_khz = self.band[1]
        self._pending_freq = int(self.freq_khz * 1000)
        self._pending_mode = self.band[4]

    def tune(self, steps):
        if steps == 0:
            return
        self.freq_khz = max(1, self.freq_khz + steps * self.step_khz)
        self._pending_freq = int(self.freq_khz * 1000)

    def toggle(self):
        self.stop() if self.running else self.start()

    def service(self):
        # aplay が死んでいたら受信も止める（後始末）。
        if self._aplay is not None and self._aplay.poll() is not None and self.running:
            self.stop()

    def start(self):
        self.stop()
        if not available():
            return
        try:
            self._sdr = RtlSdr()
            self._sdr.sample_rate = SAMPLE_RATE
            self._sdr.center_freq = int(self.freq_khz * 1000)
            try:
                self._sdr.set_manual_gain_enabled(False)  # AGC
            except Exception:  # noqa: BLE001
                self._sdr.gain = 'auto'
        except Exception as e:  # noqa: BLE001
            print("rtlsdr open failed: %s" % e)
            self._sdr = None
            return
        dev = os.environ.get("BCL_APLAY_DEVICE", "pulse")
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
        self._aplay = subprocess.Popen(
            ["aplay", "-D", dev, "-r", str(AUDIO_RATE), "-f", "S16_LE",
             "-t", "raw", "-c", "1", "--buffer-time=400000", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, preexec_fn=os.setsid, env=env,
        )
        gc.disable()   # 受信中は周期 GC を止める（音声スレッドのポーズ＝aplay underrun 防止）
        self._stop = False
        self._pending_freq = None
        self._pending_mode = None
        self._mode = self.band[4]
        self._zi = None
        self._demod_mode = None
        self._q = queue.Queue(maxsize=16)   # 深めのバッファで一時的な処理詰まりを吸収（途切れ対策）
        # 読み取り専用スレッド（同期読みを密ループ＝デバイスを常時 drain）
        self._reader = threading.Thread(target=self._run_reader, daemon=True)
        # 復調スレッド（重い numpy 処理を読み取りから分離＝FIFO オーバーフロー＝音切れを防ぐ）
        self._proc = threading.Thread(target=self._run_proc, daemon=True)
        self._reader.start()
        self._proc.start()

    def _run_reader(self):
        """同期読みの密ループ。読みの合間（デバイス idle）に同調を適用＝-6 を回避。"""
        dbg = bool(os.environ.get("BCL_SDR_DEBUG"))
        while not self._stop:
            if self._pending_freq is not None:
                try:
                    self._sdr.center_freq = self._pending_freq   # ライブ同調（開き直さない）
                except Exception:  # noqa: BLE001
                    pass
                self._pending_freq = None
            if self._pending_mode is not None:
                self._mode = self._pending_mode
                self._pending_mode = None
            try:
                t0 = time.monotonic()
                # 生バイトのみ読む（bytes→複素数変換は proc スレッドへ回し、読取の合間を最小化＝
                # サンプル取りこぼしによる供給レート不足＝周期的 underrun を防ぐ）。
                raw = bytes(self._sdr.read_bytes(BLOCK * 2))   # 即コピー（内部バッファ再利用対策・memcpy は軽量）
                if dbg:
                    rd = time.monotonic() - t0
                    if rd > 0.13:
                        print("[dbg] slow read %.3fs qsize=%d" % (rd, self._q.qsize()), flush=True)
            except Exception:  # noqa: BLE001
                break
            try:
                self._q.put_nowait(raw)
            except queue.Full:
                if dbg:
                    print("[dbg] queue FULL drop", flush=True)

    def _run_proc(self):
        dbg = bool(os.environ.get("BCL_SDR_DEBUG"))
        last = time.monotonic()
        while not self._stop:
            try:
                raw = self._q.get(timeout=0.5)
            except queue.Empty:
                if dbg:
                    print("[dbg] queue EMPTY (underrun)", flush=True)
                continue
            if dbg:
                now = time.monotonic()
                dt = now - last
                last = now
                if dt > 0.15:
                    print("[dbg] proc gap %.3fs qsize=%d" % (dt, self._q.qsize()), flush=True)
            # 生バイト(uint8 IQ インタリーブ) → 正規化複素数
            d = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            x = ((d[0::2] - 127.4) + 1j * (d[1::2] - 127.4)) / 127.5
            p = float(np.mean(np.abs(x) ** 2)) + 1e-9
            self.level_db = 10.0 * math.log10(p)
            lvl = (self.level_db - SIG_DB_LO) / (SIG_DB_HI - SIG_DB_LO)
            self.level = 0.6 * self.level + 0.4 * max(0.0, min(1.0, lvl))
            try:
                if self._aplay is not None and self._aplay.stdin is not None:
                    self._aplay.stdin.write(self._demod(x, self._mode))
            except (BrokenPipeError, ValueError, OSError):
                break

    def _demod(self, x, mode):
        """IQ → 48kHz int16。2 段 FIR デシメーション（アンチエイリアス）＋FM デエンファシス。"""
        if mode != self._demod_mode:
            self._zi = None
            self._demod_mode = mode
        if mode == "fm":
            d = np.angle(x[1:] * np.conj(x[:-1]))       # FM 判別器
            a = sig.decimate(d, 4, ftype="fir")
            a = sig.decimate(a, 5, ftype="fir")          # 960k → 48k（2 段）
            if self._zi is None:
                self._zi = sig.lfilter_zi(_DEEMPH_B, _DEEMPH_A) * (a[0] if len(a) else 0.0)
            a, self._zi = sig.lfilter(_DEEMPH_B, _DEEMPH_A, a, zi=self._zi)  # 75µs デエンファシス
            a = np.clip(a * 3.5, -1.0, 1.0)
        else:
            m = np.abs(x)                                # AM 包絡線
            a = sig.decimate(m, 4, ftype="fir")
            a = sig.decimate(a, 5, ftype="fir")
            a = a - np.mean(a)                           # DC 除去
            a = np.clip(a * 6.0, -1.0, 1.0)
        return (a * 32767).astype(np.int16).tobytes()

    def stop(self):
        self._stop = True
        gc.enable()   # 受信停止で GC を戻す
        for t in (self._reader, self._proc):
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=2.0)
        self._reader = None
        self._proc = None
        if self._sdr is not None:
            try:
                self._sdr.close()      # デバイスは 1 回だけ開閉
            except Exception:  # noqa: BLE001
                pass
            self._sdr = None
        if self._aplay is not None:
            try:
                os.killpg(os.getpgid(self._aplay.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self._aplay.wait(timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
            self._aplay = None
        self.level = 0.0
