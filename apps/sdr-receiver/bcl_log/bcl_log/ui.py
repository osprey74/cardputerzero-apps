"""App 10 BCL ログモード オンデバイス UI（pygame / 320×170）。

CardputerZero / uConsole の LCD 実解像度 320×170 に描く BCL 受信ログの操作 UI。
入力は CoreS3 の Chain Encoder（`shared/cores3_bridge` 経由・USB CDC）、無い環境では
キーボードでフォールバック。既存の機種非依存ロジック（`stations`/`markdown_template`/
`upnote`/`config`）を駆動する。

フロー（スケルトン）:
  STATION → FREQ → SINPO → CONFIRM → DONE
  ノブA(赤 role=R): 回転=選択移動 / 押下=次へ。 ノブB(青 role=B): 回転=値変更。
  キーボード: ↑↓=A回転 / ←→=B回転 / Enter=A押下 / Backspace=戻る / Esc=終了。

UpNote への実投稿は既定で **dry-run**（ノートを組み立てて表示するだけ）。実際に投稿するには
環境変数 `BCL_DISPATCH=1`（Tailscale + Mac Mini + config 必須）。

使い方:
  python3 -m bcl_log.ui                         # 実画面（要 DISPLAY）・自動でエンコーダ検出
  python3 -m bcl_log.ui --port /dev/ttyACM1     # CoreS3 ポート指定
  python3 -m bcl_log.ui --no-sensor             # キーボードのみ
  SDL_VIDEODRIVER=dummy python3 -m bcl_log.ui --screenshot out.png   # ヘッドレス 1 枚
"""
from __future__ import annotations

import argparse
import glob
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pygame

# リポジトリルートを import パスに追加（shared.cores3_bridge を使うため）。
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from . import config as cfg          # noqa: E402
from . import markdown_template as mdt  # noqa: E402
from . import sdr                     # noqa: E402
from . import stations as sdb        # noqa: E402
from . import upnote as un           # noqa: E402

W, H = 320, 170  # CardputerZero LCD 実解像度（厳守）

BG = (16, 20, 24)
FG = (215, 215, 215)
DIM = (120, 140, 160)
ACCENT = (79, 195, 247)
HI = (255, 200, 80)
OK = (120, 220, 150)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIONS_PATH = PROJECT_ROOT / "data" / "bcl_stations.yaml"

STATES = ["RX", "STATION", "FREQ", "SINPO", "CONFIRM", "DONE"]
SINPO_LABELS = ["S", "I", "N", "P", "O"]


def find_cores3_port() -> str:
    """/dev/serial/by-id から CoreS3(Espressif) を探す。無ければ既定を返す。"""
    for link in glob.glob("/dev/serial/by-id/*Espressif*"):
        try:
            return os.path.realpath(link)
        except OSError:
            pass
    return "/dev/ttyACM0"


class EncoderState:
    """バックグラウンドで CoreS3 を読み、各エンコーダの cnt/pressed を保持する。"""

    def __init__(self, port: str):
        self.port = port
        self.lock = threading.Lock()
        self.cnt = {"R": 0, "B": 0}
        self.pressed = {"R": False, "B": False}
        self.ncir_obj = None
        self.ok = False
        self.err = None
        self._stop = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            from shared.cores3_bridge.reader import CoreS3Reader
        except Exception as e:  # noqa: BLE001
            self.err = "cores3_bridge import 失敗: %s" % e
            return
        try:
            with CoreS3Reader(port=self.port) as r:
                self.ok = True
                for frame in r.frames():
                    if self._stop:
                        break
                    with self.lock:
                        for e in frame.encoders:
                            if e.role in self.cnt:
                                self.cnt[e.role] = e.cnt
                                self.pressed[e.role] = bool(e.pressed)
                        if frame.ncir:
                            self.ncir_obj = frame.ncir.t_obj
        except Exception as e:  # noqa: BLE001
            self.err = "serial: %s" % e
            self.ok = False

    def snapshot(self):
        with self.lock:
            return dict(self.cnt), dict(self.pressed), self.ncir_obj


