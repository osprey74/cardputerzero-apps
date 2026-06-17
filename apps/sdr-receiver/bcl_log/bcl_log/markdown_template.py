"""Render the UpNote note body in Markdown.

Matches HANDOFF_cardputerzero.md §3 App 10 BCL ログモード「Markdown テンプレート」.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class LogEntry:
    receiver: str
    antenna: str
    location_name: str
    location_lat: Optional[float]
    location_lng: Optional[float]
    sfi: Optional[int]
    k_index: Optional[int]
    a_index: Optional[int]
    propagation_fetched_utc: Optional[str]
    freq_khz: float
    band: str
    received_at: datetime
    mode: str
    station_name: str
    country: Optional[str]
    languages: List[str] = field(default_factory=list)
    transmitter_site: Optional[str] = None
    power_kw: Optional[int] = None
    sinpo: str = ""
    qsl_status: str = ""
    recording_remote_path: Optional[str] = None
    content: str = ""
    program: str = ""
    interference: str = ""


def title_for(entry: LogEntry) -> str:
    return f"{entry.received_at:%Y-%m-%d %H:%M} — {entry.station_name} ({int(entry.freq_khz)} kHz)"


def render(entry: LogEntry) -> str:
    lat_lng = ""
    if entry.location_lat is not None and entry.location_lng is not None:
        lat_lng = f" ({entry.location_lat:.4f}, {entry.location_lng:.4f})"

    if entry.sfi is not None and entry.k_index is not None:
        a = f" / A-index {entry.a_index}" if entry.a_index is not None else ""
        fetched = f" (取得: {entry.propagation_fetched_utc})" if entry.propagation_fetched_utc else ""
        propagation_line = f"\n- **伝搬条件**: SFI {entry.sfi} / K-index {entry.k_index}{a}{fetched}"
    else:
        propagation_line = ""

    languages = ", ".join(entry.languages) if entry.languages else ""
    site_power_parts = []
    if entry.transmitter_site:
        site_power_parts.append(entry.transmitter_site)
    if entry.power_kw:
        site_power_parts.append(f"{entry.power_kw} kW")
    site_power = " / ".join(site_power_parts)

    recording_line = (
        f"- **録音ファイル**: {entry.recording_remote_path}\n"
        if entry.recording_remote_path else ""
    )

    return (
        f"## 機材\n"
        f"- **受信機**: {entry.receiver}\n"
        f"- **アンテナ**: {entry.antenna}\n"
        f"- **受信地点**: {entry.location_name}{lat_lng}"
        f"{propagation_line}\n"
        f"\n"
        f"## 受信記録\n"
        f"- **周波数**: {int(entry.freq_khz)} kHz ({entry.band})\n"
        f"- **時刻**: {entry.received_at:%Y-%m-%d %H:%M:%S} JST\n"
        f"- **モード**: {entry.mode}\n"
        f"- **局名**: {entry.station_name}\n"
        f"- **国 / 地域**: {entry.country or ''}\n"
        f"- **言語**: {languages}\n"
        f"- **送信所 / 出力**: {site_power}\n"
        f"- **SINPO**: {entry.sinpo}\n"
        f"- **番組**: {entry.program}\n"
        f"- **混信状況**: {entry.interference}\n"
        f"- **QSL**: {entry.qsl_status}\n"
        f"{recording_line}"
        f"- **内容**: {entry.content}\n"
    )
