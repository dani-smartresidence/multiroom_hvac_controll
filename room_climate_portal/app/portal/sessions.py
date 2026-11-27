"""Heating and cooling runs of each boiler circuit, measured per room: what the model will learn from.

A *heat* run starts when a circuit opens and ends when it closes (or after MAX_HEAT_S). For every
room on that circuit it records the start temperature, the dead time (until the room is RISE_C
warmer), the heating rate after that (°C/h, least squares) and when the room reached its comfort
temperature, together with the outdoor temperature and how many circuits of the same boiler were
open (they share the boiler's power).

A *cool* run lasts from closing to reopening. If it lasts at least MIN_COOL_S, the room's time
constant tau (hours) is fitted from ln(T - T_outdoor) over the first COOL_FIT_S.

The tracker only notices transitions while the add-on runs: the first state seen after a start
opens nothing, so a run is never measured from the middle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .datalog import DataLog
from .topology import Topology

RISE_C = 0.2
MIN_HEAT_S = 600
MAX_HEAT_S = 8 * 3600
MIN_COOL_S = 2 * 3600
COOL_FIT_S = 12 * 3600
MIN_FIT_SPAN_S = 900


def room_key(room_id: str) -> str:
    return f"room:{room_id}:temp"


def _slope(points: list[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx


def analyze_heating(series: list[tuple[int, float]], start: int, end: int, target: float | None) -> dict:
    """Dead time, heating rate and time to target of one room during one heat run."""
    pts = [p for p in series if p[0] <= end]
    if not pts:
        return {}
    before = [p for p in pts if p[0] <= start]
    after = [p for p in pts if p[0] >= start]
    t0 = before[-1][1] if before else pts[0][1]
    out = {"t_start": t0, "t_end": pts[-1][1], "dead_time_min": None, "rate_c_per_h": None, "reached_min": None}
    dead = next((t for t, v in after if v >= t0 + RISE_C), None)
    reached = next((t for t, v in after if target is not None and v >= target), None)
    if reached is not None:
        out["reached_min"] = round((reached - start) / 60, 1)
    if dead is None:
        return out
    out["dead_time_min"] = round((dead - start) / 60, 1)
    stop = reached if reached is not None else end
    seg = [(t / 3600, v) for t, v in after if dead <= t <= stop]
    if len(seg) >= 3 and (seg[-1][0] - seg[0][0]) * 3600 >= MIN_FIT_SPAN_S:
        slope = _slope(seg)
        if slope is not None:
            out["rate_c_per_h"] = round(slope, 3)
    return out


def analyze_cooling(series: list[tuple[int, float]], start: int, end: int, outdoor: float | None) -> dict:
    """Time constant tau (hours) of one room while its circuit is closed."""
    pts = [p for p in series if start <= p[0] <= end]
    if not pts:
        return {}
    out = {"t_start": pts[0][1], "t_end": pts[-1][1], "tau_h": None}
    if outdoor is None or end - start < MIN_COOL_S:
        return out
    fit = [(t / 3600, math.log(v - outdoor)) for t, v in pts if t <= start + COOL_FIT_S and v - outdoor > 0.5]
    if len(fit) >= 4 and (fit[-1][0] - fit[0][0]) * 3600 >= MIN_COOL_S / 2:
        slope = _slope(fit)
        if slope is not None and slope < 0:
            out["tau_h"] = round(-1 / slope, 2)
    return out


def _mean(series: list[tuple[int, float]], start: int, end: int) -> float | None:
    vals = [v for t, v in series if t <= end]
    inside = [v for t, v in series if start <= t <= end]
    use = inside or vals[-1:]
    return round(sum(use) / len(use), 2) if use else None


def _n_open(hist: list[tuple[int, int]], end: int) -> tuple[int | None, float | None]:
    """Most and time-weighted mean number of open circuits on the boiler during a run."""
    if not hist:
        return None, None
    total = weighted = 0.0
    for (t, n), nxt in zip(hist, hist[1:] + [(end, None)]):
        span = max(0, nxt[0] - t)
        total += span
        weighted += span * n
    return max(n for _, n in hist), round(weighted / total, 2) if total else float(hist[-1][1])


@dataclass
class Run:
    kind: str  # heat | cool | skip (a heat run past MAX_HEAT_S, not measured again until it closes)
    circuit: str
    boiler: str | None
    start: int
    n_hist: list[tuple[int, int]] = field(default_factory=list)
    end: int | None = None
    end_reason: str | None = None
    rooms: list[tuple[str, float | None]] = field(default_factory=list)  # (room_id, comfort target)


class SessionTracker:
    def __init__(self, datalog: DataLog, topology: Topology, default_target: float):
        self.datalog = datalog
        self.topology = topology
        self.default_target = default_target
        self.runs: dict[str, Run] = {}
        self._known: dict[str, bool] = {}
        self._done: list[Run] = []

    def observe(self, circuit: str, is_open: bool, ts: int, n_open: int) -> None:
        """A circuit's state as seen now; ``n_open`` counts the open circuits of its boiler."""
        boiler = self.topology.boiler_of_circuit(circuit)
        bid = boiler.id if boiler else None
        for run in self.runs.values():
            if run.kind == "heat" and run.boiler == bid and (not run.n_hist or run.n_hist[-1][1] != n_open):
                run.n_hist.append((ts, n_open))
        prev = self._known.get(circuit)
        self._known[circuit] = is_open
        if prev is None or prev == is_open:
            return
        current = self.runs.pop(circuit, None)
        if current and current.kind != "skip":
            current.end, current.end_reason = ts, ("closed" if not is_open else "opened")
            self._close(current)
        self.runs[circuit] = Run("heat" if is_open else "cool", circuit, bid, ts, [(ts, n_open)] if is_open else [])

    def take_done(self, now: int) -> list[Run]:
        """Finished runs (also cutting heat runs longer than MAX_HEAT_S), ready for finalize()."""
        for circuit, run in list(self.runs.items()):
            if run.kind == "heat" and now - run.start >= MAX_HEAT_S:
                run.end, run.end_reason = now, "max_duration"
                self._close(run)
                self.runs[circuit] = Run("skip", circuit, run.boiler, now)
        done, self._done = self._done, []
        return done

    def _close(self, run: Run) -> None:
        run.rooms = [
            (link.room_id, link.comfort if link.comfort is not None else self.default_target)
            for link in self.topology.rooms_on_circuit(run.circuit)
            if link.category != "none"
        ]
        self._done.append(run)

    def finalize(self, runs: list[Run]) -> list[int]:
        """Measure finished runs from the data log and store them. Blocking: run it in a thread."""
        ids = []
        for run in runs:
            end = run.end or run.start
            duration = end - run.start
            if run.kind == "heat" and duration < MIN_HEAT_S:
                continue
            if run.kind == "cool" and duration < MIN_COOL_S:
                continue
            outdoor = _mean(self.datalog.series("outdoor", run.start, end), run.start, end)
            n_max, n_avg = _n_open(run.n_hist, end)
            base = {
                "kind": run.kind, "boiler": run.boiler, "circuit": run.circuit, "start": run.start, "end": end,
                "end_reason": run.end_reason, "outdoor": outdoor, "n_open_max": n_max, "n_open_avg": n_avg,
            }
            for room_id, target in run.rooms or [(None, None)]:
                row = dict(base, room=room_id, target=target if run.kind == "heat" else None)
                if room_id:
                    series = self.datalog.series(room_key(room_id), run.start, end)
                    if run.kind == "heat":
                        row.update(analyze_heating(series, run.start, end, target))
                    else:
                        row.update(analyze_cooling(series, run.start, end, outdoor))
                ids.append(self.datalog.add_session(row))
        return ids
