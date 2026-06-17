"""Resolve Mac Mini SSH target via Tailscale MagicDNS, with fixed-IP fallback."""
from __future__ import annotations

import subprocess


def resolve(hostname: str, fallback_ip: str, *, ping_timeout: int = 2) -> str:
    if not hostname:
        return fallback_ip
    try:
        subprocess.run(
            ["ping", "-c", "1", "-W", "1", hostname],
            check=True, capture_output=True, timeout=ping_timeout,
        )
        return hostname
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return fallback_ip
