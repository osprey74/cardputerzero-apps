"""App 16 星座盤サイドカーの方位ソース（方式A: 自機の向きを画面上に固定）。

サイドカーが毎フレーム `heading()` を問い合わせるだけで済むよう、方位の供給元を
抽象化する。平滑化・偏角/取付オフセット補正は機種非依存の `shared/compass` に委譲し、
本モジュールは「どこから生 heading を得るか」だけを担う。

  - FixedHeadingSource   : 固定値（PC 検証・回転テスト用）
  - CoreS3HeadingSource  : CoreS3 の BMM150 を USB CDC 経由で背景スレッド読取
                           （`shared/cores3_bridge`）

CardputerZero 実機では内蔵 BMM150 を読む ``CZHeadingSource`` を同じ ``HeadingSource``
インタフェースで足せば、サイドカー本体・投影ロジックは無改修で流用できる。
"""
from __future__ import annotations

import threading
from typing import Optional

from shared.compass import HeadingFilter


class HeadingSource:
    """方位ソースの共通インタフェース。"""

    def heading(self) -> Optional[float]:
        """現在の真北基準方位[deg]（未ロックなら None）。"""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "HeadingSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FixedHeadingSource(HeadingSource):
    """固定方位（回転の見え方を PC で確認する用途）。"""

    def __init__(self, value: float):
        self._value = value % 360.0

    def heading(self) -> Optional[float]:
        return self._value


class CoreS3HeadingSource(HeadingSource):
    """CoreS3 の BMM150 heading を USB CDC で読み、平滑化して供給する。

    背景スレッドで `shared/cores3_bridge` のフレームを読み続け、`mag.ok` の生 heading を
    `HeadingFilter` に流し込む。メインスレッドは最新の平滑化値を `heading()` で得る。
    """

    def __init__(self, port: Optional[str] = None, *, alpha: float = 0.2,
                 declination: float = 0.0, zero_offset: float = 0.0,
                 invert: bool = False,
                 offset_x: Optional[float] = None, offset_y: Optional[float] = None,
                 span_x: float = 1.0, span_y: float = 1.0):
        self._filter = HeadingFilter(alpha=alpha, declination=declination,
                                     zero_offset=zero_offset, invert=invert)
        self._port = port
        # ハード/ソフトアイアン較正: offset_x/y を両方与えたときのみ生 x/y から
        # heading を再計算する（未指定ならファーム算出の生 heading をそのまま使う）。
        # span は 360° スイープの x/y 半スパン (calib_probe の sx/sy)。scale=1/span で
        # 軸振幅を正規化する（atan2 は比のみ効くため軸間の相対スケールが要点）。
        self._cal = None
        if offset_x is not None and offset_y is not None:
            self._cal = dict(offset_x=offset_x, offset_y=offset_y,
                             scale_x=1.0 / (span_x or 1.0),
                             scale_y=1.0 / (span_y or 1.0))
        self._lock = threading.Lock()
        self._value: Optional[float] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cores3-mag",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        # import はスレッド内: pyserial 未導入でもソース生成自体は失敗させない。
        try:
            from shared.cores3_bridge import CoreS3Reader
        except Exception as ex:  # noqa: BLE001
            self._fail(f"cores3_bridge import 失敗: {ex}")
            return
        try:
            with CoreS3Reader(self._port) as rd:
                for frame in rd.frames():
                    if self._stop.is_set():
                        break
                    mag = frame.mag
                    if mag is None or not mag.ok:
                        continue
                    if self._cal is not None and mag.x is not None and mag.y is not None:
                        h = self._filter.update_xy(mag.x, mag.y, **self._cal)  # 較正 x/y
                    elif mag.heading is not None:
                        h = self._filter.update(mag.heading)                    # 生 heading
                    else:
                        continue
                    with self._lock:
                        self._value = h
        except Exception as ex:  # noqa: BLE001
            self._fail(f"CoreS3 読取エラー: {ex}")

    def _fail(self, msg: str) -> None:
        import sys
        print(f"# heading source: {msg}", file=sys.stderr)

    def heading(self) -> Optional[float]:
        with self._lock:
            return self._value

    def close(self) -> None:
        self._stop.set()
