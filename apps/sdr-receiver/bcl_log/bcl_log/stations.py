"""Known BCL station YAML database loader and frequency-neighborhood search."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml


class Station:
    __slots__ = (
        "name", "country", "languages", "transmitter_site",
        "power_kw", "frequencies", "raw",
    )

    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.name = raw.get("name", "")
        self.country = raw.get("country")
        self.languages = raw.get("languages") or []
        self.transmitter_site = raw.get("transmitter_site")
        self.power_kw = raw.get("power_kw")
        self.frequencies = raw.get("frequencies") or []

    def matching_frequency(self, freq_khz: float, tolerance_khz: float) -> Optional[dict]:
        for entry in self.frequencies:
            if abs(entry.get("freq_khz", 0) - freq_khz) <= tolerance_khz:
                return entry
        return None


def load(path: Path) -> List[Station]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return [Station(s) for s in (data or {}).get("stations", [])]


def candidates(stations: List[Station], freq_khz: float, tolerance_khz: float = 10.0) -> List[Station]:
    return [s for s in stations if s.matching_frequency(freq_khz, tolerance_khz) is not None]
