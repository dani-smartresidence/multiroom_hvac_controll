"""Switching the boiler circuits: open (preset Winter) when a room needs heat, close (Summer) otherwise.

Every boiler is in one of two modes, chosen on the admin page:

* shadow (default): decisions are computed and shown, nothing is sent to HA;
* active: decisions are sent. Switching a boiler to active turns off the HA automations listed as its
  "takeover" automations (they would fight the add-on); switching back to shadow turns them on again.

Once a minute each circuit is decided from its rooms:

* preheat: from the estimated start (model.py) until the event, until the room is at its target;
* event: while an event runs in a room on the circuit, hysteresis of ±``hysteresis`` around the target
  (no sensor: open for the whole event);
* frost: any heated room below ``frost_temp`` opens the circuit until it is 1 °C above it.

A circuit is switched at most once every ``min_switch_minutes`` (frost protection excepted). Room valves
(parter relays) follow their room: open while that room needs heat, closed otherwise.

The add-on publishes ``sensor.heating_controller_heartbeat`` every minute; the watchdog blueprint turns
the takeover automations back on if it goes stale (add-on stopped or crashed).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .topology import RoomLink

OPEN_PRESET = "Winter"
CLOSED_PRESET = "Summer"
MODES = ("shadow", "active")
HEARTBEAT_ENTITY = "sensor.heating_controller_heartbeat"


@dataclass
class RoomNeed:
    room: str
    heat: bool
    reason: str  # event | event_no_sensor | frost | warm | idle | not_heated
    temp: float | None = None
    target: float | None = None


@dataclass
class Decision:
    circuit: str
    boiler: str | None
    open: bool
    reason: str  # preheat | preheat_warm | event | event_no_sensor | frost | idle
    detail: str = ""
    rooms: list[RoomNeed] = field(default_factory=list)
    held: bool = False  # wants to switch but min_switch_minutes has not passed

    def as_dict(self) -> dict:
        return {
            "circuit": self.circuit, "boiler": self.boiler, "open": self.open, "reason": self.reason,
            "detail": self.detail, "held": self.held,
            "rooms": [r.__dict__ for r in self.rooms],
        }


def running_event(events: list[dict], now: datetime) -> dict | None:
    for ev in events:
        if not ev["all_day"] and datetime.fromisoformat(ev["start"]) <= now < datetime.fromisoformat(ev["end"]):
            return ev
    return None


def room_need(link: RoomLink, temp: float | None, events: list[dict], now: datetime, *, is_open: bool,
              hysteresis: float, frost_temp: float) -> RoomNeed:
    """What one room asks of its circuit right now (preheat is decided per circuit)."""
    if link.category == "none":
        return RoomNeed(link.room_id, False, "not_heated", temp)
    if temp is not None and (temp < frost_temp or (is_open and temp < frost_temp + 1.0)):
        return RoomNeed(link.room_id, True, "frost", temp, frost_temp)
    ev = running_event(events, now) if link.category == "event" else None
    if ev is None:
        return RoomNeed(link.room_id, False, "idle", temp)
    target = ev["target"] if ev.get("target_set") or link.comfort is None else link.comfort
    if temp is None:
        return RoomNeed(link.room_id, True, "event_no_sensor", None, target)
    heat = temp < target + hysteresis if is_open else temp <= target - hysteresis
    return RoomNeed(link.room_id, heat, "event" if heat else "warm", temp, target)


def decide_circuit(circuit: str, boiler: str | None, needs: list[RoomNeed], estimate: dict | None, now_ts: int,
                   *, is_open: bool, hysteresis: float, preheat_temp: float | None) -> Decision:
    """Open for preheat, a running event or frost; closed otherwise."""
    for reason in ("frost", "event", "event_no_sensor"):
        hit = [n for n in needs if n.heat and n.reason == reason]
        if hit:
            return Decision(circuit, boiler, True, reason, ", ".join(n.room for n in hit), needs)
    if estimate and estimate["start"] <= now_ts < estimate["event_start"] and estimate["lead_min"] > 0:
        target = estimate["target"]
        if preheat_temp is None:
            return Decision(circuit, boiler, True, "preheat", estimate["room"], needs)
        warm = preheat_temp >= target + hysteresis if is_open else preheat_temp > target - hysteresis
        if not warm:
            return Decision(circuit, boiler, True, "preheat", estimate["room"], needs)
        return Decision(circuit, boiler, False, "preheat_warm", estimate["room"], needs)
    return Decision(circuit, boiler, False, "idle", "", needs)


class ControlStore:
    """Per-boiler mode and takeover automations, and when the add-on last switched each circuit."""

    def __init__(self, path: Path):
        self._path = path
        self.data: dict = {"boilers": {}, "last_switch": {}}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                pass

    def boiler(self, boiler_id: str) -> dict:
        b = self.data["boilers"].get(boiler_id) or {}
        return {"mode": b.get("mode", "shadow"), "takeover": list(b.get("takeover") or [])}

    def set_boiler(self, boiler_id: str, mode: str | None = None, takeover: list[str] | None = None) -> dict:
        b = self.boiler(boiler_id)
        if mode is not None:
            if mode not in MODES:
                raise ValueError("bad_mode")
            b["mode"] = mode
        if takeover is not None:
            if not all(isinstance(a, str) and a.startswith("automation.") for a in takeover):
                raise ValueError("bad_takeover")
            b["takeover"] = sorted(set(takeover))
        self.data["boilers"][boiler_id] = b
        self._save()
        return b

    def last_switch(self, circuit: str) -> int | None:
        return self.data["last_switch"].get(circuit)

    def switched(self, circuit: str, ts: int) -> None:
        self.data["last_switch"][circuit] = ts
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
