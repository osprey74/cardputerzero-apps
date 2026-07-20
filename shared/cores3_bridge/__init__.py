"""cores3_bridge — CoreS3 入力フロントエンドの USB CDC 受信ライブラリ。

HANDOFF §1.6.1。CoreS3 (ESP32-S3) が送る JSON テレメトリを機種非依存の
データモデルに変換し、CardputerZero（および開発機）から扱えるようにする。
Chain Encoder は UID 解決済みの ``role``/``uid`` で個体を束ねられる。
"""

from __future__ import annotations

from .models import Accel, Battery, Encoder, Frame, LogLine, Mag, Power, Temp
from .parse import parse_line, sanitize_json_line
from .reader import CoreS3Reader, default_port

__all__ = [
    "Accel", "Battery", "Encoder", "Frame", "LogLine", "Mag", "Power", "Temp",
    "parse_line", "sanitize_json_line",
    "CoreS3Reader", "default_port",
]

__version__ = "0.1.0"