class BclUI:
    def __init__(self, enc: EncoderState, rx: "sdr.Receiver"):
        self.enc = enc
        self.rx = rx
        self.stations = sdb.load(STATIONS_PATH)
        self.state = 0            # index into STATES
        self.sta_idx = 0          # 選択中の局
        self.freq_idx = 0         # 選択中の周波数
        self.sinpo = [3, 3, 3, 3, 3]
        self.sinpo_cur = 0        # 編集中の SINPO 桁
        self.note_title = ""
        self.msg = ""
        # 入力エッジ検出用
        self._prev = {"R": None, "B": None}
        self._prev_btn = {"R": False, "B": False}
        self._last_press = 0.0    # ボタンデバウンス（チャタリングで二重トグル防止）

    # --- 入力（エンコーダ差分 + ボタンエッジ）→ 抽象イベント ---
    def poll_encoder(self):
        cnt, pressed, _ = self.enc.snapshot()
        a_rot = b_rot = 0
        a_press = b_press = False
        for role in ("R", "B"):
            if self._prev[role] is None:
                self._prev[role] = cnt[role]
            d = cnt[role] - self._prev[role]
            self._prev[role] = cnt[role]
            if role == "R":
                a_rot += d
            else:
                b_rot += d
            if pressed[role] and not self._prev_btn[role]:
                if role == "R":
                    a_press = True
                else:
                    b_press = True
            self._prev_btn[role] = pressed[role]
        # デバウンス: 直近 0.30s 以内の押下は無視（チャタリングによる二重トグル防止）
        if a_press or b_press:
            now = time.monotonic()
            if now - self._last_press < 0.30:
                a_press = b_press = False
            else:
                self._last_press = now
        return a_rot, b_rot, a_press, b_press

    # --- キーボードイベント → 抽象イベント ---
    def handle_key(self, key):
        if key in (pygame.K_UP, pygame.K_DOWN):
            self.on_a_rot(1 if key == pygame.K_UP else -1)
        elif key in (pygame.K_RIGHT, pygame.K_LEFT):
            self.on_b_rot(1 if key == pygame.K_RIGHT else -1)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self.on_a_press()
        elif key == pygame.K_r:
            self.on_b_press()
        elif key == pygame.K_BACKSPACE:
            self.state = max(0, self.state - 1)

    # --- 抽象イベントの適用 ---
    def on_a_rot(self, steps):
        if steps == 0:
            return
        st = STATES[self.state]
        if st == "RX":
            self.rx.tune(steps)
        elif st == "STATION" and self.stations:
            self.sta_idx = (self.sta_idx + steps) % len(self.stations)
            self.freq_idx = 0
        elif st == "FREQ":
            n = max(1, len(self._freqs()))
            self.freq_idx = (self.freq_idx + steps) % n
        elif st == "SINPO":
            self.sinpo_cur = (self.sinpo_cur + steps) % 5

    def on_b_rot(self, steps):
        if steps == 0:
            return
        st = STATES[self.state]
        if st == "RX":
            self.rx.set_band(steps)
        elif st == "SINPO":
            v = self.sinpo[self.sinpo_cur] + steps
            self.sinpo[self.sinpo_cur] = max(1, min(5, v))

    def on_a_press(self):
        st = STATES[self.state]
        if st == "RX":
            self._prefilter_station()
            self.state += 1
        elif st == "CONFIRM":
            self._build_note()
            self.state = STATES.index("DONE")
        elif st == "DONE":
            self.state = 0
            self.msg = ""
        else:
            self.state = min(len(STATES) - 1, self.state + 1)

    def on_b_press(self):
        # 青ノブ押下: RX 画面では受信 ON/OFF トグル。
        if STATES[self.state] == "RX":
            self.rx.toggle()

    def _prefilter_station(self):
        """受信中周波数に一致する既知局があれば局選択をそこに合わせる。"""
        cand = sdb.candidates(self.stations, self.rx.freq_khz,
                              tolerance_khz=max(10, self.rx.step_khz * 2))
        if cand:
            self.sta_idx = self.stations.index(cand[0])
            self.freq_idx = 0

    # --- ヘルパ ---
    def _station(self):
        return self.stations[self.sta_idx] if self.stations else None

    def _freqs(self):
        s = self._station()
        return s.frequencies if s else []

    def _freq(self):
        fl = self._freqs()
        return fl[self.freq_idx] if fl else {}

    def _sinpo_str(self):
        return "".join(str(d) for d in self.sinpo)

    def _build_note(self):
        s = self._station()
        f = self._freq()
        conf = {}
        try:
            conf = cfg.load()
        except Exception:  # noqa: BLE001
            conf = {}
        loc = (conf.get("default_location") or {}) if isinstance(conf, dict) else {}
        entry = mdt.LogEntry(
            receiver=loc.get("receiver", "RTL-SDR Blog V4"),
            antenna=loc.get("antenna", "15m ロングワイヤー"),
            location_name=loc.get("name", "札幌市"),
            location_lat=loc.get("lat"),
            location_lng=loc.get("lng"),
            sfi=None, k_index=None, a_index=None, propagation_fetched_utc=None,
            freq_khz=float(f.get("freq_khz", 0)),
            band=f.get("band", "?"),
            received_at=datetime.now(),
            mode="AM",
            station_name=s.name if s else "?",
            country=s.country if s else None,
            languages=s.languages if s else [],
            transmitter_site=s.transmitter_site if s else None,
            power_kw=s.power_kw if s else None,
            sinpo=self._sinpo_str(),
        )
        self.note_title = mdt.title_for(entry)
        body = mdt.render(entry)
        if os.environ.get("BCL_DISPATCH") == "1":
            try:
                mm = (cfg.load() or {}).get("mac_mini", {})
                url = un.build_url(title=self.note_title, body=body,
                                   notebook=mm.get("notebook", "BCL_LogBook"), tag="BCL")
                un.dispatch(url, mm.get("host"), mm.get("user"))
                self.msg = "dispatched to UpNote"
            except Exception as e:  # noqa: BLE001
                self.msg = "dispatch failed: %s" % e
        else:
            self.msg = "dry-run (BCL_DISPATCH=1 で実投稿)"


