"""Tests for infra/time_guard.py (protected windows)."""
import datetime as dt
import os
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "infra"))
import time_guard as tg  # noqa: E402

ET = ZoneInfo("America/New_York")


def at(day, h, m):  # 2026-10-22 is a Thursday, 2026-10-24 a Saturday
    return dt.datetime(2026, 10, day, h, m, tzinfo=ET)


class TestTimeGuard(unittest.TestCase):
    def test_default_windows(self):
        self.assertTrue(tg.blocked(at(22, 9, 30)))
        self.assertTrue(tg.blocked(at(22, 15, 59)))
        self.assertFalse(tg.blocked(at(22, 16, 30)))
        self.assertTrue(tg.blocked(at(22, 18, 0)))
        self.assertFalse(tg.blocked(at(22, 19, 0)))

    def test_strict_only_19_to_0930(self):
        for h, m, b in [(9, 29, False), (9, 30, True), (12, 0, True), (16, 30, True), (18, 29, True),
                        (18, 59, True), (19, 0, False), (23, 0, False), (4, 0, False)]:
            self.assertEqual(tg.blocked(at(22, h, m), strict=True), b, (h, m))

    def test_weekend_open(self):
        self.assertFalse(tg.blocked(at(24, 12, 0), strict=True))


if __name__ == "__main__":
    unittest.main()
