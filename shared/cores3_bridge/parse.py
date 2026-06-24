"""CoreS3 が送る 1 行を Frame / LogLine に変換する純パーサ（シリアル非依存）。"""

from __future__ import annotations

import json
import re
from typing import Optional, Union

from .models import Battery, Encoder, Frame, LogLine, Power, Temp

# C 言語の printf("%.3f", NAN) は小文字 "nan"/"inf" を出力するが、これは
# JSON として不正（Python の json は "NaN"/"Infinity" のみ許容）。値位置に
# 現れる nan/-nan/inf/-inf/infinity を null に置換してから読む。
_NAN_INF = re.compile(r"(?<=[:\s,\[])-?(?:nan|inf(?:inity)?)\b", re.IGNORECASE)


def sanitize_json_line(line: str) -> str:
    """不正な nan/inf トークンを null に置換した JSON 文字列を返す。"""
    return _NAN_INF.sub("null", line)


def _frame_from_dict(o: dict) -> Frame:
    bat = None
    if isinstance(o.get("bat"), dict):
        b = o["bat"]
        bat = Battery(pct=int(b.get("pct", -1)), chg=int(b.get("chg", -1)),
                      v=b.get("v"))
    ina = None
    if isinstance(o.get("ina"), dict):
        a = o["ina"]
        ina = Power(v=a.get("v"), i=a.get("i"), p=a.get("p"))
    ncir = None
    if isinstance(o.get("ncir"), dict):
        n = o["ncir"]
        ncir = Temp(t_obj=n.get("t_obj"), t_amb=n.get("t_amb"))
    encoders = []
    for e in o.get("enc", []) or []:
        if not isinstance(e, dict):
            continue
        encoders.append(Encoder(
            id=int(e.get("id", 0)),
            role=str(e.get("role", "?")),
            uid=str(e.get("uid", "")),
            cnt=int(e.get("cnt", 0)),
            delta=int(e.get("delta", 0)),
            btn=int(e.get("btn", 0)),
        ))
    return Frame(bat=bat, ina=ina, ncir=ncir, encoders=encoders)


def parse_line(line: str) -> Optional[Union[Frame, LogLine]]:
    """1 行を解釈する。

    - データ行（"enc" か "ina" を含む）→ :class:`Frame`
    - 診断行（"log" を含む）→ :class:`LogLine`
    - 空行・非 JSON・パース不能 → ``None``（呼び出し側は読み飛ばす）
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        obj = json.loads(sanitize_json_line(line))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if "log" in obj:
        return LogLine(kind=str(obj["log"]), data=obj)
    if "enc" in obj or "ina" in obj:
        return _frame_from_dict(obj)
    return None