# ---------- 描画 ----------

TB = (26, 32, 38)  # タイトルバー背景

# CJK（日本語）対応フォントを探す。局名等が日本語のため必須。無ければ既定へフォールバック。
_CJK_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]


def _find_font_path():
    for p in _CJK_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


_FONT_PATH = _find_font_path()
_FONT_CACHE = {}


def _font(size):
    f = _FONT_CACHE.get(size)
    if f is None:
        f = pygame.font.Font(_FONT_PATH, size)
        _FONT_CACHE[size] = f
    return f


def _text(surf, x, y, s, color=FG, size=16, bg=BG):
    # 不透明背景でレンダリング: AA を保ちつつ SDL1.2/dummy でアルファが落ちて
    # 「文字色ベタ塗り」になるバグを回避する（bg はその場の下地色を渡す）。
    surf.blit(_font(size).render(s, True, color, bg), (x, y))


def draw(surf, ui: BclUI):
    surf.fill(BG)
    st = STATES[ui.state]
    # タイトルバー
    pygame.draw.rect(surf, TB, pygame.Rect(0, 0, W, 20))
    _text(surf, 4, 3, "BCL LOG", ACCENT, 18, TB)
    _text(surf, 150, 5, "%d/%d %s" % (ui.state + 1, len(STATES), st), DIM, 14, TB)

    s = ui._station()
    f = ui._freq()

    if st == "RX":
        r = ui.rx
        _text(surf, 6, 28, "RECEIVE  (A=tune  B=band)", DIM, 14)
        _text(surf, 10, 48, "%s   %s" % (r.band[0], r.mode), ACCENT, 16)
        _text(surf, 10, 70, r.freq_label(), FG, 26)
        if not sdr.available():
            _text(surf, 10, 104, "rtl_fm/aplay not found", (230, 120, 120), 14)
        else:
            on = r.running
            _text(surf, 10, 104,
                  "RX " + ("ON " if on else "OFF") + " (B press: "
                  + ("stop)" if on else "start)"), OK if on else DIM, 15)
        _text(surf, 10, 126, "A press: to log", DIM, 13)
    elif st == "STATION":
        _text(surf, 6, 28, "Select station (knob A)", DIM, 14)
        for i in range(max(0, ui.sta_idx - 1), min(len(ui.stations), ui.sta_idx + 3)):
            y = 46 + (i - max(0, ui.sta_idx - 1)) * 18
            sel = i == ui.sta_idx
            _text(surf, 10, y, ("> " if sel else "  ") + ui.stations[i].name,
                  HI if sel else FG, 16)
    elif st == "FREQ":
        _text(surf, 6, 28, s.name if s else "?", ACCENT, 16)
        _text(surf, 6, 48, "Select frequency (knob A)", DIM, 14)
        fl = ui._freqs()
        for i, fr in enumerate(fl[:5]):
            y = 66 + i * 16
            sel = i == ui.freq_idx
            _text(surf, 10, y, ("> " if sel else "  ")
                  + "%d kHz %s" % (fr.get("freq_khz", 0), fr.get("band", "")),
                  HI if sel else FG, 15)
    elif st == "SINPO":
        _text(surf, 6, 28, "SINPO  (A=digit  B=value)", DIM, 14)
        for i, lab in enumerate(SINPO_LABELS):
            x = 20 + i * 56
            cur = i == ui.sinpo_cur
            _text(surf, x, 60, lab, DIM, 16)
            pygame.draw.rect(surf, HI if cur else (40, 48, 56),
                             pygame.Rect(x - 4, 78, 34, 34), 0 if cur else 1)
            _text(surf, x + 6, 84, str(ui.sinpo[i]), BG if cur else FG, 24,
                  HI if cur else BG)
    elif st == "CONFIRM":
        _text(surf, 6, 30, s.name if s else "?", ACCENT, 16)
        _text(surf, 6, 50, "%d kHz %s" % (f.get("freq_khz", 0), f.get("band", "")), FG, 15)
        _text(surf, 6, 68, "SINPO %s" % ui._sinpo_str(), FG, 15)
        _text(surf, 6, 90, "Press knob A to log", OK, 15)
    elif st == "DONE":
        _text(surf, 6, 34, "LOGGED", OK, 24)
        _text(surf, 6, 62, ui.note_title[:40], FG, 14)
        _text(surf, 6, 80, ui.msg[:44], DIM, 13)
        _text(surf, 6, 120, "knob A: new entry", DIM, 13)

    # フッタ（ライブ状態）
    cnt, pressed, ncir = ui.enc.snapshot()
    src = "ENC" if ui.enc.ok else ("KEY" if ui.enc.err else "...")
    foot = "%s A:%d B:%d" % (src, cnt["R"], cnt["B"])
    if ncir is not None:
        foot += "  %.1fC" % ncir
    _text(surf, 4, H - 15, foot, DIM, 13)


