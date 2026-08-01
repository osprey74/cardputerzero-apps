"""ncir-thermometer PoC の閾値判定・統計ロジックの単体テスト（シリアル不要）。

実行: リポジトリ直下から ``python -m pytest apps/ncir_thermometer/tests`` または
``python apps/ncir_thermometer/tests/test_thermometer_poc.py``（pytest 無し簡易ランナー）。
"""

from __future__ import annotations

import os
import sys

# apps/ をパッケージ親として import できるよう、リポジトリ直下を sys.path に追加。
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from apps.ncir_thermometer.thermometer_poc import (  # noqa: E402
    ALERT, NORMAL, WARN, Stats, classify)


def test_classify_boundaries():
    # 既定境界（warn=80, alert=100）。境界値は「以上」で上位ステータスへ。
    assert classify(33.0, 80.0, 100.0) == NORMAL
    assert classify(79.9, 80.0, 100.0) == NORMAL
    assert classify(80.0, 80.0, 100.0) == WARN     # warn 境界ちょうど
    assert classify(99.9, 80.0, 100.0) == WARN
    assert classify(100.0, 80.0, 100.0) == ALERT   # alert 境界ちょうど
    assert classify(372.4, 80.0, 100.0) == ALERT   # ハンダゴテ実測フック値


def test_classify_none_is_normal():
    # nan→None 化された t_obj は NORMAL（呼び出し側で除外される前提の安全値）。
    assert classify(None, 80.0, 100.0) == NORMAL


def test_stats_min_max_keeps_extremes():
    s = Stats()
    for obj, amb in [(33.0, 25.0), (372.4, 24.1), (28.5, 31.4)]:
        s.update(obj, amb)
    assert s.n == 3
    assert s.mn["obj"] == 28.5 and s.mx["obj"] == 372.4   # コテ先が max に保持
    assert s.mn["amb"] == 24.1 and s.mx["amb"] == 31.4
    assert abs(s.avg_obj - (33.0 + 372.4 + 28.5) / 3) < 1e-9


def test_stats_reset_clears_session():
    s = Stats()
    s.update(100.0, 20.0)
    s.reset()
    assert s.n == 0 and s.avg_obj == 0.0
    assert s.mn["obj"] is None and s.mx["obj"] is None


def test_stats_handles_none_amb():
    # t_amb だけ None（片側欠測）でも obj 側は集計され、amb は据え置き。
    s = Stats()
    s.update(50.0, None)
    assert s.n == 1 and s.mx["obj"] == 50.0
    assert s.mn["amb"] is None and s.mx["amb"] is None


def test_avg_obj_empty_is_zero():
    assert Stats().avg_obj == 0.0


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
