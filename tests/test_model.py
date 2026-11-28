"""Learned start times (model.py) and the estimate history in the data log."""
import pytest

from portal.datalog import DataLog
from portal.model import (
    DEFAULT_DEAD_MIN, DEFAULT_RATE, MARGIN_MIN, Candidate, CircuitPlan, RoomModel, fit_models, lead, plan_circuits,
    predict_temp, share_factor,
)

NOW = 1_800_000_000
H = 3600


def run(rate, dead=30, n_avg=1.0, outdoor=5.0, room="r1", circuit="c1", minutes=120, reason=None):
    return {"kind": "heat", "room": room, "circuit": circuit, "start": 0, "end": minutes * 60, "rate_c_per_h": rate,
            "dead_time_min": dead, "n_open_avg": n_avg, "outdoor": outdoor, "reason": reason}


def test_share_factor():
    assert share_factor(1) == 1 and share_factor(None) == 1
    assert share_factor(2) == pytest.approx(2 / 3)
    assert share_factor(3) == pytest.approx(0.5)


def test_fit_normalises_shared_runs_and_ignores_bad_rows():
    rows = [run(2.0), run(1.5, n_avg=2.0), run(2.0, dead=50), run(9.0, minutes=10), run(None),
            {"kind": "cool", "room": "r1", "circuit": "c1", "start": 0, "end": 1, "tau_h": 12.0}]
    rooms, circuits, taus = fit_models(rows)
    m = rooms[("c1", "r1")]
    assert m.runs == 3 and m.dead_min == 30 and m.rate1 == pytest.approx(2.0)  # 1.5 shared by 2 -> 2.25 alone
    assert circuits["c1"].runs == 3 and taus == {"r1": 12.0}
    assert m.confidence == "medium" and RoomModel().confidence == "none"


def test_fit_follows_outdoor_temperature():
    rows = [run(1.0 + 0.1 * t, outdoor=t) for t in (0, 2, 4, 6, 8)]
    m = fit_models(rows)[0][("c1", "r1")]
    assert m.slope == pytest.approx(0.1)
    assert m.rate_at(0) == pytest.approx(1.0) and m.rate_at(8) == pytest.approx(1.8)
    assert m.rate_at(-30) == pytest.approx(m.lo)  # clamped to what was observed


def test_lead_breakdown():
    m = RoomModel(dead_min=30, rate1=2.0)
    parts = lead(m, 16.0, 21.0, None, 1)
    assert parts["lead_min"] == round(30 + 150 + MARGIN_MIN)
    assert lead(m, 16.0, 21.0, None, 2)["lead_min"] == round(30 + 225 + MARGIN_MIN)
    assert lead(m, 21.5, 21.0, None, 1)["lead_min"] == 0


def test_predict_temp():
    assert predict_temp(20, 0, 10, 10) == pytest.approx(20 / 2.718281828, rel=1e-3)
    assert predict_temp(20, None, 10, 5) == 20 and predict_temp(20, 0, None, 5) == 20


def cand(room, start_h, end_h, t_now=16.0, target=21.0):
    return Candidate(room, "Event", NOW + start_h * H, NOW + end_h * H, target, t_now, 120)


def test_plan_picks_room_needing_heat_first_and_defaults():
    plans = [CircuitPlan("c1", "b1", [cand("warm", 3, 5, t_now=20.5), cand("cold", 4, 6, t_now=14.0)])]
    out = plan_circuits(plans, ({}, {}, {}), None, NOW)
    e = out[0]["estimate"]
    assert e["room"] == "cold" and e["source"] == "default" and e["confidence"] == "none"
    expected = DEFAULT_DEAD_MIN + 7.0 / DEFAULT_RATE * 60 + MARGIN_MIN
    assert e["lead_min"] == round(expected) and e["start"] == NOW + 4 * H - round(expected) * 60
    assert e["fixed_start"] == NOW + 2 * H and e["status"] == "heat_now"  # start already passed


def test_plan_shares_boiler_power_between_overlapping_circuits():
    models = ({}, {"c1": RoomModel(dead_min=30, rate1=2.0, runs=4, source="circuit"),
                   "c2": RoomModel(dead_min=30, rate1=2.0, runs=4, source="circuit")}, {})
    alone = plan_circuits([CircuitPlan("c1", "b1", [cand("a", 10, 12)])], models, 5.0, NOW)[0]["estimate"]
    both = plan_circuits(
        [CircuitPlan("c1", "b1", [cand("a", 10, 12)]), CircuitPlan("c2", "b1", [cand("b", 10, 12)])], models, 5.0, NOW
    )
    assert alone["n_open"] == 1 and both[0]["estimate"]["n_open"] == 2
    assert both[0]["estimate"]["start"] < alone["start"]
    other_boiler = plan_circuits(
        [CircuitPlan("c1", "b1", [cand("a", 10, 12)]), CircuitPlan("c2", "b2", [cand("b", 10, 12)])], models, 5.0, NOW
    )
    assert other_boiler[0]["estimate"]["n_open"] == 1


def test_plan_accounts_for_cooling_until_start():
    models = ({}, {"c1": RoomModel(dead_min=30, rate1=2.0, runs=4, source="circuit")}, {"a": 10.0})
    e = plan_circuits([CircuitPlan("c1", "b1", [cand("a", 24, 26, t_now=20.0)])], models, 0.0, NOW)[0]["estimate"]
    assert e["t_at_start"] < 20.0 and e["tau_h"] == 10.0 and e["lead_min"] > 30 + 15


