"""地磁気センサから「自機の向く方位角」を得る機種非依存ロジック（純 stdlib）。

App 16 星座盤の方式A（自機の向きを画面上に固定して全天図を回転）で使う姿勢処理を、
センサ実装から切り離してここに集約する。入力は BMM150 等の水平面磁気 x/y（µT）か、
ファーム側で計算済みの生 heading[deg]。出力は平滑化・偏角/取付オフセット補正済みの
真北基準方位角[deg]。

センサの供給元は問わない設計:
  - 先行検証: CoreS3 の BMM150 を USB CDC 経由（`shared/cores3_bridge` の ``Mag``）
  - 実機:     CardputerZero 内蔵 BMM150（`M5.Imu.getMag()` 相当）
どちらでも生 x/y または heading をこのフィルタに流し込めば同じ挙動になる。

⚠️ ハード/ソフトアイアン較正と傾き補正は本モジュールの範囲外（水平前提）。方式A では
まず生 heading の平滑化＋偏角/取付オフセットのみを行う。傾き補正は加速度と併せて
呼び出し側 or 将来の拡張で足す（[[project_app16_stellar_map]] の注記どおり）。
"""
from __future__ import annotations

import math
from typing import Optional


def wrap360(deg: float) -> float:
    """角度を [0, 360) に正規化。"""
    return deg % 360.0


def wrap180(deg: float) -> float:
    """角度を (-180, 180] に正規化（差分の符号付き表現用）。"""
    d = (deg + 180.0) % 360.0
    return 180.0 if d == 0.0 else d - 180.0


def heading_from_xy(x: float, y: float, *,
                    offset_x: float = 0.0, offset_y: float = 0.0,
                    scale_x: float = 1.0, scale_y: float = 1.0) -> float:
    """水平面磁気 x/y[µT] → 方位角[deg]（0=+X 基準・東回り）。

    offset_* はハードアイアン補正（磁気中心のずれ）、scale_* はソフトアイアン簡易補正
    （軸ごとのゲイン）。較正値が未取得なら既定（無補正）で生の atan2 を返す。返り値の
    絶対方位合わせ（センサ 0 と真北の対応）は ``HeadingFilter`` の zero_offset で行う。
    """
    mx = (x - offset_x) * scale_x
    my = (y - offset_y) * scale_y
    return wrap360(math.degrees(math.atan2(my, mx)))


def tilt_compensated_heading(mx: float, my: float, mz: float,
                             ax: float, ay: float, az: float, *,
                             offset_x: float = 0.0, offset_y: float = 0.0,
                             offset_z: float = 0.0,
                             scale_x: float = 1.0, scale_y: float = 1.0,
                             scale_z: float = 1.0) -> float:
    """加速度（重力）で磁気を水平面へ補正した方位角[deg]（tilt-compensated compass）。

    Freescale AN4248 の定式。加速度 (ax,ay,az) から roll/pitch を求め、ハード/ソフト
    アイアン補正済み磁気 (bx,by,bz) を水平面へ回して heading=atan2(by',bx') を返す。

    ⚠️ **水平時（az が支配的・ax=ay≈0）は `heading_from_xy(mx,my)` と一致する**ように
    符号を採ってある（既存の水平較正・zero_offset をそのまま流用できる）。加速度が
    ほぼゼロ（自由落下等）なら水平前提にフォールバック。軸割当・符号は BMM150/BMI270 の
    実装向きに依存するため実機で要確認（tilt の効き方が逆なら加速度側の符号で調整）。

    offset_z/scale_z は縦方向のハード/ソフトアイアン。水平 360° スイープでは推定できない
    ため既定 0/1（傾けたときの精度を上げるには 3 軸較正が要る）。
    """
    bx = (mx - offset_x) * scale_x
    by = (my - offset_y) * scale_y
    bz = (mz - offset_z) * scale_z
    if math.sqrt(ax * ax + ay * ay + az * az) < 1e-6:
        return wrap360(math.degrees(math.atan2(by, bx)))     # 水平前提フォールバック
    phi = math.atan2(ay, az)                                  # roll
    theta = math.atan2(-ax, ay * math.sin(phi) + az * math.cos(phi))  # pitch
    sp, cp = math.sin(phi), math.cos(phi)
    st, ct = math.sin(theta), math.cos(theta)
    bfx = bx * ct + by * st * sp + bz * st * cp
    bfy = by * cp - bz * sp
    return wrap360(math.degrees(math.atan2(bfy, bfx)))


