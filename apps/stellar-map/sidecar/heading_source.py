"""App 16 星座盤サイドカーの方位ソース（方式A: 自機の向きを画面上に固定）。

サイドカーが毎フレーム `heading()` を問い合わせるだけで済むよう、方位の供給元を
抽象化する。平滑化・偏角/取付オフセット補正は機種非依存の `shared/compass` に委譲し、
本モジュールは「どこから生 heading を得るか」だけを担う。

  - FixedHeadingSource   : 固定値（PC 検証・回転テスト用）
  - CoreS3HeadingSource  : CoreS3 の BMM150 を USB CDC 経由で背景スレッド読取
                           （`shared/cores3_bridge`）
  - IioHeadingSource     : CardputerZero 内蔵の BMM150（地磁気）＋BMI270（加速度）を
                           Linux IIO の sysfs から背景スレッド読取（追加パッケージ不要）
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from shared.compass import HeadingFilter

G0 = 9.80665   # 標準重力加速度 [m/s^2]（IIO の加速度は m/s^2 なので g へ換算する）


def _build_cal(offset_x, offset_y, offset_z, span_x, span_y, span_z, ell_offset, ell_matrix):
    """較正パラメータを (tilt 用 cal, 水平前提 cal_xy) に組む。未較正なら (None, None)。

    優先順位: ①楕円体フィット(ell_offset+ell_matrix・軸非平行歪みも補正)
    → ②ボックス法(offset_x/y[/z]+span・軸平行仮定) → ③無較正。
    cal は ``tilt_compensated_heading`` の引数、cal_xy は ``heading_from_xy`` の引数。
    """
    if ell_matrix is not None and ell_offset is not None:
        cal = {"offset": tuple(ell_offset), "matrix": tuple(ell_matrix)}
        cal_xy = dict(offset_x=float(ell_offset[0]), offset_y=float(ell_offset[1]),
                      scale_x=1.0, scale_y=1.0)   # 粗い 2D フォールバック
        return cal, cal_xy
    if offset_x is not None and offset_y is not None:
        sz = span_z if span_z else (((span_x or 1.0) + (span_y or 1.0)) / 2.0)
        cal_xy = dict(offset_x=offset_x, offset_y=offset_y,
                      scale_x=1.0 / (span_x or 1.0), scale_y=1.0 / (span_y or 1.0))
        cal = dict(cal_xy, offset_z=offset_z, scale_z=1.0 / (sz or 1.0))
        return cal, cal_xy
    return None, None


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
        # _cal は tilt 用（tilt_compensated_heading の引数）、_cal_xy は加速度欠落時の
        # 水平前提フォールバック用（heading_from_xy は x/y のみ）。未較正なら生 heading。
        self._cal, self._cal_xy = _build_cal(offset_x, offset_y, offset_z,
                                             span_x, span_y, span_z, ell_offset, ell_matrix)
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


def find_iio_device(name: str) -> Optional[str]:
    """IIO デバイスを名前（例 ``bmm150`` / ``bmi270``）で探し、sysfs ディレクトリを返す。"""
    import glob
    import os
    for d in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
        try:
            if open(os.path.join(d, "name")).read().strip() == name:
                return d
        except OSError:
            continue
    return None


def parse_signs(spec) -> tuple:
    """軸の符号指定（例 ``"1,-1,1"`` や [1,-1,1]）を (sx, sy, sz) に。未指定は (1,1,1)。"""
    if spec is None:
        return (1.0, 1.0, 1.0)
    if isinstance(spec, str):
        spec = [t for t in spec.replace(" ", "").split(",") if t]
    v = tuple(-1.0 if float(t) < 0 else 1.0 for t in spec)
    if len(v) != 3:
        raise ValueError("signs は 3 要素（x,y,z）で指定する")
    return v


class IioHeadingSource(HeadingSource):
    """CardputerZero 内蔵の BMM150＋BMI270 を Linux IIO（sysfs）から読んで方位を供給する。

    カーネルドライバが両センサを IIO デバイスとして公開している（2026-11-17 実機確認:
    ``bmm150``＝in_magn_{x,y,z}_raw・10Hz ／ ``bmi270``＝in_accel_{x,y,z}_raw）。`pi` ユーザーで
    読め、追加パッケージは不要。背景スレッドで読み続け、`HeadingFilter` で平滑化する。

    磁気は raw カウントのまま扱う（較正値も raw 単位。`tools/calib_iio.py` が出力する）。
    加速度は g に換算して傾き補正と加速度ゲートに使う。

    動作は較正の段階で 2 通り:
      - 水平較正のみ（x/y）: 水平前提で atan2。回転向きは ``invert`` で合わせる。
      - 3D 較正済み（z の半スパンあり）: 各軸を (raw−offset)/span で正規化し、``mag_signs`` で
        磁気の軸を加速度と同じ右手系に揃えたうえで、``heading_from_vectors`` による
        **傾き補正**を行う（この場合 ``invert`` は不要＝false にする）。
    """

    def __init__(self, *, rate_hz: float = 10.0, alpha: float = 0.2,
                 declination: float = 0.0, zero_offset: float = 0.0,
                 invert: bool = False, use_tilt: bool = True,
                 offset_x: Optional[float] = None, offset_y: Optional[float] = None,
                 offset_z: float = 0.0,
                 span_x: float = 1.0, span_y: float = 1.0,
                 span_z: Optional[float] = None,
                 ell_offset=None, ell_matrix=None, accel_gate: float = 0.12,
                 mag_signs=None, acc_signs=None,
                 mag_dir: Optional[str] = None, acc_dir: Optional[str] = None):
        self._filter = HeadingFilter(alpha=alpha, declination=declination,
                                     zero_offset=zero_offset, invert=invert)
        self._cal, self._cal_xy = _build_cal(offset_x, offset_y, offset_z,
                                             span_x, span_y, span_z, ell_offset, ell_matrix)
        # 傾き補正は z 軸まで較正されているときだけ有効にする（未較正の z を混ぜると暴れる）。
        self._tilt_ok = use_tilt and span_z is not None and offset_x is not None
        self._off = (offset_x or 0.0, offset_y or 0.0, offset_z or 0.0)
        self._span = (span_x or 1.0, span_y or 1.0, span_z or 1.0)
        self._accel_gate = accel_gate
        self._msign = parse_signs(mag_signs)
        self._asign = parse_signs(acc_signs)
        self._period = 1.0 / max(1.0, rate_hz)
        self._mag_dir = mag_dir or find_iio_device("bmm150")
        self._acc_dir = acc_dir or find_iio_device("bmi270")
        self._acc_scale = None
        self._lock = threading.Lock()
        self._value: Optional[float] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="iio-heading", daemon=True)
        self._thread.start()
        # 最初の値が入るまで少し待つ（起動直後の 1 フレームだけ北向き固定で描かれるのを防ぐ）。
        t0 = time.monotonic()
        while self._value is None and time.monotonic() - t0 < 0.5:
            time.sleep(0.02)

    @staticmethod
    def _read(path: str) -> float:
        with open(path) as f:
            return float(f.read())

    def _read_mag(self):
        d = self._mag_dir
        return tuple(self._read(f"{d}/in_magn_{a}_raw") for a in "xyz")

    def _read_acc_g(self):
        d = self._acc_dir
        if self._acc_scale is None:
            self._acc_scale = self._read(f"{d}/in_accel_scale") / G0
        return tuple(self._read(f"{d}/in_accel_{a}_raw") * self._acc_scale * s
                     for a, s in zip("xyz", self._asign))

    def _run(self) -> None:
        import sys
        if not self._mag_dir:
            print("# heading source: IIO の bmm150 が見つからない", file=sys.stderr)
            return
        from shared.compass import heading_from_vectors, heading_from_xy
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                mx, my, mz = self._read_mag()
                h = None
                moving = False
                acc = None
                if self._tilt_ok and self._acc_dir:
                    acc = self._read_acc_g()
                    norm = (acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2) ** 0.5
                    moving = self._accel_gate > 0.0 and abs(norm - 1.0) > self._accel_gate
                if moving:
                    pass                                          # 動作中→この回は更新しない
                elif acc is not None:
                    # 正規化（raw 単位の較正）→ 軸符号を加速度の座標系に揃える → ベクトル式で傾き補正
                    m = [(v - o) / sp * sg for v, o, sp, sg in
                         zip((mx, my, mz), self._off, self._span, self._msign)]
                    h = self._filter.update(heading_from_vectors(*m, *acc))
                elif self._cal_xy is not None:
                    h = self._filter.update_xy(mx, my, **self._cal_xy)            # 水平前提
                else:
                    h = self._filter.update(heading_from_xy(mx, my))              # 無較正（参考値）
                if h is not None:
                    with self._lock:
                        self._value = h
            except (OSError, ValueError) as ex:
                print(f"# heading source: IIO 読取エラー: {ex}", file=sys.stderr)
                time.sleep(1.0)
            dt = self._period - (time.monotonic() - t0)
            if dt > 0:
                self._stop.wait(dt)

    def heading(self) -> Optional[float]:
        with self._lock:
            return self._value

    def close(self) -> None:
        self._stop.set()
