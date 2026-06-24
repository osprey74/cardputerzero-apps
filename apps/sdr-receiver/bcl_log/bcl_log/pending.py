"""Pending log queue (offline / Tailscale 切断時の蓄積先)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def save(pending_dir: Path, payload: Dict[str, Any]) -> Path:
    pending_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f") + ".json"
    target = pending_dir / name
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return target


def list_all(pending_dir: Path) -> List[Path]:
    if not pending_dir.exists():
        return []
    return sorted(pending_dir.glob("*.json"))


def load_one(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
