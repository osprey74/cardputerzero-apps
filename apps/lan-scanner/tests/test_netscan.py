"""netscan のテスト（ネットワークに触れない部分）。python -m unittest discover -s apps/lan-scanner/tests"""
import gzip
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import netscan as ns  # noqa: E402

ADDR = [
    {"ifname": "lo", "flags": ["LOOPBACK", "UP"], "addr_info": [
        {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"}]},
    {"ifname": "wlan0", "flags": ["BROADCAST", "UP", "LOWER_UP"], "addr_info": [
        {"family": "inet", "local": "192.168.10.26", "prefixlen": 24, "scope": "global"}]},
    {"ifname": "eth0", "flags": ["BROADCAST"], "addr_info": [
        {"family": "inet", "local": "10.0.0.5", "prefixlen": 24, "scope": "global"}]},
    {"ifname": "tailscale0", "flags": ["UP"], "addr_info": [
        {"family": "inet", "local": "100.64.0.9", "prefixlen": 32, "scope": "global"}]},
]
ROUTE = [{"dst": "default", "gateway": "192.168.10.1", "dev": "wlan0"}]
NEIGH = [
    {"dst": "192.168.10.1", "lladdr": "1c:7c:98:00:00:01", "state": ["STALE"]},
    {"dst": "192.168.10.13", "lladdr": "1a:ec:e7:00:00:02", "state": ["REACHABLE"]},
    {"dst": "192.168.10.99", "state": ["FAILED"]},
    {"dst": "192.168.10.50", "lladdr": "00:00:00:00:00:00", "state": ["INCOMPLETE"]},
]


def dns_name(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


class NetscanTest(unittest.TestCase):
    def test_interfaces(self):
        ifs = ns.interfaces(ADDR, ROUTE)
        self.assertEqual(len(ifs), 1)                       # lo・DOWN の eth0・/32 は除外
        self.assertEqual(ifs[0]["ifname"], "wlan0")
        self.assertEqual(ifs[0]["gateway"], "192.168.10.1")

    def test_scan_network(self):
        net, hosts, narrowed = ns.scan_network("192.168.10.26", 24)
        self.assertEqual(str(net), "192.168.10.0/24")
        self.assertEqual(len(hosts), 253)                   # 本機を除く
        self.assertNotIn("192.168.10.26", hosts)
        self.assertFalse(narrowed)
        net, hosts, narrowed = ns.scan_network("10.1.2.3", 16)
        self.assertEqual(str(net), "10.1.2.0/24")
        self.assertTrue(narrowed)

    def test_neighbors(self):
        n = ns.neighbors("wlan0", NEIGH)
        self.assertEqual(set(n), {"192.168.10.1", "192.168.10.13"})
        self.assertEqual(n["192.168.10.1"], "1C:7C:98:00:00:01")

    def test_echo_checksum(self):
        pkt = ns.echo_packet(5)
        self.assertEqual(ns._checksum(pkt), 0)              # 正しいチェックサムなら全体の和は 0

    def test_mdns_roundtrip(self):
        q = ns.mdns_query("192.168.10.13", 7)
        self.assertIn(dns_name("13.10.168.192.in-addr.arpa"), q)
        self.assertEqual(q[-4:], struct.pack("!HH", 12, 0x8001))
        # 応答: 質問 1 件＋ PTR 回答（名前は圧縮ポインタで質問を指す）
        qname = dns_name("13.10.168.192.in-addr.arpa")
        target = dns_name("my-printer.local")
        resp = (struct.pack("!HHHHHH", 7, 0x8400, 1, 1, 0, 0) + qname + struct.pack("!HH", 12, 1)
                + b"\xc0\x0c" + struct.pack("!HHIH", 12, 0x8001, 120, len(target)) + target)
        self.assertEqual(ns.parse_ptr_answers(resp), {"192.168.10.13": "my-printer.local"})
        self.assertEqual(ns.parse_ptr_answers(b"\x00\x01"), {})

    def test_oui(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "oui.tsv.gz")
            with gzip.open(p, "wt", encoding="utf-8") as f:
                f.write("1C7C98\tExample Corp\n")
            o = ns.OUI(p)
            self.assertEqual(o.vendor("1c:7c:98:00:00:01"), "Example Corp")
            self.assertEqual(o.vendor("1A:EC:E7:00:00:02"), "（ランダム化 MAC）")
            self.assertEqual(o.vendor("00:11:22:33:44:55"), "")
            self.assertEqual(ns.OUI(None).vendor("1C:7C:98:00:00:01"), "")

    def test_save_diff(self):
        with tempfile.TemporaryDirectory() as d:
            h1 = [{"ip": "192.168.10.1", "mac": "AA"}, {"ip": "192.168.10.2", "mac": "BB"}]
            ns.save(d, {"time": 1_700_000_000, "network": "192.168.10.0/24", "hosts": h1})
            prev = ns.load_previous(d, "192.168.10.0/24")
            self.assertIsNotNone(prev)
            self.assertIsNone(ns.load_previous(d, "10.0.0.0/24"))
            new, gone = ns.diff(prev, [{"ip": "192.168.10.1", "mac": "AA"}, {"ip": "192.168.10.3", "mac": ""}])
            self.assertEqual(new, {"192.168.10.3"})
            self.assertEqual([g["mac"] for g in gone], ["BB"])
            self.assertEqual(ns.diff(None, h1), (set(), []))
            csv = [f for f in os.listdir(d) if f.endswith(".csv")]
            self.assertEqual(len(csv), 1)

    def test_service_name(self):
        self.assertEqual(ns.service_name(1883), "mqtt")


if __name__ == "__main__":
    unittest.main()
