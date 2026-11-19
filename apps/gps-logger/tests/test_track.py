"""track（GPX 記録・統計・修復）のテスト。python -m unittest discover -s apps/gps-logger/tests
座標はすべて架空の値。"""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from track import Recorder, Stats, haversine, recover  # noqa: E402

NS = {"g": "http://www.topografix.com/GPX/1/1"}
T0 = datetime(2026, 11, 19, 3, 0, 0)


def snap(i, lat, lon, spd=20.0, alt=50.0):
    return {"state": "fix", "lat": lat, "lon": lon, "alt": alt, "speed_kmh": spd, "hdop": 0.9,
            "mode": 3, "sats": 10, "utc": T0 + timedelta(seconds=i)}


class TrackTest(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(haversine(35.0, 135.0, 35.0 + 1 / 111.2, 135.0), 1000, delta=2)
        self.assertEqual(haversine(35.0, 135.0, 35.0, 135.0), 0.0)

    def test_stats_ignore_jitter_when_still(self):
        s = Stats()
        for i in range(30):                                   # 止まったまま数 m ふらつく
            s.add(35.0 + (i % 2) * 2e-5, 135.0, 50.0, 0.3, 0.9, 3, float(i))
        self.assertEqual(s.distance_m, 0.0)
        self.assertEqual(s.moving_s, 0.0)

    def test_stats_distance_speed_gain(self):
        s = Stats()
        for i in range(11):                                   # 北へ 10 m/s で 100 m、5 m 登る
            s.add(35.0 + i * 10 / 111195.0, 135.0, 50.0 + i * 0.5, 36.0, 0.9, 3, float(i))
        self.assertAlmostEqual(s.distance_m, 100.0, delta=1.0)
        self.assertAlmostEqual(s.moving_s, 10.0)
        self.assertAlmostEqual(s.avg_kmh(), 36.0, delta=0.5)
        self.assertEqual(s.max_kmh, 36.0)
        self.assertGreaterEqual(s.gain_m, 3.0)
        s.add(35.01, 135.0, 50.0, 500.0, 0.9, 3, 11.0)         # 誤測位の速度は最高速度に入れない
        self.assertEqual(s.max_kmh, 36.0)

    def test_record_pause_resume_stop(self):
        with tempfile.TemporaryDirectory() as d:
            r = Recorder(d)
            self.assertFalse(r.add(snap(0, 35.0, 135.0)))     # 記録前は書かない
            path = r.start(T0)
            for i in range(5):
                self.assertTrue(r.add(snap(i, 35.0 + i * 1e-4, 135.0)))
            self.assertFalse(r.add(snap(4, 35.0005, 135.0)))  # 同じ時刻は重複として捨てる
            self.assertFalse(r.add({"state": "search"}))
            r.pause()
            self.assertFalse(r.add(snap(10, 35.01, 135.0)))   # 一時停止中は書かない
            r.resume()
            for i in range(20, 23):
                r.add(snap(i, 35.001 + i * 1e-5, 135.0))
            self.assertEqual(r.stop(), path)
            self.assertIsNone(r.stop())
            root = ET.parse(path).getroot()
            segs = root.findall("g:trk/g:trkseg", NS)
            self.assertEqual([len(s.findall("g:trkpt", NS)) for s in segs], [5, 3])
            pt = segs[0].find("g:trkpt", NS)
            self.assertEqual(pt.find("g:time", NS).text, "2026-11-19T03:00:00Z")
            self.assertEqual(pt.find("g:fix", NS).text, "3d")
            self.assertEqual(r.stats.points, 8)

    def test_recover_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            r = Recorder(d)
            path = r.start(T0)
            for i in range(3):
                r.add(snap(i, 35.0 + i * 1e-4, 135.0))
            r._f.write('      <trkpt lat="35.1" lo')          # 書きかけで電池が切れた
            r._f.close()
            self.assertEqual(recover(d), [path])
            root = ET.parse(path).getroot()                  # 壊れていない XML になる
            self.assertEqual(len(root.findall("g:trk/g:trkseg/g:trkpt", NS)), 3)
            self.assertEqual(recover(d), [])                 # 2 回目は何もしない


if __name__ == "__main__":
    unittest.main()
