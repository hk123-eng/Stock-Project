"""Exit 1 if now is inside a protected window (hard rule 7):
weekday US market hours 09:30-16:00 ET, or 18:00-19:00 ET (30 min around the 18:30 ET scheduled run).
--strict (final run items 2 and 3, owner rule 2026-10-22): on weekdays only 19:00 ET -> 09:30 ET is allowed,
i.e. 09:30-19:00 ET is blocked (this also covers 16:00-18:30 ET)."""
import datetime as dt
import sys
from zoneinfo import ZoneInfo


def blocked(now, strict=False):
    t = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return False
    if strict:
        return 9 * 60 + 30 <= t < 19 * 60
    return 9 * 60 + 30 <= t < 16 * 60 or 18 * 60 <= t < 19 * 60


if __name__ == "__main__":
    strict = "--strict" in sys.argv
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    b = blocked(now, strict)
    print(f"now {now:%a %Y-%m-%d %H:%M} ET{' (strict)' if strict else ''} -> {'BLOCKED' if b else 'ok'}")
    sys.exit(1 if b else 0)
