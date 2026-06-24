"""Load `~/.config/cardputerzero/bcl_config.yaml`."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cardputerzero" / "bcl_config.yaml"


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"BCL config not found: {p}\n"
            f"Copy `apps/sdr-receiver/bcl_log/config.example.yaml` to {p} and edit it."
        )
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