_STOP = False


def _on_signal(signum, frame):
    global _STOP
    _STOP = True


def run(args):
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    pygame.init()
    pygame.display.set_caption("BCL Log")
    screen = pygame.display.set_mode((W, H))

    enc = EncoderState(args.port or find_cores3_port())
    if not args.no_sensor:
        enc.start()

    rx = sdr.Receiver()
    ui = BclUI(enc, rx)
    clock = pygame.time.Clock()

    if args.screenshot:
        ui.state = max(0, min(len(STATES) - 1, args.state))
        draw(screen, ui)
        pygame.display.flip()
        pygame.image.save(screen, args.screenshot)
        print("screenshot -> %s" % args.screenshot, file=sys.stderr)
        return

    try:
        while not _STOP:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return
                    else:
                        ui.handle_key(ev.key)
            if not args.no_sensor:
                a_rot, b_rot, a_press, b_press = ui.poll_encoder()
                if a_rot:
                    ui.on_a_rot(a_rot)
                if b_rot:
                    ui.on_b_rot(b_rot)
                if a_press:
                    ui.on_a_press()
                if b_press:
                    ui.on_b_press()
            draw(screen, ui)
            pygame.display.flip()
            clock.tick(30)
    finally:
        rx.stop()          # 受信中の rtl_fm/aplay を確実に停止（孤児化防止）
        pygame.quit()


def main():
    ap = argparse.ArgumentParser(description="App10 BCL log on-device UI (pygame, 320x170)")
    ap.add_argument("--port", default=None, help="CoreS3 シリアルポート（既定=自動検出）")
    ap.add_argument("--no-sensor", action="store_true", help="エンコーダを使わずキーボードのみ")
    ap.add_argument("--screenshot", default=None, help="1 フレーム描いて PNG 保存し終了")
    ap.add_argument("--state", type=int, default=0, help="screenshot 用に表示する状態 index (0-4)")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
