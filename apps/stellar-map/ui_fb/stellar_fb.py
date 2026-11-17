#!/usr/bin/env python3
"""App 16 星座盤 ― フレームバッファ直描画 UI（CardputerZero 実機用）。

CardputerZero の LCD は `/dev/fb0`（panel-mipi-dbi・320×170・RGB565）で、標準ランチャーや
標準アプリは SDL/Wayland を使わず**フレームバッファへ直接描画し、キーボードは evdev
（tca8418c）から直接読む**構成だった（2026-11-17 実機調査）。SDL2 版の `ui/`（uConsole で
検証）はそのままでは LCD に出ないため、同じ Scene JSON プロトコルを使う薄い UI をここに置く。

  sidecar/stellar_sidecar.py ── Scene JSON (JSON Lines) ──▶ 本スクリプト ──▶ /dev/fb0
           ▲                                                    │
           └────────── キー操作（enter/tab/up/down/esc を stdin へ）┘

描画は `tools/render_scene.py` の `render_scene()` を共用する（PC 検証と同じ絵になる）。
依存は工場出荷イメージに入っている Pillow と numpy のみ。`pi` ユーザー（video・input
グループ）で sudo なしに動く。

キー: Enter / Tab / ↑ / ↓ / Esc はサイドカーへ送る。L / D / P / C はレイヤ切替、
      S はスクリーンショット、Q は終了。

使い方:
  python3 stellar_fb.py                       # 終了は Q（またはランチャーの ESC 長押し）
  python3 stellar_fb.py --seconds 20 --restore --shot /tmp/shot.png   # 動作確認用
  python3 stellar_fb.py -- --lat 35.68 --lon 139.77                   # `--` 以降はサイドカーへ
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import select
import signal
import struct
import subprocess
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_APP, "tools"))

from render_scene import render_scene  # noqa: E402

FB_DEV = "/dev/fb0"
KBD_NAME = "tca8418c"
EV_KEY = 1
EV_FMT = "llHHi"                 # struct input_event（64bit: timeval 16B + type/code/value）
EV_SIZE = struct.calcsize(EV_FMT)

# Linux input keycode → サイドカーへ送るナビゲーション名
NAV_KEYS = {28: "enter", 15: "tab", 1: "esc", 103: "up", 108: "down"}
# Linux input keycode → UI 側で処理するレイヤ切替
KEY_L, KEY_D, KEY_P, KEY_C, KEY_S, KEY_Q = 38, 32, 25, 46, 31, 16


def find_keyboard(name: str = KBD_NAME) -> str | None:
    """/proc/bus/input/devices から名前で evdev ノードを探す。"""
    try:
        blocks = open("/proc/bus/input/devices", encoding="utf-8").read().split("\n\n")
    except OSError:
        return None
    for b in blocks:
        if f'Name="{name}"' in b:
            for tok in b.split():
                if tok.startswith("event"):
                    return "/dev/input/" + tok
    return None


def fb_geometry() -> tuple[int, int]:
    w, h = open("/sys/class/graphics/fb0/virtual_size").read().strip().split(",")
    bpp = int(open("/sys/class/graphics/fb0/bits_per_pixel").read())
    if bpp != 16:
        raise SystemExit(f"fb0 is {bpp}bpp; this UI supports RGB565 (16bpp) only")
    return int(w), int(h)


def to_rgb565(img) -> bytes:
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return v.astype("<u2").tobytes()


def apply_layers(scene: dict, show: dict) -> dict:
    """レイヤ切替を Scene に反映（MAP モードのみ。LIST/ZOOM はサイドカーの出力どおり）。"""
    if scene.get("meta", {}).get("mode", "MAP") != "MAP":
        return scene
    s = dict(scene)
    if not show["lines"]:
        s["lines"] = []
    if not show["dso"]:
        s["dso"] = []
    if not show["labels"]:
        s["labels"] = []
    if not show["cnames"]:
        s["cnames"] = []
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Stellar Map framebuffer UI (CardputerZero)")
    ap.add_argument("--sidecar", default=os.environ.get(
        "STELLAR_SIDECAR", os.path.join(_APP, "sidecar", "stellar_sidecar.py")))
    ap.add_argument("--interval", type=float, default=0.5, help="サイドカーのフレーム間隔[秒]")
    ap.add_argument("--seconds", type=float, default=0.0, help="指定秒数で自動終了（0=無期限）")
    ap.add_argument("--restore", action="store_true", help="終了時に起動前の画面内容へ戻す")
    ap.add_argument("--shot", default=None, help="終了時に最後のフレームを PNG 保存")
    ap.add_argument("--shots-dir", default=os.environ.get(
        "STELLAR_SHOTS_DIR", os.path.expanduser("~/stellar_shots")))
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="`--` 以降はサイドカーへ渡す")
    args = ap.parse_args()
    extra = [a for a in args.rest if a != "--"]

    w, h = fb_geometry()
    fb = open(FB_DEV, "r+b", buffering=0)
    saved = fb.read(w * h * 2) if args.restore else None

    cmd = [sys.executable, args.sidecar, "--interval", str(args.interval)] + extra
    if importlib.util.find_spec("skyfield") is None and "--no-planets" not in extra:
        cmd.append("--no-planets")          # 惑星・月は skyfield 導入後に有効化
    side = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    os.set_blocking(side.stdout.fileno(), False)

    kpath = find_keyboard()
    kfd = os.open(kpath, os.O_RDONLY | os.O_NONBLOCK) if kpath else None

    stop = {"flag": False}
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.__setitem__("flag", True))

    show = {"lines": True, "dso": True, "labels": True, "cnames": False}
    buf = b""
    scene = None
    img = None
    dirty = False
    frames = 0
    t_end = time.time() + args.seconds if args.seconds > 0 else None

    def nav(name: str) -> None:
        try:
            side.stdin.write((name + "\n").encode())
            side.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    try:
        while not stop["flag"]:
            if t_end and time.time() >= t_end:
                break
            if side.poll() is not None:
                print("sidecar exited:", side.returncode, file=sys.stderr)
                break
            fds = [side.stdout] + ([kfd] if kfd is not None else [])
            ready, _, _ = select.select(fds, [], [], 0.2)

            if side.stdout in ready:
                chunk = side.stdout.read()
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    if lines:
                        try:
                            scene = json.loads(lines[-1])     # 最新フレームだけ描く
                            dirty = True
                        except json.JSONDecodeError:
                            pass

            if kfd is not None and kfd in ready:
                try:
                    data = os.read(kfd, EV_SIZE * 32)
                except BlockingIOError:
                    data = b""
                for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                    _s, _u, etype, code, value = struct.unpack_from(EV_FMT, data, off)
                    if etype != EV_KEY or value == 0:
                        continue                              # 押下(1)とリピート(2)のみ
                    if code in NAV_KEYS:
                        if os.environ.get("STELLAR_DEBUG"):
                            print(f"nav {NAV_KEYS[code]} value={value}", file=sys.stderr)
                        if value == 1 or code in (103, 108):
                            nav(NAV_KEYS[code])
                    elif value == 1:
                        if os.environ.get("STELLAR_DEBUG"):
                            print(f"key code={code}", file=sys.stderr)
                        if code == KEY_L:
                            show["lines"] = not show["lines"]; dirty = True
                        elif code == KEY_D:
                            show["dso"] = not show["dso"]; dirty = True
                        elif code == KEY_P:
                            show["labels"] = not show["labels"]; dirty = True
                        elif code == KEY_C:
                            show["cnames"] = not show["cnames"]; dirty = True
                        elif code == KEY_S and img is not None:
                            os.makedirs(args.shots_dir, exist_ok=True)
                            img.save(os.path.join(args.shots_dir, f"stellar_{int(time.time())}.png"))
                        elif code == KEY_Q:
                            stop["flag"] = True

            if dirty and scene is not None:
                img = render_scene(apply_layers(scene, show))
                if img.size != (w, h):
                    img = img.resize((w, h))
                fb.seek(0)
                fb.write(to_rgb565(img))
                frames += 1
                dirty = False
    finally:
        try:
            side.terminate()
            side.wait(timeout=3)
        except Exception:  # noqa: BLE001
            side.kill()
        if kfd is not None:
            os.close(kfd)
        if args.shot and img is not None:
            img.save(args.shot)
        if saved is not None:
            fb.seek(0)
            fb.write(saved)
        fb.close()
        print(f"frames drawn: {frames}", file=sys.stderr)


if __name__ == "__main__":
    main()
