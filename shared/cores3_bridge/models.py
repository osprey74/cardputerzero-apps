"""CoreS3 入力フロントエンドが送る JSON 1 行を表すデータモデル（純 stdlib）。

HANDOFF §1.6.1 の構成。CoreS3 (ESP32-S3) が USB CDC 経由で 5Hz 送信する
JSON 1 行を、機種非依存のデータクラスに写像する。pyserial 等の外部依存を
持たないため単体テスト可能（シリアル I/O は reader.py 側）。

送信 JSON 例:
  {"bat":{"pct":100,"chg":0,"v":4.12},
   "ina":{"v":0.0,"i":0.0,"p":0.0},"ncir":{"t_obj":28.5,"t_amb":31.4},
   "enc":[{"id":1,"role":"B","uid":"78001C00","cnt":-24,"delta":0,"btn":0},
          {"id":2,"role":"R","uid":"4E001B00","cnt":39,"delta":0,"btn":0}]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Battery:
    """AXP2101 バッテリーテレメトリ。"""

    pct: int                    # 残量 0-100（-1 = 不明）
    chg: int                    # -1 不明 / 0 放電 / 1 充電
    v: Optional[float]          # 端子電圧 [V]（None = 不明）

    @property
    def charging(self) -> bool:
        return self.chg == 1


@dataclass
class Power:
    """INA226-10A 電圧/電流/電力。未取得フィールドは None。"""

    v: Optional[float]          # バス電圧 [V]
    i: Optional[float]          # 電流 [A]（符号付き）
    p: Optional[float]          # 電力 [W]


@dataclass
class Temp:
    """NCIR MLX90614 物体温度/環境温度 [℃]。未取得は None。"""

    t_obj: Optional[float]
    t_amb: Optional[float]


@dataclass
class Encoder:
    """Chain Encoder 1 ノード。

    ⚠️ ``id`` はチェーン上の物理位置（マスタ=CoreS3 寄りが 1）で、ケーブル
    接続順を入れ替えると変わる。個体を一意に指すのは ``uid``（STM32 固有 4B）
    で、``role`` はその UID をファーム側で解決した役割コード（'R'/'B'/'?'）。
    上位ロジックは原則 ``role`` か ``uid`` で個体を束ねること。
    """

    id: int                     # チェーン上の位置（1 始まり・配線順依存）
    role: str                   # 役割コード 'R'/'B'/'?'（UID 解決・配線順非依存）
    uid: str                    # 固有 UID 16 進文字列（例 "4E001B00"）
    cnt: int                    # 累積カウント
    delta: int                  # 前回読取からの増分
    btn: int                    # ノブ押下状態（1=押下）

    @property
    def pressed(self) -> bool:
        return self.btn != 0

    @property
    def resolved(self) -> bool:
        """UID が既知テーブルで解決済み（role が '?' でない）か。"""
        return self.role not in ("?", "")


@dataclass
class Frame:
    """1 周期分の全テレメトリ。"""

    bat: Optional[Battery] = None
    ina: Optional[Power] = None
    ncir: Optional[Temp] = None
    encoders: list[Encoder] = field(default_factory=list)

    def encoder(self, *, role: Optional[str] = None,
                uid: Optional[str] = None) -> Optional[Encoder]:
        """role または uid で個体を引く（配線順非依存）。見つからなければ None。"""
        for e in self.encoders:
            if role is not None and e.role == role:
                return e
            if uid is not None and e.uid.upper() == uid.upper():
                return e
        return None

    @property
    def by_role(self) -> dict[str, Encoder]:
        return {e.role: e for e in self.encoders if e.resolved}

    @property
    def by_uid(self) -> dict[str, Encoder]:
        return {e.uid.upper(): e for e in self.encoders}


@dataclass
class LogLine:
    """``{"log": "..."}`` 形式の診断行（i2c_scan / chain_uid 等）。"""

    kind: str                   # "log" 値（i2c_scan, ina226_id, chain_enum, chain_uid …）
    data: dict                  # 行全体（kind 以外のフィールドも含む）
