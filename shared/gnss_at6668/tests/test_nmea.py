"""gnss_at6668 の NMEA パーサの単体テスト（外部依存なし）。

実行: リポジトリ直下から ``python -m pytest shared/gnss_at6668/tests`` または
``python shared/gnss_at6668/tests/test_nmea.py``（pytest 無し簡易ランナー）。
テスト用の座標は実在の観測地ではない架空の値。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from shared.gnss_at6668 import NmeaParser, checksum_ok  # noqa: E402


def _s(body: str) -> str:
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"${body}*{c:02X}"


def test_checksum():
    assert checksum_ok(_s("GNRMC,010203.000,A,3500.0000,N,13500.0000,E,0.0,0.0,171126,,,A"))
    assert not checksum_ok("$GNRMC,010203.000,A*00")
    assert not checksum_ok("garbage")


def test_rmc_valid_sets_position_and_time():
    p = NmeaParser()
    assert p.feed(_s("GNRMC,010203.000,A,3530.0000,N,13945.0000,E,0.0,0.0,171126,,,A")) == "RMC"
    assert p.fix.valid
    assert abs(p.fix.lat - 35.5) < 1e-9
    assert abs(p.fix.lon - 139.75) < 1e-9
    assert p.fix.utc == datetime(2026, 11, 17, 1, 2, 3)


def test_rmc_void_keeps_time_but_not_valid():
    p = NmeaParser()
    p.feed(_s("GNRMC,010203.000,V,,,,,,,171126,,,N"))
    assert not p.fix.valid
    assert p.fix.lat is None
    assert p.fix.utc == datetime(2026, 11, 17, 1, 2, 3)


def test_rmc_ignores_unsynced_default_date():
    p = NmeaParser()
    p.feed(_s("GNRMC,000012.000,V,,,,,,,060180,,,N"))     # 未同期時の既定日付
    assert p.fix.utc is None


def test_southern_western_hemisphere():
    p = NmeaParser()
    p.feed(_s("GPRMC,120000.000,A,3330.0000,S,07030.0000,W,0.0,0.0,010127,,,A"))
    assert abs(p.fix.lat + 33.5) < 1e-9
    assert abs(p.fix.lon + 70.5) < 1e-9


def test_gga_sats_alt_and_no_fix():
    p = NmeaParser()
    assert p.feed(_s("GNGGA,010203.000,3530.0000,N,13945.0000,E,1,12,0.9,45.6,M,30.0,M,,")) == "GGA"
    assert p.fix.sats == 12 and abs(p.fix.hdop - 0.9) < 1e-9 and abs(p.fix.alt - 45.6) < 1e-9
    p.feed(_s("GNRMC,010203.000,A,3530.0000,N,13945.0000,E,0.0,0.0,171126,,,A"))
    assert p.fix.valid
    p.feed(_s("GNGGA,010204.000,,,,,0,00,25.5,,,,,,"))
    assert not p.fix.valid and p.fix.sats == 0


def test_other_sentences_counted_but_ignored():
    p = NmeaParser()
    assert p.feed(_s("GPTXT,01,01,01,ANTENNA OPEN")) is None
    assert p.feed(_s("GNZDA,010203.000,17,11,2026,00,00")) is None
    assert p.sentences == 2
    assert p.feed("$GPTXT,01,01,01,ANTENNA OPEN*00") is None      # チェックサム不一致
    assert p.sentences == 2


def test_rmc_speed_and_course():
    p = NmeaParser()
    p.feed(_s("GNRMC,010203.000,A,3530.0000,N,13945.0000,E,10.0,270.5,171126,,,A"))
    assert abs(p.fix.speed_kmh - 18.52) < 1e-9 and abs(p.fix.course - 270.5) < 1e-9
    p.feed(_s("GNRMC,010204.000,V,,,,,,,171126,,,N"))
    assert p.fix.speed_kmh is None and p.fix.course is None


def test_gsv_systems_and_signal_id():
    # 実機（Unit GPS v1.1）と同じ NMEA 4.1 形式: 末尾に信号 ID
    p = NmeaParser()
    assert p.feed(_s("GPGSV,1,1,03,07,45,120,38,15,10,300,,194,60,200,41,1"), now=100.0) == "GSV"
    p.feed(_s("GLGSV,1,1,01,72,30,045,29,1"), now=100.0)
    p.feed(_s("GQGSV,1,1,01,02,70,180,44,1"), now=100.0)
    p.feed(_s("BDGSV,1,1,01,23,20,090,,1"), now=100.0)
    sats = {s.key: s for s in p.satellites(now=100.5)}
    assert set(sats) == {"G07", "G15", "Q194", "R72", "Q02", "B23"}
    assert sats["G07"].elev == 45 and sats["G07"].azim == 120 and sats["G07"].snr == 38
    assert sats["G15"].snr is None and sats["B23"].snr is None
    assert p.satellites(now=106.0) == []                      # 5 秒より古い衛星は消える


def test_gsv_without_signal_id_and_empty():
    p = NmeaParser()
    p.feed(_s("GAGSV,1,1,02,04,55,010,35,11,05,250,22"), now=1.0)
    assert {s.key for s in p.satellites(now=1.0)} == {"E04", "E11"}
    assert p.feed(_s("GPGSV,1,1,00,1"), now=1.0) == "GSV"     # 衛星なし（冷えた起動直後の実機出力）


def test_gsa_mode_and_used_with_sysid():
    p = NmeaParser()
    p.feed(_s("GNGSA,A,3,07,15,,,,,,,,,,,1.8,0.9,1.5,1"), now=10.0)
    p.feed(_s("GNGSA,A,3,72,,,,,,,,,,,,1.8,0.9,1.5,2"), now=10.0)
    p.feed(_s("GNGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,4"), now=10.0)
    assert p.fix.mode == 3
    assert set(p.used) == {"G07", "G15", "R72"}
    p2 = NmeaParser()
    p2.feed(_s("GNGSA,A,1,,,,,,,,,,,,,25.5,25.5,25.5,1"), now=1.0)
    assert p2.fix.mode == 1 and not p2.used


# -- pytest 無しでも走る簡易ランナー --------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
