from __future__ import annotations

import datetime
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DEFAULT_TIMEZONE_NAME = "UTC"
_OFFSET_PATTERN = re.compile(r"^(UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


def _parse_utc_gmt_offset(raw_value: str):
    match = _OFFSET_PATTERN.fullmatch(raw_value)
    if not match:
        return None

    sign = 1 if match.group(2) == "+" else -1
    hours = int(match.group(3))
    minutes = int(match.group(4) or 0)
    if hours > 23 or minutes > 59:
        return None

    delta = datetime.timedelta(hours=hours, minutes=minutes)
    offset = sign * delta
    normalized_name = f"UTC{match.group(2)}{hours:02d}:{minutes:02d}"
    return normalized_name, datetime.timezone(offset, name=normalized_name)


def _resolve_configured_timezone():
    raw_timezone = str(os.getenv("TIMEZONE", _DEFAULT_TIMEZONE_NAME)).strip()
    if not raw_timezone:
        raw_timezone = _DEFAULT_TIMEZONE_NAME

    try:
        return raw_timezone, ZoneInfo(raw_timezone)
    except ZoneInfoNotFoundError:
        pass

    parsed_offset = _parse_utc_gmt_offset(raw_timezone)
    if parsed_offset is not None:
        return parsed_offset

    return _DEFAULT_TIMEZONE_NAME, datetime.timezone.utc


def get_configured_timezone_name() -> str:
    timezone_name, _ = _resolve_configured_timezone()
    return timezone_name


def get_configured_timezone() -> datetime.tzinfo:
    _, timezone_info = _resolve_configured_timezone()
    return timezone_info


def now_in_configured_timezone() -> datetime.datetime:
    return datetime.datetime.now(get_configured_timezone())


def today_in_configured_timezone() -> datetime.date:
    return now_in_configured_timezone().date()


def today_iso_in_configured_timezone() -> str:
    return today_in_configured_timezone().isoformat()
