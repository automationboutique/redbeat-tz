from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

from celery.utils.time import timezone

from redbeat.schedules import TzAwareCrontab, rrule

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo


@patch.object(rrule, 'now', datetime.utcnow)
@patch.object(rrule, 'utc_enabled', True)
@patch.object(rrule, 'tz', timezone.utc)
class test_rrule_remaining_estimate(TestCase):
    def test_freq(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow() + timedelta(minutes=1))
        eta_from_now = r.remaining_estimate(datetime.utcnow())
        eta_after_one_minute = r.remaining_estimate(datetime.utcnow() + timedelta(minutes=1))
        self.assertTrue(eta_from_now.total_seconds() > 0)
        self.assertTrue(eta_after_one_minute.total_seconds() > 0)

    def test_freq__with_single_count(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow() + timedelta(minutes=1), count=1)
        eta_from_now = r.remaining_estimate(datetime.utcnow())
        eta_after_one_minute = r.remaining_estimate(datetime.utcnow() + timedelta(minutes=1))
        self.assertTrue(eta_from_now.total_seconds() > 0)
        self.assertEqual(eta_after_one_minute, None)

    def test_freq__with_multiple_count(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow() + timedelta(minutes=1), count=2)
        eta_from_now = r.remaining_estimate(datetime.utcnow())
        eta_after_one_minute = r.remaining_estimate(datetime.utcnow() + timedelta(minutes=1))
        eta_after_two_minutes = r.remaining_estimate(datetime.utcnow() + timedelta(minutes=2))
        self.assertTrue(eta_from_now.total_seconds() > 0)
        self.assertTrue(eta_after_one_minute.total_seconds() > 0)
        self.assertEqual(eta_after_two_minutes, None)


class test_tzaware_crontab_dst(TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo('America/New_York')

    def test_spring_forward_nonexistent_0230(self):
        # DST starts 2025-03-09 in America/New_York; 02:00 -> 03:00 (02:30 nonexistent)
        cron = TzAwareCrontab(minute='30', hour='2', tz='America/New_York')
        # Set deterministic "now" just before jump
        cron.nowfun = lambda: datetime(2025, 3, 9, 1, 59, tzinfo=self.tz)
        # Last successful run was previous day at 02:30
        last_run_at = datetime(2025, 3, 8, 2, 30, tzinfo=self.tz)
        # Remaining time until next occurrence should be positive
        eta = cron.remaining_estimate(last_run_at)
        self.assertTrue(eta.total_seconds() > 0)

        # Move now to 03:00 on DST day; 02:30 does not occur, so not due
        cron.nowfun = lambda: datetime(2025, 3, 9, 3, 0, tzinfo=self.tz)
        is_due, nxt = cron.is_due(last_run_at)
        self.assertFalse(is_due)
        self.assertTrue(nxt is None or nxt > 0)

    def test_fall_back_ambiguous_0130_runs_once(self):
        # DST ends 2025-11-02 in America/New_York; 01:00 repeats
        cron = TzAwareCrontab(minute='30', hour='1', tz='America/New_York')

        # First, at 00:59 before first 01:30 (deterministic now)
        cron.nowfun = lambda: datetime(2025, 11, 2, 0, 59, tzinfo=self.tz)
        last_run_prev_day = datetime(2025, 11, 1, 1, 30, tzinfo=self.tz)
        eta1 = cron.remaining_estimate(last_run_prev_day)
        self.assertTrue(eta1.total_seconds() > 0)

        # During the first ambiguous hour window at 01:30 (fold=0), it should be due once
        cron.nowfun = lambda: datetime(2025, 11, 2, 1, 30, tzinfo=self.tz, fold=0)
        is_due_first, next_first = cron.is_due(last_run_prev_day)
        self.assertTrue(is_due_first)
        self.assertTrue(next_first > 0)

        # After the first run has occurred, later in the repeated hour (still fold=0)
        cron.nowfun = lambda: datetime(2025, 11, 2, 1, 45, tzinfo=self.tz, fold=0)
        is_due_second_window, next_second_window = cron.is_due(
            datetime(2025, 11, 2, 1, 30, tzinfo=self.tz, fold=0)
        )
        # Should not run a second time in the repeated hour
        self.assertFalse(is_due_second_window)
        # next should be positive (towards next day occurrence)
        self.assertTrue(next_second_window is None or next_second_window > 0)

    def test_mixed_app_utc_vs_entry_tz(self):
        # App tz treated as UTC in our tests; ensure schedule evaluation follows entry tz
        cron = TzAwareCrontab(minute='0', hour='0', tz='America/New_York')
        # Case A (not due): same-day last_run_at at midnight, now at 00:30
        last_same_day = datetime(2025, 1, 10, 0, 0, tzinfo=self.tz)
        cron.nowfun = lambda: datetime(2025, 1, 10, 0, 30, tzinfo=self.tz)
        is_due_ny, next_ny = cron.is_due(last_same_day)
        self.assertFalse(is_due_ny)
        self.assertTrue(next_ny > 0)

        # Case B (due): previous-day last_run_at, now at midnight
        last_prev = datetime(2025, 1, 9, 0, 0, tzinfo=self.tz)
        cron.nowfun = lambda: datetime(2025, 1, 10, 0, 0, tzinfo=self.tz)
        is_due_midnight, next_midnight = cron.is_due(last_prev)
        self.assertTrue(is_due_midnight)
        self.assertTrue(next_midnight > 0)


@patch.object(rrule, 'now', datetime.utcnow)
@patch.object(rrule, 'utc_enabled', True)
@patch.object(rrule, 'tz', timezone.utc)
class test_rrule_is_due(TestCase):
    def test_freq__starting_now(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow())
        # Assuming job was never run, i.e. last_run_at == epoch
        is_due, next = r.is_due(datetime(1970, 1, 1))
        self.assertTrue(is_due)
        self.assertTrue(next > 0)

    def test_freq__starts_after_one_minute(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow() + timedelta(minutes=1))
        is_due, next = r.is_due(datetime.utcnow())
        self.assertFalse(is_due)
        self.assertTrue(next > 0)

    def test_freq__with_single_count(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow(), count=1)
        # If job was never run, it should be due and have
        # no ETA for the following occurrence.
        is_due, next = r.is_due(datetime(1970, 1, 1))
        self.assertTrue(is_due)
        self.assertEqual(next, None)
        # It should not be due if it was already run once.
        is_due, next = r.is_due(datetime.utcnow())
        self.assertFalse(is_due)
        self.assertEqual(next, None)

    def test_freq__with_multiple_count(self):
        r = rrule('MINUTELY', dtstart=datetime.utcnow(), count=2)
        is_due, next = r.is_due(datetime(1970, 1, 1))
        self.assertTrue(is_due)
        self.assertTrue(next > 0)
        # There should still be one more occurrence remaining
        # if it was run once after dtstart.
        is_due, next = r.is_due(datetime.utcnow())
        self.assertFalse(is_due)
        self.assertTrue(next > 0)
        # There should be no more occurrences after one minute.
        is_due, next = r.is_due(datetime.utcnow() + timedelta(minutes=1))
        self.assertFalse(is_due)
        self.assertEqual(next, None)
