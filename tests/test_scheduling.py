"""Unit tests for the time-critical logic: offsets, past-offset skipping, timezone
conversion, the "due now" query, and input parsing."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from bot import db, i18n
from bot.scheduler import roll_recurring
from bot.scheduling import (
    ParseError,
    compute_occurrences,
    local_to_utc,
    next_monthly_due,
    parse_reminder_input,
    plan_occurrences,
    shift_out_of_quiet_hours,
    utc_to_local,
)

UTC = timezone.utc


def labels(occurrences):
    return [label for label, _ in occurrences]


class ComputeOccurrencesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    def test_both_when_created_more_than_24h_out(self):
        due = self.now + timedelta(hours=30)
        occ = compute_occurrences(due, self.now)
        self.assertEqual(labels(occ), ["-24h", "-2h"])
        self.assertEqual([fire for _, fire in occ],
                         [due - timedelta(hours=24), due - timedelta(hours=2)])

    def test_skips_past_offset_when_created_8h_out(self):
        # -24h is already in the past; only the -2h ping remains.
        due = self.now + timedelta(hours=8)
        self.assertEqual(labels(compute_occurrences(due, self.now)), ["-2h"])

    def test_none_when_created_within_2h(self):
        # Both offsets are in the past — no at-due ping exists anymore.
        due = self.now + timedelta(hours=1)
        self.assertEqual(compute_occurrences(due, self.now), [])

    def test_none_when_deadline_already_passed(self):
        due = self.now - timedelta(hours=1)
        self.assertEqual(compute_occurrences(due, self.now), [])


class TimezoneConversionTests(unittest.TestCase):
    def test_summer_offset_new_york(self):
        # 2026-07-01 12:00 EDT (UTC-4) -> 16:00 UTC.
        utc = local_to_utc(datetime(2026, 7, 1, 12, 0), "America/New_York")
        self.assertEqual(utc, datetime(2026, 7, 1, 16, 0, tzinfo=UTC))

    def test_winter_offset_new_york(self):
        # 2026-01-01 12:00 EST (UTC-5) -> 17:00 UTC.
        utc = local_to_utc(datetime(2026, 1, 1, 12, 0), "America/New_York")
        self.assertEqual(utc, datetime(2026, 1, 1, 17, 0, tzinfo=UTC))

    def test_round_trip_preserves_wall_clock(self):
        naive = datetime(2026, 7, 1, 12, 0)
        utc = local_to_utc(naive, "Europe/Kyiv")
        back = utc_to_local(utc, "Europe/Kyiv")
        self.assertEqual(back.replace(tzinfo=None), naive)

    def test_invalid_timezone_raises(self):
        with self.assertRaises(ValueError):
            local_to_utc(datetime(2026, 1, 1, 9, 0), "Mars/Phobos")


class DueOccurrenceQueryTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        db.upsert_user(self.conn, 1, "UTC", self.now)

    def test_returns_only_past_unsent_active(self):
        due = self.now + timedelta(hours=2)
        past = ("-6h", self.now - timedelta(minutes=1))   # already due
        future = ("0", self.now + timedelta(hours=1))      # not yet due
        rid = db.add_reminder(self.conn, 1, "Appt", due, [past, future], self.now)

        rows = db.get_due_occurrences(self.conn, self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["offset"], "-6h")
        self.assertEqual(rows[0]["reminder_id"], rid)
        self.assertEqual(rows[0]["timezone"], "UTC")

    def test_marked_sent_is_not_returned(self):
        rid = db.add_reminder(
            self.conn, 1, "Appt", self.now + timedelta(hours=1),
            [("0", self.now - timedelta(minutes=1))], self.now,
        )
        row = db.get_due_occurrences(self.conn, self.now)[0]
        db.mark_sent(self.conn, row["occurrence_id"])
        self.assertEqual(db.get_due_occurrences(self.conn, self.now), [])

    def test_cancelled_reminder_occurrences_not_returned(self):
        rid = db.add_reminder(
            self.conn, 1, "Appt", self.now + timedelta(hours=1),
            [("0", self.now - timedelta(minutes=1))], self.now,
        )
        db.set_status(self.conn, rid, "cancelled")
        self.assertEqual(db.get_due_occurrences(self.conn, self.now), [])

    def tearDown(self):
        self.conn.close()


class ParsingTests(unittest.TestCase):
    # A fixed "now" in the user's local time for deterministic year defaulting.
    NOW = datetime(2026, 6, 1, 12, 0)

    def test_parse_reminder_input_valid(self):
        p = parse_reminder_input("Doctor appointment @ June 21 16:00", self.NOW)
        self.assertEqual(p.note, "Doctor appointment")
        self.assertEqual(p.when, datetime(2026, 6, 21, 16, 0))
        self.assertEqual(p.recurrence, "none")
        self.assertIsNone(p.anchor_day)

    def test_parse_reminder_input_uses_current_year(self):
        self.assertEqual(parse_reminder_input("Note @ December 31 09:00", self.NOW).when.year, 2026)

    def test_parse_reminder_input_rolls_to_next_year_when_past(self):
        # "March 1" entered in June has already passed this year -> next year.
        p = parse_reminder_input("Taxes @ March 1 09:00", self.NOW)
        self.assertEqual(p.when, datetime(2027, 3, 1, 9, 0))

    def test_parse_reminder_input_accepts_abbrev_and_day_first(self):
        a = parse_reminder_input("x @ Jun 21 16:00", self.NOW)
        b = parse_reminder_input("x @ 21 June 16:00", self.NOW)
        self.assertEqual(a.when, datetime(2026, 6, 21, 16, 0))
        self.assertEqual(b.when, datetime(2026, 6, 21, 16, 0))

    def test_parse_reminder_input_ukrainian_month(self):
        # Genitive "червня" (June) and day-first order, as Ukrainian dates are written.
        p = parse_reminder_input("Прийом @ 21 червня 16:00", self.NOW)
        self.assertEqual(p.note, "Прийом")
        self.assertEqual(p.when, datetime(2026, 6, 21, 16, 0))

    def test_parse_reminder_input_ukrainian_month_nominative(self):
        p = parse_reminder_input("x @ грудень 31 09:00", self.NOW)
        self.assertEqual(p.when, datetime(2026, 12, 31, 9, 0))

    def test_parse_reminder_input_note_with_separator(self):
        # Splitting on the LAST separator keeps an "@" inside the note intact.
        p = parse_reminder_input("Email @bob about lunch @ June 21 16:00", self.NOW)
        self.assertEqual(p.note, "Email @bob about lunch")
        self.assertEqual(p.when, datetime(2026, 6, 21, 16, 0))

    def test_parse_reminder_input_missing_delimiter(self):
        with self.assertRaises(ParseError):
            parse_reminder_input("Doctor appointment June 21 16:00", self.NOW)

    def test_parse_reminder_input_bad_datetime(self):
        for bad in ("Note @ 21/06 4pm", "Note @ Funday 99 16:00", "Note @ February 30 10:00"):
            with self.assertRaises(ParseError):
                parse_reminder_input(bad, self.NOW)

    def test_parse_reminder_input_empty_note(self):
        with self.assertRaises(ParseError):
            parse_reminder_input(" @ June 21 16:00", self.NOW)


class RecurringParsingTests(unittest.TestCase):
    NOW = datetime(2026, 6, 1, 12, 0)

    def test_monthly_keyword(self):
        p = parse_reminder_input("Pay rent @ monthly 5 09:00", self.NOW)
        self.assertEqual(p.note, "Pay rent")
        self.assertEqual(p.recurrence, "monthly")
        self.assertEqual(p.anchor_day, 5)
        self.assertEqual(p.when, datetime(2026, 6, 5, 9, 0))

    def test_every_month_synonym(self):
        p = parse_reminder_input("Pay rent @ every month 5 09:00", self.NOW)
        self.assertEqual((p.recurrence, p.anchor_day), ("monthly", 5))
        self.assertEqual(p.when, datetime(2026, 6, 5, 9, 0))

    def test_ukrainian_synonyms(self):
        for text in ("Оренда @ щомісяця 5 09:00", "Оренда @ кожного місяця 5 09:00"):
            p = parse_reminder_input(text, self.NOW)
            self.assertEqual((p.recurrence, p.anchor_day), ("monthly", 5), text)
            self.assertEqual(p.when, datetime(2026, 6, 5, 9, 0), text)

    def test_first_due_rolls_to_next_month_when_passed(self):
        # Day 1 at 09:00 has already passed on 1 Jun 12:00 -> first due is 1 Jul.
        p = parse_reminder_input("x @ monthly 1 09:00", self.NOW)
        self.assertEqual(p.when, datetime(2026, 7, 1, 9, 0))
        self.assertEqual(p.anchor_day, 1)

    def test_first_due_clamps_short_month(self):
        # Day 31 in June (30 days) clamps to 30 Jun, but the anchor stays 31.
        p = parse_reminder_input("x @ monthly 31 09:00", self.NOW)
        self.assertEqual(p.when, datetime(2026, 6, 30, 9, 0))
        self.assertEqual(p.anchor_day, 31)

    def test_bad_recurrence_raises(self):
        for bad in ("x @ monthly 09:00", "x @ monthly 45 09:00", "x @ monthly 5"):
            with self.assertRaises(ParseError, msg=bad):
                parse_reminder_input(bad, self.NOW)

    def test_force_monthly_without_keyword(self):
        # Type picker chose monthly: no keyword needed, just day + time.
        p = parse_reminder_input("Pay rent @ 5 09:00", self.NOW, force_recurrence="monthly")
        self.assertEqual((p.recurrence, p.anchor_day), ("monthly", 5))
        self.assertEqual(p.when, datetime(2026, 6, 5, 9, 0))

    def test_force_monthly_strips_typed_keyword(self):
        p = parse_reminder_input("Pay rent @ monthly 5 09:00", self.NOW, force_recurrence="monthly")
        self.assertEqual((p.recurrence, p.anchor_day), ("monthly", 5))

    def test_force_none_parses_one_shot(self):
        p = parse_reminder_input("Doctor @ June 21 16:00", self.NOW, force_recurrence="none")
        self.assertEqual(p.recurrence, "none")
        self.assertEqual(p.when, datetime(2026, 6, 21, 16, 0))


class NextMonthlyDueTests(unittest.TestCase):
    def test_clamps_to_feb_non_leap(self):
        prev = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
        self.assertEqual(next_monthly_due(prev, 31, "UTC", prev),
                         datetime(2026, 2, 28, 9, 0, tzinfo=UTC))

    def test_clamps_to_feb_leap(self):
        prev = datetime(2028, 1, 31, 9, 0, tzinfo=UTC)
        self.assertEqual(next_monthly_due(prev, 31, "UTC", prev),
                         datetime(2028, 2, 29, 9, 0, tzinfo=UTC))

    def test_anchor_day_preserved_when_month_has_it(self):
        # Previous cycle clamped to 30 Jun; July has a 31st, so the anchor reasserts.
        prev = datetime(2026, 6, 30, 9, 0, tzinfo=UTC)
        self.assertEqual(next_monthly_due(prev, 31, "UTC", prev),
                         datetime(2026, 7, 31, 9, 0, tzinfo=UTC))

    def test_catch_up_skips_fully_past_months(self):
        # Host was off; now is well past two cycles -> jump to the next future one.
        prev = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
        now = datetime(2026, 3, 20, 0, 0, tzinfo=UTC)
        self.assertEqual(next_monthly_due(prev, 15, "UTC", now),
                         datetime(2026, 4, 15, 9, 0, tzinfo=UTC))

    def test_year_rollover(self):
        prev = datetime(2026, 12, 5, 9, 0, tzinfo=UTC)
        self.assertEqual(next_monthly_due(prev, 5, "UTC", prev),
                         datetime(2027, 1, 5, 9, 0, tzinfo=UTC))

    def test_dst_keeps_wall_clock(self):
        # 09:00 local on the 5th must stay 09:00 across the spring DST change in New York
        # (EST UTC-5 -> EDT UTC-4): the UTC instant shifts from 14:00 to 13:00.
        tz = "America/New_York"
        prev = local_to_utc(datetime(2026, 3, 5, 9, 0), tz)  # 14:00 UTC (EST)
        result = next_monthly_due(prev, 5, tz, prev)
        self.assertEqual(result, datetime(2026, 4, 5, 13, 0, tzinfo=UTC))
        self.assertEqual(utc_to_local(result, tz).hour, 9)


class RollForwardTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        db.upsert_user(self.conn, 1, "UTC", self.now)

    def tearDown(self):
        self.conn.close()

    def _add_monthly(self, due, anchor_day=5):
        return db.add_reminder(
            self.conn, 1, "Rent", due, [], self.now,
            recurrence="monthly", anchor_day=anchor_day,
        )

    def test_get_due_recurring_returns_active_past(self):
        rid = self._add_monthly(datetime(2026, 6, 5, 9, 0, tzinfo=UTC))
        rows = db.get_due_recurring(self.conn, self.now)
        self.assertEqual([r["reminder_id"] for r in rows], [rid])

    def test_cancelled_recurring_not_due(self):
        rid = self._add_monthly(datetime(2026, 6, 5, 9, 0, tzinfo=UTC))
        db.set_status(self.conn, rid, "cancelled")
        self.assertEqual(db.get_due_recurring(self.conn, self.now), [])

    def test_one_shot_not_returned_as_recurring(self):
        db.add_reminder(self.conn, 1, "Once", datetime(2026, 6, 5, 9, 0, tzinfo=UTC), [], self.now)
        self.assertEqual(db.get_due_recurring(self.conn, self.now), [])

    def test_roll_forward_advances_and_replans(self):
        rid = self._add_monthly(datetime(2026, 6, 5, 9, 0, tzinfo=UTC), anchor_day=5)
        row = db.get_due_recurring(self.conn, self.now)[0]
        next_due = roll_recurring(self.conn, row["reminder_id"], row["due_at_utc"],
                                  row["anchor_day"], row["timezone"], self.now)
        self.assertEqual(next_due, datetime(2026, 7, 5, 9, 0, tzinfo=UTC))
        r = db.get_reminder(self.conn, rid)
        self.assertEqual(db.from_db(r["due_at_utc"]), next_due)
        self.assertEqual(r["status"], "active")
        self.assertTrue(db.get_pending_occurrences(self.conn, rid))


class QuietHoursTests(unittest.TestCase):
    # Use UTC so local time == the datetimes below.
    TZ = "UTC"

    def _at(self, h, m=0, day=20):
        return datetime(2026, 7, day, h, m, tzinfo=UTC)

    def test_daytime_unchanged(self):
        self.assertEqual(shift_out_of_quiet_hours(self._at(13), self.TZ), self._at(13))

    def test_eight_am_boundary_allowed(self):
        self.assertEqual(shift_out_of_quiet_hours(self._at(8), self.TZ), self._at(8))

    def test_before_eight_moves_to_eight_same_day(self):
        self.assertEqual(shift_out_of_quiet_hours(self._at(1), self.TZ), self._at(8))
        self.assertEqual(shift_out_of_quiet_hours(self._at(7, 59), self.TZ), self._at(8))

    def test_late_night_moves_to_next_morning(self):
        self.assertEqual(shift_out_of_quiet_hours(self._at(22), self.TZ), self._at(8, day=21))
        self.assertEqual(shift_out_of_quiet_hours(self._at(23, 30), self.TZ), self._at(8, day=21))

    def test_morning_deadline_shifts_2h_ping(self):
        # Due 20 Jul 09:00; -2h (07:00) is in quiet hours -> 08:00. -24h (19 Jul 09:00) ok.
        due = self._at(9)
        now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        fire_times = [fire for _, fire in plan_occurrences(due, now, self.TZ)]
        self.assertEqual(fire_times, [self._at(9, day=19), self._at(8)])

    def test_daytime_deadline_not_shifted(self):
        # Due 20 Jul 13:00; -24h (19 Jul 13:00) and -2h (11:00) are both daytime.
        due = self._at(13)
        now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        fire_times = [fire for _, fire in plan_occurrences(due, now, self.TZ)]
        self.assertEqual(fire_times, [self._at(13, day=19), self._at(11)])

    def test_sorted_and_future_only(self):
        due = self._at(9)
        now = self._at(10, day=19)  # past the -24h ping, before the shifted -2h ping
        planned = plan_occurrences(due, now, self.TZ)
        self.assertEqual([fire for _, fire in planned], [self._at(8)])

    def test_fallback_at_deadline_when_too_close(self):
        # Created 1h before a 13:00 deadline: both offsets are past -> at-due fallback.
        due = self._at(13)
        now = self._at(12)
        planned = plan_occurrences(due, now, self.TZ)
        self.assertEqual(planned, [("0", self._at(13))])

    def test_fallback_respects_quiet_hours(self):
        # Created 22:00 for a 23:30 deadline: both offsets past, deadline is in quiet
        # hours -> at-due fallback shifts to 08:00 next morning.
        due = self._at(23, 30)
        now = self._at(22)
        planned = plan_occurrences(due, now, self.TZ)
        self.assertEqual(planned, [("0", self._at(8, day=21))])

    def test_no_fallback_when_deadline_passed(self):
        due = self._at(13)
        now = self._at(14)
        self.assertEqual(plan_occurrences(due, now, self.TZ), [])

    def test_no_fallback_when_an_offset_survives(self):
        # -2h still in the future -> no at-due fallback added.
        due = self._at(13)
        now = self._at(9)
        labels_ = [label for label, _ in plan_occurrences(due, now, self.TZ)]
        self.assertEqual(labels_, ["-2h"])


class LocalizationTests(unittest.TestCase):
    def test_every_key_exists_in_every_language(self):
        # Each language must define exactly the same set of keys as English.
        en_keys = set(i18n.TEXT["en"])
        for lang in i18n.LANGUAGES:
            self.assertEqual(set(i18n.TEXT[lang]), en_keys, f"key mismatch in {lang}")

    def test_normalize_lang(self):
        self.assertEqual(i18n.normalize_lang("uk"), "uk")
        self.assertEqual(i18n.normalize_lang("en-US"), "en")
        self.assertEqual(i18n.normalize_lang(None), "en")
        self.assertEqual(i18n.normalize_lang("de"), "en")  # unsupported -> default

    def test_t_formats_and_differs_by_language(self):
        en = i18n.t("en", "cb_done_msg", text="Buy milk")
        uk = i18n.t("uk", "cb_done_msg", text="Buy milk")
        self.assertIn("Buy milk", en)
        self.assertIn("Buy milk", uk)
        self.assertNotEqual(en, uk)

    def test_format_when_localized_month(self):
        dt = datetime(2026, 6, 21, 16, 0, tzinfo=UTC)
        self.assertEqual(i18n.format_when(dt, "UTC", "en"), "Sun 21 Jun 16:00")
        self.assertEqual(i18n.format_when(dt, "UTC", "uk"), "Нд 21 чер 16:00")


if __name__ == "__main__":
    unittest.main()
