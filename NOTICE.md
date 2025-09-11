RedBeat-TZ: Per-entry timezone support (DST-aware)

Overview
--------
This fork introduces a timezone-aware crontab schedule, `TzAwareCrontab`, that accepts IANA timezone names (e.g., "America/New_York") to compute due times correctly across DST transitions. The goal is to provide per-entry timezone behavior similar to Django Celery Beat's `TzAwareCrontab`, while keeping changes minimal and backward compatible with existing RedBeat deployments.

What changed (minimal and surgical)
-----------------------------------
- Added `TzAwareCrontab` in `redbeat/schedules.py`, a subclass of `celery.schedules.crontab` that:
  - Accepts `tz` as an IANA string or tzinfo.
  - Uses a timezone-bound `nowfunc()` and converts `last_run_at` to the entry timezone in `is_due()`.
  - Preserves equality and pickling semantics similar to Django Celery Beat.
- Extended JSON serialization in `redbeat/decoder.py`:
  - Encoder emits `{"__type__": "crontab", ..., "tz": "<IANA>"}` for `TzAwareCrontab`.
  - Decoder reconstructs `TzAwareCrontab` when `'tz'` is present; falls back to legacy `crontab` (UTC) otherwise.
- No changes to scheduler logic; per-entry tz is encapsulated in the schedule object.

Usage
-----
Create a tz-aware crontab entry:

```python
from redbeat.schedules import TzAwareCrontab

schedule = TzAwareCrontab(minute='30', hour='2', tz='America/New_York')
```

Compatibility
-------------
- Existing crontab entries without a `tz` field continue to behave as UTC.
- New entries may provide an IANA tz string; values are stored and round-tripped through Redis.

Behavior inspiration
--------------------
This implementation mirrors the behavior of Django Celery Beat's timezone-aware crontab for predictable DST handling:

- Reference: django_celery_beat.tzcrontab — https://django-celery-beat.readthedocs.io/en/latest/_modules/django_celery_beat/tzcrontab.html

Apache License NOTICE
---------------------
This project includes and modifies code under the Apache License, Version 2.0. See `LICENSE` at the repo root. The RedBeat project is the upstream source for this fork. The DST-aware crontab behavior is inspired by the design in Django Celery Beat's tz-aware crontab implementation.


Changelog
---------------------
- **v2.3.3-tz.1** – Initial release  
  Forked from upstream RedBeat v2.3.3. Adds per-entry timezone support via the new `TzAwareCrontab` schedule, enabling correct DST-aware scheduling without breaking existing UTC-based entries.
