"""Manual heating periods ("holds") started or planned from the room page.

* manual: starts now, ends after `hold_default_minutes` (2 h) unless the guest extends it,
  sets an end hour, or stops it. Any setpoint change from the page starts one.
* planned: a period later today (or within the next 24 h) with its own target.

When a hold ends the add-on turns the thermostat off (or to the setback temperature),
unless a calendar event is preconditioning or running in that room at that moment.
Holds are stored in /data/holds.json so they survive restarts.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_PLANNED_PER_ROOM = 4


class HoldError(ValueError):
    pass


def parse_hhmm(value: str, now: datetime, tz: ZoneInfo, *, after: datetime | None = None) -> datetime:
    """'15:30' -> the next 15:30 (today, or tomorrow if already past `after`/now)."""
    try:
        hh, mm = str(value).strip().split(":")[:2]
        t = dtime(int(hh), int(mm))
    except (ValueError, TypeError):
        raise HoldError("bad_time")
    ref = after or now
    local = ref.astimezone(tz)
    dt = datetime.combine(local.date(), t, tzinfo=tz)
    if dt <= ref:
        dt += timedelta(days=1)
    return dt


class HoldStore:
    def __init__(self, path: Path):
        self._path = path
        self.holds: list[dict] = []
        if path.exists():
            try:
                self.holds = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.holds = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.holds, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def for_room(self, room_id: str) -> list[dict]:
        return sorted((h for h in self.holds if h["room"] == room_id), key=lambda h: h["start"])

    def active(self, room_id: str) -> dict | None:
        return next((h for h in self.holds if h["room"] == room_id and h.get("active")), None)

    def add(self, room_id: str, start: datetime, end: datetime, target: float, kind: str, active: bool) -> dict:
        hold = {
            "id": secrets.token_hex(4),
            "room": room_id,
            "kind": kind,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "target": target,
            "active": active,
        }
        self.holds.append(hold)
        self.save()
        return hold

    def remove(self, hold_id: str) -> dict | None:
        for h in self.holds:
            if h["id"] == hold_id:
                self.holds.remove(h)
                self.save()
                return h
        return None

    def check_planned(self, room_id: str, start: datetime, end: datetime) -> None:
        planned = [h for h in self.holds if h["room"] == room_id and not h.get("active")]
        if len(planned) >= MAX_PLANNED_PER_ROOM:
            raise HoldError("too_many")
        for h in planned:
            if start < datetime.fromisoformat(h["end"]) and end > datetime.fromisoformat(h["start"]):
                raise HoldError("overlap")

    @staticmethod
    def public(h: dict) -> dict:
        return {k: h[k] for k in ("id", "kind", "start", "end", "target", "active")}
