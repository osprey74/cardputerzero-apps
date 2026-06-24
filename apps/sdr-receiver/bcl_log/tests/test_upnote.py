"""Unit tests for UpNote URL builder.

Run from `apps/sdr-receiver/bcl_log/`:
    python3 -m pytest tests/
"""
from __future__ import annotations

import urllib.parse

from bcl_log import upnote as un


def test_tag_is_last():
    url = un.build_url(title="t", body="b", notebook="NB", tag="BCL")
    qs = urllib.parse.urlparse(url).query
    keys = [pair.split("=", 1)[0] for pair in qs.split("&")]
    assert keys == ["title", "text", "notebook", "markdown", "tag"]


def test_scheme_and_host():
    url = un.build_url(title="t", body="b", notebook="NB", tag="BCL")
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == "upnote"
    assert parsed.netloc == "x-callback-url"
    assert parsed.path == "/note/new"


def test_japanese_round_trip():
    url = un.build_url(
        title="2026-06-15 14:32 — ラジオ NIKKEI 第1 (3925 kHz)",
        body="## 受信記録\n- **局名**: ラジオ NIKKEI 第1\n",
        notebook="BCL_LogBook",
        tag="BCL",
    )
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    assert "ラジオ NIKKEI 第1" in params["title"]
    assert "ラジオ NIKKEI 第1" in params["text"]
    assert params["notebook"] == "BCL_LogBook"
    assert params["tag"] == "BCL"
    assert params["markdown"] == "true"
