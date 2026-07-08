#!/usr/bin/env python3
"""CardputerZero Python サイドカー雛形 ― JSON Lines でフレームを stdout に吐く。

サイドカーの型: 重い計算/センサ読取を Python 側で行い、320×170 のデバイス座標プリミティブを
1 行 1 フレームの JSON（JSON Lines）で stdout に出す。UI（例: rust-sdl2-app 派生）はこれを
読んで点・線・文字を描くだけ、の薄い実装にする。両者はパイプ or 子プロセスで連携する。

実例: 星座盤 App16 の `apps/stellar-map/sidecar/stellar_sidecar.py`（Scene プロトコル）。

使い方:
  python3 sidecar.py                 # 1 フレーム出力して終了
  python3 sidecar.py --interval 0.1  # 0.1 秒ごとに出力し続ける（JSON Lines）
  python3 sidecar.py --frames 50     # 50 フレームで終了
  python3 sidecar.py | <ui>          # UI へパイプ
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

# CardputerZero LCD 実解像度（厳守）。
W, H = 320, 170


def build_frame(t: float) -> dict:
    """1 フレームを組む。実アプリはここを天体計算/センサ/カメラ等に置き換える。

    フレーム schema（UI と合意する契約・全て 320×170 の整数デバイス画素）:
      w, h            : 画面サイズ
      t               : 経過秒
      points[[x,y,side,r,g,b]] : 一辺 side px の塗り四角
      labels[[x,y,text,r,g,b]] : 8×8 文字列
      meta{...}       : UI が情報表示に使う任意データ
    """
    # デモ計算: 点をリサージュ状に往復させる。
    x = int((W / 2 - 20) * math.sin(t * 1.3) + W / 2)
    y = int((H / 2 - 20) * math.sin(t * 0.9) + H / 2)
    return {
        "w": W, "h": H, "t": round(t, 3),
        "points": [[x, y, 3, 0x4F, 0xC3, 0xF7]],
        "labels": [
            [6, 6, "sidecar demo", 200, 200, 200],
            [6, 18, f"x={x:3d} y={y:3d}", 120, 140, 160],
        ],
        "meta": {"note": "python-sidecar-app template"},
    }


def emit(frame: dict) -> None:
    sys.stdout.write(json.dumps(frame, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser(description="CardputerZero Python sidecar template")
    ap.add_argument("--interval", type=float, default=0.0,
                    help="秒。>0 でこの間隔で出し続ける（JSON Lines）")
    ap.add_argument("--frames", type=int, default=0,
                    help=">0 でこのフレーム数だけ出して終了")
    args = ap.parse_args()

    t0 = time.monotonic()
    n = 0
    while True:
        emit(build_frame(time.monotonic() - t0))
        n += 1
        if args.frames and n >= args.frames:
            break
        if args.interval and args.interval > 0:
            time.sleep(args.interval)
        else:
            break


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass  # UI 側がパイプを閉じたら静かに終了
    except KeyboardInterrupt:
        pass
