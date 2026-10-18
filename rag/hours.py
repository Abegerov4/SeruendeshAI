"""Conservative subset of OSM hours. Unsupported syntax is always unknown."""
import re
from datetime import datetime, timedelta, timezone

ASTANA = timezone(timedelta(hours=5))
DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

def _days(expr):
    result = set()
    for item in expr.split(','):
        bounds = item.split('-')
        start = DAYS.index(bounds[0])
        end = DAYS.index(bounds[-1])
        result.update((start + i) % 7 for i in range((end-start) % 7 + 1))
    return result

def _minute(text):
    hour, minute = map(int, text.split(':'))
    if minute > 59 or hour > 24 or (hour == 24 and minute):
        raise ValueError('Invalid time')
    return hour * 60 + minute

def open_status(opening_hours: str | None, dt: datetime) -> tuple[str, str]:
    if not opening_hours or not opening_hours.strip():
        return 'unknown', 'none'
    value = opening_hours.strip()
    if value == '24/7':
        return 'open', 'high'
    if value in ('off', 'closed'):
        return 'closed', 'high'
    local = dt.replace(tzinfo=ASTANA) if dt.tzinfo is None else dt.astimezone(ASTANA)
    # Build a weekly minute calendar; later rules override the selected days.
    calendar = bytearray(7 * 1440)
    try:
        for rule in value.split(';'):
            match = re.fullmatch(r'\s*(?:(\w{2}(?:-\w{2})?(?:,\w{2}(?:-\w{2})?)*)\s+)?(off|closed|\d{2}:\d{2}-\d{2}:\d{2}(?:,\s*\d{2}:\d{2}-\d{2}:\d{2})*)\s*', rule)
            if not match:
                return 'unknown', 'none'
            selected = _days(match[1]) if match[1] else set(range(7))
            for day in selected:
                calendar[day*1440:(day+1)*1440] = bytes(1440)
            if match[2] in ('off', 'closed'):
                continue
            for span in match[2].split(','):
                start, end = map(_minute, span.strip().split('-'))
                if start == 1440 or start == end:
                    return 'unknown', 'none'
                if end < start:
                    end += 1440
                for day in selected:
                    for minute in range(start, end):
                        calendar[(day*1440 + minute) % len(calendar)] = 1
    except (ValueError, IndexError):
        return 'unknown', 'none'
    return ('open' if calendar[local.weekday()*1440 + local.hour*60 + local.minute] else 'closed'), 'high'
