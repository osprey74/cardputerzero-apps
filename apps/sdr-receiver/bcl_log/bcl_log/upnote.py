"""UpNote `x-callback-url` builder and SSH dispatcher.

The `tag` query parameter MUST come last (HANDOFF §3 App 10 / verified 2026-06-13 v3-v4).
Placing it earlier breaks `title` / `text` URL decoding on the UpNote side.
"""
from __future__ import annotations

import subprocess
import urllib.parse
from typing import Optional


def build_url(*, title: str, body: str, notebook: str, tag: str) -> str:
    params = [
        ("title",    title),
        ("text",     body),
        ("notebook", notebook),
        ("markdown", "true"),
        ("tag",      tag),
    ]
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"upnote://x-callback-url/note/new?{qs}"


def dispatch(url: str, ssh_target: str, ssh_user: str, *, timeout: int = 10) -> Optional[str]:
    try:
        subprocess.run(
            ["ssh", f"{ssh_user}@{ssh_target}", "open", url],
            check=True, timeout=timeout, capture_output=True,
        )
        return None
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        return f"ssh exit {e.returncode}: {stderr}"
    except subprocess.TimeoutExpired:
        return "ssh timeout"
    except FileNotFoundError:
        return "ssh command not found"
