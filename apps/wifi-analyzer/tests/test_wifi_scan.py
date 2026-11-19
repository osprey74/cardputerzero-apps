"""wifi_scan の解析部分のテスト（python -m unittest discover -s apps/wifi-analyzer/tests）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wifi_scan import Scanner, parse_list, parse_proc_wireless, split_terse  # noqa: E402

NMCLI = (
    " :02\\:00\\:00\\:00\\:00\\:01:Demo\\:Colon:2:2417 MHz:130 Mbit/s:92:WPA2:20 MHz\n"
    "*:02\\:00\\:00\\:00\\:00\\:02:Back\\\\slash:11:2462 MHz:270 Mbit/s:85:WPA1 WPA2:40 MHz\n"
    " :02\\:00\\:00\\:00\\:00\\:03::6:2437 MHz:54 Mbit/s:30::20 MHz\n"
    "broken line\n"
)

PROC = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   61.  -49.  -256        0      0      0      1      0        0
"""


class ParseTest(unittest.TestCase):
    def test_split_escapes(self):
        self.assertEqual(split_terse(r"a\:b:c\\d:"), ["a:b", "c\\d", ""])

    def test_parse_list(self):
        rows = parse_list(NMCLI)
        self.assertEqual(len(rows), 3)
        a, b, c = rows
        self.assertEqual(a["bssid"], "02:00:00:00:00:01")
        self.assertEqual(a["ssid"], "Demo:Colon")
        self.assertEqual((a["chan"], a["freq"], a["rate"], a["signal"], a["width"]), (2, 2417, 130, 92, 20))
        self.assertFalse(a["in_use"])
        self.assertTrue(b["in_use"])
        self.assertEqual(b["ssid"], "Back\\slash")
        self.assertEqual(b["width"], 40)
        self.assertEqual(c["ssid"], "")
        self.assertEqual(c["security"], "")

    def test_proc_wireless(self):
        self.assertEqual(parse_proc_wireless(PROC), -49.0)
        self.assertIsNone(parse_proc_wireless(PROC, "wlan1"))

    def test_ingest_history_and_security(self):
        sc = Scanner()
        sc.ingest(parse_list(NMCLI), 100.0)
        sc.ingest(parse_list(NMCLI), 110.0)
        aps = {a.bssid: a for a in sc.snapshot()}
        self.assertEqual(len(aps["02:00:00:00:00:01"].hist), 2)
        self.assertEqual(aps["02:00:00:00:00:01"].sec_short, "WPA2")
        self.assertEqual(aps["02:00:00:00:00:02"].sec_short, "WPA2")
        self.assertEqual(aps["02:00:00:00:00:03"].sec_short, "OPEN")
        sc.ingest([], 200.0)                       # 60 秒より長く見えない AP は外れる
        self.assertEqual(sc.snapshot(), [])

    def test_fallback_without_rescan(self):
        calls = []
        def runner(rescan):
            calls.append(rescan)
            return (1, "", "Error: Scanning not allowed") if rescan == "yes" else (0, NMCLI, "")
        sc = Scanner(runner=runner)
        sc.scan_once()
        self.assertEqual(calls, ["yes", "no"])
        self.assertEqual(len(sc.snapshot()), 3)
        self.assertEqual(sc.error, "")


if __name__ == "__main__":
    unittest.main()
