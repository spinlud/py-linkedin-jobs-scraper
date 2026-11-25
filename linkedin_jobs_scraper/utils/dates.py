"""Derive an approximate ISO date from LinkedIn's relative date text.

The job detail panel exposes no machine-readable date, only relative text such as
"Reposted 8 hours ago" or "2 weeks ago". These helpers turn that text into an
approximate 'YYYY-MM-DD' string. They are pure so they can be unit-tested without a
browser; the current time is injected rather than read internally.
"""

import re
from datetime import datetime, timedelta

# Days assumed per unit. Weeks/months/years are approximations, since the relative text
# carries no exact date.
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365

# Leading "Posted"/"Reposted" prefix LinkedIn puts in front of the relative text.
_LEADING_PREFIX_RE = re.compile(r'^\s*re?posted\b', re.IGNORECASE)

# "just now" and sub-hour granularities all resolve to the current day.
_TODAY_RE = re.compile(r'\b(just now|\d+\s+(?:minute|hour)s?\s+ago)\b', re.IGNORECASE)

# "N <unit> ago" where the unit is day/week/month/year.
_RELATIVE_RE = re.compile(r'(\d+)\s+(day|week|month|year)s?\s+ago', re.IGNORECASE)

_UNIT_DAYS = {
    'day': 1,
    'week': DAYS_PER_WEEK,
    'month': DAYS_PER_MONTH,
    'year': DAYS_PER_YEAR,
}


def parse_relative_date(text: str, now: datetime) -> str:
    """Return an approximate ISO 'YYYY-MM-DD' date for LinkedIn's relative date text.

    A leading "Posted"/"Reposted" prefix is stripped. "just now" and minute/hour
    granularities resolve to now's date; day/week/month/year subtract the corresponding
    number of days (weeks, months and years approximated at 7, 30 and 365 days). Returns
    an empty string when nothing matches.
    """
    if not text:
        return ''

    stripped = _LEADING_PREFIX_RE.sub('', text).strip()

    if _TODAY_RE.search(stripped):
        return now.date().isoformat()

    match = _RELATIVE_RE.search(stripped)

    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        days = amount * _UNIT_DAYS[unit]
        return (now - timedelta(days=days)).date().isoformat()

    return ''
