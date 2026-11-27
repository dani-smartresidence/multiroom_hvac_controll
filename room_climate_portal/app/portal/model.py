"""Learned start times: how long before an event each boiler circuit has to start heating.

From the measured heat runs (sessions.py) each room on a circuit gets a model:

* dead time: median minutes until the room starts warming,
* heating rate with the circuit alone on its boiler (°C/h). A run made while ``n`` circuits shared
  the boiler is scaled up by ``1 + SHARE_K * (n - 1)``; with five runs or more over at least
  OUTDOOR_SPREAD_C of outdoor temperatures the rate also follows the outdoor temperature (least squares),
* tau: median time constant from cool runs, used to predict how far the room cools until the start.

lead = dead time + (target - temperature at start) / (rate x share) + MARGIN_MIN

A circuit starts for whichever room on it needs heat first. Circuits of the same boiler whose
heating windows overlap share its power, so their rates drop and they start earlier. Rooms and
circuits without runs use the room's circuit-wide model, else DEFAULT_DEAD_MIN / DEFAULT_RATE.
This version only shows the result: nothing is switched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable
from statistics import median

DEFAULT_DEAD_MIN = 40.0
DEFAULT_RATE = 1.5
SHARE_K = 0.5
MARGIN_MIN = 15.0
MAX_LEAD_MIN = 720.0
MIN_RUN_MIN = 30
OUTDOOR_FIT_RUNS = 5
OUTDOOR_SPREAD_C = 4.0


def share_factor(n_open: int | float | None) -> float:
    """Fraction of the boiler's power a circuit gets while ``n_open`` circuits heat at once."""
    return 1 / (1 + SHARE_K * (max(1.0, float(n_open or 1)) - 1))


def confidence(runs: int) -> str:
    return "none" if runs == 0 else "low" if runs < 3 else "medium" if runs < 6 else "high"


@dataclass
class RoomModel:
    dead_min: float = DEFAULT_DEAD_MIN
    rate1: float = DEFAULT_RATE  # °C/h with the circuit alone on its boiler, at ref_outdoor
    slope: float | None = None  # °C/h per °C outdoor
    ref_outdoor: float | None = None
    lo: float = 0.0
    hi: float = math.inf
    tau_h: float | None = None
    runs: int = 0
    source: str = "default"  # room | circuit | default

    def rate_at(self, outdoor: float | None) -> float:
        rate = self.rate1
        if self.slope is not None and outdoor is not None and self.ref_outdoor is not None:
            rate = min(max(rate + self.slope * (outdoor - self.ref_outdoor), self.lo), self.hi)
        return max(rate, 0.1)

    @property
    def confidence(self) -> str:
        return confidence(self.runs if self.source != "default" else 0)


def _fit(rows: list[dict], source: str) -> RoomModel:
    rates = [r["rate_c_per_h"] * (1 + SHARE_K * ((r.get("n_open_avg") or 1) - 1)) for r in rows]
    m = RoomModel(
        dead_min=float(median(r["dead_time_min"] for r in rows)),
        rate1=float(median(rates)),
        runs=len(rows),
        source=source,
        lo=min(rates) * 0.8,
        hi=max(rates) * 1.2,
    )
    pts = [(r["outdoor"], rate) for r, rate in zip(rows, rates) if r.get("outdoor") is not None]
    if len(pts) >= OUTDOOR_FIT_RUNS and max(p[0] for p in pts) - min(p[0] for p in pts) >= OUTDOOR_SPREAD_C:
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        m.slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
        m.ref_outdoor, m.rate1 = mx, my
    return m


def fit_models(sessions: list[dict]) -> tuple[dict[tuple[str, str], RoomModel], dict[str, RoomModel], dict[str, float]]:
    """Room models keyed (circuit, room), circuit-wide models, and tau (hours) per room."""
    heat = [
        s for s in sessions
        if s["kind"] == "heat" and s.get("room") and s.get("rate_c_per_h") and s["rate_c_per_h"] > 0
        and s.get("dead_time_min") is not None and s["end"] - s["start"] >= MIN_RUN_MIN * 60
    ]
    by_room: dict[tuple[str, str], list[dict]] = {}
    by_circuit: dict[str, list[dict]] = {}
    for s in heat:
        by_room.setdefault((s["circuit"], s["room"]), []).append(s)
        by_circuit.setdefault(s["circuit"], []).append(s)
    taus: dict[str, list[float]] = {}
    for s in sessions:
        if s["kind"] == "cool" and s.get("room") and s.get("tau_h"):
            taus.setdefault(s["room"], []).append(s["tau_h"])
    return (
        {k: _fit(v, "room") for k, v in by_room.items()},
        {k: _fit(v, "circuit") for k, v in by_circuit.items()},
        {k: float(median(v)) for k, v in taus.items()},
    )


def model_for(circuit: str, room: str, rooms: dict, circuits: dict, taus: dict) -> RoomModel:
    base = rooms.get((circuit, room)) or circuits.get(circuit) or RoomModel()
    m = RoomModel(**{k: getattr(base, k) for k in base.__dataclass_fields__})
    m.tau_h = taus.get(room)
    return m


def predict_temp(t_now: float, outdoor: float | None, tau_h: float | None, hours: float) -> float:
    """Room temperature after ``hours`` without heating (Newton cooling towards outdoor)."""
    if tau_h is None or outdoor is None or hours <= 0 or t_now <= outdoor:
        return t_now
    return outdoor + (t_now - outdoor) * math.exp(-hours / tau_h)


