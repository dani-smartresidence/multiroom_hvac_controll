"""Room discovery: which HA entities belong to which QR room.

A room is an HA Area carrying the configured label (default ``qr_room``). Inside that
area the add-on picks the climate entity, the calendar, the precondition lead-time
entity and an optional humidity sensor. ``/config/rooms.yaml`` (the add-on's config
folder, /addon_configs/<slug>/rooms.yaml from HA) can override any of this per room,
or define rooms that have no labelled area at all.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import Options

_LOGGER = logging.getLogger(__name__)

LEAD_DOMAINS = ("sensor", "input_number", "number")
LEAD_NAME_RE = re.compile(r"precondition|preconditionare|lead_time", re.I)


@dataclass
class Room:
    id: str
    name: str
    subtitle: str = ""
    climate: str | None = None
    calendar: str | None = None
    lead_time: str | None = None
    humidity: str | None = None
    temperature: str | None = None  # room temperature sensor, used when the thermostat reports none
    min_temp: float = 16.0
    max_temp: float = 25.0
    step: float = 0.5
    allow_mode_change: bool = False
    issues: list[str] = field(default_factory=list)

    @property
    def entities(self) -> set[str]:
        return {e for e in (self.climate, self.calendar, self.lead_time, self.humidity, self.temperature) if e}

    def as_dict(self) -> dict:
        return asdict(self)


def load_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as err:
        _LOGGER.error("Cannot read %s: %s", path, err)
        return {}
    rooms = raw.get("rooms") or {}
    if isinstance(rooms, list):  # also accept a list of {id: ..., ...}
        rooms = {r["id"]: r for r in rooms if isinstance(r, dict) and r.get("id")}
    return {str(k): (v or {}) for k, v in rooms.items()}


def _entity_area(entry: dict, devices: dict[str, dict]) -> str | None:
    if entry.get("area_id"):
        return entry["area_id"]
    dev = devices.get(entry.get("device_id") or "")
    return dev.get("area_id") if dev else None


def discover(
    *,
    areas: list[dict],
    floors: list[dict],
    entities: list[dict],
    devices: list[dict],
    states: dict[str, dict],
    overrides: dict[str, dict],
    options: Options,
) -> dict[str, Room]:
    floor_names = {f["floor_id"]: f.get("name", "") for f in floors}
    dev_by_id = {d["id"]: d for d in devices}

    by_area: dict[str, list[dict]] = {}
    for entry in entities:
        if entry.get("disabled_by"):
            continue
        area = _entity_area(entry, dev_by_id)
        if area:
            by_area.setdefault(area, []).append(entry)

    rooms: dict[str, Room] = {}
    area_by_id = {a["area_id"]: a for a in areas}
    wanted = [a for a in areas if options.room_label in (a.get("labels") or [])]
    wanted_ids = [a["area_id"] for a in wanted] + [k for k in overrides if k not in {a["area_id"] for a in wanted}]

    for room_id in wanted_ids:
        area = area_by_id.get(room_id, {})
        ov = overrides.get(room_id, {})
        members = by_area.get(room_id, [])

        def of_domain(*domains: str) -> list[dict]:
            return sorted(
                (e for e in members if e["entity_id"].split(".")[0] in domains),
                key=lambda e: e["entity_id"],
            )

        room = Room(
            id=room_id,
            name=ov.get("name") or area.get("name") or room_id,
            subtitle=ov.get("subtitle") or floor_names.get(area.get("floor_id") or "", ""),
            min_temp=float(ov.get("min_temp", options.min_temp)),
            max_temp=float(ov.get("max_temp", options.max_temp)),
            step=float(ov.get("step", options.temp_step)),
            allow_mode_change=bool(ov.get("allow_mode_change", options.allow_mode_change)),
        )

        climates = of_domain("climate")
        room.climate = ov.get("climate") or (climates[0]["entity_id"] if climates else None)
        if not ov.get("climate") and len(climates) > 1:
            room.issues.append(
                "ambiguous_climate: " + ", ".join(e["entity_id"] for e in climates)
            )

        calendars = of_domain("calendar")
        room.calendar = ov.get("calendar") or (calendars[0]["entity_id"] if calendars else None)

        if ov.get("lead_time"):
            room.lead_time = ov["lead_time"]
        else:
            labelled = [e for e in of_domain(*LEAD_DOMAINS) if options.lead_time_label in (e.get("labels") or [])]
            named = [e for e in of_domain(*LEAD_DOMAINS) if LEAD_NAME_RE.search(e["entity_id"])]
            pick = labelled or named
            room.lead_time = pick[0]["entity_id"] if pick else None

        if ov.get("humidity"):
            room.humidity = ov["humidity"]
        else:
            for e in of_domain("sensor"):
                st = states.get(e["entity_id"]) or {}
                if (st.get("attributes") or {}).get("device_class") == "humidity":
                    room.humidity = e["entity_id"]
                    break

        if ov.get("temperature"):
            room.temperature = ov["temperature"]
        else:
            for e in of_domain("sensor"):
                st = states.get(e["entity_id"]) or {}
                if e["entity_id"] != options.outdoor_sensor and (st.get("attributes") or {}).get("device_class") == "temperature":
                    room.temperature = e["entity_id"]
                    break

        if not room.climate:
            room.issues.append("missing_climate")
        elif room.climate not in states:
            room.issues.append(f"climate_not_found: {room.climate}")
        if not room.calendar:
            room.issues.append("missing_calendar")
        if not room.lead_time:
            room.issues.append(f"missing_lead_time (using {options.default_lead_minutes} min)")
        if room.min_temp >= room.max_temp:
            room.issues.append("invalid_limits")
            room.min_temp, room.max_temp = options.min_temp, options.max_temp
        rooms[room_id] = room

    return dict(sorted(rooms.items(), key=lambda kv: kv[1].name.lower()))


def clamp_setpoint(room: Room, value: float, entity_attrs: dict) -> float:
    lo = room.min_temp
    hi = room.max_temp
    if isinstance(entity_attrs.get("min_temp"), (int, float)):
        lo = max(lo, float(entity_attrs["min_temp"]))
    if isinstance(entity_attrs.get("max_temp"), (int, float)):
        hi = min(hi, float(entity_attrs["max_temp"]))
    step = room.step if room.step > 0 else 0.5
    value = round(round(value / step) * step, 2)
    return min(max(value, lo), hi)
