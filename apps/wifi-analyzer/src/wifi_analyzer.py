#!/usr/bin/env python3
"""App07 Wi-Fi アナライザー（CardputerZero・320×170 フレームバッファ UI）。

周辺 AP の一覧・2.4GHz 帯のチャンネルマップ・信号強度の時系列グラフを表示する。
受信するのは AP のビーコンだけで、接続・解読・送信は行わない（HANDOFF §7）。

画面: 1=一覧 / 2=チャンネル / 3=グラフ（Z/C・Tab で切替）
キー: F/X（F/X）選択 / Enter 一覧→グラフ / Esc 一覧へ / R 再スキャン / O 並べ替え /
      L CSV 記録の開始・停止（~/wifi_logs/）/ S 画面保存 / Q 終了

使い方:
  python3 wifi_analyzer.py                         # 実機（ランチャーから起動）
  python3 wifi_analyzer.py --demo --headless --script "3 shot /tmp/a.png; 4 quit"
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "..", "shared"), os.path.join(_HERE, "..", "shared")):
    if os.path.isdir(p):
        sys.path.insert(0, os.path.abspath(p))
sys.path.insert(0, _HERE)

from fb_ui import KEY, THEME, common_args, font, footer, header, new_canvas, run, text_w, truncate  # noqa: E402
from wifi_scan import Scanner  # noqa: E402

VIEWS = ["LIST", "CHAN", "GRAPH"]
VIEW_TITLE = {"LIST": "一覧", "CHAN": "チャンネル", "GRAPH": "グラフ"}
SORTS = ["signal", "chan", "ssid"]
SORT_TITLE = {"signal": "強い順", "chan": "ch 順", "ssid": "名前順"}
PALETTE = [(88, 180, 255), (250, 160, 70), (120, 220, 130), (230, 110, 200), (250, 220, 90),
           (110, 220, 230), (200, 150, 255), (255, 120, 120), (170, 210, 90), (150, 170, 255)]
GRAPH_SPAN = 600.0            # グラフの横幅[秒]
BODY_TOP, BODY_BOTTOM = 17, 156


def sig_color(pct: float):
    return THEME["good"] if pct >= 70 else THEME["warn"] if pct >= 40 else THEME["bad"]


def ap_color(bssid: str):
    return PALETTE[sum(bssid.encode()) % len(PALETTE)]


class WifiApp:
    def __init__(self, scanner: Scanner, log_dir: str):
        self.sc = scanner
        self.log_dir = log_dir
        self.view = "LIST"
        self.sort = "signal"
        self.sel = None              # 選択中の BSSID
        self.top = 0                 # 一覧の先頭行
        self.seen_version = -1
        self.last_clock = 0
        self.msg = ""
        self.msg_until = 0.0

    # ---- 並べ替えと選択 ----
    def ordered(self):
        aps = self.sc.snapshot()
        if self.sort == "signal":
            aps.sort(key=lambda a: (-a.signal, a.ssid))
        elif self.sort == "chan":
            aps.sort(key=lambda a: (a.freq, -a.signal))
        else:
            aps.sort(key=lambda a: (a.ssid == "", a.ssid.lower(), -a.signal))
        return aps

    def sel_index(self, aps) -> int:
        for i, a in enumerate(aps):
            if a.bssid == self.sel:
                return i
        return 0

    def move(self, step: int) -> None:
        aps = self.ordered()
        if not aps:
            return
        i = min(max(self.sel_index(aps) + step, 0), len(aps) - 1) if self.sel else 0
        self.sel = aps[i].bssid

    def flash(self, text: str) -> None:
        self.msg = text
        self.msg_until = time.time() + 2.5

    # ---- fb_ui から呼ばれる ----
    def on_key(self, code: int, repeat: bool):
        if code in (KEY["up"], KEY["down"]):
            self.move(-1 if code == KEY["up"] else 1)
            return True
        if repeat:
            return False
        if code in (KEY["tab"], KEY["right"]):
            self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
        elif code == KEY["left"]:
            self.view = VIEWS[(VIEWS.index(self.view) - 1) % len(VIEWS)]
        elif code in (KEY["1"], KEY["2"], KEY["3"]):
            self.view = VIEWS[[KEY["1"], KEY["2"], KEY["3"]].index(code)]
        elif code == KEY["enter"] and self.view == "LIST":
            self.view = "GRAPH"
        elif code == KEY["esc"]:
            self.view = "LIST"
        elif code == KEY["r"]:
            self.sc.rescan_now()
            self.flash("再スキャン")
        elif code == KEY["o"]:
            self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
            self.flash("並べ替え: " + SORT_TITLE[self.sort])
        elif code == KEY["l"]:
            if self.sc.log_path:
                self.sc.stop_log()
                self.flash("記録を停止")
            else:
                path = self.sc.start_log(self.log_dir)
                self.flash("記録: " + os.path.basename(path))
        else:
            return False
        return True

    def tick(self) -> bool:
        dirty = False
        if self.sc.version != self.seen_version:
            self.seen_version = self.sc.version
            if self.sel is None:
                aps = self.ordered()
                cur = [a for a in aps if a.in_use]
                if cur or aps:
                    self.sel = (cur or aps)[0].bssid
            dirty = True
        sec = int(time.time())
        if sec != self.last_clock:
            self.last_clock = sec
            dirty = True
        return dirty

    def close(self) -> None:
        self.sc.stop()

    # ---- 描画 ----
    def render(self) -> Image.Image:
        img, d = new_canvas()
        aps = self.ordered()
        state = "scan…" if self.sc.scanning else time.strftime("%H:%M:%S")
        rec = "●REC " if self.sc.log_path else ""
        header(d, f"Wi-Fi  {VIEW_TITLE[self.view]}  {len(aps)} AP", rec + state)
        if self.sc.log_path:
            f = font(11, "mono")
            w = text_w(f, rec + state)
            d.text((320 - 4 - w, 2), "●", font=f, fill=THEME["bad"])
        if self.view == "LIST":
            self.draw_list(d, aps)
        elif self.view == "CHAN":
            img = self.draw_chan(img, aps)
            d = ImageDraw.Draw(img)
        else:
            self.draw_graph(d, aps)
        if time.time() < self.msg_until:
            hint = self.msg
        elif self.sc.error:
            hint = "エラー: " + self.sc.error
        else:
            hint = {"LIST": f"F/X選択 Enter グラフ Z/C 画面 O {SORT_TITLE[self.sort]} R 再走査 L 記録",
                    "CHAN": "F/X選択 Z/C 画面 Esc 一覧 R 再走査 L 記録",
                    "GRAPH": "F/X AP 切替 Z/C 画面 Esc 一覧 L 記録"}[self.view]
        footer(d, hint)
        return img

    def draw_list(self, d: ImageDraw.ImageDraw, aps) -> None:
        if not aps:
            d.text((8, 60), "スキャン中…" if self.sc.scans == 0 else "AP が見つかりません",
                   font=font(13), fill=THEME["dim"])
            return
        row_h, rows = 15, 9
        i = self.sel_index(aps)
        if i < self.top:
            self.top = i
        elif i >= self.top + rows:
            self.top = i - rows + 1
        self.top = max(0, min(self.top, max(0, len(aps) - rows)))
        fs, fm = font(11), font(11, "mono")
        for k, a in enumerate(aps[self.top:self.top + rows]):
            y = BODY_TOP + 2 + k * row_h
            if a.bssid == self.sel:
                d.rectangle((0, y - 1, 319, y + row_h - 2), fill=THEME["sel"])
            if a.in_use:
                d.text((2, y), "*", font=fm, fill=THEME["good"])
            # 信号バー
            d.rectangle((10, y + 4, 36, y + 9), outline=THEME["line"])
            d.rectangle((11, y + 5, 11 + int(24 * a.signal / 100), y + 8), fill=sig_color(a.signal))
            d.text((40, y), f"{a.signal:3d}", font=fm, fill=THEME["fg"])
            d.text((66, y), f"{a.chan:3d}", font=fm, fill=THEME["accent"])
            sec = a.sec_short
            sw = text_w(fm, sec)
            d.text((316 - sw, y), sec, font=fm, fill=THEME["bad"] if sec in ("OPEN", "WEP") else THEME["dim"])
            name = a.ssid or "（非公開）"
            d.text((92, y - 1), truncate(fs, name, 316 - sw - 6 - 92), font=fs,
                   fill=THEME["fg"] if a.ssid else THEME["dim"])
        if len(aps) > rows:                                   # スクロール位置
            h = BODY_BOTTOM - BODY_TOP - 2
            bh = max(8, h * rows // len(aps))
            by = BODY_TOP + 1 + (h - bh) * self.top // max(1, len(aps) - rows)
            d.rectangle((318, by, 319, by + bh), fill=THEME["dim"])

    def draw_chan(self, img: Image.Image, aps) -> Image.Image:
        x0, x1, ytop, ybase = 16, 314, 22, 136
        lo, hi = -1.0, 16.0                                   # 表示する ch の範囲（裾を含む）
        def cx(ch: float) -> float:
            return x0 + (ch - lo) * (x1 - x0) / (hi - lo)
        def sy(pct: float) -> float:
            return ybase - (ybase - ytop) * pct / 100.0
        d = ImageDraw.Draw(img)
        fm = font(9, "mono")
        for pct in (25, 50, 75, 100):                         # 目盛り
            y = sy(pct)
            d.line((x0, y, x1, y), fill=THEME["panel"])
            d.text((1, y - 5), f"{pct}", font=fm, fill=THEME["dim"])
        d.line((x0, ybase, x1, ybase), fill=THEME["line"])
        g24 = [a for a in aps if a.band == "2.4G" and 1 <= a.chan <= 14]
        counts = {c: 0 for c in range(1, 15)}
        for a in g24:
            counts[a.chan] += 1
        for c in range(1, 15):
            x = cx(c)
            d.line((x, ybase, x, ybase + 2), fill=THEME["line"])
            t = str(c)
            d.text((x - text_w(fm, t) / 2, ybase + 2), t, font=fm,
                   fill=THEME["fg"] if counts[c] else THEME["dim"])
            if counts[c]:
                n = str(counts[c])
                d.text((x - text_w(fm, n) / 2, ybase + 11), n, font=fm, fill=THEME["accent"])
        # AP ごとの占有帯域（20MHz ≒ ±2ch）
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(over)
        sel_ap = None
        for a in sorted(g24, key=lambda a: a.signal):
            hs = max(2.0, a.width / 10.0)
            top = sy(a.signal)
            pts = [(cx(a.chan - hs), ybase), (cx(a.chan - hs + 0.6), top),
                   (cx(a.chan + hs - 0.6), top), (cx(a.chan + hs), ybase)]
            col = ap_color(a.bssid)
            if a.bssid == self.sel:
                sel_ap = (a, pts)
                continue
            od.polygon(pts, fill=col + (38,), outline=col + (200,))
        if sel_ap:
            a, pts = sel_ap
            od.polygon(pts, fill=ap_color(a.bssid) + (110,))
            od.line(pts, fill=(255, 255, 255, 255), width=2)
        img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
        d = ImageDraw.Draw(img)
        # ラベル: 選択中＋強い順に 3 つ
        fs = font(10)
        labels = ([sel_ap[0]] if sel_ap else []) + [a for a in sorted(g24, key=lambda a: -a.signal)
                                                    if not sel_ap or a.bssid != sel_ap[0].bssid][:3]
        placed: list[tuple[float, float, float, float]] = []
        for a in labels:
            t = truncate(fs, a.ssid or "（非公開）", 90)
            w = text_w(fs, t)
            x = min(max(cx(a.chan) - w / 2, x0), x1 - w)
            y = max(sy(a.signal) - 13, BODY_TOP)
            box = (x, y, x + w, y + 12)
            if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in placed):
                continue
            placed.append(box)
            d.text((x, y), t, font=fs, fill=(255, 255, 255) if a.bssid == self.sel else ap_color(a.bssid))
        n5 = len(aps) - len(g24)
        if n5:
            t = f"5GHz {n5} AP は一覧で確認"
            d.text((x1 - text_w(fs, t), BODY_TOP + 1), t, font=fs, fill=THEME["dim"])
        return img

    def draw_graph(self, d: ImageDraw.ImageDraw, aps) -> None:
        a = next((x for x in aps if x.bssid == self.sel), None)
        if a is None:
            d.text((8, 60), "AP を選んでください（F/X）" if aps else "スキャン中…",
                   font=font(13), fill=THEME["dim"])
            return
        fb, fm, fs = font(12, "bold"), font(10, "mono"), font(10)
        right = f"ch{a.chan} {a.sec_short} {a.rate}Mb/s"
        rw = text_w(fm, right)
        d.text((4, BODY_TOP), truncate(fb, a.ssid or "（非公開）", 316 - rw - 10), font=fb,
               fill=THEME["fg"])
        d.text((316 - rw, BODY_TOP + 2), right, font=fm, fill=THEME["dim"])
        d.text((4, BODY_TOP + 16), f"{a.bssid}  {a.freq}MHz  {a.band}  {a.width}MHz",
               font=fm, fill=THEME["dim"])

        live = a.in_use and len(self.sc.link_hist) > 0
        if live:
            with self.sc.lock:
                pts = list(self.sc.link_hist)
            vmin, vmax, unit, note = -95.0, -25.0, "dBm", "接続中・1秒ごと"
        else:
            pts = list(a.hist)
            vmin, vmax, unit, note = 0.0, 100.0, "%", f"スキャンごと（約{int(self.sc.interval)}秒）"
        gx0, gx1, gy0, gy1 = 30, 314, BODY_TOP + 31, BODY_BOTTOM - 14
        now = time.time()
        def px(t: float) -> float:
            return gx1 - (now - t) * (gx1 - gx0) / GRAPH_SPAN
        def py(v: float) -> float:
            v = min(max(v, vmin), vmax)
            return gy1 - (v - vmin) * (gy1 - gy0) / (vmax - vmin)
        steps = (-90, -70, -50, -30) if live else (0, 25, 50, 75, 100)
        for v in steps:
            y = py(v)
            d.line((gx0, y, gx1, y), fill=THEME["panel"])
            t = str(v)
            d.text((gx0 - 3 - text_w(fm, t), y - 6), t, font=fm, fill=THEME["dim"])
        for m in range(0, int(GRAPH_SPAN // 60) + 1, 2):    # 2 分ごとの縦線
            x = px(now - m * 60)
            d.line((x, gy0, x, gy1), fill=THEME["panel"])
        d.rectangle((gx0, gy0, gx1, gy1), outline=THEME["line"])
        seg, prev_t = [], None
        gap = 3.0 if live else self.sc.interval * 2.5
        col = sig_color(pts[-1][1] if not live else (pts[-1][1] + 100) * 100 / 60) if pts else THEME["fg"]
        for t, v in pts:
            if now - t > GRAPH_SPAN:
                continue
            if prev_t is not None and t - prev_t > gap and len(seg) > 1:
                d.line(seg, fill=col, width=2)
                seg = []
            elif prev_t is not None and t - prev_t > gap:
                seg = []
            seg.append((px(t), py(v)))
            prev_t = t
        if len(seg) > 1:
            d.line(seg, fill=col, width=2)
        elif len(seg) == 1:
            x, y = seg[0]
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=col)
        vals = [v for t, v in pts if now - t <= GRAPH_SPAN]
        if vals:
            cur = vals[-1]
            fmt = (lambda v: f"{v:.0f}") if live else (lambda v: f"{v:.0f}")
            stat = (f"今 {fmt(cur)}{unit}  最小 {fmt(min(vals))}  平均 {fmt(sum(vals) / len(vals))}"
                    f"  最大 {fmt(max(vals))}")
        else:
            stat = "データ待ち"
        d.text((4, BODY_BOTTOM - 13), stat, font=fs, fill=THEME["fg"])
        t = f"{note}・10分"
        d.text((316 - text_w(fs, t), BODY_BOTTOM - 13), t, font=fs, fill=THEME["dim"])


# ---- PC での確認用の疑似データ ----
def demo_runner():
    rnd = random.Random(7)
    base = [("Demo-Home", 2, 88, "WPA2", "*"), ("Demo-Home-WPA3", 2, 84, "WPA3", " "),
            ("Demo-Office", 6, 70, "WPA2 802.1X", " "), ("Demo-Guest", 6, 52, "", " "),
            ("Demo-Printer", 11, 45, "WPA2", " "), ("", 11, 38, "WPA2", " "),
            ("デモ_2階", 1, 63, "WPA1 WPA2", " "), ("Demo-Camera", 9, 30, "WEP", " "),
            ("Demo-IoT", 13, 25, "WPA2", " "), ("Demo-Far", 4, 15, "WPA2", " "),
            ("Demo-5G", 36, 60, "WPA2", " ")]
    t0 = time.time()
    def runner(_rescan: str):
        lines = []
        for i, (ssid, ch, s, sec, use) in enumerate(base):
            freq = 5000 + ch * 5 if ch > 14 else 2407 + ch * 5
            sig = max(5, min(100, int(s + 8 * math.sin((time.time() - t0) / 20 + i) + rnd.randint(-3, 3))))
            bssid = f"02\\:00\\:00\\:00\\:00\\:{i:02X}"
            lines.append(f"{use}:{bssid}:{ssid}:{ch}:{freq} MHz:130 Mbit/s:{sig}:{sec}:20 MHz")
        return 0, "\n".join(lines) + "\n", ""
    return runner


def main() -> None:
    ap = argparse.ArgumentParser(description="App07 Wi-Fi analyzer (CardputerZero)")
    ap.add_argument("--interval", type=float, default=10.0, help="スキャン間隔[秒]")
    ap.add_argument("--ifname", default="wlan0")
    ap.add_argument("--log-dir", default=os.path.expanduser("~/wifi_logs"))
    ap.add_argument("--demo", action="store_true", help="疑似データで動かす（PC での画面確認用）")
    ap.add_argument("--view", choices=VIEWS, default="LIST", help="起動時の画面")
    common_args(ap, "wifi")
    args = ap.parse_args()

    sc = Scanner(interval=args.interval, ifname=args.ifname,
                 runner=demo_runner() if args.demo else None)
    app = WifiApp(sc, args.log_dir)
    app.view = args.view
    sc.start()
    run(app, args)


if __name__ == "__main__":
    main()
