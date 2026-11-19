"""フレームバッファ UI の共通ループ（表示・キー入力・終了処理・動作確認用の台本実行）。

アプリ側は次のメソッドを持つオブジェクトを `run()` に渡す。

    render() -> PIL.Image          画面全体（320×170）を描いて返す
    on_key(code, repeat) -> bool    キー押下。再描画が要れば True、終了なら "quit"
    tick() -> bool                  定期処理（約 0.1 秒ごと）。再描画が要れば True
    close()                         終了時の後始末（スレッド停止など）

共通キー: Q＝終了、S＝スクリーンショット（~/<app>_shots/）。
カーソル: F／X／C／Z の単独押しを ↑／↓／→／← として渡す（Fn との組み合わせと同じ扱い）。

動作確認用のオプション（ランチャーを通さず SSH から試すとき）:
    --headless          LCD とキーボードに触れずに動かす（画像は --shot / 台本の shot で保存）
    --script "2 down; 3 enter; 4 shot /tmp/a.png; 6 quit"
                        起動からの秒数ごとにキーを送る・画面を保存する・終了する
    --seconds N         N 秒で終了 / --restore 終了時に起動前の画面へ戻す
"""
from __future__ import annotations

import argparse
import os
import select
import signal
import struct
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FB_DEV = "/dev/fb0"
KBD_NAME = "tca8418c"
EV_KEY = 1
EV_FMT = "llHHi"                  # struct input_event（64bit: timeval 16B + type/code/value）
EV_SIZE = struct.calcsize(EV_FMT)
SIZE = (320, 170)

# Linux input のキーコード（必要なものだけ）
KEY = {
    "esc": 1, "tab": 15, "enter": 28, "space": 57, "backspace": 14,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50,
    "minus": 12, "equal": 13, "comma": 51, "dot": 52, "slash": 53,
}

# CardputerZero のカーソルは Fn＋F/X/C/Z（↑↓→←）。Fn なしの単独押しもカーソルとして扱う
# （2026-11-19 総司様指示）。文字入力が要るアプリは app.letter_cursor = False で無効にする。
LETTER_CURSOR = {KEY["f"]: KEY["up"], KEY["x"]: KEY["down"], KEY["c"]: KEY["right"], KEY["z"]: KEY["left"]}

# 配色（暗い背景・LCD で読みやすい明度差）
THEME = {
    "bg": (8, 12, 22),
    "panel": (20, 28, 44),
    "line": (52, 64, 88),
    "fg": (226, 232, 240),
    "dim": (128, 140, 160),
    "accent": (88, 180, 255),
    "sel": (34, 70, 120),
    "good": (80, 210, 120),
    "warn": (250, 196, 60),
    "bad": (240, 90, 90),
    "new": (120, 230, 160),
}

_FONT_PATHS = {
    "sans": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ],
    "bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ],
    "mono": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ],
}
_font_cache: dict = {}


def font(size: int, kind: str = "sans"):
    """フォントを返す。kind = sans（日本語可）/ bold / mono（英数字の表）。"""
    key = (size, kind)
    if key not in _font_cache:
        f = None
        for p in _FONT_PATHS.get(kind, []) + _FONT_PATHS["sans"]:
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except OSError:
                    continue
        _font_cache[key] = f or ImageFont.load_default(size)
    return _font_cache[key]


def text_w(fnt, s: str) -> int:
    return int(fnt.getlength(s))


def truncate(fnt, s: str, max_w: int) -> str:
    """幅 max_w に収まるよう末尾を「…」で切る。"""
    if text_w(fnt, s) <= max_w:
        return s
    while s and text_w(fnt, s + "…") > max_w:
        s = s[:-1]
    return s + "…"


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


class Display:
    """/dev/fb0（RGB565）への出力。headless では何もしない。"""

    def __init__(self, headless: bool = False, restore: bool = False):
        self.fb = None
        self.saved = None
        self.size = SIZE
        if headless:
            return
        w, h = open("/sys/class/graphics/fb0/virtual_size").read().strip().split(",")
        bpp = int(open("/sys/class/graphics/fb0/bits_per_pixel").read())
        if bpp != 16:
            raise SystemExit(f"fb0 is {bpp}bpp; RGB565 (16bpp) only")
        self.size = (int(w), int(h))
        self.fb = open(FB_DEV, "r+b", buffering=0)
        if restore:
            self.saved = self.fb.read(self.size[0] * self.size[1] * 2)

    def show(self, img: Image.Image) -> None:
        if self.fb is None:
            return
        if img.size != self.size:
            img = img.resize(self.size)
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
        self.fb.seek(0)
        self.fb.write(v.astype("<u2").tobytes())

    def close(self) -> None:
        if self.fb is None:
            return
        if self.saved is not None:
            self.fb.seek(0)
            self.fb.write(self.saved)
        self.fb.close()
        self.fb = None


