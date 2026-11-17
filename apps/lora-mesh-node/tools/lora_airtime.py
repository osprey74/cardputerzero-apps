#!/usr/bin/env python3
"""LoRa の送信時間（Time on Air）と、Meshtastic プリセットの日本向け既定周波数を計算する。

標準ライブラリだけで動く。電波は出さない（計算のみ）。

  python3 lora_airtime.py              # 一覧表を表示
  python3 lora_airtime.py --selftest   # HANDOFF §3 App02 の表と照合
  python3 lora_airtime.py --bw 125 --sf 9 --cr 5 --len 32   # 1 点だけ計算

根拠:
  送信時間の式 : Semtech SX1261/2 データシート 6.1.4 "LoRa Time-on-Air"
  プリセット   : meshtastic/firmware src/mesh/MeshRadio.h modemPresetToParams()
  周波数の決定 : 同 src/mesh/RadioInterface.cpp applyModemConfig() / hash()
  パケット構成 : 同 src/mesh/RadioLibInterface.h getPacketConfig()
                 （プリアンブル 16・明示ヘッダ・CRC あり・シンボル時間 16ms 以上で LDRO）
  確認した版   : master 6d41e279（2026-08-20）。プリセットは版で変わり得る。

認証条件（LIMIT_*）は Cap LoRa-1262（工事設計認証 211-251216）の試験成績書の記載値。
この出力は計算値であり、送信の可否を保証するものではない。
"""
from __future__ import annotations

import argparse
import math

# --- Meshtastic（確認した版の値） -------------------------------------------
PREAMBLE = 16          # RadioInterface.h: preambleLength
HEADER_BYTES = 16      # sizeof(PacketHeader): to4 + from4 + id4 + flags/channel/next_hop/relay_node
JP_START_MHZ = 920.5   # RadioInterface.cpp: RDEF(JP, 920.5f, 923.5f, 100, 0, 13, ...)
JP_END_MHZ = 923.5
JP_POWER_LIMIT_DBM = 13

# 表示名（＝既定チャネル名。周波数スロットのハッシュに使われる）: (帯域幅 kHz, SF, CR 分母)
PRESETS = {
    "ShortTurbo": (500, 7, 5),
    "ShortFast": (250, 7, 5),
    "ShortSlow": (250, 8, 5),
    "MediumFast": (250, 9, 5),
    "MediumSlow": (250, 10, 5),
    "LongFast": (250, 11, 5),   # 既定
    "LongMod": (125, 11, 8),    # LONG_MODERATE
    "LongSlow": (125, 12, 8),
    "LongTurbo": (500, 11, 8),
}

# --- Cap LoRa-1262 の認証条件（試験成績書の記載値） --------------------------
LIMIT_TOA_MS = 400.0                   # 1 回の送信は 0.4 秒未満
# 試験成績書の Channel List（中心周波数）。922.0〜923.4MHz は「占有範囲」ではなく「中心周波数の範囲」。
# 実測の占有範囲は中心の外側へ広がる（例: 500kHz 幅・923.4MHz で 923.146〜923.654MHz）。
CERT_CHANNELS_KHZ = [922000 + 200 * i for i in range(8)]
CERT_BW_KHZ = {125: 5.0, 500: 1.5}     # 試験対象の帯域幅: 定格出力 mW（250kHz は対象外）


def on_cert_channel(freq_mhz: float) -> bool:
    """中心周波数が Channel List の 8 波のどれかに一致するか（1kHz 未満の差は一致とみなす）。"""
    return any(abs(freq_mhz * 1000 - c) < 1.0 for c in CERT_CHANNELS_KHZ)


def time_on_air_ms(bw_khz: float, sf: int, cr: int, payload_len: int, *,
                   preamble: int = PREAMBLE, explicit_header: bool = True,
                   crc: bool = True, ldro: bool | None = None) -> float:
    """LoRa 1 パケットの送信時間 [ms]。cr は符号化率の分母（4/5 なら 5）。

    ldro=None のときは、シンボル時間 16ms 以上で有効（Meshtastic・RadioLib の自動設定と同じ）。
    """
    t_sym = (2 ** sf) / bw_khz                      # シンボル時間 [ms]
    if ldro is None:
        ldro = t_sym >= 16.0
    bits = 8 * payload_len + (16 if crc else 0) - 4 * sf + (20 if explicit_header else 0)
    if sf in (5, 6):
        fixed, per_sym = 6.25, 4 * sf
    else:
        bits += 8
        fixed, per_sym = 4.25, 4 * (sf - 2) if ldro else 4 * sf
    n_payload = math.ceil(max(bits, 0) / per_sym) * cr
    return (preamble + fixed + 8 + n_payload) * t_sym


def max_len_under(bw_khz: float, sf: int, cr: int, limit_ms: float = LIMIT_TOA_MS) -> int:
    """limit_ms 未満に収まる最大の長さ [bytes]（ヘッダ込み）。収まらなければ 0。"""
    best = 0
    for n in range(1, 256):
        if time_on_air_ms(bw_khz, sf, cr, n) < limit_ms:
            best = n
    return best


