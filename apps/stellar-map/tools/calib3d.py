#!/usr/bin/env python3
"""BMM150 3D ハードアイアン較正（uConsole）。傾き補正用。

フレームをあらゆる向きに転がして x/y/z 各軸の min/max を集め、オフセット（中心）と
半スパンを算出する。水平 360° スイープ（calib_probe.py）では z が採れないため、傾き
補正には本 3D 較正が要る。出力を config の mag_offset_x/y/z・mag_span_x/y/z に入れる。
"""
import glob
import json
import re
import sys
import time

import serial

p = glob.glob("/dev/serial/by-id/*Espressif*")[0]
s = serial.Serial(p, 115200, timeout=1)
time.sleep(0.3)
s.reset_input_buffer()
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 35.0
print("TUMBLE the frame through ALL orientations (roll+pitch+yaw fully). %.0fs" % dur)

mnx = mny = mnz = 1e9
mxx = mxy = mxz = -1e9
t0 = time.monotonic()
n = 0
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
    x, y, z = d["x"], d["y"], d["z"]
    n += 1
    mnx, mxx = min(mnx, x), max(mxx, x)
    mny, mxy = min(mny, y), max(mxy, y)
    mnz, mxz = min(mnz, z), max(mxz, z)
    now = time.monotonic()
    if now - last > 2.0:
        print("t=%4.1f n=%d x[%.0f,%.0f] y[%.0f,%.0f] z[%.0f,%.0f]"
              % (now - t0, n, mnx, mxx, mny, mxy, mnz, mxz))
        last = now
s.close()

ox, oy, oz = (mnx + mxx) / 2, (mny + mxy) / 2, (mnz + mxz) / 2
sx, sy, sz = (mxx - mnx) / 2, (mxy - mny) / 2, (mxz - mnz) / 2
print("\n=== 3D hard-iron (n=%d) ===" % n)
print("offset  x=%.0f y=%.0f z=%.0f" % (ox, oy, oz))
print("span    x=%.0f y=%.0f z=%.0f" % (sx, sy, sz))
print("config keys:")
print(json.dumps({"mag_offset_x": round(ox), "mag_offset_y": round(oy),
                  "mag_offset_z": round(oz), "mag_span_x": round(sx),
                  "mag_span_y": round(sy), "mag_span_z": round(sz)}, indent=2))
