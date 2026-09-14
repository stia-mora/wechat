"""Body collection window in the project's Shanghai timezone."""

import os
from datetime import UTC, datetime, timedelta, timezone


def body_since():
    return datetime.fromisoformat(os.getenv("BODY_SINCE", "2026-06-01")).replace(
        tzinfo=timezone(timedelta(hours=8))
    )


def eligible(published):
    if not published:
        return False
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published, UTC)
    return published >= body_since()