class Keyboard:
    """evdev から押下(1)とリピート(2)を読む。見つからなければ fd=None。"""

    def __init__(self, headless: bool = False):
        self.fd = None
        if headless:
            return
        path = find_keyboard()
        if path:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def read(self) -> list[tuple[int, int]]:
        if self.fd is None:
            return []
        try:
            data = os.read(self.fd, EV_SIZE * 32)
        except BlockingIOError:
            return []
        out = []
        for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
            _s, _u, etype, code, value = struct.unpack_from(EV_FMT, data, off)
            if etype == EV_KEY and value in (1, 2):
                out.append((code, value))
        return out

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def parse_script(s: str) -> list[tuple[float, str, str]]:
    """'2 down; 3.5 enter; 4 shot /tmp/a.png; 6 quit' → [(2.0,'down',''), ...]"""
    out = []
    for part in s.split(";"):
        toks = part.split(None, 2)
        if len(toks) >= 2:
            out.append((float(toks[0]), toks[1], toks[2] if len(toks) > 2 else ""))
    return sorted(out, key=lambda x: x[0])


def common_args(ap: argparse.ArgumentParser, app_id: str) -> None:
    ap.add_argument("--headless", action="store_true", help="LCD とキーボードに触れずに動かす")
    ap.add_argument("--seconds", type=float, default=0.0, help="指定秒数で自動終了（0=無期限）")
    ap.add_argument("--restore", action="store_true", help="終了時に起動前の画面内容へ戻す")
    ap.add_argument("--shot", default=None, help="終了時に最後の画面を PNG 保存")
    ap.add_argument("--script", default="", help="動作確認用の台本（'秒 キー名; 秒 shot パス; 秒 quit'）")
    ap.add_argument("--shots-dir", default=os.path.expanduser(f"~/{app_id}_shots"))


def run(app, args) -> None:
    """共通のメインループ。args は common_args() を足した ArgumentParser の結果。"""
    disp = Display(headless=args.headless, restore=args.restore)
    kbd = Keyboard(headless=args.headless)
    stop = {"flag": False}
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):          # SIGHUP は Windows に無い（PC 確認用）
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.__setitem__("flag", True))

    script = parse_script(args.script)
    t0 = time.time()
    t_end = t0 + args.seconds if args.seconds > 0 else None
    img = None
    dirty = True
    frames = 0

    def save(path: str) -> None:
        if img is not None:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            img.save(path)

    def handle(code: int, repeat: bool) -> bool:
        if getattr(app, "letter_cursor", True):
            code = LETTER_CURSOR.get(code, code)
        if code == KEY["q"] and not repeat:
            stop["flag"] = True
            return False
        if code == KEY["s"] and not repeat and getattr(app, "global_shot", True):
            save(os.path.join(args.shots_dir, f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"))
            return False
        r = app.on_key(code, repeat)
        if r == "quit":
            stop["flag"] = True
            return False
        return bool(r)

    try:
        while not stop["flag"]:
            now = time.time()
            if t_end and now >= t_end:
                break
            while script and now - t0 >= script[0][0]:
                _t, act, arg = script.pop(0)
                if act == "quit":
                    stop["flag"] = True
                elif act == "shot":
                    if dirty:                      # 保存前に最新の状態を描く
                        img = app.render()
                        dirty = False
                    save(arg)
                elif act in KEY:
                    dirty |= handle(KEY[act], False)
            if stop["flag"]:
                break

            if kbd.fd is not None:
                ready, _, _ = select.select([kbd.fd], [], [], 0.1)
                if ready:
                    for code, value in kbd.read():
                        dirty |= handle(code, value == 2)
            else:
                time.sleep(0.1)

            dirty |= bool(app.tick())
            if dirty:
                img = app.render()
                disp.show(img)
                frames += 1
                dirty = False
    finally:
        try:
            app.close()
        finally:
            kbd.close()
            if args.shot:
                save(args.shot)
            disp.close()
            print(f"frames drawn: {frames}", file=sys.stderr)


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", SIZE, THEME["bg"])
    return img, ImageDraw.Draw(img)


def header(d: ImageDraw.ImageDraw, title: str, right: str = "") -> None:
    """上端 16px の見出し帯。"""
    d.rectangle((0, 0, SIZE[0], 15), fill=THEME["panel"])
    d.text((4, 1), title, font=font(12, "bold"), fill=THEME["accent"])
    if right:
        f = font(11, "mono")
        d.text((SIZE[0] - 4 - text_w(f, right), 2), right, font=f, fill=THEME["dim"])


def footer(d: ImageDraw.ImageDraw, hint: str) -> None:
    """下端 13px の操作ヒント。"""
    y = SIZE[1] - 13
    d.rectangle((0, y, SIZE[0], SIZE[1]), fill=THEME["panel"])
    f = font(10)
    d.text((4, y), truncate(f, hint, SIZE[0] - 8), font=f, fill=THEME["dim"])
