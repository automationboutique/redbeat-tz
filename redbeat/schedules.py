try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

from datetime import datetime, timezone

from celery import schedules as celery_schedules
from celery.schedules import BaseSchedule as schedule
from celery.schedules import schedstate
from dateutil.rrule import DAILY, HOURLY, MINUTELY, MONTHLY, SECONDLY, WEEKLY, YEARLY
from dateutil.rrule import rrule as dateutil_rrule


class rrule(schedule):
    RRULE_REPR = (
        '<rrule: freq: {0.freq}, dtstart: {0.dtstart}, interval: {0.interval}, '
        'wkst: {0.wkst}, count: {0.count}, until: {0.until}, bysetpos: {0.bysetpos}, '
        'bymonth: {0.bymonth}, bymonthday: {0.bymonthday}, byyearday: {0.byyearday}, '
        'byeaster: {0.byeaster}, byweekno: {0.byweekno}, byweekday: {0.byweekday}, '
        'byhour: {0.byhour}, byminute: {0.byminute}, bysecond: {0.bysecond}>'
    )

    FREQ_MAP = {
        'YEARLY': YEARLY,
        'MONTHLY': MONTHLY,
        'WEEKLY': WEEKLY,
        'DAILY': DAILY,
        'HOURLY': HOURLY,
        'MINUTELY': MINUTELY,
        'SECONDLY': SECONDLY,
    }

    def __init__(
        self,
        freq,
        dtstart=None,
        interval=1,
        wkst=None,
        count=None,
        until=None,
        bysetpos=None,
        bymonth=None,
        bymonthday=None,
        byyearday=None,
        byeaster=None,
        byweekno=None,
        byweekday=None,
        byhour=None,
        byminute=None,
        bysecond=None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if type(freq) is str:
            freq_str = freq.upper()
            assert freq_str in rrule.FREQ_MAP
            freq = rrule.FREQ_MAP[freq_str]

        dtstart = (
            self.maybe_make_aware(dtstart)
            if dtstart
            else self.maybe_make_aware(self.now())
        )
        until = self.maybe_make_aware(until) if until else None

        self.freq = freq
        self.dtstart = dtstart
        self.interval = interval
        self.wkst = wkst
        self.count = count
        self.until = until
        self.bysetpos = bysetpos
        self.bymonth = bymonth
        self.bymonthday = bymonthday
        self.byyearday = byyearday
        self.byeaster = byeaster
        self.byweekno = byweekno
        self.byweekday = byweekday
        self.byhour = byhour
        self.byminute = byminute
        self.bysecond = bysecond
        self.rrule = dateutil_rrule(
            freq,
            dtstart,
            interval,
            wkst,
            count,
            until,
            bysetpos,
            bymonth,
            bymonthday,
            byyearday,
            byeaster,
            byweekno,
            byweekday,
            byhour,
            byminute,
            bysecond,
        )

    def remaining_estimate(self, last_run_at):
        last_run_at = self.maybe_make_aware(last_run_at)
        next_run = self.rrule.after(last_run_at)
        if next_run:
            next_run = self.maybe_make_aware(next_run)
            now = self.maybe_make_aware(self.now())
            delta = next_run - now
            return delta
        return None

    def is_due(self, last_run_at):
        rem_delta = self.remaining_estimate(last_run_at)
        if rem_delta is not None:
            rem = max(rem_delta.total_seconds(), 0)
            due = rem == 0
            if due:
                rem_delta = self.remaining_estimate(self.now())
                if rem_delta is not None:
                    rem = max(rem_delta.total_seconds(), 0)
                else:
                    rem = None
            return schedstate(due, rem)
        return schedstate(False, None)

    def __repr__(self):
        return self.RRULE_REPR.format(self)

    def __reduce__(self):
        return (self.__class__, (self.rrule), None)


class TzAwareCrontab(celery_schedules.crontab):
    """Timezone Aware Crontab schedule implementation.

    Mirrors the behavior of django-celery-beat's TzAwareCrontab to ensure
    per-entry timezone handling and DST-correct scheduling.
    """

    def __init__(
        self,
        minute='*',
        hour='*',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
        tz=timezone.utc,
        app=None,
    ):
        # Normalize tz: accept IANA string or tzinfo
        if isinstance(tz, str):
            tz = zoneinfo.ZoneInfo(tz)
        self.tz = tz

        # Use instance nowfunc bound to the provided timezone
        nowfun = self.nowfunc

        super().__init__(
            minute=minute,
            hour=hour,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            month_of_year=month_of_year,
            nowfun=nowfun,
            app=app,
        )

    def nowfunc(self):
        return datetime.now(self.tz)

    def is_due(self, last_run_at):
        """Calculate when the next run will take place.

        Return tuple of (is_due, next_time_to_check).
        The last_run_at argument needs to be timezone aware.
        """
        # convert last_run_at to the schedule timezone
        last_run_at = last_run_at.astimezone(self.tz)

        rem_delta = self.remaining_estimate(last_run_at)
        rem = max(rem_delta.total_seconds(), 0)
        due = rem == 0
        if due:
            rem_delta = self.remaining_estimate(self.now())
            rem = max(rem_delta.total_seconds(), 0)
        return schedstate(due, rem)

    def __repr__(self):
        return """<crontab: {0._orig_minute} {0._orig_hour}
         {0._orig_day_of_week} {0._orig_day_of_month}
          {0._orig_month_of_year} (m/h/d/dM/MY), {0.tz}>
        """.format(self)

    def __reduce__(self):
        return (
            self.__class__,
            (
                self._orig_minute,
                self._orig_hour,
                self._orig_day_of_week,
                self._orig_day_of_month,
                self._orig_month_of_year,
                self.tz,
            ),
            None,
        )

    def __eq__(self, other):
        if isinstance(other, celery_schedules.crontab):
            return (
                other.month_of_year == self.month_of_year
                and other.day_of_month == self.day_of_month
                and other.day_of_week == self.day_of_week
                and other.hour == self.hour
                and other.minute == self.minute
                and getattr(other, 'tz', None) == self.tz
            )
        return NotImplemented
