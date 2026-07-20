#!/usr/bin/env python3
"""BMM150 ハードアイアン較正プローブ (uConsole)。

CoreS3 の生 mag を約 DUR 秒ロギングし、水平 360° 回転中の x/y min/max から
ハードアイアン・オフセットを推定。較正前後の heading レンジを比較して、
オフセット補正で追従するようになるかを判定する。
"""
import glob
import json
import math
import re
import sys
import time

import serial

p = glob.glob("/dev/serial/by-id/*Espressif*")[0]
s = serial.Serial(p, 115200, timeout=1)
time.sleep(0.3)
s.reset_input_buffer()
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
print("port=%s  logging %.0fs -- rotate CoreS3 slowly 360 deg now" % (p, dur))

t0 = time.monotonic()
xs, ys, zs, hs = [], [], [], []
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
    x, y, z, h = d["x"], d["y"], d["z"], d["heading"]
    xs.append(x)
    ys.append(y)
    zs.append(z)
    hs.append(h)
    now = time.monotonic()
    if now - last > 1.0:
        print("t=%4.1f x=%8.1f y=%8.1f z=%7.1f raw_head=%6.1f" % (now - t0, x, y, z, h))
        last = now
s.close()

if not xs:
    print("no samples")
    sys.exit(1)

ox = (min(xs) + max(xs)) / 2.0
oy = (min(ys) + max(ys)) / 2.0
sx = (max(xs) - min(xs)) / 2.0
sy = (max(ys) - min(ys)) / 2.0
print("\n--- summary (%d samples) ---" % len(xs))
print("x range [%.0f .. %.0f] span %.0f" % (min(xs), max(xs), max(xs) - min(xs)))
print("y range [%.0f .. %.0f] span %.0f" % (min(ys), max(ys), max(ys) - min(ys)))
print("z range [%.0f .. %.0f] span %.0f" % (min(zs), max(zs), max(zs) - min(zs)))
print("raw heading range [%.1f .. %.1f] span %.1f"
      % (min(hs), max(hs), max(hs) - min(hs)))
print("hard-iron offset est: ox=%.0f oy=%.0f   soft-iron half-span sx=%.0f sy=%.0f"
      % (ox, oy, sx, sy))

# 較正後 heading をサンプル（オフセット除去＋軸スケール正規化）。
scale = (sx + sy) / 2.0 or 1.0
cal = []
for x, y in zip(xs, ys):
    cx = (x - ox) / (sx or 1.0)
    cy = (y - oy) / (sy or 1.0)
    cal.append(math.degrees(math.atan2(cy, cx)) % 360.0)
# 円周上のカバレッジ = 12 セクタのうち何個に点が入ったか。
sect = set(int(c // 30) for c in cal)
print("calibrated heading coverage: %d/12 sectors (360deg = full sweep detected)"
      % len(sect))
print("calibrated heading samples:",
      ["%.0f" % c for c in cal[::max(1, len(cal) // 16)]])
