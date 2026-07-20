#!/usr/bin/env python3
"""BMM150 3D ハードアイアン＋ソフトアイアン較正（楕円体フィット・uConsole）。

フレームをあらゆる向きに転がして磁気 (x,y,z) を集め、**楕円体フィット**でハードアイアン
中心（オフセット 3 ベクトル）とソフトアイアン補正 3×3 行列を求める。補正後は
corrected = M @ (raw - offset) が単位球に載る＝傾き補正の残差（軸非平行な歪み由来）が
バウンディングボックス法より小さくなる。

出力を config の mag_ellipsoid_offset(3) / mag_ellipsoid_matrix(9・行優先) に入れる。
比較用にボックス法(min/max)の offset/span も表示する。numpy が要る。
"""
import glob
import json
import re
import sys
import time

import numpy as np
import serial


def ellipsoid_fit(P):
    """N×3 サンプル → (offset[3], M[3x3])。corrected = M @ (raw-offset) が単位球。"""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    D = np.column_stack([x * x, y * y, z * z, 2 * x * y, 2 * x * z, 2 * y * z,
                         2 * x, 2 * y, 2 * z])
    v, *_ = np.linalg.lstsq(D, np.ones(len(P)), rcond=None)
    A, B, C, Dd, E, F, G, H, I = v
    Q = np.array([[A, Dd, E], [Dd, B, F], [E, F, C]])
    p = np.array([G, H, I])
    c = -np.linalg.solve(Q, p)                      # ハードアイアン中心
    k = 1.0 - (c @ Q @ c + 2 * p @ c)               # u^T (Q/k) u = 1
    Qp = Q / k
    w, V = np.linalg.eigh(Qp)
    if np.any(w <= 0):
        raise ValueError("フィット失敗（正定値でない＝サンプル不足/偏り）: eig=%s" % w)
    M = V @ np.diag(np.sqrt(w)) @ V.T               # 単位球化（direction 保存）
    return c, M


def main():
    p = glob.glob("/dev/serial/by-id/*Espressif*")[0]
    s = serial.Serial(p, 115200, timeout=1)
    time.sleep(0.3)
    s.reset_input_buffer()
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    print("TUMBLE the frame through ALL orientations. %.0fs (collecting samples)" % dur)

    pts = []
    t0 = time.monotonic()
    last = 0.0
    while time.monotonic() - t0 < dur:
        ln = s.readline().decode("utf-8", "replace").strip()
        m = re.search(r'"mag":\{[^}]*\}', ln)
        if not m:
            continue
        try:
            d = json.loads("{" + m.group(0) + "}")["mag"]
        except Exception:
            continue
        if not d.get("ok"):
            continue
        pts.append((d["x"], d["y"], d["z"]))
        now = time.monotonic()
        if now - last > 3.0:
            print("t=%4.1f n=%d" % (now - t0, len(pts)))
            last = now
    s.close()

    P = np.array(pts, dtype=float)
    n = len(P)
    if n < 30:
        print("samples too few: %d" % n)
        return
    # ボックス法（比較・フォールバック用）
    mn, mx = P.min(0), P.max(0)
    boff = (mn + mx) / 2
    bspan = (mx - mn) / 2
    print("\n=== box (min/max) ===")
    print("offset x=%.0f y=%.0f z=%.0f  span x=%.0f y=%.0f z=%.0f"
          % (*boff, *bspan))

    # 楕円体フィット
    c, M = ellipsoid_fit(P)
    corr = (P - c) @ M.T                    # corrected = M (raw-offset)
    r = np.linalg.norm(corr, axis=1)
    print("\n=== ellipsoid fit (n=%d) ===" % n)
    print("offset  x=%.1f y=%.1f z=%.1f" % (c[0], c[1], c[2]))
    print("matrix (row-major):")
    for row in M:
        print("  %+.5f %+.5f %+.5f" % (row[0], row[1], row[2]))
    print("|corrected| mean=%.3f std=%.3f (理想 mean=1 std=0)" % (r.mean(), r.std()))
    # ボックス補正後の球面度（比較）
    bc = (P - boff) / bspan
    rb = np.linalg.norm(bc, axis=1)
    print("box  |corrected| mean=%.3f std=%.3f" % (rb.mean(), rb.std()))
    print("\nconfig keys:")
    print(json.dumps({"mag_ellipsoid_offset": [round(v, 2) for v in c],
                      "mag_ellipsoid_matrix": [round(v, 6) for v in M.flatten()]},
                     indent=2))


if __name__ == "__main__":
    main()
