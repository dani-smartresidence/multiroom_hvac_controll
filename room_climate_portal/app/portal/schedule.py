"""Turn calendar events into the room schedule shown on the page.

Precondition start = event start - lead time. The lead time comes from the room's
lead-time entity (minutes); an event can override it with a line like
``precondition: 60`` in its description, and set its target with ``target: 22``.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TARGET_RE = re.compile(r"(?:target|tinta|țintă|ținta|temp(?:eratura)?)\s*[:=]\s*(\d{1,2}(?:[.,]\d+)?)", re.I)
LEAD_RE = re.compile(r"(?:precondition(?:ing)?|precondi[tț]ionare|lead)\s*[:=]\s*(\d{1,3})", re.I)


def parse_target(text: str | None) -> float | None:
    m = TARGET_RE.search(text or "")
    return float(m.group(1).replace(",", ".")) if m else None


def parse_lead(text: str | None) -> int | None:
    m = LEAD_RE.search(text or "")
    return int(m.group(1)) if m else None


def lead_minutes_from_state(state: dict | None, default: int) -> int:
    """Minutes from a sensor / input_number state; supports h/s units too."""
    if not state:
        return default
    try:
        value = float(state.get("state"))
    except (TypeError, ValueError):
        return default
    unit = ((state.get("attributes") or {}).get("unit_of_measurement") or "min").lower()
    if unit in ("h", "hr", "hours"):
        value *= 60
    elif unit in ("s", "sec", "seconds"):
        value /= 60
    return max(0, min(int(round(value)), 24 * 60))


def _parse_when(value: str, tz: ZoneInfo) -> tuple[datetime, bool]:
    if len(value) == 10:  # all-day: YYYY-MM-DD
        d = date.fromisoformat(value)
        return datetime(d.year, d.month, d.day, tzinfo=tz), True
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz), False


def build_events(
    raw_events: list[dict],
    *,
    lead_minutes: int,
    default_target: float,
    tz: ZoneInfo,
    now: datetime,
) -> list[dict]:
    out = []
    for ev in raw_events:
        try:
            start, all_day = _parse_when(ev["start"], tz)
            end, _ = _parse_when(ev["end"], tz)
        except (KeyError, ValueError):
            continue
        if end <= now:
            continue
        description = ev.get("description") or ""
        lead = parse_lead(description)
        lead = lead_minutes if lead is None else lead
        target = parse_target(description)
        out.append(
            {
                "summary": ev.get("summary") or "",
                "location": ev.get("location") or "",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "all_day": all_day,
                "target": target if target is not None else default_target,
                "lead_minutes": None if all_day else lead,
                "precondition_start": None if all_day else (start - timedelta(minutes=lead)).isoformat(),
            }
        )
    out.sort(key=lambda e: e["start"])
    return out


def next_precondition(events: list[dict], now: datetime) -> dict | None:
    """First timed event whose precondition start is still ahead, or is running now."""
    for ev in events:
        if ev["all_day"] or not ev["precondition_start"]:
            continue
        if datetime.fromisoformat(ev["start"]) > now:
            return ev
    return None