class HeadingFilter:
    """生の方位角を円周上で平滑化し、真北基準方位を返すフィルタ。

    単純な指数移動平均（EMA）を sin/cos 成分に掛けることで 359°↔0° の巻き戻り
    問題を避ける。磁力計は雑音が多く、そのままだと星図が細かく震えるため必須。

    引数:
      alpha:        EMA 係数 (0<alpha<=1)。大きいほど追従が速く雑音も乗る（既定 0.2）。
      declination:  磁気偏角[deg]（磁北→真北。西偏はマイナス。例: 札幌 ≈ -9）。
      zero_offset:  センサ取付角オフセット[deg]（センサ 0 と機体前方の差）。
      invert:       方位の回転向きが逆な個体向けに符号反転。
    """

    def __init__(self, *, alpha: float = 0.2, declination: float = 0.0,
                 zero_offset: float = 0.0, invert: bool = False):
        self.alpha = alpha
        self.declination = declination
        self.zero_offset = zero_offset
        self.invert = invert
        self._s: Optional[float] = None
        self._c: Optional[float] = None

    def reset(self) -> None:
        """平滑化状態を破棄（次サンプルで再ロック）。"""
        self._s = self._c = None

    def update(self, raw_heading_deg: Optional[float]) -> Optional[float]:
        """生 heading[deg] を 1 つ取り込み、平滑化済み真北方位を返す。

        raw が None（磁気未取得）なら状態を変えず現在値を返す。
        """
        if raw_heading_deg is None:
            return self.heading
        h = -raw_heading_deg if self.invert else raw_heading_deg
        h = h + self.zero_offset + self.declination
        r = math.radians(h)
        sn, cs = math.sin(r), math.cos(r)
        if self._s is None:
            self._s, self._c = sn, cs          # 初回はそのままシード（0° への偏りを防ぐ）
        else:
            a = self.alpha
            self._s = (1.0 - a) * self._s + a * sn
            self._c = (1.0 - a) * self._c + a * cs
        return self.heading

    def update_xy(self, x: Optional[float], y: Optional[float], **cal) -> Optional[float]:
        """磁気 x/y から heading を計算して取り込む（``heading_from_xy`` の較正引数を透過）。"""
        if x is None or y is None:
            return self.heading
        return self.update(heading_from_xy(x, y, **cal))

    def update_tilt(self, mx: Optional[float], my: Optional[float], mz: Optional[float],
                    ax: Optional[float], ay: Optional[float], az: Optional[float],
                    **cal) -> Optional[float]:
        """磁気＋加速度から傾き補正 heading を計算して取り込む。

        加速度が欠けていれば水平前提（``update_xy``）にフォールバックする。
        cal は ``tilt_compensated_heading`` の較正引数（offset_x/y/z・scale_x/y/z）。
        """
        if mx is None or my is None:
            return self.heading
        if None in (mz, ax, ay, az):
            xy_cal = {k: v for k, v in cal.items() if k in
                      ("offset_x", "offset_y", "scale_x", "scale_y")}
            return self.update_xy(mx, my, **xy_cal)
        return self.update(tilt_compensated_heading(mx, my, mz, ax, ay, az, **cal))

    @property
    def heading(self) -> Optional[float]:
        """現在の平滑化済み真北方位[deg]（未ロックなら None）。"""
        if self._s is None or self._c is None:
            return None
        return wrap360(math.degrees(math.atan2(self._s, self._c)))

    @property
    def locked(self) -> bool:
        """有効な方位を保持しているか（1 度以上サンプルを取り込んだか）。"""
        return self._s is not None
