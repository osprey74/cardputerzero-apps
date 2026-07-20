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
import time
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
                 invert: bool = False, use_tilt: bool = True,
                 offset_x: Optional[float] = None, offset_y: Optional[float] = None,
                 offset_z: float = 0.0,
                 span_x: float = 1.0, span_y: float = 1.0,
                 span_z: Optional[float] = None,
                 ell_offset=None, ell_matrix=None, accel_gate: float = 0.12):
        self._filter = HeadingFilter(alpha=alpha, declination=declination,
                                     zero_offset=zero_offset, invert=invert)
        self._port = port
        self._use_tilt = use_tilt
        # 加速度ゲート[g]: |加速度|が 1g からこの幅を超えて外れたら「動作中」とみなし
        # heading を更新しない（直前値保持）。動的加速度で pitch/roll 推定が狂うのを防ぐ。
        # 0 以下で無効。傾き補正が有効なときのみ効く。
        self._accel_gate = accel_gate
        # 較正の優先順位: ①楕円体フィット(ell_offset+ell_matrix・軸非平行歪みも補正・最良)
        # → ②ボックス法(offset_x/y[/z]+span・軸平行仮定) → ③無較正(生 heading)。
        # _cal は tilt 用（tilt_compensated_heading の引数）、_cal_xy は加速度欠落時の
        # 水平前提フォールバック用（heading_from_xy は x/y のみ）。
        self._cal = None
        self._cal_xy = None
        if ell_matrix is not None and ell_offset is not None:
            self._cal = {"offset": tuple(ell_offset), "matrix": tuple(ell_matrix)}
            self._cal_xy = dict(offset_x=float(ell_offset[0]), offset_y=float(ell_offset[1]),
                                scale_x=1.0, scale_y=1.0)   # 粗い 2D フォールバック
        elif offset_x is not None and offset_y is not None:
            sz = span_z if span_z else (((span_x or 1.0) + (span_y or 1.0)) / 2.0)
            self._cal_xy = dict(offset_x=offset_x, offset_y=offset_y,
                                scale_x=1.0 / (span_x or 1.0),
                                scale_y=1.0 / (span_y or 1.0))
            self._cal = dict(self._cal_xy, offset_z=offset_z, scale_z=1.0 / (sz or 1.0))
        self._lock = threading.Lock()
        self._value: Optional[float] = None
        # Chain Encoder 入力（App16 星座リスト/拡大 UI 用）: role R/B の回転累積＋押下エッジ。
        # 同じリーダスレッドで mag と一緒に読む（1 ポート 1 リーダ）。drain_input() で取り出す。
        self._enc_lock = threading.Lock()
        self._rot = {"R": 0, "B": 0}          # 未処理の回転カウント
        self._press = {"R": 0, "B": 0}        # 未処理の押下エッジ回数
        self._prev_cnt = {}                   # role -> 前回 cnt
        self._prev_btn = {"R": 0, "B": 0}     # role -> 前回 btn
        # ボタンデバウンス[s]: この間隔以内の連続押下エッジは 1 回に集約（チャタリング対策）。
        # 青ボタンのチャタリングで ZOOM→LIST→ZOOM と二重遷移するのを防ぐ。
        self._btn_debounce = 0.30
        self._last_press_t = {"R": 0.0, "B": 0.0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cores3-input",
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
                    self._process_encoders(frame)   # mag の有無に依らず毎フレーム
                    mag = frame.mag
                    if mag is None or not mag.ok:
                        continue
                    acc = frame.acc
                    have_acc = (self._use_tilt and acc is not None and acc.ok
                                and mag.z is not None
                                and None not in (acc.x, acc.y, acc.z))
                    if self._cal is not None and mag.x is not None and mag.y is not None:
                        if have_acc:
                            # 加速度ゲート: 動作中（|a|≠1g）は更新せず直前値保持。
                            if self._accel_gate > 0.0:
                                norm = (acc.x ** 2 + acc.y ** 2 + acc.z ** 2) ** 0.5
                                if abs(norm - 1.0) > self._accel_gate:
                                    continue                                   # 動作中→スキップ
                            h = self._filter.update_tilt(mag.x, mag.y, mag.z,   # 傾き補正
                                                         acc.x, acc.y, acc.z, **self._cal)
                        else:
                            h = self._filter.update_xy(mag.x, mag.y, **self._cal_xy)  # 水平前提
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

    def _process_encoders(self, frame) -> None:
        """フレームの各エンコーダから回転累積と押下エッジ(0→1)を貯める。"""
        for e in frame.encoders:
            role = e.role
            if role not in ("R", "B"):
                continue
            with self._enc_lock:
                prev = self._prev_cnt.get(role)
                if prev is not None:
                    self._rot[role] += e.cnt - prev      # cnt 差で回転を累積（欠落に強い）
                self._prev_cnt[role] = e.cnt
                if e.btn and not self._prev_btn.get(role, 0):
                    now = time.monotonic()               # 押下エッジ（デバウンス付き）
                    if now - self._last_press_t[role] > self._btn_debounce:
                        self._press[role] += 1
                        self._last_press_t[role] = now
                self._prev_btn[role] = e.btn

    def drain_input(self) -> dict:
        """前回 drain 以降の入力を返してクリア。

        返り値: {"red_rot","blue_rot","red_press","blue_press"}
        （*_rot=回転カウント累積、*_press=押下回数）。
        """
        with self._enc_lock:
            out = {"red_rot": self._rot["R"], "blue_rot": self._rot["B"],
                   "red_press": self._press["R"], "blue_press": self._press["B"]}
            self._rot["R"] = self._rot["B"] = 0
            self._press["R"] = self._press["B"] = 0
        return out

    def heading(self) -> Optional[float]:
        with self._lock:
            return self._value

    def close(self) -> None:
        self._stop.set()
