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

from shared.compass import (HeadingFilter, heading_from_xy,  # noqa: E402
                            tilt_compensated_heading, wrap180, wrap360)


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


def test_tilt_level_matches_horizontal():
    # 水平（az=1・ax=ay=0）では tilt 補正は heading_from_xy と一致すべき。
    for mx, my, mz in [(1.0, 0.0, 0.5), (0.3, 0.7, -0.2), (-0.5, -0.5, 0.9)]:
        h_flat = heading_from_xy(mx, my)
        h_tilt = tilt_compensated_heading(mx, my, mz, 0.0, 0.0, 1.0)
        assert abs(wrap180(h_tilt - h_flat)) < 1e-6


def test_tilt_invariant_under_roll():
    # ロール r をかけても真方位 H を回復すること（AN4248 の検証）。
    H = 50.0
    dip = 0.8          # 磁気の鉛直成分（伏角相当・大きめにして水平前提の誤差を明確化）
    r = math.radians(45.0)
    hr = math.radians(H)
    # ロール r で機体が傾いたときの body 系での重力・磁気（earth→body = Rx(-r)）。
    ax, ay, az = 0.0, math.sin(r), math.cos(r)
    mx = math.cos(hr)
    my = math.cos(r) * math.sin(hr) + math.sin(r) * dip
    mz = -math.sin(r) * math.sin(hr) + math.cos(r) * dip
    h_tilt = tilt_compensated_heading(mx, my, mz, ax, ay, az)
    assert abs(wrap180(h_tilt - H)) < 1e-6
    # 傾き補正なし（水平前提）だと H からズレる＝補正が効いている証拠。
    h_flat = heading_from_xy(mx, my)
    assert abs(wrap180(h_flat - H)) > 2.0


def test_tilt_matrix_identity_matches_peraxis():
    # 単位行列＋ゼロオフセットの楕円体補正は、軸別 scale=1 と同じ heading。
    ident = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    for mx, my, mz, ax, ay, az in [(0.3, 0.7, 0.2, 0.0, 0.4, 0.9),
                                   (-0.5, 0.5, -0.1, 0.2, -0.3, 0.9)]:
        h_axis = tilt_compensated_heading(mx, my, mz, ax, ay, az)
        h_mat = tilt_compensated_heading(mx, my, mz, ax, ay, az,
                                         offset=(0.0, 0.0, 0.0), matrix=ident)
        assert abs(wrap180(h_mat - h_axis)) < 1e-9


def test_tilt_matrix_corrects_soft_iron():
    # 楕円体（軸別ゲイン歪み）を仮定し、逆行列補正で真方位を回復する。
    import math as _m
    H = 40.0
    hr = _m.radians(H)
    # level・真方位 H の理想磁気（単位球）。
    bx, by, bz = _m.cos(hr), _m.sin(hr), 0.2
    # ソフトアイアン歪み: 各軸ゲイン (2.0, 0.5, 1.5) をかけた生値＋オフセット。
    ox, oy, oz = 100.0, -50.0, 20.0
    gx, gy, gz = 2.0, 0.5, 1.5
    mx, my, mz = bx * gx + ox, by * gy + oy, bz * gz + oz
    # 補正行列 = 逆ゲイン、オフセット除去。
    matrix = [1 / gx, 0, 0, 0, 1 / gy, 0, 0, 0, 1 / gz]
    h = tilt_compensated_heading(mx, my, mz, 0.0, 0.0, 1.0,
                                 offset=(ox, oy, oz), matrix=matrix)
    assert abs(wrap180(h - H)) < 1e-6


def test_tilt_falls_back_when_accel_zero():
    # 加速度がほぼゼロなら水平前提にフォールバック。
    h = tilt_compensated_heading(0.3, 0.7, 0.1, 0.0, 0.0, 0.0)
    assert abs(wrap180(h - heading_from_xy(0.3, 0.7))) < 1e-6


def test_filter_update_tilt_falls_back_without_accel():
    # accel が None のとき update_tilt は update_xy と同じ結果。
    f1 = HeadingFilter(alpha=1.0)
    f2 = HeadingFilter(alpha=1.0)
    a = f1.update_tilt(0.3, 0.7, None, None, None, None)
    b = f2.update_xy(0.3, 0.7)
    assert abs(wrap180(a - b)) < 1e-6


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
