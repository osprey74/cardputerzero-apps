"""App11 LAN スキャナーのネットワーク処理（標準ライブラリのみ・root 不要）。

- 対象: 本機が接続しているサブネットだけ（/22 より広い場合は本機を含む /24 に絞る）
- ホスト発見: ICMP エコー（ping ソケット。`net.ipv4.ping_group_range` により一般ユーザーで可）
  ＋ その結果できた ARP 表（`ip -j neigh`）。ICMP に応えない機器も ARP で見つかる
- 名前: 逆引き DNS ＋ mDNS（224.0.0.251 への逆引き PTR 問い合わせ）
- ベンダー: IEEE の OUI 一覧（data/oui.tsv.gz・tools/build_oui.py で生成）
- ポート: TCP の接続確認（connect）だけ。バナー取得や OS 推定は行わない
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import os
import select
import selectors
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait

MAX_HOSTS = 1024
QUICK_PORTS = [21, 22, 23, 25, 53, 80, 110, 139, 143, 443, 445, 502, 548, 554, 631, 1433, 1883,
               3306, 3389, 5000, 5432, 5900, 6379, 8080, 8443, 8883, 9100]
EXTRA_SERVICES = {502: "modbus", 1883: "mqtt", 8883: "mqtt-tls", 9100: "printer", 8443: "https-alt",
                  5000: "upnp", 554: "rtsp", 548: "afp", 62078: "iphone-sync", 3389: "rdp", 5900: "vnc"}


def _run_json(cmd: list[str]):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    return json.loads(out or "[]")


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------- インターフェース
def interfaces(addr_json=None, route_json=None) -> list[dict]:
    """IPv4 の付いた UP の I/F を返す（lo と /31・/32 は除く）。"""
    addrs = addr_json if addr_json is not None else _run_json(["ip", "-j", "-4", "addr", "show"])
    routes = route_json if route_json is not None else _run_json(["ip", "-j", "-4", "route", "show", "default"])
    gw = {r.get("dev"): r.get("gateway") for r in routes if r.get("gateway")}
    out = []
    for it in addrs:
        name = it.get("ifname", "")
        if name == "lo" or "UP" not in it.get("flags", []):
            continue
        for a in it.get("addr_info", []):
            if a.get("family") != "inet" or a.get("scope") != "global" or a.get("prefixlen", 32) >= 31:
                continue
            out.append({"ifname": name, "addr": a["local"], "prefix": a["prefixlen"],
                        "gateway": gw.get(name), "mac": _read(f"/sys/class/net/{name}/address").upper()})
    return out


def scan_network(addr: str, prefix: int, max_hosts: int = MAX_HOSTS):
    """(ネットワーク, 対象 IP のリスト, 絞り込んだか)。広すぎる場合は本機を含む /24 にする。"""
    net = ipaddress.ip_network(f"{addr}/{prefix}", strict=False)
    narrowed = False
    if net.num_addresses - 2 > max_hosts:
        net = ipaddress.ip_network(f"{addr}/24", strict=False)
        narrowed = True
    hosts = [str(h) for h in net.hosts() if str(h) != addr]
    return net, hosts, narrowed


# ---------------------------------------------------------------- ICMP
def _checksum(b: bytes) -> int:
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack(f"!{len(b) // 2}H", b))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def echo_packet(seq: int, payload: bytes = b"cz-lan-scan") -> bytes:
    hdr = struct.pack("!BBHHH", 8, 0, 0, 0, seq & 0xFFFF)
    return struct.pack("!BBHHH", 8, 0, _checksum(hdr + payload), 0, seq & 0xFFFF) + payload


def icmp_sweep(targets: list[str], rounds: int = 2, wait_s: float = 1.5, progress=None, stop=None) -> dict:
    """ICMP エコーを全対象へ送り、応答した IP → 往復時間[ms] を返す。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    s.setblocking(False)
    sent: dict[str, float] = {}
    found: dict[str, float] = {}
    total = max(1, len(targets) * rounds)
    done = 0

    def drain():
        while True:
            try:
                data, (src, _p) = s.recvfrom(2048)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            if data and data[0] == 0 and src in sent and src not in found:
                found[src] = (time.time() - sent[src]) * 1000.0

    try:
        for r in range(rounds):
            for i, ip in enumerate(targets):
                if stop is not None and stop.is_set():
                    return found
                done += 1
                if ip in found:
                    continue
                for _try in range(3):
                    try:
                        s.sendto(echo_packet(r * 4096 + i), (ip, 0))
                        sent[ip] = time.time()
                        break
                    except (BlockingIOError, OSError) as e:
                        if getattr(e, "errno", None) in (105, 11):     # ENOBUFS / EAGAIN
                            time.sleep(0.02)
                            drain()
                            continue
                        break
                if i % 8 == 7:
                    drain()
                    time.sleep(0.004)
                    if progress:
                        progress(done, total, len(found))
            end = time.time() + (wait_s if r == rounds - 1 else 0.6)
            while time.time() < end:
                if stop is not None and stop.is_set():
                    return found
                select.select([s], [], [], 0.1)
                drain()
                if progress:
                    progress(done, total, len(found))
    finally:
        s.close()
    return found


