#!/usr/bin/env python3
"""App11 LAN スキャナー（CardputerZero・320×170 フレームバッファ UI）。

本機が接続しているネットワークの機器を探し、IP・MAC・メーカー・名前を一覧表示する。
選んだ機器は TCP の接続確認で開いているポートを調べられる。結果は ~/lan_scans/ に
JSON と CSV で保存し、同じネットワークの前回結果との差分（新しく見えた機器）を示す。
⚠️ 自分が管理するネットワークだけで使うこと（HANDOFF §7）。

画面: 開始（I/F 選択）→ 走査中 → 一覧 → 詳細
キー: F/X（↑↓）選択 / Enter 決定・ポート確認 / A 詳細で 1〜1024 番を確認 / R 再走査 /
      Esc 戻る（走査中は中止）/ S 画面保存 / Q 終了

使い方:
  python3 lan_scanner.py                       # 実機（ランチャーから起動）
  python3 lan_scanner.py --headless --script "1 enter; 20 shot /tmp/a.png; 21 quit"
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, "..", "..", "..", "shared"), os.path.join(_HERE, "..", "shared")):
    if os.path.isdir(p):
        sys.path.insert(0, os.path.abspath(p))
sys.path.insert(0, _HERE)

import netscan as ns  # noqa: E402
from fb_ui import KEY, THEME, common_args, font, footer, header, new_canvas, run, text_w, truncate  # noqa: E402

BODY_TOP, BODY_BOTTOM = 17, 156


def ip_sort_key(ip: str):
    return tuple(int(x) for x in ip.split("."))


class Scan:
    """1 回分の走査（背景スレッド）。UI は lock の下で属性を読む。"""

    def __init__(self, iface: dict, oui: ns.OUI, out_dir: str):
        self.iface = iface
        self.oui = oui
        self.out_dir = out_dir
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.phase = "準備"
        self.done = 0
        self.total = 1
        self.found = 0
        self.hosts: list[dict] = []
        self.network = ""
        self.narrowed = False
        self.new_keys: set[str] = set()
        self.gone: list[dict] = []
        self.path: str | None = None
        self.started = time.time()
        self.finished = False
        self.error = ""
        self.version = 0
        self.port_job: dict | None = None        # {"ip", "done", "total", "full"}

    def bump(self) -> None:
        self.version += 1

    def _progress(self, done: int, total: int, found: int) -> None:
        self.done, self.total, self.found = done, total, found
        self.bump()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"[:70]
        finally:
            self.finished = True
            self.bump()

    def _run(self) -> None:
        ifc = self.iface
        net, targets, self.narrowed = ns.scan_network(ifc["addr"], ifc["prefix"])
        self.network = str(net)
        self.phase = "ICMP"
        self.bump()
        rtt = ns.icmp_sweep(targets, progress=self._progress, stop=self.stop)
        if self.stop.is_set():
            return
        self.phase = "ARP"
        self.bump()
        time.sleep(0.8)
        neigh = ns.neighbors(ifc["ifname"])
        tset = set(targets)
        ips = set(rtt) | {ip for ip in neigh if ip in tset}
        hosts = []
        for ip in ips:
            mac = neigh.get(ip, "")
            hosts.append({"ip": ip, "mac": mac, "vendor": self.oui.vendor(mac),
                          "rtt_ms": rtt.get(ip), "via": "ICMP" if ip in rtt else "ARP",
                          "dns": "", "mdns": "", "ports": None})
        hosts.append({"ip": ifc["addr"], "mac": ifc.get("mac", ""), "vendor": self.oui.vendor(ifc.get("mac", "")),
                      "rtt_ms": 0.0, "via": "self", "dns": "", "mdns": "", "ports": None, "self": True})
        hosts.sort(key=lambda h: ip_sort_key(h["ip"]))
        for h in hosts:
            if h["ip"] == ifc.get("gateway"):
                h["gateway"] = True
        with self.lock:
            self.hosts = hosts
            self.found = len(hosts)
        self.phase = "名前"
        self.bump()
        others = [h["ip"] for h in hosts if not h.get("self")]
        dns = ns.reverse_dns(others)
        mdns = ns.mdns_names(others, ifc["addr"]) if not self.stop.is_set() else {}
        with self.lock:
            for h in self.hosts:
                h["dns"] = dns.get(h["ip"], "")
                h["mdns"] = mdns.get(h["ip"], "")
        self.phase = "保存"
        self.bump()
        result = self.result()
        prev = ns.load_previous(self.out_dir, self.network)
        self.new_keys, self.gone = ns.diff(prev, self.hosts)
        try:
            self.path = ns.save(self.out_dir, result)
        except OSError as e:
            self.error = f"保存失敗: {e}"[:70]
        self.phase = "完了"

    def result(self) -> dict:
        with self.lock:
            return {"time": self.started, "ifname": self.iface["ifname"], "network": self.network,
                    "self": {"ip": self.iface["addr"], "mac": self.iface.get("mac", "")},
                    "gateway": self.iface.get("gateway"), "hosts": [dict(h) for h in self.hosts]}

    def port_scan(self, ip: str, full: bool) -> None:
        ports = list(range(1, 1025)) if full else ns.QUICK_PORTS
        job = {"ip": ip, "done": 0, "total": len(ports), "full": full, "stop": threading.Event()}
        self.port_job = job

        def prog(done, total, _n):
            job["done"] = done
            self.bump()

        def work():
            opened = ns.tcp_scan(ip, ports, progress=prog, stop=job["stop"])
            if not job["stop"].is_set():
                with self.lock:
                    for h in self.hosts:
                        if h["ip"] == ip:
                            h["ports"] = opened
                            h["ports_range"] = "1-1024" if full else "quick"
                if self.path:
                    try:
                        ns.save(self.out_dir, self.result(), self.path)
                    except OSError:
                        pass
            if self.port_job is job:
                self.port_job = None
            self.bump()

        threading.Thread(target=work, daemon=True).start()


class LanApp:
    def __init__(self, out_dir: str, oui: ns.OUI):
        self.out_dir = out_dir
        self.oui = oui
        self.view = "HOME"
        self.ifaces: list[dict] = []
        self.if_sel = 0
        self.scan: Scan | None = None
        self.sel = 0
        self.top = 0
        self.seen = -1
        self.last_clock = 0
        self.refresh_ifaces()

    def refresh_ifaces(self) -> None:
        self.prev_cache: dict = {}
        try:
            self.ifaces = ns.interfaces()
        except Exception:  # noqa: BLE001
            self.ifaces = []
        self.if_sel = min(self.if_sel, max(0, len(self.ifaces) - 1))

    def start_scan(self) -> None:
        if not self.ifaces:
            return
        self.cancel()
        self.scan = Scan(self.ifaces[self.if_sel], self.oui, self.out_dir)
        threading.Thread(target=self.scan.run, daemon=True).start()
        self.view = "SCAN"
        self.sel = self.top = 0

    def cancel(self) -> None:
        if self.scan:
            self.scan.stop.set()
            if self.scan.port_job:
                self.scan.port_job["stop"].set()

    def hosts(self) -> list[dict]:
        if not self.scan:
            return []
        with self.scan.lock:
            return list(self.scan.hosts)

    # ---- fb_ui から呼ばれる ----
    def on_key(self, code: int, repeat: bool):
        up, down = code == KEY["up"], code == KEY["down"]
        if self.view == "HOME":
            if up or down:
                if self.ifaces:
                    self.if_sel = (self.if_sel + (1 if down else -1)) % len(self.ifaces)
                return True
            if repeat:
                return False
            if code == KEY["enter"]:
                self.start_scan()
            elif code == KEY["r"]:
                self.refresh_ifaces()
            else:
                return False
            return True
        if self.view == "SCAN":
            if code == KEY["esc"] and not repeat:
                self.cancel()
                self.view = "LIST" if self.hosts() else "HOME"
                return True
            return False
        hosts = self.hosts()
        if up or down:
            if hosts:
                self.sel = min(max(self.sel + (1 if down else -1), 0), len(hosts) - 1)
            return True
        if repeat:
            return False
        if self.view == "LIST":
            if code == KEY["enter"] and hosts:
                self.view = "DETAIL"
            elif code == KEY["r"]:
                self.start_scan()
            elif code == KEY["esc"]:
                self.refresh_ifaces()
                self.view = "HOME"
            else:
                return False
            return True
        if self.view == "DETAIL":
            busy = self.scan and self.scan.port_job
            if code in (KEY["enter"], KEY["a"]) and hosts and not busy:
                self.scan.port_scan(hosts[self.sel]["ip"], full=code == KEY["a"])
            elif code == KEY["esc"]:
                if busy:
                    self.scan.port_job["stop"].set()
                else:
                    self.view = "LIST"
            else:
                return False
            return True
        return False

    def tick(self) -> bool:
        dirty = False
        if self.scan and self.scan.version != self.seen:
            self.seen = self.scan.version
            dirty = True
            if self.view == "SCAN" and self.scan.finished:
                self.view = "LIST"
        sec = int(time.time())
        if sec != self.last_clock:
            self.last_clock = sec
            dirty = True
        return dirty

    def close(self) -> None:
        self.cancel()

    # ---- 描画 ----
    def render(self) -> Image.Image:
        img, d = new_canvas()
        getattr(self, "draw_" + self.view.lower())(d)
        return img

    def draw_home(self, d: ImageDraw.ImageDraw) -> None:
        header(d, "LAN スキャナー", time.strftime("%H:%M:%S"))
        fs, fm, fb = font(11), font(11, "mono"), font(12, "bold")
        y = BODY_TOP + 2
        d.text((6, y), "調べるネットワーク", font=fs, fill=THEME["dim"])
        y += 16
        if not self.ifaces:
            d.text((10, y + 4), "接続中のネットワークがありません（R で再読込）", font=fs, fill=THEME["warn"])
        for i, it in enumerate(self.ifaces[:4]):
            net, _t, narrowed = ns.scan_network(it["addr"], it["prefix"])
            if i == self.if_sel:
                d.rectangle((2, y - 1, 317, y + 26), fill=THEME["sel"])
            d.text((8, y), f'{it["ifname"]}', font=fb, fill=THEME["accent"])
            d.text((70, y + 1), f'{it["addr"]}/{it["prefix"]}', font=fm, fill=THEME["fg"])
            sub = f'対象 {net}（{net.num_addresses - 2} 台分）' + ("・/24 に絞り込み" if narrowed else "")
            d.text((70, y + 14), sub, font=font(10), fill=THEME["dim"])
            if it.get("gateway"):
                gw = f'GW {it["gateway"]}'
                d.text((314 - text_w(fm, gw), y + 1), gw, font=fm, fill=THEME["dim"])
            y += 30
        warn = "⚠ 自分が管理するネットワークだけで使ってください"
        d.text((6, BODY_BOTTOM - 30), warn, font=font(11), fill=THEME["warn"])
        prev = None
        if self.ifaces:
            it = self.ifaces[self.if_sel]
            net, _t, _n = ns.scan_network(it["addr"], it["prefix"])
            if str(net) not in self.prev_cache:              # 毎秒の再描画でファイルを読み直さない
                self.prev_cache[str(net)] = ns.load_previous(self.out_dir, str(net))
            prev = self.prev_cache[str(net)]
        if prev:
            t = time.strftime("%m/%d %H:%M", time.localtime(prev.get("time", 0)))
            d.text((6, BODY_BOTTOM - 15), f'前回 {t}・{len(prev.get("hosts", []))} 台', font=font(10),
                   fill=THEME["dim"])
        footer(d, "F/X 選択  Enter 走査開始  R 再読込  Q 終了")

    def draw_scan(self, d: ImageDraw.ImageDraw) -> None:
        sc = self.scan
        header(d, "走査中", f"{time.time() - sc.started:4.0f}s")
        fs, fb = font(12), font(16, "bold")
        d.text((10, BODY_TOP + 8), sc.network or sc.iface["addr"], font=fb, fill=THEME["fg"])
        steps = ["ICMP", "ARP", "名前", "保存"]
        x = 10
        for s in steps:
            cur = s == sc.phase
            past = steps.index(s) < steps.index(sc.phase) if sc.phase in steps else False
            col = THEME["accent"] if cur else THEME["good"] if past else THEME["dim"]
            d.text((x, BODY_TOP + 36), s, font=fs, fill=col)
            x += text_w(fs, s) + 18
        frac = sc.done / max(1, sc.total) if sc.phase == "ICMP" else 1.0
        d.rectangle((10, BODY_TOP + 60, 310, BODY_TOP + 72), outline=THEME["line"])
        d.rectangle((11, BODY_TOP + 61, 11 + int(298 * frac), BODY_TOP + 71), fill=THEME["accent"])
        d.text((10, BODY_TOP + 80), f"見つかった機器 {sc.found} 台", font=fs, fill=THEME["fg"])
        if sc.error:
            d.text((10, BODY_TOP + 100), sc.error, font=font(10), fill=THEME["bad"])
        footer(d, "Esc 中止")

    def label(self, h: dict) -> str:
        return h.get("mdns") or h.get("dns") or h.get("vendor") or ""

    def draw_list(self, d: ImageDraw.ImageDraw) -> None:
        sc = self.scan
        hosts = self.hosts()
        right = ""
        if sc.new_keys or sc.gone:
            right = f"+{len(sc.new_keys)} -{len(sc.gone)}"
        header(d, f"{sc.network}  {len(hosts)} 台", right)
        row_h, rows = 15, 9
        if not hosts:
            d.text((10, 60), "機器が見つかりません", font=font(13), fill=THEME["dim"])
        self.sel = min(self.sel, max(0, len(hosts) - 1))
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        fm, fs = font(11, "mono"), font(11)
        for k, h in enumerate(hosts[self.top:self.top + rows]):
            i = self.top + k
            y = BODY_TOP + 2 + k * row_h
            if i == self.sel:
                d.rectangle((0, y - 1, 319, y + row_h - 2), fill=THEME["sel"])
            is_new = ns.host_key(h) in sc.new_keys
            if is_new:
                d.ellipse((2, y + 4, 7, y + 9), fill=THEME["new"])
            d.text((10, y), h["ip"].rjust(15), font=fm, fill=THEME["fg"])
            tag = "自分" if h.get("self") else "GW" if h.get("gateway") else ""
            x = 122
            if tag:
                d.text((x, y - 1), tag, font=fs, fill=THEME["accent"])
                x += text_w(fs, tag) + 6
            if h.get("ports"):
                pt = f'{len(h["ports"])}p'
                d.text((316 - text_w(fm, pt), y), pt, font=fm, fill=THEME["warn"])
            name = self.label(h)
            if h.get("via") == "ARP":
                name = (name + " ") if name else ""
                name += "(ARP)"
            col = THEME["fg"] if (h.get("mdns") or h.get("dns")) else THEME["dim"]
            d.text((x, y - 1), truncate(fs, name, 300 - x), font=fs, fill=col)
        msg = sc.error or ("保存: " + os.path.basename(sc.path) if sc.path else "")
        footer(d, msg if msg and sc.phase == "完了" and time.time() - sc.started < 30
               else "F/X 選択  Enter 詳細  R 再走査  Esc 戻る  ●=前回から新規")

    def draw_detail(self, d: ImageDraw.ImageDraw) -> None:
        sc = self.scan
        hosts = self.hosts()
        if not hosts:
            self.view = "LIST"
            return self.draw_list(d)
        h = hosts[min(self.sel, len(hosts) - 1)]
        header(d, h["ip"], f"{self.sel + 1}/{len(hosts)}")
        fs, fm = font(11), font(11, "mono")
        y = BODY_TOP + 2
        def row(label: str, value: str, mono: bool = False, col=None) -> None:
            nonlocal y
            d.text((6, y), label, font=fs, fill=THEME["dim"])
            f = fm if mono else fs
            d.text((52, y + (1 if mono else 0)), truncate(f, value or "—", 262), font=f,
                   fill=col or THEME["fg"])
            y += 15
        tags = []
        if h.get("self"):
            tags.append("本機")
        if h.get("gateway"):
            tags.append("ゲートウェイ")
        if ns.host_key(h) in sc.new_keys:
            tags.append("前回から新規")
        row("MAC", h.get("mac", ""), mono=True)
        row("メーカー", h.get("vendor", ""))
        row("mDNS", h.get("mdns", ""))
        row("DNS", h.get("dns", ""))
        rtt = "—" if h.get("rtt_ms") is None else f'{h["rtt_ms"]:.1f} ms'
        via = {"ICMP": "ICMP 応答", "ARP": "ARP のみ（ICMP 無応答）", "self": "本機"}.get(h.get("via"), "")
        row("応答", f"{rtt}  {via}" + ("  " + "・".join(tags) if tags else ""))
        job = sc.port_job
        d.line((4, y + 1, 316, y + 1), fill=THEME["line"])
        y += 4
        if job and job["ip"] == h["ip"]:
            frac = job["done"] / max(1, job["total"])
            d.text((6, y), f'ポート確認中 {job["done"]}/{job["total"]}', font=fs, fill=THEME["accent"])
            d.rectangle((150, y + 4, 314, y + 11), outline=THEME["line"])
            d.rectangle((151, y + 5, 151 + int(162 * frac), y + 10), fill=THEME["accent"])
        elif h.get("ports") is None:
            d.text((6, y), "ポート: Enter で主要ポート / A で 1〜1024 番を確認", font=fs, fill=THEME["dim"])
        elif not h["ports"]:
            rng = "1〜1024 番" if h.get("ports_range") == "1-1024" else "主要ポート"
            d.text((6, y), f"開いているポートなし（{rng}）", font=fs, fill=THEME["dim"])
        else:
            items = [f"{p}" + (f" {ns.service_name(p)}" if ns.service_name(p) else "") for p in h["ports"]]
            line, lines = "", []
            for it in items:
                cand = (line + "  " + it) if line else it
                if text_w(fm, cand) > 308:
                    lines.append(line)
                    line = it
                else:
                    line = cand
            lines.append(line)
            for ln in lines[: max(1, (BODY_BOTTOM - y) // 13)]:
                d.text((6, y), ln, font=fm, fill=THEME["warn"])
                y += 13
        footer(d, "Esc 中止" if job else "F/X 前後の機器  Enter 主要ポート  A 1〜1024  Esc 一覧")


def main() -> None:
    ap = argparse.ArgumentParser(description="App11 LAN scanner (CardputerZero)")
    ap.add_argument("--out-dir", default=os.path.expanduser("~/lan_scans"))
    ap.add_argument("--oui", default=None, help="OUI 表（既定: data/oui.tsv.gz）")
    ap.add_argument("--auto", action="store_true", help="起動と同時に最初の I/F を走査")
    common_args(ap, "lan")
    args = ap.parse_args()

    oui_path = args.oui
    if oui_path is None:
        for p in (os.path.join(_HERE, "..", "data", "oui.tsv.gz"), os.path.join(_HERE, "data", "oui.tsv.gz")):
            if os.path.exists(p):
                oui_path = p
                break
    app = LanApp(args.out_dir, ns.OUI(oui_path))
    if args.auto:
        app.start_scan()
    run(app, args)


if __name__ == "__main__":
    main()
