"""Helpers for parsing coarse time values used across agents."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def extract_year(value: Any) -> int | None:
    """Extract a 4-digit year from int/date/datetime/string values."""
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, datetime):
        return value.year

    if isinstance(value, date):
        return value.year

    if isinstance(value, str):
        match = re.search(r"\b(19|20)\d{2}\b", value)
        if match:
            return int(match.group(0))

    return None
