#!/usr/bin/env python3
"""App 16 星座盤 ― CardputerZero 内蔵 BMM150／BMI270 の較正プローブ（Linux IIO）。

実機上で動かし、内蔵の地磁気（bmm150）・加速度／ジャイロ（bmi270）を sysfs から記録して
ハードアイアン較正値を求める。追加パッケージ不要（numpy があれば楕円体フィットも行う）。

  --mode flat   本体を**水平に保ったまま 360° 以上**ゆっくり回す（机の上で回す）。
                x/y のオフセットと半スパン、回転方向（heading_invert）を求める。
  --mode 3d     本体を**あらゆる向きに転がす**（8 の字・裏返しも含む）。
                x/y/z のオフセットと半スパン、磁気と加速度の軸符号の整合を求める。
                傾き補正（tilt compensation）にはこちらが必要。
  --mode align  本体を水平に置いて**静止**。現在の較正済み方位を測り、`--true-heading` に
                与えた「上辺が向いている実際の方位」から heading_offset を求める。

結果は設定ファイル（既定 ~/.config/cardputerzero/stellar_map.json）へ `--write` で反映できる。

使い方（実機）:
  python3 calib_iio.py --mode flat --seconds 30 --write
  python3 calib_iio.py --mode align --true-heading 0 --write     # 上辺を真北へ向けて静止
  python3 calib_iio.py --mode 3d --seconds 45 --write
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time

CFG = os.path.expanduser("~/.config/cardputerzero/stellar_map.json")
G0 = 9.80665


def find(name):
    for d in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
        try:
            if open(os.path.join(d, "name")).read().strip() == name:
                return d
        except OSError:
            pass
    raise SystemExit(f"IIO device '{name}' not found")


def rd(path):
    with open(path) as f:
        return float(f.read())


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def record(seconds, rate):
    mag, imu = find("bmm150"), find("bmi270")
    a_scale = rd(f"{imu}/in_accel_scale") / G0          # raw -> g
    g_scale = rd(f"{imu}/in_anglvel_scale")             # raw -> rad/s
    rows = []
    period = 1.0 / rate
    t0 = time.monotonic()
    nxt = t0
    while True:
        t = time.monotonic()
        if t - t0 >= seconds:
            break
        m = [rd(f"{mag}/in_magn_{a}_raw") for a in "xyz"]
        a = [rd(f"{imu}/in_accel_{c}_raw") * a_scale for c in "xyz"]
        gz = rd(f"{imu}/in_anglvel_z_raw") * g_scale
        rows.append((t - t0, *m, *a, gz))
        nxt += period
        dt = nxt - time.monotonic()
        if dt > 0:
            time.sleep(dt)
    return rows


def vec_heading(m, a):
    """shared/compass の heading_from_vectors と同じ式（本ツール単体で動くよう複製）。"""
    an = math.sqrt(sum(v * v for v in a))
    if an < 1e-6:
        return math.degrees(math.atan2(m[1], m[0])) % 360.0
    u = [v / an for v in a]
    md = sum(p * q for p, q in zip(m, u))
    h = [m[i] - md * u[i] for i in range(3)]
    x = [1.0 - u[0] * u[0], -u[0] * u[1], -u[0] * u[2]]
    c = [x[1] * h[2] - x[2] * h[1], x[2] * h[0] - x[0] * h[2], x[0] * h[1] - x[1] * h[0]]
    return math.degrees(math.atan2(sum(p * q for p, q in zip(c, u)),
                                   sum(p * q for p, q in zip(h, x)))) % 360.0


def box(vals):
    lo, hi = min(vals), max(vals)
    return (hi + lo) / 2.0, (hi - lo) / 2.0, lo, hi


def load_cfg(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(path, upd):
    cfg = load_cfg(path)
    cfg.update(upd)
    # 実機は「地上から見上げた向き」（星座が実際の形・北向きで東が右）を既定にする。
    # 既に指定があれば尊重する。
    cfg.setdefault("mirror_ew", True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[write] {path}: updated {', '.join(sorted(upd))}")


def sectors(angles, n=12):
    return len({int((a % 360.0) // (360.0 / n)) for a in angles})


def mode_flat(rows):
    xs, ys, zs = [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows]
    ox, sx, *_ = box(xs)
    oy, sy, *_ = box(ys)
    raw = [math.degrees(math.atan2(y, x)) for x, y in zip(xs, ys)]
    cal = [math.degrees(math.atan2((y - oy) / (sy or 1), (x - ox) / (sx or 1)))
           for x, y in zip(xs, ys)]
    # 回転方向: ジャイロ z の積分（+ は z 軸まわり反時計回り）と、較正済み角度の変化を比べる
    gyro_deg = 0.0
    mag_deg = 0.0
    for i in range(1, len(rows)):
        dt = rows[i][0] - rows[i - 1][0]
        gyro_deg += math.degrees(rows[i][7]) * dt
        mag_deg += wrap180(cal[i] - cal[i - 1])
    tilt = [math.degrees(math.acos(max(-1, min(1, abs(r[6]) / math.sqrt(r[4] ** 2 + r[5] ** 2 + r[6] ** 2)))))
            for r in rows]
    print(f"samples {len(rows)}  duration {rows[-1][0]:.1f}s")
    print(f"mag x: offset {ox:8.1f} half-span {sx:7.1f}   y: offset {oy:8.1f} half-span {sy:7.1f}"
          f"   z mean {sum(zs) / len(zs):8.1f}")
    print(f"raw heading sectors covered: {sectors(raw)}/12   calibrated: {sectors(cal)}/12")
    print(f"rotation by gyro: {gyro_deg:+.0f} deg   by calibrated mag angle: {mag_deg:+.0f} deg")
    print(f"tilt from horizontal: mean {sum(tilt) / len(tilt):.1f} deg  max {max(tilt):.1f} deg")
    upd = {"mag_source": "iio", "mag_offset_x": round(ox, 1), "mag_offset_y": round(oy, 1),
           "mag_span_x": round(sx, 1), "mag_span_y": round(sy, 1)}
    ok = sectors(cal) >= 11 and min(sx, sy) > 0 and max(sx, sy) / max(min(sx, sy), 1e-9) < 1.6
    if abs(gyro_deg) > 180 and abs(mag_deg) > 180:
        # 整合する右手系なら「磁気角の変化 = −(ジャイロ z の回転)」。同符号なら鏡像＝反転が必要。
        # heading_from_xy は atan2(my,mx) をそのまま方位（東回り）として扱うため、
        # 磁気角がジャイロと逆符号で動くとき（＝時計回りで増える）が invert 不要。
        invert = (gyro_deg * mag_deg) > 0
        upd["heading_invert"] = bool(invert)
        print(f"heading_invert: {invert}  (gyro and mag angle moved in "
              f"{'the same' if invert else 'opposite'} direction)")
    else:
        print("heading_invert: undetermined (rotate at least one full turn)")
        ok = False
    print("QUALITY:", "OK" if ok else "POOR - repeat with a slow, level, full 360 deg turn")
    return upd, ok


def mode_3d(rows):
    upd = {"mag_source": "iio"}
    names = "xyz"
    off, span = [], []
    for i in range(3):
        o, s, lo, hi = box([r[1 + i] for r in rows])
        off.append(o)
        span.append(s)
        print(f"mag {names[i]}: min {lo:8.1f} max {hi:8.1f} offset {o:8.1f} half-span {s:7.1f}")
        upd[f"mag_offset_{names[i]}"] = round(o, 1)
        upd[f"mag_span_{names[i]}"] = round(s, 1)
    # 磁気と加速度の軸符号の整合: 較正後の磁気ベクトルと重力の内積（＝伏角で決まる定数）が
    # 最も一定になる符号の組を選ぶ。全体反転は区別できないため x の符号を + に固定した 4 通り。
    best = None
    for sy in (1, -1):
        for sz in (1, -1):
            dots = []
            for r in rows:
                m = [(r[1 + i] - off[i]) / (span[i] or 1) for i in range(3)]
                m[1] *= sy
                m[2] *= sz
                a = r[4:7]
                an = math.sqrt(sum(v * v for v in a)) or 1
                mn = math.sqrt(sum(v * v for v in m)) or 1
                if abs(an - 1.0) > 0.15:
                    continue                      # 動かしている最中のサンプルは除く
                dots.append(sum(mi * ai for mi, ai in zip(m, a)) / (mn * an))
            if len(dots) < 20:
                continue
            mean = sum(dots) / len(dots)
            sd = math.sqrt(sum((d - mean) ** 2 for d in dots) / len(dots))
            print(f"signs mag (+1,{sy:+d},{sz:+d}): dot mean {mean:+.3f} sd {sd:.3f}  n={len(dots)}")
            if best is None or sd < best[0]:
                best = (sd, mean, (1, sy, sz))
    ok = min(span) > 0 and max(span) / max(min(span), 1e-9) < 1.8
    if best:
        sd, mean, sg = best
        dip = math.degrees(math.asin(max(-1, min(1, abs(mean)))))
        # 加速度は静止時 +z が上向き（重力の反作用）。北半球では磁場は下向き成分を持つので、
        # 整合していれば内積は負になる。正なら全体の符号を反転する。
        if mean > 0:
            sg = tuple(-v for v in sg)
        upd["iio_mag_signs"] = list(sg)
        # 3D 較正後は軸符号で座標系を揃えるので回転向きの反転は不要。方位のずれ補正は
        # 取り直しが必要（--mode align を再実行）。
        upd["heading_invert"] = False
        upd["heading_offset"] = 0.0
        print(f"best mag signs {sg}  dot sd {sd:.3f}  implied dip angle ~{dip:.0f} deg")
        ok = ok and sd < 0.2
        if ok:
            print("NEXT: run '--mode align' again (heading_offset was reset to 0)")
    else:
        ok = False
    print("QUALITY:", "OK" if ok else "POOR - tumble the device through all orientations, slowly")
    return upd, ok


def mode_align(rows, cfg, true_heading):
    need = ("mag_offset_x", "mag_offset_y", "mag_span_x", "mag_span_y")
    if not all(k in cfg for k in need):
        raise SystemExit("run --mode flat first (no calibration in config)")
    ox, oy, sx, sy = (cfg[k] for k in need)
    inv = cfg.get("heading_invert", False)
    tilt = "mag_span_z" in cfg and "iio_mag_signs" in cfg     # 3D 較正済み→実行時と同じ傾き補正式
    if tilt:
        off = (ox, oy, cfg.get("mag_offset_z", 0.0))
        span = (sx or 1, sy or 1, cfg["mag_span_z"] or 1)
        sg = cfg["iio_mag_signs"]
    print("method:", "tilt-compensated (3D calibration)" if tilt else "horizontal (flat calibration)")
    s = c = 0.0
    for r in rows:
        if tilt:
            m = [(r[1 + i] - off[i]) / span[i] * sg[i] for i in range(3)]
            a = math.radians(vec_heading(m, r[4:7]))
        else:
            a = math.atan2((r[2] - oy) / (sy or 1), (r[1] - ox) / (sx or 1))
        if inv:
            a = -a
        s += math.sin(a)
        c += math.cos(a)
    mean = math.degrees(math.atan2(s, c)) % 360.0
    R = math.hypot(s, c) / len(rows)
    sd = math.degrees(math.sqrt(max(0.0, -2.0 * math.log(max(R, 1e-9)))))
    off = (true_heading - mean) % 360.0
    print(f"calibrated heading (before offset): {mean:.1f} deg  circular sd {sd:.1f} deg  n={len(rows)}")
    print(f"true heading given: {true_heading:.1f} deg  ->  heading_offset {off:.1f} deg")
    ok = sd < 5.0
    print("QUALITY:", "OK" if ok else "POOR - keep the device still and level")
    return {"heading_offset": round(off, 1)}, ok


def main():
    ap = argparse.ArgumentParser(description="CardputerZero built-in compass calibration (IIO)")
    ap.add_argument("--mode", choices=["flat", "3d", "align"], required=True)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--true-heading", type=float, default=None,
                    help="align: 本体の上辺が実際に向いている方位[deg]（北=0・東=90）")
    ap.add_argument("--config", default=CFG)
    ap.add_argument("--write", action="store_true", help="結果を設定ファイルへ反映（品質 OK のときのみ）")
    ap.add_argument("--force", action="store_true", help="品質 POOR でも書き込む")
    args = ap.parse_args()
    if args.mode == "align" and args.true_heading is None:
        raise SystemExit("--mode align には --true-heading が必要")

    print(f"recording {args.seconds:.0f} s (mode={args.mode}) ...", flush=True)
    rows = record(args.seconds, args.rate)
    if len(rows) < 20:
        raise SystemExit("too few samples")
    if args.mode == "flat":
        upd, ok = mode_flat(rows)
    elif args.mode == "3d":
        upd, ok = mode_3d(rows)
    else:
        upd, ok = mode_align(rows, load_cfg(args.config), args.true_heading)
    print("result:", json.dumps(upd, ensure_ascii=False))
    if args.write and (ok or args.force):
        save_cfg(args.config, upd)
    elif args.write:
        print("[write] skipped (quality POOR; use --force to write anyway)")


if __name__ == "__main__":
    main()