# ---------------------------------------------------------------- ARP
def neighbors(ifname: str, neigh_json=None) -> dict[str, str]:
    """ARP 表から IP → MAC（解決済みのもの）。"""
    rows = neigh_json if neigh_json is not None else _run_json(["ip", "-j", "-4", "neigh", "show", "dev", ifname])
    out = {}
    for r in rows:
        st = r.get("state", [])
        if r.get("lladdr") and not any(x in st for x in ("FAILED", "INCOMPLETE")):
            out[r["dst"]] = r["lladdr"].upper()
    return out


# ---------------------------------------------------------------- OUI
class OUI:
    def __init__(self, path: str | None):
        self.db: dict[str, str] = {}
        if path and os.path.exists(path):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.rstrip("\n").partition("\t")
                    if k and v:
                        self.db[k] = v

    @staticmethod
    def is_random(mac: str) -> bool:
        """ローカル管理ビットが立った MAC（スマホ等のランダム化 MAC）。"""
        try:
            return bool(int(mac[:2], 16) & 0x02)
        except ValueError:
            return False

    def vendor(self, mac: str) -> str:
        if not mac:
            return ""
        if self.is_random(mac):
            return "（ランダム化 MAC）"
        return self.db.get(mac.replace(":", "").replace("-", "")[:6].upper(), "")


# ---------------------------------------------------------------- 名前解決
def reverse_dns(ips: list[str], timeout: float = 4.0) -> dict[str, str]:
    ex = ThreadPoolExecutor(max_workers=16)
    futs = {ex.submit(socket.gethostbyaddr, ip): ip for ip in ips}
    done, _ = wait(futs, timeout=timeout)
    ex.shutdown(wait=False, cancel_futures=True)
    out = {}
    for f in done:
        try:
            name = f.result()[0]
        except (OSError, UnicodeError):
            continue
        if name and name != futs[f]:
            out[futs[f]] = name
    return out


def _qname(name: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in name.strip(".").split(".")) + b"\0"


def ptr_name(ip: str) -> str:
    return ".".join(reversed(ip.split("."))) + ".in-addr.arpa"


def mdns_query(ip: str, qid: int) -> bytes:
    """逆引き PTR の問い合わせ（unicast 応答を求める QU ビット付き）。"""
    return struct.pack("!HHHHHH", qid, 0, 1, 0, 0, 0) + _qname(ptr_name(ip)) + struct.pack("!HH", 12, 0x8001)


