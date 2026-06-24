#!/usr/bin/env python3
"""uconsole_battery_hud — floating accurate battery indicator (HUD style).

LXPanel が XEmbed トレイ (`_NET_SYSTEM_TRAY_S0`) も SNI ホストも持たないため
通常のトレイインジケータは表示できない。代替として、画面隅に常駐する
小型 GTK ウィンドウとして実装する。

- フレームレス・常時最前面・タスクバー / ページャ非表示
- 30 秒ごとに OCV テーブルで再計算した SoC を表示
- 残量に応じて色変化（緑 / 黄 / 赤）
- 右クリックで Refresh / Move (4 隅) / Quit メニュー

位置はデフォルト右上。`--position {top-right,top-left,bottom-right,bottom-left}`
で起動時指定、または右クリックメニューから随時変更可能。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

REFRESH_INTERVAL_SEC = 30
MARGIN_PX = 6

CSS = b"""
#hud-window { background: rgba(0,0,0,0.78); border-radius: 8px; }
#hud-label  { color: #eee; font-family: monospace; font-size: 10pt; padding: 4px 10px; }
"""

POSITIONS = ("top-right", "top-left", "bottom-right", "bottom-left")


def gather() -> dict:
    out = subprocess.run(
        ["/usr/local/bin/uconsole_battery", "--json"],
        capture_output=True, text=True, timeout=5, check=True,
    )
    return json.loads(out.stdout)


def _format_eta(minutes: float) -> str:
    if minutes < 0:
        return ""
    h, m = int(minutes // 60), int(minutes % 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


class BatteryHUD:
    def __init__(self, position: str = "top-right") -> None:
        self.position = position if position in POSITIONS else "top-right"

        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_name("hud-window")
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_accept_focus(False)
        self.window.set_resizable(False)
        self.window.set_app_paintable(True)

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)

        self.label = Gtk.Label()
        self.label.set_name("hud-label")
        self.label.set_use_markup(True)
        self.window.add(self.label)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.window.add_events(0)  # ensure event mask defaults
        self.window.connect("button-press-event", self._on_button)

        self.window.show_all()
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_INTERVAL_SEC, self._on_timer)

    def _reposition(self) -> bool:
        # メニューバー (strut) を除いた作業領域に配置
        display = self.window.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is not None:
            wa = monitor.get_workarea()
            ax, ay, aw, ah = wa.x, wa.y, wa.width, wa.height
        else:
            screen = self.window.get_screen()
            ax, ay = 0, 0
            aw, ah = screen.get_width(), screen.get_height()

        ww, wh = self.window.get_size()
        if self.position == "top-right":
            x, y = ax + aw - ww - MARGIN_PX, ay + MARGIN_PX
        elif self.position == "top-left":
            x, y = ax + MARGIN_PX, ay + MARGIN_PX
        elif self.position == "bottom-right":
            x, y = ax + aw - ww - MARGIN_PX, ay + ah - wh - MARGIN_PX
        else:  # bottom-left
            x, y = ax + MARGIN_PX, ay + ah - wh - MARGIN_PX
        self.window.move(x, y)
        return False

    def refresh(self) -> None:
        try:
            data = gather()
        except Exception as e:
            self.label.set_markup(
                f"<span foreground='#FF5555'>BAT ERR</span> "
                f"<span foreground='#888'>{e}</span>"
            )
            GLib.idle_add(self._reposition)
            return

        percent = data["percent"]
        voltage = data["voltage_v"]
        power = data["power_w"]
        status = data["status"]
        eta = data.get("eta_min")

        if percent >= 50:
            color = "#7CFC00"
        elif percent >= 20:
            color = "#FFD54F"
        else:
            color = "#FF5252"

        prefix = "⚡ " if status == "Charging" else ""
        eta_str = ""
        if eta is not None and status == "Discharging":
            es = _format_eta(eta)
            if es:
                eta_str = f"  {es}"

        self.label.set_markup(
            f"<span foreground='{color}'><b>{prefix}{percent:.0f}%</b></span>"
            f"<span foreground='#aaa'>  {voltage:.2f}V {power:+.1f}W{eta_str}</span>"
        )
        GLib.idle_add(self._reposition)

    def _on_timer(self) -> bool:
        self.refresh()
        return True

    def _on_button(self, _widget: Gtk.Widget, event) -> None:
        if event.button == 3:  # right
            menu = Gtk.Menu()

            item_refresh = Gtk.MenuItem(label="Refresh")
            item_refresh.connect("activate", lambda *_: self.refresh())
            menu.append(item_refresh)

            menu.append(Gtk.SeparatorMenuItem())
            for pos in POSITIONS:
                mi = Gtk.MenuItem(label=f"Move to {pos}")
                mi.connect("activate", lambda _w, p=pos: self._set_position(p))
                menu.append(mi)

            menu.append(Gtk.SeparatorMenuItem())
            item_quit = Gtk.MenuItem(label="Quit")
            item_quit.connect("activate", lambda *_: Gtk.main_quit())
            menu.append(item_quit)

            menu.show_all()
            menu.popup_at_pointer(event)

    def _set_position(self, pos: str) -> None:
        self.position = pos
        self._reposition()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="uconsole_battery_hud")
    parser.add_argument(
        "--position", choices=POSITIONS, default="top-right",
        help="HUD の初期位置 (デフォルト: top-right)",
    )
    args = parser.parse_args(argv)

    BatteryHUD(position=args.position)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