def lead(model: RoomModel, t_start: float, target: float, outdoor: float | None, n_open: int) -> dict:
    rate = model.rate_at(outdoor) * share_factor(n_open)
    delta = max(0.0, target - t_start)
    heat_min = delta / rate * 60
    total = min(model.dead_min + heat_min + MARGIN_MIN, MAX_LEAD_MIN) if delta > 0 else 0.0
    return {
        "lead_min": round(total), "dead_min": round(model.dead_min, 1), "heat_min": round(heat_min, 1),
        "margin_min": MARGIN_MIN if delta > 0 else 0.0, "rate": round(rate, 2), "rate_alone": round(model.rate_at(outdoor), 2),
        "delta": round(delta, 2), "share": round(share_factor(n_open), 2),
    }


@dataclass
class Candidate:
    """A room's next event on a circuit."""
    room: str
    event_summary: str
    event_start: int  # epoch seconds
    event_end: int
    target: float
    t_now: float | None
    fixed_lead_min: int
    assumed_temp: bool = False  # no sensor: t_now is the setback temperature


@dataclass
class CircuitPlan:
    circuit: str
    boiler: str | None
    candidates: list[Candidate] = field(default_factory=list)


def coast_minutes(t_room: float | None, outdoor: float | None, tau_h: float | None, drop: float, max_min: float) -> float:
    """How long before an event ends heating can stop and the room loses at most ``drop`` °C."""
    if t_room is None or tau_h is None or outdoor is None or t_room - drop <= outdoor:
        return 0.0
    hours = -tau_h * math.log((t_room - drop - outdoor) / (t_room - outdoor))
    return round(min(max_min, hours * 60), 1)


def setback_floor(m: RoomModel, target: float, outdoor: float | None, frost: float, max_preheat_h: float) -> float:
    """Lowest temperature the room may fall to so that preheating never needs more than ``max_preheat_h``."""
    heat_h = max(0.0, max_preheat_h - (m.dead_min + MARGIN_MIN) / 60)
    return round(max(frost, target - m.rate_at(outdoor) * heat_h), 2)


OutdoorAt = Callable[[int, int], "float | None"]


def _estimate(c: Candidate, m: RoomModel, outdoor: float | None, n_open: int, now: int, outdoor_at: OutdoorAt | None = None) -> dict:
    t_now = c.t_now if c.t_now is not None else 0.0
    t_at = t_now
    parts = lead(m, t_at, c.target, outdoor, n_open)
    for _ in range(3):  # the later the start, the more the room cools first
        start = c.event_start - parts["lead_min"] * 60
        if outdoor_at is not None:  # the forecast for the preheat window, when there is one
            forecast = outdoor_at(start, c.event_start)
            outdoor = forecast if forecast is not None else outdoor
        t_at = predict_temp(t_now, outdoor, m.tau_h, max(0, start - now) / 3600)
        parts = lead(m, t_at, c.target, outdoor, n_open)
    return {
        "room": c.room, "event_summary": c.event_summary, "event_start": c.event_start, "event_end": c.event_end,
        "target": c.target, "t_now": c.t_now, "assumed_temp": c.assumed_temp, "t_at_start": round(t_at, 2),
        "outdoor": outdoor, "n_open": n_open, "start": c.event_start - parts["lead_min"] * 60,
        "fixed_lead_min": c.fixed_lead_min, "fixed_start": c.event_start - c.fixed_lead_min * 60,
        "confidence": m.confidence, "runs": m.runs if m.source != "default" else 0, "source": m.source,
        "tau_h": m.tau_h, **parts,
    }


def plan_circuits(plans: list[CircuitPlan], models: tuple, outdoor: float | None, now: int,
                  outdoor_at: OutdoorAt | None = None) -> list[dict]:
    """For every circuit, the room that needs heat first and when the circuit must open for it.
    Each entry also lists every room's own estimate under "rooms"."""
    rooms, circuits, taus = models

    def options(p: CircuitPlan, n_open: int) -> list[dict]:
        return sorted(
            (_estimate(c, model_for(p.circuit, c.room, rooms, circuits, taus), outdoor, n_open, now, outdoor_at) for c in p.candidates),
            key=lambda e: e["start"],
        )

    def best(p: CircuitPlan, n_open: int) -> dict | None:
        found = options(p, n_open)
        return found[0] if found else None

    first = {p.circuit: best(p, 1) for p in plans}
    out = []
    for p in plans:
        est = first[p.circuit]
        if est is not None:
            # Other circuits of the boiler heating at the same time share its power.
            overlap = sum(
                1 for q in plans
                if q is not p and q.boiler and q.boiler == p.boiler and first[q.circuit]
                and first[q.circuit]["start"] < est["event_start"] and first[q.circuit]["event_end"] > est["start"]
            )
            n_open = 1 + overlap
            per_room = options(p, n_open)
            est = per_room[0]
            est["status"] = (
                "heat_now" if est["start"] <= now < est["event_start"] else "warm" if est["lead_min"] == 0 else "planned"
            )
        else:
            per_room = []
        out.append({"circuit": p.circuit, "boiler": p.boiler, "estimate": est, "rooms": per_room})
    return out