def _read_name(buf: bytes, off: int, depth: int = 0) -> tuple[str, int]:
    labels, jumped, end = [], False, off
    while depth < 20:
        if off >= len(buf):
            raise ValueError("truncated")
        n = buf[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = ((n & 0x3F) << 8) | buf[off + 1]
            if not jumped:
                end = off + 2
            jumped = True
            off = ptr
            depth += 1
            continue
        labels.append(buf[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    return ".".join(labels), (end if jumped else off)


def parse_ptr_answers(buf: bytes) -> dict[str, str]:
    """DNS 応答から in-addr.arpa の PTR だけ取り出す（IP → 名前）。"""
    out = {}
    try:
        _id, _fl, qd, an, ns, ar = struct.unpack_from("!HHHHHH", buf, 0)
        off = 12
        for _ in range(qd):
            _n, off = _read_name(buf, off)
            off += 4
        for _ in range(an + ns + ar):
            name, off = _read_name(buf, off)
            rtype, _cls, _ttl, rdlen = struct.unpack_from("!HHIH", buf, off)
            off += 10
            if rtype == 12 and name.endswith(".in-addr.arpa"):
                target, _ = _read_name(buf, off)
                ip = ".".join(reversed(name[: -len(".in-addr.arpa")].split(".")))
                out[ip] = target.rstrip(".")
            off += rdlen
    except (ValueError, struct.error, IndexError):
        pass
    return out


def mdns_names(ips: list[str], local_addr: str, timeout: float = 2.0) -> dict[str, str]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    out: dict[str, str] = {}
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_addr))
        except OSError:
            pass
        s.bind(("", 0))
        s.setblocking(False)
        for i, ip in enumerate(ips):
            try:
                s.sendto(mdns_query(ip, i + 1), ("224.0.0.251", 5353))
            except OSError:
                pass
            time.sleep(0.003)
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([s], [], [], 0.1)
            if not r:
                continue
            try:
                data, _src = s.recvfrom(4096)
            except OSError:
                continue
            out.update(parse_ptr_answers(data))
    finally:
        s.close()
    return out


# ---------------------------------------------------------------- ポート
def service_name(port: int) -> str:
    if port in EXTRA_SERVICES:
        return EXTRA_SERVICES[port]
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return ""


def tcp_scan(ip: str, ports: list[int], timeout: float = 0.8, parallel: int = 64,
             progress=None, stop=None) -> list[int]:
    """TCP の接続確認。接続できたポートの一覧を返す（接続後すぐ閉じる）。"""
    opened: list[int] = []
    todo = list(ports)
    done = 0
    sel = selectors.DefaultSelector()
    try:
        while todo:
            if stop is not None and stop.is_set():
                break
            batch, todo = todo[:parallel], todo[parallel:]
            socks = {}
            for p in batch:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setblocking(False)
                rc = s.connect_ex((ip, p))
                if rc in (0, 115, 11, 10035, 10036):       # 0 / EINPROGRESS / EAGAIN / WSA
                    socks[s] = p
                    sel.register(s, selectors.EVENT_WRITE)
                else:
                    s.close()
            end = time.time() + timeout
            while socks and time.time() < end:
                for key, _ev in sel.select(timeout=max(0.0, end - time.time())):
                    s = key.fileobj
                    p = socks.pop(s)
                    sel.unregister(s)
                    if s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                        opened.append(p)
                    s.close()
            for s in list(socks):
                sel.unregister(s)
                s.close()
            done += len(batch)
            if progress:
                progress(done, len(ports), len(opened))
    finally:
        sel.close()
    return sorted(opened)


# ---------------------------------------------------------------- 保存と差分
def host_key(h: dict) -> str:
    return h.get("mac") or h["ip"]


def load_previous(directory: str, network: str, exclude: str | None = None) -> dict | None:
    """同じネットワークの直前の結果（JSON）を返す。"""
    try:
        files = sorted(f for f in os.listdir(directory) if f.startswith("scan_") and f.endswith(".json"))
    except OSError:
        return None
    for f in reversed(files):
        path = os.path.join(directory, f)
        if exclude and os.path.abspath(path) == os.path.abspath(exclude):
            continue
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            continue
        if data.get("network") == network:
            return data
    return None


def diff(prev: dict | None, hosts: list[dict]) -> tuple[set[str], list[dict]]:
    """(新しく見えたホストのキー, 前回いて今回いないホスト)。前回が無ければ差分なし。"""
    if not prev:
        return set(), []
    old = {host_key(h): h for h in prev.get("hosts", [])}
    cur = {host_key(h) for h in hosts}
    return cur - set(old), [h for k, h in old.items() if k not in cur]


def save(directory: str, result: dict, path: str | None = None) -> str:
    os.makedirs(directory, exist_ok=True)
    if path is None:
        path = os.path.join(directory, time.strftime("scan_%Y%m%d_%H%M%S.json",
                                                      time.localtime(result["time"])))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    csv = path[:-5] + ".csv"
    with open(csv, "w", encoding="utf-8") as f:
        f.write("ip,mac,vendor,name,rtt_ms,via,open_ports\n")
        for h in result["hosts"]:
            name = (h.get("mdns") or h.get("dns") or "").replace('"', '""')
            vendor = h.get("vendor", "").replace('"', '""')
            ports = " ".join(str(p) for p in h.get("ports") or [])
            rtt = "" if h.get("rtt_ms") is None else f'{h["rtt_ms"]:.1f}'
            f.write(f'{h["ip"]},{h.get("mac", "")},"{vendor}","{name}",{rtt},{h.get("via", "")},{ports}\n')
    return path
