import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from celery.schedules import crontab, schedule
from celery.utils.time import maybe_make_aware

from redbeat import RedBeatSchedulerEntry
from redbeat.decoder import RedBeatJSONDecoder, from_timestamp, to_timestamp
from tests.basecase import RedBeatCase

CELERY_CONFIG_DEFAULT_KWARGS = {}


class test_RedBeatEntry(RedBeatCase):
    def test_basic_save(self):
        e = self.create_entry()
        e.save()

        expected = {
            'name': 'test',
            'task': 'tasks.test',
            'schedule': e.schedule,
            'args': None,
            'kwargs': CELERY_CONFIG_DEFAULT_KWARGS,
            'options': {},
            'enabled': True,
        }
        expected_key = self.app.redbeat_conf.key_prefix + 'test'

        redis = self.app.redbeat_redis
        value = redis.hget(expected_key, 'definition')
        self.assertEqual(expected, json.loads(value, cls=RedBeatJSONDecoder))
        self.assertEqual(redis.zrank(self.app.redbeat_conf.schedule_key, e.key), 0)
        self.assertEqual(redis.zscore(self.app.redbeat_conf.schedule_key, e.key), e.score)

    def test_from_key_nonexistent_key(self):
        with self.assertRaises(KeyError):
            RedBeatSchedulerEntry.from_key('doesntexist', self.app)

    def test_from_key_missing_meta(self):
        initial = self.create_entry().save()

        loaded = RedBeatSchedulerEntry.from_key(initial.key, self.app)
        self.assertEqual(initial.task, loaded.task)
        self.assertIsNotNone(loaded.last_run_at)

    def test_next(self):
        initial = self.create_entry().save()
        now = self.app.now()
        # 3.x is naive but 4.x is aware
        now = maybe_make_aware(now)

        n = initial.next(last_run_at=now)

        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(n.last_run_at, now)
        self.assertEqual(initial.total_run_count + 1, n.total_run_count)

        # updated meta was stored into redis
        loaded = RedBeatSchedulerEntry.from_key(initial.key, app=self.app)
        self.assertEqual(loaded.last_run_at, now)
        self.assertEqual(loaded.total_run_count, initial.total_run_count + 1)

        # new entry updated the schedule
        redis = self.app.redbeat_redis
        self.assertEqual(redis.zscore(self.app.redbeat_conf.schedule_key, n.key), n.score)

    def test_next_only_update_last_run_at(self):
        initial = self.create_entry()

        n = initial.next(only_update_last_run_at=True)
        self.assertGreater(n.last_run_at, initial.last_run_at)
        self.assertEqual(n.total_run_count, initial.total_run_count)

    def test_delete(self):
        initial = self.create_entry()
        initial.save()

        e = RedBeatSchedulerEntry.from_key(initial.key, app=self.app)
        e.delete()

        exists = self.app.redbeat_redis.exists(initial.key)
        self.assertFalse(exists)

        score = self.app.redbeat_redis.zrank(self.app.redbeat_conf.schedule_key, initial.key)
        self.assertIsNone(score)

    def test_due_at_never_run(self):
        entry = self.create_entry(last_run_at=datetime.min)

        before = entry._default_now()
        due_at = entry.due_at
        after = entry._default_now()

        self.assertLess(before, due_at)
        self.assertLess(due_at, after)

    def test_due_at(self):
        entry = self.create_entry()

        now = entry._default_now()

        entry.last_run_at = now
        due_at = entry.due_at

        self.assertLess(now, due_at)
        self.assertLess(due_at, now + entry.schedule.run_every)

    def test_due_at_overdue(self):
        last_run_at = self.app.now() - timedelta(hours=10)
        entry = self.create_entry(last_run_at=last_run_at)

        before = entry._default_now()
        due_at = entry.due_at

        self.assertLess(last_run_at, due_at)
        self.assertGreater(due_at, before)

    def test_due_at_counts_from_now(self):
        # remaining_estimate is measured from now, not from last_run_at (#210)
        now = self.app.now()
        s = schedule(run_every=60, nowfun=lambda: now, app=self.app)
        entry = self.create_entry(s=s, last_run_at=now - timedelta(seconds=30))

        self.assertEqual(entry.due_at, now + timedelta(seconds=30))

    def test_score(self):
        run_every = 61 * 60
        entry = self.create_entry(run_every=run_every)
        entry = entry._next_instance()

        score = entry.score
        expected = entry.last_run_at + timedelta(seconds=run_every)
        expected = expected.replace(microsecond=0)  # discard microseconds, lost in timestamp
        # 3.x returns naive, but 4.x returns aware
        expected = maybe_make_aware(expected)

        self.assertEqual(score, to_timestamp(expected))
        self.assertEqual(expected, from_timestamp(score))

    def test_generate_key(self) -> None:
        entry = self.create_entry()

        key = entry.generate_key(app=self.app, name="mock_task_name")

        self.assertEqual(key, "redbeat:mock_task_name")

    @patch.object(RedBeatSchedulerEntry, "generate_key")
    def test_key(self, mock_generate_key: MagicMock) -> None:
        entry = self.create_entry()

        key = entry.key

        mock_generate_key.assert_called_once_with(app=self.app, name="test")

        self.assertEqual(key, mock_generate_key.return_value)


class test_RedBeatEntryDaylightSaving(RedBeatCase):
    # In 2026 the autumn change is on 25 Oct and in 2027 the spring change is
    # on 28 Mar, both at 01:00 UTC.
    config_dict = {'timezone': 'Europe/Amsterdam'}

    def score_after_run(self, last_run_utc, saved_after=timedelta(seconds=1)):
        """Score of a daily 22:00 local entry, saved `saved_after` its last run."""
        last_run_at = last_run_utc.astimezone(self.app.timezone)
        now = last_run_at + saved_after
        s = crontab(minute=0, hour=22, nowfun=lambda: now, app=self.app)
        entry = self.create_entry(s=s, last_run_at=last_run_at)
        return from_timestamp(entry.score)

    def test_score_on_a_normal_day(self):
        self.assertEqual(
            self.score_after_run(datetime(2026, 10, 27, 21, 0, tzinfo=timezone.utc)),
            datetime(2026, 10, 28, 21, 0, tzinfo=timezone.utc),
        )

    def test_score_across_autumn_change(self):
        # 22:00 CEST is 20:00 UTC, the next 22:00 CET is 21:00 UTC: 25 hours later
        self.assertEqual(
            self.score_after_run(datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)),
            datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc),
        )

    def test_score_across_spring_change(self):
        self.assertEqual(
            self.score_after_run(datetime(2027, 3, 27, 21, 0, tzinfo=timezone.utc)),
            datetime(2027, 3, 28, 20, 0, tzinfo=timezone.utc),
        )

    def test_score_saved_hours_after_run(self):
        self.assertEqual(
            self.score_after_run(
                datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc),
                saved_after=timedelta(hours=2),
            ),
            datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc),
        )
