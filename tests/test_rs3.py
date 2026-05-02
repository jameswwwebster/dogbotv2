"""Pure-Python tests for RS3 parsers and reset arithmetic.

Run with `python -m unittest discover tests`. No network access; the
hiscores test feeds a synthetic CSV through the parser and the resets
test pins datetime.now() through a fixed argument.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from rs3 import api, resets


class HiscoresParserTests(unittest.TestCase):
    SAMPLE_CSV = "\n".join([
        # Overall + 28 skills (Lite endpoint as of late 2025 / early 2026)
        "1234,2738,500000000",
        "5000,99,13034431",   # Attack
        "5100,99,13034431",   # Defence
        "4900,99,13034431",   # Strength
        "5200,99,14391160",   # Constitution
        "6000,99,13034431",   # Ranged
        "7000,99,13034431",   # Prayer
        "5500,99,13034431",   # Magic
        "8000,99,13034431",   # Cooking
        "9000,99,13034431",   # Woodcutting
        "9500,99,13034431",   # Fletching
        "9800,99,13034431",   # Fishing
        "9900,99,13034431",   # Firemaking
        "8500,99,13034431",   # Crafting
        "9100,99,13034431",   # Smithing
        "8700,99,13034431",   # Mining
        "8800,99,13034431",   # Herblore
        "9200,99,13034431",   # Agility
        "9400,99,13034431",   # Thieving
        "8200,99,13034431",   # Slayer
        "8600,99,13034431",   # Farming
        "9700,99,13034431",   # Runecrafting
        "9300,99,13034431",   # Hunter
        "9600,99,13034431",   # Construction
        "8900,99,13034431",   # Summoning
        "8400,120,200000000", # Dungeoneering
        "9000,99,13034431",   # Divination
        "7500,150,1000000000",# Invention
        "5700,120,104273167", # Archaeology
        "3500,99,13034431",   # Necromancy
    ])

    def test_parses_csv_into_skills(self):
        profile = api.parse_hiscores_csv(self.SAMPLE_CSV, username="Bob")
        self.assertEqual(profile.username, "Bob")
        self.assertEqual(len(profile.skills), len(api.HISCORES_SKILLS))
        self.assertEqual(profile.overall.level, 2738)
        self.assertEqual(profile.overall.xp, 500_000_000)

    def test_lookup_by_name(self):
        profile = api.parse_hiscores_csv(self.SAMPLE_CSV, username="Bob")
        invention = profile.by_name("Invention")
        self.assertIsNotNone(invention)
        self.assertEqual(invention.level, 150)
        self.assertEqual(invention.xp, 1_000_000_000)

    def test_pads_missing_trailing_skills(self):
        truncated = "\n".join(self.SAMPLE_CSV.splitlines()[:5])
        profile = api.parse_hiscores_csv(truncated, username="Pre-Necro")
        self.assertEqual(len(profile.skills), len(api.HISCORES_SKILLS))
        # Padded entries are unranked level-1
        self.assertEqual(profile.skills[-1].rank, -1)
        self.assertEqual(profile.skills[-1].level, 1)


class GePriceTests(unittest.TestCase):
    def test_parse_price_handles_int(self):
        self.assertEqual(api._parse_price(1234), 1234)

    def test_parse_price_handles_k_suffix(self):
        self.assertEqual(api._parse_price("12.5k"), 12_500)

    def test_parse_price_handles_m_suffix(self):
        self.assertEqual(api._parse_price("1.5m"), 1_500_000)

    def test_parse_price_handles_b_suffix(self):
        self.assertEqual(api._parse_price("2.1b"), 2_100_000_000)

    def test_parse_price_handles_commas(self):
        self.assertEqual(api._parse_price("1,234,567"), 1_234_567)

    def test_parse_price_handles_garbage(self):
        self.assertEqual(api._parse_price("???"), 0)


class ResetArithmeticTests(unittest.TestCase):
    UTC = timezone.utc

    def test_daily_reset_today_before_firing(self):
        now = datetime(2026, 5, 2, 6, 30, tzinfo=self.UTC)
        nxt = resets.next_occurrence(resets.get("daily"), now)
        self.assertEqual(nxt, datetime(2026, 5, 3, 0, 0, tzinfo=self.UTC))

    def test_daily_reset_today_at_firing_jumps_to_tomorrow(self):
        # Spec: "<= now" rolls forward to avoid returning the past.
        now = datetime(2026, 5, 2, 0, 0, tzinfo=self.UTC)
        nxt = resets.next_occurrence(resets.get("daily"), now)
        self.assertEqual(nxt, datetime(2026, 5, 3, 0, 0, tzinfo=self.UTC))

    def test_weekly_reset_lands_on_wednesday(self):
        # Friday 2026-05-08 → next Wed is 2026-05-13 00:00.
        now = datetime(2026, 5, 8, 12, 0, tzinfo=self.UTC)
        nxt = resets.next_occurrence(resets.get("weekly"), now)
        self.assertEqual(nxt.weekday(), 2)
        self.assertEqual(nxt, datetime(2026, 5, 13, 0, 0, tzinfo=self.UTC))

    def test_weekly_reset_on_wednesday_after_firing_rolls_a_week(self):
        now = datetime(2026, 5, 6, 0, 30, tzinfo=self.UTC)  # Wed 00:30
        nxt = resets.next_occurrence(resets.get("weekly"), now)
        self.assertEqual(nxt, datetime(2026, 5, 13, 0, 0, tzinfo=self.UTC))

    def test_hourly_reset(self):
        now = datetime(2026, 5, 2, 14, 30, tzinfo=self.UTC)
        nxt = resets.next_occurrence(resets.get("flash"), now)
        self.assertEqual(nxt, datetime(2026, 5, 2, 15, 0, tzinfo=self.UTC))

    def test_format_timedelta(self):
        self.assertEqual(resets.format_timedelta(timedelta(days=2, hours=3, minutes=4)), "2d 3h 4m")
        self.assertEqual(resets.format_timedelta(timedelta(hours=5, minutes=10)), "5h 10m")
        self.assertEqual(resets.format_timedelta(timedelta(minutes=7, seconds=8)), "7m 8s")
        self.assertEqual(resets.format_timedelta(timedelta(seconds=42)), "42s")
        self.assertEqual(resets.format_timedelta(timedelta(seconds=-100)), "0s")


if __name__ == "__main__":
    unittest.main()
