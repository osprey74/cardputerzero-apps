"""compass（方位フィルタ）の単体テスト（外部依存なし）。

実行: リポジトリ直下から ``python -m pytest shared/compass/tests`` または
``python shared/compass/tests/test_compass.py``（pytest 無し簡易ランナー）。
"""

from __future__ import annotations

import math
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from shared.compass import HeadingFilter, heading_from_xy, wrap180, wrap360  # noqa: E402


def test_wrap360():
    assert wrap360(0.0) == 0.0
    assert wrap360(360.0) == 0.0
    assert wrap360(-10.0) == 350.0
    assert wrap360(725.0) == 5.0


def test_wrap180():
    assert wrap180(0.0) == 0.0
    assert wrap180(190.0) == -170.0
    assert wrap180(-190.0) == 170.0
    assert wrap180(180.0) == 180.0


def test_heading_from_xy_cardinals():
    # +X → 0°, +Y → 90°, -X → 180°, -Y → 270°
    assert abs(heading_from_xy(1.0, 0.0) - 0.0) < 1e-9
    assert abs(heading_from_xy(0.0, 1.0) - 90.0) < 1e-9
    assert abs(heading_from_xy(-1.0, 0.0) - 180.0) < 1e-9
    assert abs(heading_from_xy(0.0, -1.0) - 270.0) < 1e-9


def test_heading_from_xy_hard_iron_offset():
    # 磁気中心が (10, 5) にずれていても offset で補正すれば +X 方向は 0°。
    assert abs(heading_from_xy(11.0, 5.0, offset_x=10.0, offset_y=5.0) - 0.0) < 1e-9


def test_filter_seeds_on_first_sample():
    f = HeadingFilter(alpha=0.2)
    assert f.locked is False and f.heading is None
    # 初回はそのまま採用（0° への偏り無し）。
    assert abs(f.update(123.0) - 123.0) < 1e-9
    assert f.locked is True


def test_filter_none_keeps_state():
    f = HeadingFilter()
    f.update(90.0)
    assert abs(f.update(None) - 90.0) < 1e-9   # 未取得は状態維持


def test_filter_smooths_toward_input():
    f = HeadingFilter(alpha=0.5)
    f.update(0.0)
    h = f.update(90.0)
    # 0°と90°の中間へ寄る（円周 EMA なので atan2(0.5, 0.5)=45°）。
    assert abs(h - 45.0) < 1e-6


def test_filter_wraparound_no_jump():
    # 350° と 10° の平滑化は 0° 付近になる（179° 付近に飛ばない）。
    f = HeadingFilter(alpha=0.5)
    f.update(350.0)
    h = f.update(10.0)
    assert min(h, 360.0 - h) < 1.0


def test_declination_and_zero_offset_applied():
    f = HeadingFilter(alpha=1.0, declination=-9.0, zero_offset=5.0)
    # alpha=1 で平滑化なし。生 100 + zero(5) + decl(-9) = 96。
    assert abs(f.update(100.0) - 96.0) < 1e-9


def test_invert():
    f = HeadingFilter(alpha=1.0, invert=True)
    assert abs(f.update(30.0) - wrap360(-30.0)) < 1e-9  # 330°


def test_reset_reloc():
    f = HeadingFilter()
    f.update(45.0)
    f.reset()
    assert f.locked is False and f.heading is None
    assert abs(f.update(200.0) - 200.0) < 1e-9


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
