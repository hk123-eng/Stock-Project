"""Exit 1 if now is inside a protected window (hard rule 7):
weekday US market hours 09:30-16:00 ET, or 18:00-19:00 ET (30 min around the 18:30 ET scheduled run)."""
import datetime as dt
import sys
from zoneinfo import ZoneInfo

now = dt.datetime.now(ZoneInfo("America/New_York"))
t = now.hour * 60 + now.minute
weekday = now.weekday() < 5
blocked = weekday and (9 * 60 + 30 <= t < 16 * 60 or 18 * 60 <= t < 19 * 60)
print(f"now {now:%a %Y-%m-%d %H:%M} ET -> {'BLOCKED' if blocked else 'ok'}")
sys.exit(1 if blocked else 0)
