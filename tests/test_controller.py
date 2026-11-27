"""Circuit decisions (controller.py) and the per-boiler control store."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from portal.controller import ControlStore, decide_circuit, room_need
from portal.topology import RoomLink

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 11, 29, 10, 30, tzinfo=TZ)
TS = int(NOW.timestamp())


def event(start_h, end_h, target=21.0, target_set=False):
    day = NOW.replace(hour=0, minute=0)
    return {"summary": "Serviciu", "all_day": False, "target": target, "target_set": target_set,
            "start": (day + timedelta(hours=start_h)).isoformat(), "end": (day + timedelta(hours=end_h)).isoformat()}


def need(temp, events, is_open=False, category="event", comfort=None):
    link = RoomLink("sala", circuit="climate.sala_plen1", category=category, comfort=comfort)
    return room_need(link, temp, events, NOW, is_open=is_open, hysteresis=0.3, frost_temp=10.0)


def test_room_need_during_event_hysteresis():
    running = [event(10, 12)]
    assert need(20.5, running).heat and need(20.5, running).reason == "event"
    assert not need(20.8, running).heat and need(20.8, running).reason == "warm"  # closed: opens at 20.7
    assert need(21.2, running, is_open=True).heat  # open: closes at 21.3
    assert not need(21.3, running, is_open=True).heat
    assert need(None, running).reason == "event_no_sensor" and need(None, running).heat


def test_room_need_target_comes_from_event_or_comfort():
    assert need(20.0, [event(10, 12)], comfort=19.0).heat is False  # comfort 19 wins over the default target
    assert need(20.0, [event(10, 12, target=22.0, target_set=True)], comfort=19.0).heat  # the event's own target wins


def test_room_need_frost_idle_and_not_heated():
    assert need(9.5, []).reason == "frost" and need(9.5, []).heat
    assert need(10.5, [], is_open=True).reason == "frost"  # keeps heating up to frost + 1 °C
    assert not need(10.5, []).heat and need(10.5, []).reason == "idle"
    assert need(5.0, [event(10, 12)], category="none").reason == "not_heated"
    assert need(15.0, [event(10, 12)], category="frost").reason == "idle"  # frost rooms ignore events
    assert need(15.0, [event(11, 12)]).reason == "idle"  # event not started yet


def estimate(start_offset_min, event_offset_min, target=21.0, lead=60):
    return {"room": "sala", "start": TS + start_offset_min * 60, "event_start": TS + event_offset_min * 60,
            "target": target, "lead_min": lead}


def decide(needs=(), est=None, is_open=False, pre=None):
    return decide_circuit("climate.sala_plen1", "sala_plen", list(needs), est, TS, is_open=is_open, hysteresis=0.3, preheat_temp=pre)


def test_decide_preheat_window():
    d = decide(est=estimate(-10, 50), pre=18.0)
    assert d.open and d.reason == "preheat" and d.detail == "sala"
    assert not decide(est=estimate(10, 70), pre=18.0).open  # not time yet
    assert not decide(est=estimate(-10, 50), pre=21.0).open  # warm already
    assert decide(est=estimate(-10, 50), pre=21.0, is_open=True).open  # open: until target + hysteresis
    assert decide(est=estimate(-10, 50), pre=None).open  # no sensor: whole window
    assert not decide(est=estimate(-10, 50, lead=0), pre=None).open


def test_decide_priority_and_idle():
    frost = need(9.0, [])
    ev = need(20.0, [event(10, 12)])
    assert decide([ev, frost]).reason == "frost"
    assert decide([ev]).reason == "event" and decide([ev]).open
    d = decide([need(15.0, [])])
    assert not d.open and d.reason == "idle"
    assert d.as_dict()["rooms"][0]["reason"] == "idle"


def test_control_store(tmp_path):
    store = ControlStore(tmp_path / "control.json")
    assert store.boiler("sala_plen") == {"mode": "shadow", "takeover": []}
    store.set_boiler("sala_plen", "active", ["automation.b", "automation.a", "automation.a"])
    store.switched("climate.sala_plen1", 123)
    again = ControlStore(tmp_path / "control.json")
    assert again.boiler("sala_plen") == {"mode": "active", "takeover": ["automation.a", "automation.b"]}
    assert again.last_switch("climate.sala_plen1") == 123
    with pytest.raises(ValueError):
        store.set_boiler("sala_plen", "on")
    with pytest.raises(ValueError):
        store.set_boiler("sala_plen", takeover=["script.x"])


def test_room_need_coast_and_setback():
    running = [event(10, 11)]  # ends at 11:00, NOW is 10:30
    link = RoomLink("sala", circuit="climate.sala_plen1")
    n = room_need(link, 21.0, running, NOW, is_open=True, hysteresis=0.3, frost_temp=10.0, coast_min=40)
    assert not n.heat and n.reason == "coast"
    cold = room_need(link, 19.5, running, NOW, is_open=True, hysteresis=0.3, frost_temp=10.0, coast_min=40)
    assert cold.heat and cold.reason == "event"  # 1 °C under target: keeps heating
    later = [event(14, 16)]
    s = room_need(link, 13.0, later, NOW, is_open=False, hysteresis=0.3, frost_temp=10.0, floor=14.0)
    assert s.heat and s.reason == "setback" and s.floor == 14.0
    assert not room_need(link, 14.5, later, NOW, is_open=False, hysteresis=0.3, frost_temp=10.0, floor=14.0).heat
    assert decide([s]).reason == "setback" and decide([s]).open
    assert decide([n]).reason == "coast" and not decide([n]).open


def test_experiment_phases():
    from portal.controller import experiment_step
    exp = {"start": 1000, "rise": 3.0, "max_hours": 4, "cool_hours": 8, "room": "sala", "phase": "wait"}
    assert experiment_step(exp, 15.0, 999)[1] is None
    exp, want = experiment_step(exp, 15.0, 1000)
    assert want is True and exp["phase"] == "A" and exp["t0"] == 15.0
    exp, want = experiment_step(exp, 17.9, 1000 + 3600)
    assert want is True
    exp, want = experiment_step(exp, 18.0, 1000 + 7200)
    assert want is False and exp["phase"] == "B" and exp["a_end_reason"] == "risen"
    exp, want = experiment_step(exp, 16.0, 1000 + 7200 + 8 * 3600)
    assert want is None and exp["phase"] == "done"
    timeout = experiment_step(dict(exp, phase="A", a_start=0, t0=15.0), 15.5, 4 * 3600)[0]
    assert timeout["phase"] == "B" and timeout["a_end_reason"] == "max_hours"


def test_experiment_notes(tmp_path):
    store = ControlStore(tmp_path / "control.json")
    store.set_experiment("c1", {"start": 0, "phase": "B", "a_start": 1000, "b_start": 5000, "max_hours": 4, "cool_hours": 8, "room": "r"})
    assert store.experiment_note("c1", 1000, 5000) == "Test A"
    assert store.experiment_note("c1", 5000, 20000) == "Test B"
    assert store.experiment_note("c2", 1000, 5000) is None
    store.finish_experiment("c1", store.experiment("c1"), "done")
    assert store.experiment("c1") is None and store.experiment_note("c1", 1000, 5000) == "Test A"