def djb2(s: str) -> int:
    """RadioInterface.cpp の hash()（32 ビットで桁あふれ）。"""
    h = 5381
    for c in s.encode():
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def jp_default_slot(name: str, bw_khz: float) -> tuple[int, int, float]:
    """日本（JP）リージョンでの既定スロット。(スロット番号 1 始まり, スロット数, 中心周波数 MHz)"""
    n = math.floor((JP_END_MHZ - JP_START_MHZ) / (bw_khz / 1000))
    ch = djb2(name) % n
    return ch + 1, n, JP_START_MHZ + bw_khz / 2000 + ch * bw_khz / 1000


def print_presets() -> None:
    print("## Meshtastic プリセットと Cap LoRa-1262 の認証条件\n")
    print(f"JP リージョン: {JP_START_MHZ}〜{JP_END_MHZ}MHz・出力上限 {JP_POWER_LIMIT_DBM}dBm")
    print(f"認証条件     : 中心 922.0〜923.4MHz の 8 波（200kHz 刻み）・帯域幅 125kHz(5mW)/500kHz(1.5mW)・1 回 {LIMIT_TOA_MS:.0f}ms 未満\n")
    print("| プリセット | 帯域幅 | SF | CR | JP 既定スロット | 中心 | 計算上の占有範囲 | 帯域幅 | 中心が 8 波に一致 | 0.4 秒未満の最大長 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, (bw, sf, cr) in PRESETS.items():
        slot, n, f = jp_default_slot(name, bw)
        lo, hi = f - bw / 2000, f + bw / 2000
        bw_ok = "試験対象" if bw in CERT_BW_KHZ else "対象外"
        in_band = "一致" if on_cert_channel(f) else "不一致"
        m = max_len_under(bw, sf, cr)
        fit = f"{m}B（本文 {m - HEADER_BYTES}B）" if m > HEADER_BYTES else "収まらない"
        mark = "（既定）" if name == "LongFast" else ""
        print(f"| {name}{mark} | {bw}kHz | {sf} | 4/{cr} | {slot}/{n} | {f:.3f}MHz | "
              f"{lo:.3f}〜{hi:.3f} | {bw_ok} | {in_band} | {fit} |")


def print_toa_table() -> None:
    lens = [20, 32, 48, 64, 100, 253]
    rows = [(125, 7, 5), (125, 8, 5), (125, 9, 5), (125, 10, 5), (125, 11, 8), (125, 12, 8),
            (500, 7, 5), (500, 9, 5), (500, 11, 8), (250, 11, 5)]
    print("\n## 送信時間 [ms]（プリアンブル 16・明示ヘッダ・CRC あり。長さは 16 バイトのヘッダ込み）\n")
    print("| 設定 | " + " | ".join(f"{n}B" for n in lens) + " | 0.4 秒未満の最大長 |")
    print("|---|" + "---|" * (len(lens) + 1))
    for bw, sf, cr in rows:
        cells = " | ".join(f"{time_on_air_ms(bw, sf, cr, n):.0f}" for n in lens)
        print(f"| {bw}kHz SF{sf} CR4/{cr} | {cells} | {max_len_under(bw, sf, cr)}B |")


# HANDOFF_cardputerzero.md §3 App02「Meshtastic プリセットとの適合」の表（2026-11-17 時点）
HANDOFF_TABLE = {
    (125, 7, 5): {20: 65, 32: 80, 48: 106, 64: 126, 100: 183},
    (125, 8, 5): {20: 119, 32: 150, 48: 191, 64: 232, 100: 324},
    (125, 9, 5): {20: 218, 32: 280, 48: 341, 64: 423, 100: 587},
    (125, 10, 5): {20: 436, 32: 518, 48: 641, 64: 764, 100: 1092},
    (125, 11, 8): {20: 1118, 32: 1511},
    (125, 12, 8): {20: 1974, 32: 2761},
    (500, 7, 5): {20: 16, 32: 20, 48: 26, 64: 32, 100: 46},
    (500, 9, 5): {20: 55, 32: 70, 48: 85, 64: 106, 100: 147},
    (500, 11, 8): {20: 247, 32: 312, 48: 411, 64: 509, 100: 738},
    (250, 11, 5): {20: 395, 32: 477, 48: 600, 64: 723, 100: 1010},
}


def selftest() -> int:
    bad = 0
    for (bw, sf, cr), cells in HANDOFF_TABLE.items():
        for n, want in cells.items():
            got = time_on_air_ms(bw, sf, cr, n)
            ok = abs(got - want) < 1.0
            bad += not ok
            if not ok:
                print(f"NG  {bw}kHz SF{sf} CR4/{cr} {n}B: 表 {want}ms / 計算 {got:.1f}ms")
    total = sum(len(c) for c in HANDOFF_TABLE.values())
    print(f"selftest: {total - bad}/{total} 一致")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true", help="HANDOFF の表と照合する")
    ap.add_argument("--bw", type=float, help="帯域幅 [kHz]")
    ap.add_argument("--sf", type=int, help="拡散率")
    ap.add_argument("--cr", type=int, default=5, help="符号化率の分母（4/5 なら 5）")
    ap.add_argument("--len", type=int, dest="length", help="長さ [bytes]（ヘッダ込み）")
    ap.add_argument("--preamble", type=int, default=PREAMBLE, help="プリアンブル長")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.bw and a.sf and a.length:
        t = time_on_air_ms(a.bw, a.sf, a.cr, a.length, preamble=a.preamble)
        print(f"{a.bw:g}kHz SF{a.sf} CR4/{a.cr} {a.length}B preamble={a.preamble}: {t:.1f}ms")
        return 0
    print_presets()
    print_toa_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
