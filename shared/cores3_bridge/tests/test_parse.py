"""cores3_bridge パーサ・モデルの単体テスト（シリアル不要）。

実行: リポジトリ直下から ``python -m pytest shared/cores3_bridge/tests`` または
``python shared/cores3_bridge/tests/test_parse.py``（pytest 無し簡易ランナー）。
"""

from __future__ import annotations

import math
import os
import sys

# shared/ をパッケージ親として import できるよう、リポジトリ直下を sys.path に追加。
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from shared.cores3_bridge import Frame, LogLine, Mag, parse_line, sanitize_json_line  # noqa: E402

_SAMPLES = os.path.join(os.path.dirname(__file__), "sample_frames.jsonl")


def _load_lines():
    with open(_SAMPLES, encoding="utf-8") as fh:
        return [ln.rstrip("\n") for ln in fh if ln.strip()]


def test_log_lines_parse_as_logline():
    lines = _load_lines()
    log = parse_line(lines[0])
    assert isinstance(log, LogLine)
    assert log.kind == "i2c_scan"
    assert log.data["found"] == ["0x41", "0x5A"]


def test_chain_uid_log():
    log = parse_line('{"log":"chain_uid","id":1,"ok":1,"uid":"78001C00","ident":1,"name":"BLUE"}')
    assert isinstance(log, LogLine)
    assert log.kind == "chain_uid"
    assert log.data["uid"] == "78001C00"


def test_data_frame_basic():
    f = parse_line('{"bat":{"pct":85,"chg":1,"v":4.05},'
                   '"ina":{"v":5.012,"i":0.123,"p":0.616},'
                   '"ncir":{"t_obj":36.5,"t_amb":24.1},'
                   '"enc":[{"id":1,"role":"R","uid":"4E001B00","cnt":12,"delta":1,"btn":0}]}')
    assert isinstance(f, Frame)
    assert f.bat.pct == 85 and f.bat.charging is True
    assert abs(f.ina.v - 5.012) < 1e-6
    assert abs(f.ncir.t_obj - 36.5) < 1e-6
    assert len(f.encoders) == 1 and f.encoders[0].role == "R"


def test_encoder_lookup_is_position_independent():
    # ケーブル差し替え後（id↔role が入れ替わった実機サンプル）でも、
    # role/uid で引けば同じ個体を指す。
    swapped = parse_line(
        '{"enc":[{"id":1,"role":"B","uid":"78001C00","cnt":-24,"delta":0,"btn":0},'
        '{"id":2,"role":"R","uid":"4E001B00","cnt":39,"delta":1,"btn":1}]}')
    assert isinstance(swapped, Frame)
    red = swapped.encoder(role="R")
    assert red is not None and red.uid == "4E001B00"
    assert red.id == 2          # 物理位置は 2 に移動している
    assert red.pressed is True
    # uid 引きでも一致
    assert swapped.encoder(uid="4e001b00").role == "R"
    assert set(swapped.by_role.keys()) == {"R", "B"}


def test_mag_frame_parses():
    # 実機 (COM5・2026-07-07) 採取値。BMM150 は getMag 経由で取得可。
    f = parse_line('{"bat":{"pct":100,"chg":0,"v":4.14},'
                   '"ina":{"v":0.0,"i":0.0,"p":0.0},'
                   '"ncir":{"t_obj":28.6,"t_amb":28.6},'
                   '"mag":{"ok":1,"x":-1520.38,"y":623.75,"z":-9.00,"heading":157.7},'
                   '"enc":[]}')
    assert isinstance(f, Frame)
    assert isinstance(f.mag, Mag)
    assert f.mag.ok is True
    assert abs(f.mag.x + 1520.38) < 1e-6 and abs(f.mag.heading - 157.7) < 1e-6


def test_mag_absent_is_none():
    # mag フィールドの無い旧フォーマットでも frame.mag は None で安全。
    f = parse_line('{"ina":{"v":0.0,"i":0.0,"p":0.0},"enc":[]}')
    assert isinstance(f, Frame) and f.mag is None


def test_mag_unavailable_null_values():
    # getMag 失敗時 (ok:0・値 null) も落ちない。
    f = parse_line('{"mag":{"ok":0,"x":null,"y":null,"z":null,"heading":null},"enc":[]}')
    assert isinstance(f, Frame) and f.mag is not None
    assert f.mag.ok is False and f.mag.x is None and f.mag.heading is None


def test_nan_sanitize_to_null():
    raw = '{"ina":{"v":nan,"i":nan,"p":nan},"ncir":{"t_obj":nan,"t_amb":nan},"enc":[]}'
    assert "null" in sanitize_json_line(raw)
    f = parse_line(raw)
    assert isinstance(f, Frame)
    assert f.ina.v is None and f.ina.i is None and f.ina.p is None
    assert f.ncir.t_obj is None


def test_quoted_uid_not_clobbered_by_sanitizer():
    # "nan" を含む文字列値（例えば将来 uid やログ）を壊さないこと。
    raw = '{"log":"banana","val":nan}'
    out = sanitize_json_line(raw)
    assert '"banana"' in out          # 文字列内は無傷
    assert ":null" in out             # 値の nan は null


def test_non_json_and_empty_return_none():
    assert parse_line("") is None
    assert parse_line("not json") is None
    assert parse_line("M5Chain Encoder Test") is None


def test_all_sample_lines_classified():
    frames = logs = other = 0
    for ln in _load_lines():
        p = parse_line(ln)
        if isinstance(p, Frame):
            frames += 1
        elif isinstance(p, LogLine):
            logs += 1
        else:
            other += 1
    assert frames == 3 and logs == 4 and other == 0


# -- pytest 無しでも走る簡易ランナー --------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
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
