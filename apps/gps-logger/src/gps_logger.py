#!/usr/bin/env python3
"""App01 GPS ロガー（CardputerZero・320×170 フレームバッファ UI）。

GNSS（Cap LoRa-1262 の GPS または Grove の Unit GPS v1.1）で走行ルートを GPX 1.1 に記録する。
受信のみで、電波の送信はしない。

画面: 1=メーター / 2=天球図 / 3=軌跡 / 4=詳細（Z/C・Tab で切替）
キー: Enter 記録開始・一時停止・再開 / E 2 回で記録終了 / F/X 衛星の選択（天球図）/
      G GPS の切替（auto→grove→cap・記録していないとき）/ B 画面の明るさ（明→暗→消）/
      Esc メーターへ / S 画面保存 / Q 終了（記録中は 2 回）

記録は ~/gps_logs/track_<日時>.gpx。電池切れなどで閉じタグが無いまま残った GPX は、
次の起動時に自動で閉じる。

使い方:
  python3 gps_logger.py                     # 実機（ランチャーから起動）
  python3 gps_logger.py --demo --headless --script "2 enter; 8 shot /tmp/a.png; 9 quit"
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "..", "shared"), os.path.join(_HERE, "..", "shared")):
    if os.path.isdir(p):
        sys.path.insert(0, os.path.abspath(p))
sys.path.insert(0, _HERE)

from fb_ui import KEY, THEME, common_args, font, footer, new_canvas, run, text_w, truncate  # noqa: E402
from fb_ui.fbui import SIZE  # noqa: E402
from track import Recorder, haversine, recover  # noqa: E402

VIEWS = ["DASH", "SKY", "TRACK", "INFO"]
CONFIG = os.path.expanduser("~/.config/cardputerzero/gps_logger.json")
SOURCES = ["auto", "grove", "cap"]
SOURCE_TITLE = {"cap": "Cap", "grove": "Grove", "demo": "デモ", None: "—"}
SYS_COLOR = {"G": (90, 210, 110), "Q": (240, 80, 80), "R": (90, 150, 255), "E": (240, 210, 70),
             "B": (190, 120, 255), "S": (150, 150, 150)}
BACKLIGHT = "/sys/class/backlight/backlight"
BODY_TOP, BODY_BOTTOM = 17, 156


# ---------------------------------------------------------------- 周辺（設定・電池・バックライト）
def load_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def battery() -> tuple[int | None, str]:
    """(残量 %, 状態) を返す（bq27220）。"""
    base = "/sys/class/power_supply"
    try:
        for n in os.listdir(base):
            d = os.path.join(base, n)
            if open(os.path.join(d, "type")).read().strip() == "Battery":
                cap = int(open(os.path.join(d, "capacity")).read())
                st = open(os.path.join(d, "status")).read().strip()
                return cap, st
    except (OSError, ValueError):
        pass
    return None, ""


class Backlight:
    LEVELS = (1.0, 0.15, 0.0)

    def __init__(self, enabled: bool = True):
        self.path = os.path.join(BACKLIGHT, "brightness")
        self.orig = None
        self.max = 100
        self.level = 0
        if not enabled:
            self.path = None
            return
        try:
            self.orig = int(open(self.path).read())
            self.max = int(open(os.path.join(BACKLIGHT, "max_brightness")).read())
        except (OSError, ValueError):
            self.path = None

    def set(self, level: int) -> None:
        self.level = level % len(self.LEVELS)
        if self.path:
            try:
                with open(self.path, "w") as f:
                    f.write(str(max(0, round(self.max * self.LEVELS[self.level]))))
            except OSError:
                pass

    @property
    def off(self) -> bool:
        return self.LEVELS[self.level] == 0.0

    def restore(self) -> None:
        if self.path and self.orig is not None:
            try:
                with open(self.path, "w") as f:
                    f.write(str(self.orig))
            except OSError:
                pass


# ---------------------------------------------------------------- GNSS の供給元
class Source:
    """GnssReader を Cap／Grove で切り替える。auto は Cap を 8 秒試し、NMEA が来なければ Grove。"""

    def __init__(self, mode: str, on_rmc):
        self.mode = mode
        self.on_rmc = on_rmc
        self.active = None
        self.reader = None
        self.t_start = time.monotonic()

    def _start(self, which: str) -> None:
        from gnss_at6668 import EXT_5V, GROVE_5V, GnssReader
        power = GROVE_5V if which == "grove" else EXT_5V
        probe = 8.0 if (self.mode == "auto" and which == "cap") else 20.0
        self.active = which
        self.reader = GnssReader(power_path=power, probe_timeout=probe, on_rmc=self.on_rmc).start()

    def start(self) -> None:
        self.t_start = time.monotonic()
        self._start("grove" if self.mode == "grove" else "cap")

    def restart(self, mode: str) -> None:
        self.close()
        self.mode = mode
        self.start()

    def poll(self) -> None:
        if (self.mode == "auto" and self.active == "cap" and self.reader is not None
                and not self.reader.alive() and self.reader.snapshot()["state"] == "nodata"):
            self.reader.close()
            self._start("grove")

    def snapshot(self) -> dict:
        if self.reader is None:
            return {"state": "off", "sky": []}
        s = self.reader.snapshot()
        s.setdefault("sky", [])
        return s

    def close(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None


class DemoSource:
    """PC での画面確認用。架空の地点（北緯 35 度・東経 135 度付近）を周回する。"""

    def __init__(self, on_rmc):
        self.on_rmc = on_rmc
        self.mode = "demo"
        self.active = "demo"
        self.t_start = time.monotonic()
        self._snap = {"state": "search", "sky": []}
        self._stop = threading.Event()
        rnd = random.Random(3)
        self._sky = [(s, p, rnd.randint(5, 85), rnd.randint(0, 359), rnd.randint(15, 45))
                     for s, p in [("G", 5), ("G", 7), ("G", 13), ("G", 20), ("G", 30), ("Q", 194),
                                  ("Q", 199), ("R", 72), ("R", 81), ("E", 4), ("E", 11), ("B", 23),
                                  ("B", 37), ("B", 41)]]

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        k = 0
        utc = datetime(2026, 11, 19, 3, 0, 0)
        while not self._stop.wait(0.25):           # 4 倍速
            k += 1
            utc += timedelta(seconds=1)
            sky = [{"key": f"{s}{p:02d}", "sys": s, "prn": p, "elev": e, "azim": (a + k // 8) % 360,
                    "snr": n if k > 6 else None, "used": k > 10 and n > 22} for s, p, e, a, n in self._sky]
            if k < 12:
                self._snap = {"state": "search", "sky": sky, "mode": 1, "utc": utc}
                continue
            ang = (k - 12) / 600.0 * 2 * math.pi          # 1 周約 3.3km を 10 分（時速 20km 前後）
            lat = 35.0 + 0.004 * math.sin(ang) + 0.001 * math.sin(3 * ang)
            lon = 135.0 + 0.006 * (1 - math.cos(ang))
            spd = 18 + 8 * math.sin(ang * 3)
            self._snap = {"state": "fix", "lat": lat, "lon": lon, "alt": 40 + 25 * math.sin(ang * 2),
                          "sats": sum(1 for x in sky if x["used"]), "hdop": 0.9, "speed_kmh": spd,
                          "course": (math.degrees(ang) + 90) % 360, "mode": 3, "utc": utc, "sky": sky,
                          "error": None}
            self.on_rmc(dict(self._snap))

    def poll(self) -> None:
        pass

    def restart(self, mode: str) -> None:
        pass

    def snapshot(self) -> dict:
        return dict(self._snap)

    def close(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------- 画面
def fmt_dur(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def fmt_dist(m: float) -> tuple[str, str]:
    return (f"{m / 1000:.2f}", "km") if m >= 1000 else (f"{m:.0f}", "m")


class LoggerApp:
    def __init__(self, source, rec: Recorder, cfg: dict, backlight: Backlight):
        self.src = source
        self.rec = rec
        self.cfg = cfg
        self.bl = backlight
        self.view = "DASH"
        self.sel = 0
        self.msg = ""
        self.msg_until = 0.0
        self.confirm = None            # ("stop" | "quit", 期限)
        self.last_draw = 0.0
        self.bat = (None, "")
        self.t_bat = 0.0

    def flash(self, text: str, sec: float = 2.5) -> None:
        self.msg, self.msg_until = text, time.time() + sec

    # ---- キー ----
    def on_key(self, code: int, repeat: bool):
        if self.bl.off:                                   # 消灯中はどのキーでも点灯（キーは使わない）
            if not repeat:
                self.bl.set(0)
            return True
        if code in (KEY["up"], KEY["down"]):
            if self.view == "SKY":
                self.sel += -1 if code == KEY["up"] else 1
            return True
        if repeat:
            return False
        armed = self.confirm and time.time() < self.confirm[1]
        if code == KEY["enter"]:
            st = self.rec.state
            if st == "idle":
                snap = self.src.snapshot()
                path = self.rec.start(snap.get("utc"))
                self.flash("記録開始: " + os.path.basename(path))
            elif st == "rec":
                self.rec.pause()
                self.flash("一時停止（Enter で再開・E 2 回で終了）", 4)
            else:
                self.rec.resume()
                self.flash("記録を再開")
        elif code == KEY["e"]:
            if self.rec.state == "idle":
                return False
            if armed and self.confirm[0] == "stop":
                path = self.rec.stop()
                self.confirm = None
                self.flash("保存: " + os.path.basename(path or ""), 5)
            else:
                self.confirm = ("stop", time.time() + 3)
                self.flash("もう一度 E で記録を終了して保存", 3)
        elif code in (KEY["tab"], KEY["right"]):
            self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
        elif code == KEY["left"]:
            self.view = VIEWS[(VIEWS.index(self.view) - 1) % len(VIEWS)]
        elif code in (KEY["1"], KEY["2"], KEY["3"], KEY["4"]):
            self.view = VIEWS[[KEY["1"], KEY["2"], KEY["3"], KEY["4"]].index(code)]
        elif code == KEY["esc"]:
            self.view = "DASH"
        elif code == KEY["b"]:
            self.bl.set(self.bl.level + 1)
        elif code == KEY["g"]:
            if self.rec.state != "idle":
                self.flash("記録中は GPS を切り替えられません")
            elif self.src.mode != "demo":
                mode = SOURCES[(SOURCES.index(self.src.mode) + 1) % len(SOURCES)]
                self.src.restart(mode)
                self.cfg["gnss"] = mode
                save_config(self.cfg)
                self.flash(f"GPS: {mode}")
        else:
            return False
        return True

    def want_quit(self) -> bool:
        """Q の処理（記録中は 2 回押しで保存して終了）。fb_ui の Q より先に呼ぶ。"""
        if self.rec.state == "idle":
            return True
        if self.confirm and self.confirm[0] == "quit" and time.time() < self.confirm[1]:
            return True
        self.confirm = ("quit", time.time() + 3)
        self.flash("記録中です。もう一度 Q で保存して終了", 3)
        return False

    def tick(self) -> bool:
        self.src.poll()
        now = time.time()
        if now - self.t_bat > 30:
            self.bat = battery()
            self.t_bat = now
        if now - self.last_draw >= 1.0:
            self.last_draw = now
            return not self.bl.off
        return False

    def close(self) -> None:
        path = self.rec.stop()
        if path:
            print(f"saved {path}", file=sys.stderr)
        self.src.close()
        self.bl.restore()

    # ---- 描画 ----
    def render(self) -> Image.Image:
        snap = self.src.snapshot()
        img, d = new_canvas()
        if self.view == "SKY":
            self.draw_sky(d, snap)
            return img
        self.draw_header(d)
        if self.view == "DASH":
            if snap.get("state") != "fix" and self.rec.state == "idle":
                self.draw_wait(d, snap)
            else:
                self.draw_dash(d, snap)
        elif self.view == "TRACK":
            self.draw_track(d, snap)
        else:
            self.draw_info(d, snap)
        if time.time() < self.msg_until:
            hint = self.msg
        else:
            st = self.rec.state
            first = {"idle": "Enter 記録開始", "rec": "Enter 一時停止  E×2 終了",
                     "paused": "Enter 再開  E×2 終了"}[st]
            hint = f"{first}  Z/C 画面  B 明るさ" + ("  G GPS 切替" if st == "idle" else "")
        footer(d, hint)
        return img

    def draw_header(self, d: ImageDraw.ImageDraw) -> None:
        d.rectangle((0, 0, 320, 15), fill=THEME["panel"])
        fb, fm = font(12, "bold"), font(11, "mono")
        d.text((4, 1), "GPS", font=fb, fill=THEME["accent"])
        st = self.rec.state
        if st == "rec":
            blink = int(time.time()) % 2 == 0
            d.ellipse((36, 4, 44, 12), fill=THEME["bad"] if blink else THEME["panel"])
            d.text((48, 2), f"REC {fmt_dur(self.rec.elapsed())}", font=fm, fill=THEME["bad"])
        elif st == "paused":
            d.text((36, 2), f"II 一時停止 {fmt_dur(self.rec.elapsed())}", font=font(11), fill=THEME["warn"])
        else:
            d.text((36, 1), "待機", font=font(11), fill=THEME["dim"])
        cap, stat = self.bat
        right = time.strftime("%H:%M")
        if cap is not None:
            right = f"{'+' if stat == 'Charging' else ''}{cap}%  " + right
        col = THEME["bad"] if cap is not None and cap <= 20 and stat != "Charging" else THEME["dim"]
        d.text((316 - text_w(fm, right), 2), right, font=fm, fill=col)

    def status_line(self, d: ImageDraw.ImageDraw, snap: dict, y: int) -> None:
        fs = font(11)
        mode = snap.get("mode") or 1
        if snap.get("state") == "fix":
            badge, col = ("3D", THEME["good"]) if mode == 3 else ("2D", THEME["warn"])
        elif snap.get("state") == "nodata":
            badge, col = "応答なし", THEME["bad"]
        else:
            badge, col = "未測位", THEME["bad"]
        w = text_w(fs, badge) + 8
        d.rounded_rectangle((4, y, 4 + w, y + 14), radius=3, fill=col)
        d.text((8, y), badge, font=fs, fill=THEME["bg"])
        sky = snap.get("sky", [])
        used = sum(1 for s in sky if s.get("used"))
        hd = snap.get("hdop")
        txt = f"衛星 {used}/{len(sky)}" + (f"  HDOP {hd:.1f}" if hd is not None else "")
        d.text((w + 10, y), txt, font=fs, fill=THEME["fg"])
        src = SOURCE_TITLE.get(self.src.active, "—")
        d.text((316 - text_w(fs, src), y), src, font=fs, fill=THEME["dim"])

    def draw_wait(self, d: ImageDraw.ImageDraw, snap: dict) -> None:
        sky = snap.get("sky", [])
        el = time.monotonic() - self.src.t_start
        if snap.get("state") in ("nodata", "off") and snap.get("error"):
            d.text((8, BODY_TOP + 6), "GPS から応答がありません", font=font(15, "bold"), fill=THEME["bad"])
            d.text((8, BODY_TOP + 32), truncate(font(10), snap["error"], 304), font=font(10), fill=THEME["dim"])
            d.text((8, BODY_TOP + 52), f"G で GPS を切り替え（今: {self.src.mode}）", font=font(12),
                   fill=THEME["fg"])
            d.text((8, BODY_TOP + 72), "Cap／Grove の差し込みと Grove の 5V 設定を確認してください",
                   font=font(10), fill=THEME["dim"])
        else:
            d.text((8, BODY_TOP + 4), "衛星を探しています…", font=font(16, "bold"), fill=THEME["fg"])
            tracked = sorted((s for s in sky if s.get("snr")), key=lambda s: -s["snr"])
            d.text((8, BODY_TOP + 28), f"経過 {fmt_dur(el)[2:]}   受信 {len(tracked)} 機／見えている {len(sky)} 機",
                   font=font(11), fill=THEME["dim"])
            x = 8
            for s in tracked[:12]:                       # SNR の棒
                h = int(min(50, s["snr"]) * 1.1)
                col = SYS_COLOR.get(s["sys"], THEME["fg"])
                d.rectangle((x, BODY_TOP + 104 - h, x + 18, BODY_TOP + 104), fill=col)
                f8 = font(8, "mono")
                d.text((x + 9 - text_w(f8, s["key"]) / 2, BODY_TOP + 105), s["key"], font=f8, fill=THEME["dim"])
                x += 25
            if not tracked:
                d.text((8, BODY_TOP + 60), "空の開けた屋外で、しばらく動かさずに待ってください", font=font(11),
                       fill=THEME["dim"])
        self.status_line(d, snap, BODY_BOTTOM - 16)

    def draw_dash(self, d: ImageDraw.ImageDraw, snap: dict) -> None:
        st = self.rec.stats
        spd = snap.get("speed_kmh") if snap.get("state") == "fix" else None
        fb = font(46, "bold")
        t = "--.-" if spd is None else f"{spd:4.1f}"
        d.text((8, BODY_TOP - 4), t, font=fb, fill=THEME["fg"])
        d.text((10, BODY_TOP + 52), "km/h", font=font(12), fill=THEME["dim"])
        alt = snap.get("alt")
        d.text((60, BODY_TOP + 52), "標高 " + ("—" if alt is None else f"{alt:.0f} m"), font=font(12),
               fill=THEME["dim"])
        crs = snap.get("course")
        if crs is not None and spd is not None and spd >= 2:   # 進行方向の矢印
            cx, cy, r = 128, BODY_TOP + 90, 14
            a = math.radians(crs)
            pts = [(cx + r * math.sin(a), cy - r * math.cos(a)),
                   (cx + r * 0.6 * math.sin(a + 2.5), cy - r * 0.6 * math.cos(a + 2.5)),
                   (cx + r * 0.6 * math.sin(a - 2.5), cy - r * 0.6 * math.cos(a - 2.5))]
            d.polygon(pts, fill=THEME["accent"])
            d.text((8, BODY_TOP + 84), f"進行 {crs:3.0f}°", font=font(12), fill=THEME["dim"])
        dist, unit = fmt_dist(st.distance_m)
        rows = [("距離", f"{dist} {unit}"), ("時間", fmt_dur(self.rec.elapsed())),
                ("平均", f"{st.avg_kmh():.1f} km/h"), ("最高", f"{st.max_kmh:.1f} km/h"),
                ("獲得標高", f"+{st.gain_m:.0f} m"), ("記録点", f"{st.points}")]
        fl, fv = font(11), font(13, "bold")
        y = BODY_TOP + 1
        for k, v in rows:
            d.text((170, y + 2), k, font=fl, fill=THEME["dim"])
            d.text((316 - text_w(fv, v), y), v, font=fv, fill=THEME["fg"])
            y += 18
        d.line((164, BODY_TOP + 2, 164, BODY_BOTTOM - 20), fill=THEME["line"])
        self.status_line(d, snap, BODY_BOTTOM - 16)

    def draw_sky(self, d: ImageDraw.ImageDraw, snap: dict) -> None:
        sky = sorted(snap.get("sky", []), key=lambda s: (-(s.get("snr") or 0), s["key"]))
        cx, cy, R = 85, 85, 78
        for k in (1.0, 2 / 3, 1 / 3):                      # 仰角 0・30・60 度
            r = R * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=THEME["line"])
        d.line((cx - R, cy, cx + R, cy), fill=THEME["panel"])
        d.line((cx, cy - R, cx, cy + R), fill=THEME["panel"])
        fs = font(10, "bold")
        for lab, (x, y) in {"N": (cx, cy - R - 1), "E": (cx + R + 1, cy), "S": (cx, cy + R + 1),
                            "W": (cx - R - 1, cy)}.items():
            w = text_w(fs, lab)
            d.text((min(max(x - w / 2, 0), 170 - w), min(max(y - 7, 0), 156)), lab, font=fs,
                   fill=THEME["warn"] if lab == "N" else THEME["dim"])
        if sky:
            self.sel %= len(sky)
        sel_key = sky[self.sel]["key"] if sky else None
        for s in sky:
            if s.get("elev") is None or s.get("azim") is None:
                continue
            r = R * (1.0 - max(0, min(90, s["elev"])) / 90.0)
            th = math.radians(s["azim"] - 90)
            x, y = cx + r * math.cos(th), cy + r * math.sin(th)
            snr = s.get("snr") or 0
            dot = 3 if snr < 15 else 4 if snr < 25 else 6 if snr < 35 else 8
            col = SYS_COLOR.get(s["sys"], THEME["fg"])
            h = dot / 2
            if s.get("used"):
                d.ellipse((x - h, y - h, x + h, y + h), fill=col)
            else:
                d.ellipse((x - h, y - h, x + h, y + h), outline=col)
            if s["key"] == sel_key:
                d.ellipse((x - h - 3, y - h - 3, x + h + 3, y + h + 3), outline=(255, 255, 255), width=2)
        # 右: 衛星リスト
        x0 = 172
        d.rectangle((x0, 0, 320, 170), fill=THEME["panel"])
        used = sum(1 for s in sky if s.get("used"))
        mode = snap.get("mode") or 1
        hd = snap.get("hdop")
        fm = font(10, "mono")
        d.text((x0 + 4, 1), f"衛星 {used}/{len(sky)}", font=font(11, "bold"), fill=THEME["accent"])
        m = {3: "3D", 2: "2D"}.get(mode, "--") if snap.get("state") == "fix" else "--"
        d.text((316 - text_w(fm, m), 3), m, font=fm, fill=THEME["good"] if m == "3D" else THEME["warn"])
        rows, rh, y0 = 11, 12, 18
        top = max(0, min(self.sel - rows // 2, len(sky) - rows))
        for i, s in enumerate(sky[top:top + rows]):
            y = y0 + i * rh
            if top + i == self.sel:
                d.rectangle((x0, y - 1, 320, y + rh - 2), fill=THEME["sel"])
            col = SYS_COLOR.get(s["sys"], THEME["fg"])
            d.text((x0 + 4, y), f"{s['key']:<4}", font=fm, fill=col)
            snr = s.get("snr") or 0
            bw = int(min(50, snr) * 1.3)
            if bw:
                d.rectangle((x0 + 36, y + 3, x0 + 36 + bw, y + 8),
                            fill=col if s.get("used") else THEME["line"])
            d.text((x0 + 104, y), f"{snr:2d}" if snr else " -", font=fm, fill=THEME["fg"])
            el = s.get("elev")
            d.text((x0 + 124, y), f"{el:2d}°" if el is not None else "  ", font=fm, fill=THEME["dim"])
        if not sky:
            d.text((x0 + 4, 40), "衛星の情報待ち", font=font(11), fill=THEME["dim"])
        d.text((x0 + 4, 155), f"HDOP {hd:.1f}" if hd is not None else "HDOP --", font=fm, fill=THEME["dim"])
        d.text((262, 155), "F/X 選択", font=font(9), fill=THEME["dim"])

    def draw_track(self, d: ImageDraw.ImageDraw, snap: dict) -> None:
        with self.rec.lock:
            trail = list(self.rec.trail)
        here = (snap["lat"], snap["lon"]) if snap.get("state") == "fix" and snap.get("lat") is not None else None
        pts = trail + ([here] if here else [])
        x0, y0, x1, y1 = 6, BODY_TOP + 4, 314, BODY_BOTTOM - 4
        d.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=THEME["line"])
        if not pts:
            d.text((20, 70), "記録を始めると、ここに軌跡が出ます", font=font(12), fill=THEME["dim"])
            return
        lat0 = sum(p[0] for p in pts) / len(pts)
        kx = 111320.0 * math.cos(math.radians(lat0))
        xs = [p[1] * kx for p in pts]
        ys = [p[0] * 110540.0 for p in pts]
        span = max(max(xs) - min(xs), (max(ys) - min(ys)) * (x1 - x0) / (y1 - y0), 100.0)
        scale = (x1 - x0) / span                           # 1 m あたりの画素
        mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        def px(x, y):
            return ((x1 + x0) / 2 + (x - mx) * scale, (y1 + y0) / 2 - (y - my) * scale)
        line = [px(x, y) for x, y in zip(xs[:len(trail)], ys[:len(trail)])]
        if len(line) > 1:
            d.line(line, fill=THEME["accent"], width=2)
        if trail:
            sx, sy = line[0]
            d.rectangle((sx - 3, sy - 3, sx + 3, sy + 3), fill=THEME["good"])
        if here:
            hx, hy = px(xs[-1], ys[-1])
            d.ellipse((hx - 5, hy - 5, hx + 5, hy + 5), fill=THEME["bad"], outline=(255, 255, 255))
        # 縮尺
        target = span / 4
        mag = 10 ** math.floor(math.log10(target))
        bar = max(m for m in (mag, 2 * mag, 5 * mag) if m <= target)
        bl = bar * scale
        d.line((x1 - 6 - bl, y1 - 6, x1 - 6, y1 - 6), fill=THEME["fg"], width=2)
        lab = f"{bar / 1000:g} km" if bar >= 1000 else f"{bar:g} m"
        f = font(10)
        d.text((x1 - 6 - text_w(f, lab), y1 - 20), lab, font=f, fill=THEME["fg"])
        d.text((x0 + 2, y0), "N↑", font=font(10, "bold"), fill=THEME["warn"])

    def draw_info(self, d: ImageDraw.ImageDraw, snap: dict) -> None:
        fl, fv = font(11), font(11, "mono")
        fix = snap.get("state") == "fix"
        def ll(v, pos, neg):
            return "—" if v is None or not fix else f"{abs(v):.6f}° {pos if v >= 0 else neg}"
        utc = snap.get("utc")
        local = "—"
        if utc is not None:
            local = (utc.replace(tzinfo=timezone.utc).astimezone()).strftime("%Y-%m-%d %H:%M:%S")
        spd, crs, alt, hd = snap.get("speed_kmh"), snap.get("course"), snap.get("alt"), snap.get("hdop")
        cap, stat = self.bat
        rows = [("緯度", ll(snap.get("lat"), "N", "S")), ("経度", ll(snap.get("lon"), "E", "W")),
                ("標高", "—" if alt is None else f"{alt:.1f} m"),
                ("速度・方向", "—" if spd is None else f"{spd:.1f} km/h  {crs or 0:.0f}°"),
                ("時刻", local), ("測位", f"{'3D' if (snap.get('mode') or 1) == 3 else '2D' if snap.get('mode') == 2 else '—'}"
                                          f"  使用 {snap.get('sats') or 0} 機  HDOP {hd if hd is not None else '—'}"),
                ("GPS", f"{SOURCE_TITLE.get(self.src.active, '—')}（設定 {self.src.mode}）"),
                ("ファイル", os.path.basename(self.rec.path) if self.rec.path and self.rec.state != "idle" else "—"),
                ("電池", "—" if cap is None else f"{cap}%  {stat}")]
        y = BODY_TOP + 1
        for k, v in rows:
            d.text((6, y), k, font=fl, fill=THEME["dim"])
            d.text((78, y + 1), truncate(fv, v, 236), font=fv if v.isascii() else fl, fill=THEME["fg"])
            y += 15


def main() -> None:
    ap = argparse.ArgumentParser(description="App01 GPS logger (CardputerZero)")
    ap.add_argument("--log-dir", default=os.path.expanduser("~/gps_logs"))
    ap.add_argument("--gnss", choices=SOURCES, default=None, help="GPS（既定は設定ファイル、無ければ auto）")
    ap.add_argument("--demo", action="store_true", help="架空の周回データで動かす（PC での画面確認用）")
    ap.add_argument("--view", choices=VIEWS, default="DASH")
    common_args(ap, "gps")
    args = ap.parse_args()

    for p in recover(args.log_dir):
        print(f"recovered {p}", file=sys.stderr)
    cfg = load_config()
    rec = Recorder(args.log_dir)
    if args.demo:
        src = DemoSource(rec.add)
    else:
        src = Source(args.gnss or cfg.get("gnss", "auto"), rec.add)
    app = LoggerApp(src, rec, cfg, Backlight(enabled=not args.headless))
    app.view = args.view
    src.start()
    run(app, args)


if __name__ == "__main__":
    main()
