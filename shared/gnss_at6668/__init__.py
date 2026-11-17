"""gnss_at6668 — Cap LoRa-1262 の GNSS（GP-02／ATGM336H／AT6668）を読む共通ドライバ。

`nmea`   : NMEA 0183（RMC・GGA）の最小パーサ（機種非依存・外部依存なし）
`reader` : CardputerZero 実機用の背景リーダ（5V 出力の制御・`/dev/serial0` 115200bps・
           前回測位の保存）。標準ライブラリのみで動く。

App 16 星座盤（観測地と時刻）と App 01 GPS ロガーで共用する。
"""
from __future__ import annotations

from .nmea import Fix, NmeaParser, checksum_ok
from .reader import (DEFAULT_PORT, EXT_5V, LAST_FIX, GnssReader, available,
                     load_last_fix, save_last_fix)

__all__ = ["Fix", "NmeaParser", "checksum_ok", "GnssReader", "available",
           "load_last_fix", "save_last_fix", "DEFAULT_PORT", "EXT_5V", "LAST_FIX"]

__version__ = "0.1.0"