def test_estimate_history_freezes_and_evaluates(tmp_path):
    log = DataLog(tmp_path / "h.db")
    ev = NOW + 4 * H
    base = {"circuit": "c1", "event_start": ev, "room": "r1", "event_end": ev + 2 * H, "event_summary": "Serviciu",
            "target": 21.0, "fixed_lead_min": 120, "confidence": "low", "runs": 1}
    log.save_estimate(dict(base, est_start=ev - 3 * H, lead_min=180, computed_at=NOW))
    log.save_estimate(dict(base, est_start=ev - 2.5 * H, lead_min=150, computed_at=NOW + 60))
    log.save_estimate(dict(base, est_start=ev - 1 * H, lead_min=60, computed_at=ev - 2 * H))  # after the start: ignored
    row = log.estimates()[0]
    assert row["lead_min"] == 150 and row["evaluated"] == 0
    log.record("circuit:c1:on", 0.0, ev - 5 * H)
    log.record("circuit:c1:on", 1.0, ev - 2 * H)
    for i, t in enumerate((18.0, 19.0, 20.5, 21.2)):
        log.record("room:r1:temp", t, ev - 2 * H + i * 1800)
    log.flush_sync()
    assert log.evaluate_estimates(ev + H) == 0  # event still running
    assert log.evaluate_estimates(ev + 3 * H) == 1
    row = log.estimates()[0]
    assert row["opened_at"] == ev - 2 * H and row["t_at_event"] == 21.2 and row["reached_at"] == ev - 2 * H + 3 * 1800
    assert row["evaluated"] == 1


def test_coast_minutes():
    from portal.model import coast_minutes
    # 21 °C, 1 °C outside, tau 10 h: losing 0.5 °C takes 10 * ln(20 / 19.5) h = 15.2 min
    assert coast_minutes(21.0, 1.0, 10.0, 0.5, 45) == pytest.approx(15.2, abs=0.1)
    assert coast_minutes(21.0, 1.0, 100.0, 0.5, 45) == 45  # capped
    assert coast_minutes(21.0, 1.0, None, 0.5, 45) == 0 and coast_minutes(None, 1.0, 10, 0.5, 45) == 0


def test_setback_floor():
    from portal.model import setback_floor
    m = RoomModel(dead_min=30, rate1=2.0)
    # 6 h allowed, 45 min of dead time and margin: 5.25 h x 2 °C/h below the target
    assert setback_floor(m, 21.0, None, 10.0, 6.0) == pytest.approx(21.0 - 10.5)
    assert setback_floor(m, 21.0, None, 12.0, 6.0) == 12.0  # never below frost protection
    assert setback_floor(m, 21.0, None, 10.0, 0.5) == 21.0


def test_setback_floor_never_lifts_far_above_the_setback_temperature():
    """A pessimistic rate must not hold a room near comfort for hours.

    Measured on 28.11.2026: holding runs taught the hall 0.44 °C/h, so the floor for a 21.0 °C event came
    out at 18.7 °C. The hall levelled off at 18.5 °C, so the demand never cleared: 83 kWh (~30 RON) of gas
    overnight for +0.9 °C.
    """
    from portal.model import setback_floor
    poisoned = RoomModel(dead_min=34, rate1=0.44)
    assert setback_floor(poisoned, 21.0, None, 10.0, 6.0) == 18.72  # what the add-on did
    assert setback_floor(poisoned, 21.0, None, 10.0, 6.0, 16.0) == 17.0  # capped at setback + 1.0
    healthy = RoomModel(dead_min=34, rate1=0.87)  # the rate its preheat ramps measured
    assert setback_floor(healthy, 21.0, None, 10.0, 6.0, 16.0) == pytest.approx(16.49, abs=0.01)
    assert setback_floor(poisoned, 21.0, None, 17.5, 6.0, 16.0) == 17.5  # frost still wins


def test_fit_skips_holding_runs_and_blocked_delivery():
    """Setback holds and runs that gain almost nothing describe a held room, not how fast it heats."""
    rows = [run(0.87), run(0.89), run(0.80, reason="setback"), run(0.11, minutes=260)]
    m = fit_models(rows)[0][("c1", "r1")]
    assert m.runs == 2 and m.rate1 == pytest.approx(0.88)
    assert fit_models([run(0.11), run(0.2)])[0] == {}  # nothing worth learning from
    assert fit_models([run(0.9, reason="preheat")])[0][("c1", "r1")].runs == 1


def test_fit_keeps_slow_runs_that_were_real_ramps():
    """The 0.25 °C/h floor only cleans rows logged without a reason. A preheat that heated slowly
    (28.11.2026: 0.13 °C/h from 11:05 to 13:50) is how the room really behaves and must be learned."""
    m = fit_models([run(0.13, reason="preheat"), run(0.11), run(0.20, reason="event")])[0][("c1", "r1")]
    assert m.runs == 2 and m.rate1 == pytest.approx(0.165)


def test_plan_uses_forecast_and_lists_rooms():
    models = ({}, {"c1": RoomModel(dead_min=30, rate1=1.0, slope=0.1, ref_outdoor=5.0, lo=0.2, hi=5, runs=6, source="circuit")}, {})
    plans = [CircuitPlan("c1", "b1", [cand("a", 10, 12), cand("b", 20, 22)])]
    mild = plan_circuits(plans, models, 5.0, NOW)[0]
    cold = plan_circuits(plans, models, 5.0, NOW, lambda s, e: -5.0)[0]
    assert [e["room"] for e in mild["rooms"]] == ["a", "b"] and mild["estimate"]["room"] == "a"
    assert cold["estimate"]["outdoor"] == -5.0 and cold["estimate"]["lead_min"] > mild["estimate"]["lead_min"]
