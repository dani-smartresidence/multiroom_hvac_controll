"""Switching the boiler circuits: open (preset Winter) when a room needs heat, close (Summer) otherwise.

Every boiler is in one of two modes, chosen on the admin page:

* shadow (default): decisions are computed and shown, nothing is sent to HA;
* active: decisions are sent. Switching a boiler to active turns off the HA automations listed as its
  "takeover" automations (they would fight the add-on); switching back to shadow turns them on again.

Once a minute each circuit is decided from its rooms:

* preheat: from the estimated start (model.py) until the event, until the room is at its target;
* event: while an event runs in a room on the circuit, hysteresis of ±``hysteresis`` around the target
  (no sensor: open for the whole event);
* frost: any heated room below ``frost_temp`` opens the circuit until it is 1 °C above it;
* setback: before an event within ``setback_horizon_hours``, a room is kept above the lowest temperature
  from which preheating still fits in ``max_preheat_hours`` (model.setback_floor);
* coast: heating stops ``coast`` minutes before an event ends, the time the room needs to lose
  ``coast_drop`` °C (model.coast_minutes), unless the room is already 1 °C under its target;
* test: a scheduled experiment (A: heat until the room is ``rise`` °C warmer or ``max_hours`` pass,
  then B: closed for ``cool_hours``) overrides everything but frost protection.

A circuit is switched at most once every ``min_switch_minutes`` (frost protection excepted). Room valves
(parter relays) follow their room: open while that room needs heat, closed otherwise.

The add-on publishes ``sensor.heating_controller_heartbeat`` every minute; the watchdog blueprint turns
the takeover automations back on if it goes stale (add-on stopped or crashed).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    reason: str  # event | event_no_sensor | frost | setback | coast | warm | idle | not_heated
    temp: float | None = None
    target: float | None = None
    floor: float | None = None  # setback floor, when one applies
    coast_min: float | None = None


@dataclass
class Decision:
    circuit: str
    boiler: str | None
    open: bool
    reason: str  # preheat | preheat_warm | event | event_no_sensor | frost | setback | coast | test_a | test_b | idle
    detail: str = ""
    rooms: list[RoomNeed] = field(default_factory=list)
    held: bool = False  # wants to switch but min_switch_minutes has not passed
    progress: dict | None = None  # preheat on track or late (core.Portal._track_preheat)

    def as_dict(self) -> dict:
        return {
            "circuit": self.circuit, "boiler": self.boiler, "open": self.open, "reason": self.reason,
            "detail": self.detail, "held": self.held, "progress": self.progress,
            "rooms": [r.__dict__ for r in self.rooms],
        }


def running_event(events: list[dict], now: datetime) -> dict | None:
    for ev in events:
        if not ev["all_day"] and datetime.fromisoformat(ev["start"]) <= now < datetime.fromisoformat(ev["end"]):
            return ev
    return None


def event_target(ev: dict, link: RoomLink) -> float:
    return ev["target"] if ev.get("target_set") or link.comfort is None else link.comfort


def room_need(link: RoomLink, temp: float | None, events: list[dict], now: datetime, *, is_open: bool,
              hysteresis: float, frost_temp: float, coast_min: float = 0.0, floor: float | None = None) -> RoomNeed:
    """What one room asks of its circuit right now (preheat is decided per circuit)."""
    if link.category == "none":
        return RoomNeed(link.room_id, False, "not_heated", temp)
    if temp is not None and (temp < frost_temp or (is_open and temp < frost_temp + 1.0)):
        return RoomNeed(link.room_id, True, "frost", temp, frost_temp)
    ev = running_event(events, now) if link.category == "event" else None
    if ev is None:
        if floor is not None and temp is not None and (temp < floor or (is_open and temp < floor + hysteresis)):
            return RoomNeed(link.room_id, True, "setback", temp, floor, floor=floor)
        return RoomNeed(link.room_id, False, "idle", temp, floor=floor)
    target = event_target(ev, link)
    if coast_min and now >= datetime.fromisoformat(ev["end"]) - timedelta(minutes=coast_min) and (temp is None or temp > target - 1.0):
        return RoomNeed(link.room_id, False, "coast", temp, target, coast_min=coast_min)
    if temp is None:
        return RoomNeed(link.room_id, True, "event_no_sensor", None, target, coast_min=coast_min)
    heat = temp < target + hysteresis if is_open else temp <= target - hysteresis
    return RoomNeed(link.room_id, heat, "event" if heat else "warm", temp, target, coast_min=coast_min)


def decide_circuit(circuit: str, boiler: str | None, needs: list[RoomNeed], estimate: dict | None, now_ts: int,
                   *, is_open: bool, hysteresis: float, preheat_temp: float | None) -> Decision:
    """Open for preheat, a running event or frost; closed otherwise."""
    for reason in ("frost", "event", "event_no_sensor", "setback"):
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
    coasting = [n for n in needs if n.reason == "coast"]
    if coasting:
        return Decision(circuit, boiler, False, "coast", ", ".join(n.room for n in coasting), needs)
    return Decision(circuit, boiler, False, "idle", "", needs)


def experiment_step(exp: dict, temp: float | None, now: int) -> tuple[dict, bool | None]:
    """Advance a test on one circuit. Returns the updated test and whether the circuit should be open
    (None: not started yet, or finished)."""
    exp = dict(exp)
    if now < exp["start"]:
        return exp, None
    if exp.get("phase") in (None, "wait"):
        exp.update(phase="A", a_start=now, t0=temp)
    if exp["phase"] == "A":
        rose = temp is not None and exp.get("t0") is not None and temp >= exp["t0"] + exp["rise"]
        if rose or now - exp["a_start"] >= exp["max_hours"] * 3600:
            exp.update(phase="B", b_start=now, a_end_reason="risen" if rose else "max_hours")
        else:
            return exp, True
    if exp["phase"] == "B":
        if now - exp["b_start"] >= exp["cool_hours"] * 3600:
            exp.update(phase="done", end=now)
            return exp, None
        return exp, False
    return exp, None


class ControlStore:
    """Per-boiler mode and takeover automations, and when the add-on last switched each circuit."""

    def __init__(self, path: Path):
        self._path = path
        self.data: dict = {"boilers": {}, "last_switch": {}, "experiments": {}, "experiment_log": []}
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

    # -------------------------------------------------------------- experiments
    def experiment(self, circuit: str) -> dict | None:
        return self.data.setdefault("experiments", {}).get(circuit)

    def set_experiment(self, circuit: str, exp: dict | None) -> None:
        exps = self.data.setdefault("experiments", {})
        if exp is None:
            exps.pop(circuit, None)
        else:
            exps[circuit] = exp
        self._save()

    def finish_experiment(self, circuit: str, exp: dict, status: str) -> None:
        self.data.setdefault("experiments", {}).pop(circuit, None)
        log = self.data.setdefault("experiment_log", [])
        log.append({**exp, "circuit": circuit, "status": status})
        del log[:-200]
        self._save()

    def experiment_note(self, circuit: str, start: int, end: int) -> str | None:
        """'Test A' / 'Test B' for a run that falls inside a test's phase."""
        tests = [dict(e, circuit=circuit) for c, e in self.data.get("experiments", {}).items() if c == circuit]
        for e in tests + [e for e in self.data.get("experiment_log", []) if e.get("circuit") == circuit]:
            a0, b0 = e.get("a_start"), e.get("b_start")
            b1 = e.get("end") or (b0 + e["cool_hours"] * 3600 if b0 else None)
            if a0 and a0 - 120 <= start < (b0 or a0 + e["max_hours"] * 3600):
                return "Test A"
            if b0 and b0 - 120 <= start < (b1 or end + 1):
                return "Test B"
        return None

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
