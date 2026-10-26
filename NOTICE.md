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
- One scheduler fix in `redbeat/schedulers.py`: `RedBeatSchedulerEntry.due_at` adds the time left to the current time in UTC. Upstream adds it to `last_run_at`. In a timezone with daylight saving that follows the wall clock, so the first run after the autumn clock change fires an hour late. Upstream issue #210 reports a related error in the same line.

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

Branches and releases
---------------------
- `main` mirrors upstream `sibson/redbeat`. Never commit to it.
- Each `tz/<line>` branch (for example `tz/2.4.x`) is an upstream release tag plus this fork's commits. The newest one is the default branch.
- The version is the upstream version plus `.postN`, for example `2.4.2.post1`. Set it in both `version` fields of `setup.cfg`. pbr reads the version from git, not from `setup.cfg`, so build with `PBR_VERSION` set (see below), or the wheel gets a `.devN` version.
- To move to a new upstream release, start a new `tz/` branch from the upstream tag and cherry-pick this fork's commits onto it (`git log <old upstream tag>..tz/<old line>` lists them). Never force-push a `tz/` branch once it is pushed.
- Actions are off on this fork and should stay off: upstream's `publish.yml` publishes to PyPI. Run the tests locally:

      uv venv --python 3.13 .venv
      uv pip install -r requirements-dev.txt -e .
      .venv/bin/python -m unittest discover tests

- To release: build with `PBR_VERSION=<version> uv build`, push the branch, push only the new tag (never `git push --tags`), then `gh release create <tag> -R automationboutique/redbeat-tz --target <branch> dist/*`.

Apache License NOTICE
---------------------
This project includes and modifies code under the Apache License, Version 2.0. See `LICENSE` at the repo root. The RedBeat project is the upstream source for this fork. The DST-aware crontab behavior is inspired by the design in Django Celery Beat's tz-aware crontab implementation.


Changelog
---------------------
- **v2.4.2.post1** – Rebased onto upstream RedBeat v2.4.2.  
  Fixes `due_at`: the first run after the autumn clock change no longer fires an hour late, and an entry saved some time after its last run no longer gets an early score.
- **v2.3.3.post1** – Initial release  
  Forked from upstream RedBeat v2.3.3. Adds per-entry timezone support via the new `TzAwareCrontab` schedule, enabling correct DST-aware scheduling without breaking existing UTC-based entries.
