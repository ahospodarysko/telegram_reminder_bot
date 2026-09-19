"""Unit tests for the location -> IANA timezone lookup used by the /timezone flow."""

from __future__ import annotations

import unittest

from bot.geo import timezone_from_location
from bot.scheduling import is_valid_timezone


class TimezoneFromLocationTests(unittest.TestCase):
    def test_known_city_resolves_to_its_timezone(self):
        self.assertEqual(timezone_from_location(51.5074, -0.1278), "Europe/London")

    def test_result_is_a_valid_timezone_bot_accepts(self):
        # Whatever timezonefinder returns must round-trip through the bot's own
        # validator, since it's fed straight into db.set_timezone.
        tz = timezone_from_location(40.7128, -74.0060)  # New York
        self.assertTrue(is_valid_timezone(tz))
