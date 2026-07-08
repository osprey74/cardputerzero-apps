"""RTL-SDR 受信コントローラ（rtl_fm → aplay で実音声出力）。

App 10 の SDR 受信統合。UI から周波数/バンドを選んで `rtl_fm` を起動し、復調音声を
`aplay` で再生する薄いラッパー。RTL-SDR は 1 プロセス占有のため、再同調は
rtl_fm の再起動で行う（rtl_fm はライブ再同調不可）。

依存: `rtl_fm`/`aplay`（無い場合は available()=False）。エンコーダ(cores3_bridge)とは
デバイスが別（SDR=USB RTL2838 / エンコーダ=USB CDC ttyACM）なので同時動作可。
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess

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
        self._proc = None  # type: ignore

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
        return self._proc is not None and self._proc.poll() is None

    def freq_label(self) -> str:
        if self.band[0] == "FM":
            return "%.1f MHz" % (self.freq_khz / 1000.0)
        return "%d kHz" % self.freq_khz

    # --- 操作 ---
    def set_band(self, delta: int):
        was = self.running
        self.band_idx = (self.band_idx + delta) % len(BANDS)
        self.freq_khz = self.band[1]
        if was:
            self.start()  # 再起動で反映

    def tune(self, steps: int):
        if steps == 0:
            return
        self.freq_khz = max(1, self.freq_khz + steps * self.step_khz)
        if self.running:
            self.start()

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        self.stop()
        if not available():
            return
        _name, _d, _uim, _st, rtl_mode, samp, audio = self.band
        hz = int(self.freq_khz * 1000)
        # 出力先: 既定は PulseAudio(=デスクトップの音量/スピーカーに確実に届く)。
        # CZ 実機等 pulse が無い環境では BCL_APLAY_DEVICE=default 等に上書きする。
        dev = os.environ.get("BCL_APLAY_DEVICE", "pulse")
        # rtl_fm(raw S16LE mono) → aplay。プロセスグループで一括 kill するため setsid。
        cmd = (
            "rtl_fm -f %d -M %s -s %d -r %d -l 0 - | "
            "aplay -D %s -r %d -f S16_LE -t raw -c 1 - >/dev/null 2>&1"
            % (hz, rtl_mode, samp, audio, dev, audio)
        )
        # SSH 起動でも user PulseAudio に届くよう XDG_RUNTIME_DIR を補う。
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
        self._proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, preexec_fn=os.setsid, env=env,
        )

    def stop(self):
        if self._proc is not None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            self._proc = None
