"""USB CDC シリアルから CoreS3 のフレームを読み出すリーダ（pyserial 依存）。

開発時は Windows 開発機の COM5 を、CardputerZero 実機では /dev/ttyACM* を
読む想定。ポートは引数で差し替え可能。
"""

from __future__ import annotations

import sys
import time
from typing import Iterator, Optional, Union

from .models import Frame, LogLine
from .parse import parse_line

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - 実行時のみ必要
    serial = None


def default_port() -> str:
    """プラットフォーム既定のポート名を返す（Windows=COM5 / その他=ttyACM0）。"""
    if sys.platform.startswith("win"):
        return "COM5"
    return "/dev/ttyACM0"


class CoreS3Reader:
    """CoreS3 フロントエンドの JSON ストリームを読むコンテキストマネージャ。

    例::

        with CoreS3Reader() as rd:
            for frame in rd.frames():
                enc = frame.encoder(role="R")   # 配線順によらず赤を取得
                ...
    """

    def __init__(self, port: Optional[str] = None, baud: int = 115200,
                 timeout: float = 0.3):
        if serial is None:
            raise RuntimeError(
                "pyserial が必要です: pip install pyserial")
        self.port = port or default_port()
        self.baud = baud
        self.timeout = timeout
        self._s: Optional["serial.Serial"] = None

    # -- ライフサイクル ----------------------------------------------------
    def open(self) -> "CoreS3Reader":
        self._s = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        self._s.reset_input_buffer()
        return self

    def close(self) -> None:
        if self._s is not None:
            self._s.close()
            self._s = None

    def __enter__(self) -> "CoreS3Reader":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 読み出し ----------------------------------------------------------
    def _raw_lines(self) -> Iterator[str]:
        assert self._s is not None, "open() を先に呼ぶこと"
        while True:
            raw = self._s.readline()
            if not raw:
                yield ""  # タイムアウト（呼び出し側が継続判断できるよう空行を出す）
                continue
            yield raw.decode("utf-8", "replace").strip()

    def stream(self, include_logs: bool = False
               ) -> Iterator[Union[Frame, LogLine]]:
        """Frame（と任意で LogLine）を無限に yield する。"""
        for raw in self._raw_lines():
            if not raw:
                continue
            parsed = parse_line(raw)
            if parsed is None:
                continue
            if isinstance(parsed, LogLine) and not include_logs:
                continue
            yield parsed

    def frames(self) -> Iterator[Frame]:
        """Frame のみを yield する（LogLine は読み飛ばす）。"""
        for item in self.stream(include_logs=False):
            if isinstance(item, Frame):
                yield item

    def read_frame(self, timeout: float = 2.0) -> Optional[Frame]:
        """次の 1 フレームを最大 timeout 秒待って返す。タイムアウトで None。"""
        deadline = time.monotonic() + timeout
        for raw in self._raw_lines():
            if time.monotonic() > deadline:
                return None
            parsed = parse_line(raw) if raw else None
            if isinstance(parsed, Frame):
                return parsed
        return None
