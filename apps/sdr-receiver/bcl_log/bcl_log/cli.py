"""Terminal UI entry point for App 10 BCL ログモード (uConsole 先行構築版)."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import config as cfg
from . import markdown_template as mdt
from . import pending as pq
from . import ssh_target as sshr
from . import stations as sdb
from . import upnote as un


console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIONS_PATH = PROJECT_ROOT / "data" / "bcl_stations.yaml"


def _band_for(freq_khz: float) -> str:
    if 526.5 <= freq_khz <= 1606.5:
        return "中波"
    if 2300 <= freq_khz <= 30000:
        return "短波"
    if 87500 <= freq_khz <= 108000:
        return "FM"
    if 118000 <= freq_khz <= 137000:
        return "航空 VHF"
    if 137000 <= freq_khz <= 174000:
        return "VHF 業務"
    return "その他"


def _ask_freq() -> float:
    while True:
        raw = Prompt.ask("[bold]周波数 (kHz)[/bold]")
        try:
            return float(raw)
        except ValueError:
            console.print("[red]数値を入力してください[/red]")


def _ask_choice(label: str, options: List[str], default: int = 1) -> int:
    for i, opt in enumerate(options, 1):
        console.print(f"  [{i}] {opt}")
    while True:
        raw = Prompt.ask(label, default=str(default))
        try:
            idx = int(raw)
        except ValueError:
            console.print("[red]番号を入力してください[/red]")
            continue
        if 1 <= idx <= len(options):
            return idx
        console.print("[red]範囲外です[/red]")


def _ask_sinpo() -> str:
    while True:
        raw = Prompt.ask("[bold]SINPO[/bold] (5 桁、例 45433)")
        if len(raw) == 5 and all(c in "12345" for c in raw):
            return raw
        console.print("[red]各桁 1-5 の 5 桁数字を入力してください[/red]")


def _select_station(stations: List[sdb.Station], freq_khz: float) -> Optional[sdb.Station]:
    matches = sdb.candidates(stations, freq_khz, tolerance_khz=10.0)
    if not matches:
        console.print(f"[yellow]既知局 DB に {int(freq_khz)} kHz 近傍の局なし → 手動入力に切替[/yellow]")
        return None
    table = Table(title=f"候補局 ({int(freq_khz)} kHz ±10)")
    table.add_column("#", justify="right")
    table.add_column("局名")
    table.add_column("国")
    table.add_column("出力")
    for i, s in enumerate(matches, 1):
        table.add_row(
            str(i), s.name, s.country or "",
            f"{s.power_kw} kW" if s.power_kw else "",
        )
    console.print(table)
    labels = [s.name for s in matches] + ["手動入力 (新規局)"]
    idx = _ask_choice("選択", labels)
    return matches[idx - 1] if idx <= len(matches) else None


def _current_antenna_label(bcl: dict) -> str:
    current_id = bcl.get("current_antenna")
    for a in bcl.get("antennas") or []:
        if a.get("id") == current_id:
            return a.get("name") or current_id or "未指定"
    return current_id or "未指定"


def _dispatch_payload(payload: dict, mac: dict) -> Optional[str]:
    target = sshr.resolve(mac.get("hostname", ""), mac.get("ip", ""))
    ssh_user = mac.get("user", "")
    if not target or not ssh_user:
        return "mac_mini.{hostname|ip|user} が未設定です"
    url = un.build_url(
        title=payload["title"],
        body=payload["body"],
        notebook=payload["notebook"],
        tag=payload["tag"],
    )
    console.print(f"[dim]→ ssh {ssh_user}@{target} open <url>[/dim]")
    return un.dispatch(url, target, ssh_user)


def cmd_new(_args: argparse.Namespace) -> int:
    c = cfg.load()
    bcl = c.get("bcl", {})
    mac = c.get("mac_mini", {})
    upnote = c.get("upnote", {})
    storage = c.get("storage", {})

    stations = sdb.load(STATIONS_PATH)

    freq_khz = _ask_freq()
    station = _select_station(stations, freq_khz)
    station_name = station.name if station else Prompt.ask("[bold]局名[/bold]")
    mode = Prompt.ask("[bold]モード[/bold]", default="AM")
    sinpo = _ask_sinpo()
    qsl_opts = bcl.get("qsl_status_options") or ["未送付", "送付済", "受領済", "不要"]
    qsl = qsl_opts[_ask_choice("[bold]QSL 状況[/bold]", qsl_opts) - 1]
    content = Prompt.ask("[bold]内容[/bold] (空欄可)", default="")
    rec_name = Prompt.ask("[bold]録音ファイル名[/bold] (GQRX で手動録音、Mac Mini 配置済み、空欄可)", default="")

    remote_dir = bcl.get("recording", {}).get("remote_dir", "")
    remote_path = f"{remote_dir}/{rec_name}" if rec_name and remote_dir else (rec_name or None)
    loc = bcl.get("default_location", {})

    entry = mdt.LogEntry(
        receiver=bcl.get("default_receiver", "RTL-SDR Blog V4 + GQRX"),
        antenna=_current_antenna_label(bcl),
        location_name=loc.get("name", ""),
        location_lat=loc.get("lat"),
        location_lng=loc.get("lng"),
        sfi=None, k_index=None, a_index=None, propagation_fetched_utc=None,
        freq_khz=freq_khz,
        band=_band_for(freq_khz),
        received_at=datetime.now(),
        mode=mode,
        station_name=station_name,
        country=station.country if station else None,
        languages=list(station.languages) if station else [],
        transmitter_site=station.transmitter_site if station else None,
        power_kw=station.power_kw if station else None,
        sinpo=sinpo,
        qsl_status=qsl,
        recording_remote_path=remote_path,
        content=content,
    )

    title = mdt.title_for(entry)
    body = mdt.render(entry)

    console.rule("確認")
    console.print(f"[bold]タイトル[/bold]: {title}")
    console.print(body)
    if not Confirm.ask("UpNote へ送信しますか?", default=True):
        console.print("[yellow]中止しました[/yellow]")
        return 0

    payload = {
        "title": title,
        "body": body,
        "notebook": upnote.get("notebook", "BCL_LogBook"),
        "tag": upnote.get("tag", "BCL"),
        "queued_at": datetime.now().isoformat(),
    }

    err = _dispatch_payload(payload, mac)
    log_dir = Path(storage.get("log_dir", "/tmp/bcl_logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    if err is None:
        sent_path = log_dir / (datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_sent.md")
        sent_path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        console.print("[green]✓ UpNote へ送信成功[/green]")
        console.print(f"[dim]ローカル保存: {sent_path}[/dim]")
        return 0

    console.print(f"[red]✗ 送信失敗: {err}[/red]")
    pending_dir = Path(storage.get("pending_dir", "/tmp/bcl_pending"))
    queued = pq.save(pending_dir, payload)
    console.print(f"[yellow]→ _pending/ に蓄積: {queued}[/yellow]")
    return 1


def cmd_resend(_args: argparse.Namespace) -> int:
    c = cfg.load()
    mac = c.get("mac_mini", {})
    storage = c.get("storage", {})
    pending_dir = Path(storage.get("pending_dir", "/tmp/bcl_pending"))

    items = pq.list_all(pending_dir)
    if not items:
        console.print("未送信ログなし")
        return 0

    sent = failed = 0
    for path in items:
        payload = pq.load_one(path)
        err = _dispatch_payload(payload, mac)
        if err is None:
            path.unlink()
            sent += 1
            console.print(f"[green]✓[/green] {payload.get('title', path.name)}")
        else:
            failed += 1
            console.print(f"[red]✗[/red] {payload.get('title', path.name)}: {err}")

    console.print(f"\n送信: {sent} / 失敗: {failed}")
    return 0 if failed == 0 else 1


def cmd_list(_args: argparse.Namespace) -> int:
    c = cfg.load()
    pending_dir = Path(c.get("storage", {}).get("pending_dir", "/tmp/bcl_pending"))
    items = pq.list_all(pending_dir)
    if not items:
        console.print("未送信ログなし")
        return 0
    table = Table(title=f"_pending/ ({len(items)} 件)")
    table.add_column("ファイル")
    table.add_column("タイトル")
    table.add_column("Queued at")
    for path in items:
        payload = pq.load_one(path)
        table.add_row(path.name, payload.get("title", ""), payload.get("queued_at", ""))
    console.print(table)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bcl_log",
        description="App 10 BCL ログモード (uConsole 先行構築版)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="新規 BCL ログを作成・UpNote へ投稿")
    p_new.set_defaults(func=cmd_new)

    p_resend = sub.add_parser("resend", help="_pending/ の未送信ログを一括再送")
    p_resend.set_defaults(func=cmd_resend)

    p_list = sub.add_parser("list", help="_pending/ の一覧を表示")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]中断されました[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
