#!/usr/bin/env python3
"""App 02 lora-mesh-node ― Meshtastic レンジテストの到達距離解析ツール。

固定局(C6L)を Range Test の sender、移動局(PaperMono)を receiver とし、移動局が
出力する `rangetest.csv`(受信連番・RSSI・SNR・受信時刻)と、別途 Garmin GPSMAP 67i
等で取得した GPX トラック(移動軌跡・UTC 時刻)を **時刻をキーに突合**して、

  - 受信点ごとの固定局からの距離 (haversine)
  - 距離 vs RSSI / SNR
  - 距離 vs パケット到達率(連番の欠落から算出。欠落分は時刻線形補間で位置推定)

を CSV とグラフに出力する。両機とも GPS 非搭載のため、位置は GPX 側から与える設計。

⚠️ 時計合わせが命: receiver(PaperMono)の RTC が UTC に同期していないと突合がズレる。
   ズレが既知なら `--rx-clock-offset <秒>` で補正できる(RX 時刻に加算)。実行時に
   突合時刻差の中央値を診断表示するので、大きければオフセットを疑うこと。

Meshtastic Range Test の CSV 既定ヘッダ:
  time,sender,rx_snr,num,rx_rssi,distance,hop_limit,payload
  - time    : epoch 秒(UTC)。ノード時計未同期だと 0 になり得る。
  - num     : mesh パケット ID(連番ではない)。連番は payload 内の整数から拾う。
  - distance: FW 側算出(両機 GPS 前提)。本ツールでは使わず GPX から自前計算。

使い方:
  python rangetest_analyze.py \
      --gpx track.gpx \
      --csv rangetest.csv \
      --fixed 43.06417,141.34694 \
      --out-dir ./rangetest_out

依存: numpy, matplotlib (requirements.txt 参照)。
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面を持たない環境でも savefig できるよう非対話バックエンド
import matplotlib.pyplot as plt
import numpy as np

# Windows 既定コンソール(cp932)だと診断・サマリの日本語が化けるため UTF-8 を強制。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — 非対応ストリーム(パイプ等)は無視
        pass

EARTH_R = 6371008.8  # 平均地球半径 [m] (IUGG mean radius)

# Meshtastic RangeTest CSV の既定カラム名(小文字・strip 後に照合)
COL_TIME = "time"
COL_RSSI = "rx_rssi"
COL_SNR = "rx_snr"
COL_NUM = "num"
COL_PAYLOAD = "payload"


# --------------------------------------------------------------------------- #
# 時刻パース
# --------------------------------------------------------------------------- #
def parse_epoch(value: str) -> float | None:
    """CSV/GPX の時刻文字列を UTC epoch 秒(float)へ。失敗時 None。

    - 数値(かつ十分大きい)なら epoch 秒とみなす。
    - それ以外は ISO8601 として解釈(末尾 Z / +00:00 / 分数秒に対応)。
    """
    s = (value or "").strip()
    if not s:
        return None
    # epoch 秒(整数/小数)
    try:
        f = float(s)
        if f > 1e8:  # 1973 年以降 ~ を epoch とみなす閾値
            return f
    except ValueError:
        pass
    # ISO8601
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:  # naive はローカルではなく UTC とみなす(GPX は UTC が基本)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# --------------------------------------------------------------------------- #
# GPX 読み込み
# --------------------------------------------------------------------------- #
def load_gpx(path: Path) -> tuple[list[float], list[float], list[float]]:
    """GPX トラックから (times, lats, lons) を時刻昇順で返す。名前空間非依存。"""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]  # '{ns}trkpt' -> 'trkpt'

    pts: list[tuple[float, float, float]] = []
    for el in root.iter():
        if local(el.tag) != "trkpt":
            continue
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            continue
        t = None
        for child in el:
            if local(child.tag) == "time":
                t = parse_epoch(child.text or "")
                break
        if t is None:
            continue
        pts.append((t, float(lat), float(lon)))

    pts.sort(key=lambda p: p[0])
    times = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    lons = [p[2] for p in pts]
    return times, lats, lons


class Track:
    """GPX トラックへの最近傍時刻検索(二分探索)。"""

    def __init__(self, times: list[float], lats: list[float], lons: list[float]):
        if not times:
            raise ValueError("GPX にタイムスタンプ付き trkpt がありません")
        self.times = times
        self.lats = lats
        self.lons = lons

    def at(self, t: float) -> tuple[float, float, float]:
        """時刻 t に最も近い点の (lat, lon, |時刻差秒|) を返す。"""
        i = bisect.bisect_left(self.times, t)
        cands = []
        if i < len(self.times):
            cands.append(i)
        if i > 0:
            cands.append(i - 1)
        best = min(cands, key=lambda j: abs(self.times[j] - t))
        return self.lats[best], self.lons[best], abs(self.times[best] - t)


# --------------------------------------------------------------------------- #
# 距離
# --------------------------------------------------------------------------- #
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2 点間の大圏距離 [m]。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- #
# CSV 読み込み
# --------------------------------------------------------------------------- #
_INT_RE = re.compile(r"-?\d+")


def extract_seq(payload: str, fallback: str) -> int | None:
    """payload 内の最後の整数を連番として拾う。無ければ num(fallback)。"""
    ints = _INT_RE.findall(payload or "")
    if ints:
        return int(ints[-1])
    ints = _INT_RE.findall(fallback or "")
    return int(ints[-1]) if ints else None


def load_rangetest(path: Path, clock_offset: float) -> list[dict]:
    """rangetest.csv を読み、[{seq,t,rssi,snr}] のリストへ。時刻昇順。"""
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV にヘッダがありません")
        # ヘッダを小文字 strip で正規化した参照表
        norm = {name.strip().lower(): name for name in reader.fieldnames}

        def col(key: str) -> str | None:
            return norm.get(key)

        c_time, c_rssi = col(COL_TIME), col(COL_RSSI)
        c_snr, c_num = col(COL_SNR), col(COL_NUM)
        c_pl = col(COL_PAYLOAD)
        if c_time is None:
            raise ValueError(f"CSV に '{COL_TIME}' 列がありません: {reader.fieldnames}")

        for r in reader:
            t = parse_epoch(r.get(c_time, ""))
            if t is None:
                continue
            t += clock_offset
            seq = extract_seq(
                r.get(c_pl, "") if c_pl else "",
                r.get(c_num, "") if c_num else "",
            )
            rows.append(
                {
                    "seq": seq,
                    "t": t,
                    "rssi": _to_float(r.get(c_rssi)) if c_rssi else None,
                    "snr": _to_float(r.get(c_snr)) if c_snr else None,
                }
            )
    rows.sort(key=lambda x: x["t"])
    return rows


def _to_float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 到達率(欠落連番を時刻線形補間で位置推定)
# --------------------------------------------------------------------------- #
def build_delivery(
    rows: list[dict],
    track: Track,
    fixed: tuple[float, float],
    seq_min: int | None,
    seq_max: int | None,
    interval: float | None,
) -> list[dict]:
    """連番の全域を received/missed で埋め、各点に距離を付与して返す。

    受信済み連番の間に挟まれた欠落は、前後受信の時刻を線形補間して発信時刻を推定
    → GPX 最近傍で位置化。区間外(先頭前・末尾後)の欠落は --interval があれば
    アンカーからの外挿で埋め、無ければ補間不能として除外(件数はログ)。
    """
    recv = [r for r in rows if r["seq"] is not None]
    if not recv:
        return []
    # 同一連番の重複は最初の受信を採用
    by_seq: dict[int, dict] = {}
    for r in recv:
        by_seq.setdefault(r["seq"], r)

    seqs_sorted = sorted(by_seq)
    lo = seq_min if seq_min is not None else seqs_sorted[0]
    hi = seq_max if seq_max is not None else seqs_sorted[-1]
    anchor_seq = seqs_sorted[0]
    anchor_t = by_seq[anchor_seq]["t"]

    out: list[dict] = []
    dropped = 0
    for k in range(lo, hi + 1):
        if k in by_seq:
            r = by_seq[k]
            lat, lon, dt = track.at(r["t"])
            out.append(
                {
                    "seq": k,
                    "received": True,
                    "t": r["t"],
                    "gps_dt": dt,
                    "lat": lat,
                    "lon": lon,
                    "dist": haversine(lat, lon, fixed[0], fixed[1]),
                    "rssi": r["rssi"],
                    "snr": r["snr"],
                }
            )
            continue
        # 欠落: 発信時刻を推定
        t_est = _estimate_time(k, seqs_sorted, by_seq, anchor_seq, anchor_t, interval)
        if t_est is None:
            dropped += 1
            continue
        lat, lon, dt = track.at(t_est)
        out.append(
            {
                "seq": k,
                "received": False,
                "t": t_est,
                "gps_dt": dt,
                "lat": lat,
                "lon": lon,
                "dist": haversine(lat, lon, fixed[0], fixed[1]),
                "rssi": None,
                "snr": None,
            }
        )
    if dropped:
        print(
            f"[info] 到達率: 区間外で位置推定できなかった欠落 {dropped} 件を除外"
            f"(--interval 指定で外挿可能)",
            file=sys.stderr,
        )
    return out


def _estimate_time(
    k: int,
    seqs_sorted: list[int],
    by_seq: dict[int, dict],
    anchor_seq: int,
    anchor_t: float,
    interval: float | None,
) -> float | None:
    """欠落連番 k の発信時刻推定。区間内は線形補間、区間外は interval 外挿。"""
    i = bisect.bisect_left(seqs_sorted, k)
    left = seqs_sorted[i - 1] if i > 0 else None
    right = seqs_sorted[i] if i < len(seqs_sorted) else None
    if left is not None and right is not None:  # 区間内 → 線形補間
        ta, tb = by_seq[left]["t"], by_seq[right]["t"]
        return ta + (tb - ta) * (k - left) / (right - left)
    if interval is not None:  # 区間外 → アンカーからの外挿
        return anchor_t + (k - anchor_seq) * interval
    return None


# --------------------------------------------------------------------------- #
# 出力
# --------------------------------------------------------------------------- #
def write_csv(path: Path, data: list[dict]) -> None:
    cols = ["seq", "received", "t_utc", "gps_dt_s", "lat", "lon", "dist_m", "rssi", "snr"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in data:
            w.writerow(
                [
                    d["seq"],
                    int(d["received"]),
                    datetime.fromtimestamp(d["t"], timezone.utc).isoformat(),
                    f"{d['gps_dt']:.1f}",
                    f"{d['lat']:.6f}",
                    f"{d['lon']:.6f}",
                    f"{d['dist']:.1f}",
                    "" if d["rssi"] is None else f"{d['rssi']:.1f}",
                    "" if d["snr"] is None else f"{d['snr']:.2f}",
                ]
            )


def plot_signal(path: Path, data: list[dict]) -> None:
    """距離 vs RSSI / SNR(受信点のみ)。"""
    recv = [d for d in data if d["received"]]
    if not recv:
        return
    dist = np.array([d["dist"] for d in recv]) / 1000.0  # km
    rssi = np.array([np.nan if d["rssi"] is None else d["rssi"] for d in recv])
    snr = np.array([np.nan if d["snr"] is None else d["snr"] for d in recv])

    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.scatter(dist, rssi, s=18, c="tab:blue", label="RSSI", alpha=0.7)
    ax1.set_xlabel("固定局からの距離 [km]")
    ax1.set_ylabel("RSSI [dBm]", color="tab:blue")
    ax1.tick_params(axis="y", labelcolor="tab:blue")
    ax1.grid(True, alpha=0.3)

    ax2 = ax1.twinx()
    ax2.scatter(dist, snr, s=18, c="tab:red", marker="^", label="SNR", alpha=0.7)
    ax2.set_ylabel("SNR [dB]", color="tab:red")
    ax2.tick_params(axis="y", labelcolor="tab:red")

    ax1.set_title("距離 vs RSSI / SNR")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_delivery(path: Path, data: list[dict], bin_width: float) -> None:
    """距離ビンごとの到達率(received / (received+missed))。"""
    if not data:
        return
    dist = np.array([d["dist"] for d in data])
    recvd = np.array([d["received"] for d in data], dtype=bool)
    edges = np.arange(0, dist.max() + bin_width, bin_width)
    if len(edges) < 2:
        return
    idx = np.digitize(dist, edges) - 1
    centers, ratios, totals = [], [], []
    for b in range(len(edges) - 1):
        m = idx == b
        n = int(m.sum())
        if n == 0:
            continue
        centers.append((edges[b] + edges[b + 1]) / 2 / 1000.0)  # km
        ratios.append(recvd[m].mean() * 100.0)
        totals.append(n)

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(centers, ratios, width=bin_width / 1000.0 * 0.9, color="tab:green", alpha=0.75)
    for rect, n in zip(bars, totals):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 1,
                f"n={n}", ha="center", va="bottom", fontsize=7)
    ax.set_xlabel("固定局からの距離 [km]")
    ax.set_ylabel("到達率 [%]")
    ax.set_ylim(0, 105)
    ax.set_title(f"距離 vs パケット到達率(ビン幅 {bin_width:.0f} m)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_map(path: Path, data: list[dict], fixed: tuple[float, float]) -> None:
    """移動軌跡を RSSI で色分け散布(受信点)＋固定局・欠落点。"""
    recv = [d for d in data if d["received"] and d["rssi"] is not None]
    miss = [d for d in data if not d["received"]]
    fig, ax = plt.subplots(figsize=(7, 7))
    if miss:
        ax.scatter([d["lon"] for d in miss], [d["lat"] for d in miss],
                   s=10, c="lightgray", marker="x", label="欠落", alpha=0.6)
    if recv:
        sc = ax.scatter([d["lon"] for d in recv], [d["lat"] for d in recv],
                        s=22, c=[d["rssi"] for d in recv], cmap="viridis", label="受信")
        fig.colorbar(sc, ax=ax, label="RSSI [dBm]")
    ax.scatter([fixed[1]], [fixed[0]], s=140, c="red", marker="*",
               edgecolors="black", label="固定局", zorder=5)
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(loc="best", fontsize=8)
    ax.set_title("受信マップ(RSSI 色分け)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _use_jp_font() -> None:
    """日本語ラベルの豆腐化を可能な範囲で回避(無ければ英字のまま)。"""
    for name in ("Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP", "IPAexGothic"):
        try:
            matplotlib.rcParams["font.family"] = name
            return
        except Exception:  # noqa: BLE001
            continue


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def parse_fixed(s: str) -> tuple[float, float]:
    lat, lon = (float(x) for x in s.split(","))
    return lat, lon


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gpx", required=True, type=Path, help="Garmin 等の GPX トラック")
    ap.add_argument("--csv", required=True, type=Path, help="Meshtastic rangetest.csv")
    ap.add_argument("--fixed", required=True, type=parse_fixed,
                    help="固定局(C6L)座標 'lat,lon' 例 43.06417,141.34694")
    ap.add_argument("--out-dir", type=Path, default=Path("./rangetest_out"))
    ap.add_argument("--rx-clock-offset", type=float, default=0.0,
                    help="受信機時計の補正[秒](RX 時刻に加算)")
    ap.add_argument("--max-dt", type=float, default=30.0,
                    help="GPX との突合許容時刻差[秒]。超過点は信号グラフから除外")
    ap.add_argument("--bin-width", type=float, default=100.0, help="到達率ビン幅[m]")
    ap.add_argument("--interval", type=float, default=None,
                    help="送信間隔[秒]。指定時は区間外欠落も外挿して到達率に含める")
    ap.add_argument("--seq-min", type=int, default=None, help="連番の下限を明示")
    ap.add_argument("--seq-max", type=int, default=None, help="連番の上限を明示")
    args = ap.parse_args(argv)

    _use_jp_font()

    times, lats, lons = load_gpx(args.gpx)
    track = Track(times, lats, lons)
    rows = load_rangetest(args.csv, args.rx_clock_offset)
    if not rows:
        print("[error] CSV から有効な受信行を取得できませんでした", file=sys.stderr)
        return 1

    # 診断: 突合時刻差の中央値(大きければ時計ズレを疑う)
    dts = sorted(track.at(r["t"])[2] for r in rows)
    median_dt = dts[len(dts) // 2]
    print(f"[diag] 受信 {len(rows)} 件 / GPX 突合時刻差 中央値 {median_dt:.1f}s "
          f"(min {dts[0]:.1f}s / max {dts[-1]:.1f}s)")
    if median_dt > args.max_dt:
        print(f"[warn] 中央時刻差が --max-dt({args.max_dt:.0f}s) 超。"
              f"receiver の時計同期 or --rx-clock-offset を確認してください", file=sys.stderr)

    data = build_delivery(rows, track, args.fixed,
                          args.seq_min, args.seq_max, args.interval)
    if not data:
        print("[error] 連番を持つ受信行が無く到達率を算出できません"
              "(payload に整数が無い?)", file=sys.stderr)
        return 1

    # --max-dt 超の受信点は距離が不正確なため信号系グラフでは除外(到達率は保持)
    reliable = [d for d in data if d["gps_dt"] <= args.max_dt]
    excluded = sum(1 for d in data if d["received"] and d["gps_dt"] > args.max_dt)
    if excluded:
        print(f"[info] 時刻差 {args.max_dt:.0f}s 超の受信点 {excluded} 件を"
              f"信号グラフ/マップから除外(到達率には含む)", file=sys.stderr)

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "enriched.csv", data)
    plot_signal(out / "dist_vs_rssi_snr.png", reliable)
    plot_delivery(out / "delivery_vs_distance.png", data, args.bin_width)
    plot_map(out / "track_rssi_map.png", reliable, args.fixed)

    # サマリ
    recv = [d for d in data if d["received"]]
    n_recv, n_total = len(recv), len(data)
    max_recv = max((d["dist"] for d in recv), default=0.0)
    # 到達率 50% を維持できた最遠ビン
    reach50 = _reach_at_ratio(data, args.bin_width, 0.5)
    print("\n===== レンジテスト サマリ =====")
    print(f"受信/総連番     : {n_recv}/{n_total}  (全体到達率 {100*n_recv/n_total:.1f}%)")
    print(f"最遠受信距離     : {max_recv/1000:.2f} km")
    print(f"到達率50%維持    : {'~%.2f km' % (reach50/1000) if reach50 else 'N/A'}")
    if recv:
        rssis = [d["rssi"] for d in recv if d["rssi"] is not None]
        if rssis:
            print(f"RSSI 範囲        : {min(rssis):.0f} 〜 {max(rssis):.0f} dBm")
    print(f"出力先           : {out.resolve()}")
    print("  - enriched.csv / dist_vs_rssi_snr.png / delivery_vs_distance.png / track_rssi_map.png")
    return 0


def _reach_at_ratio(data: list[dict], bin_width: float, thresh: float) -> float | None:
    """到達率が thresh 以上を維持できた最遠ビン中心距離[m]。"""
    dist = np.array([d["dist"] for d in data])
    recvd = np.array([d["received"] for d in data], dtype=bool)
    edges = np.arange(0, dist.max() + bin_width, bin_width)
    idx = np.digitize(dist, edges) - 1
    reach = None
    for b in range(len(edges) - 1):
        m = idx == b
        if not m.any():
            continue
        if recvd[m].mean() >= thresh:
            reach = (edges[b] + edges[b + 1]) / 2
        else:
            break  # 連続維持が途切れた最初のビンで打ち切り
    return reach


if __name__ == "__main__":
    raise SystemExit(main())
