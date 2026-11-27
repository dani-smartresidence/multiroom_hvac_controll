"""Heating plant topology, the SQLite data log and heating-session measurements."""
import json
import math

import pytest

from portal.datalog import BUCKET_S, HEARTBEAT_S, DataLog
from portal.rooms import Room
from portal.sessions import SessionTracker, _n_open, analyze_cooling, analyze_heating, room_key
from portal.topology import Topology, TopologyError, is_circuit_open

T0 = 1_800_000_000  # a fixed epoch second, so runs are reproducible


def circuit(preset="Summer", heat_request=0.0):
    return {"state": "heat", "attributes": {"preset_mode": preset, "heat_request": heat_request}}


STATES = {
    "climate.sala_plen1": circuit(),
    "climate.etaj1": circuit(),
    "climate.zone1_2": circuit(),  # second circuits stay in HA but are not used
}
# Two circuits on one boiler, to test how they share its power.
TWO_CIRCUITS = {"boilers": [{"id": "sala_plen", "name": "Sala Plen", "circuits": ["climate.sala_plen1", "climate.zone1_2"]},
                            {"id": "etaj_1", "name": "Etaj 1", "circuits": ["climate.etaj1"]}], "rooms": {}}


def make_topology(tmp_path, data=None):
    if data is not None:
        (tmp_path / "topology.json").write_text(json.dumps(data))
    topo = Topology(tmp_path / "topology.json")
    rooms = {
        "sala_mare": Room("sala_mare", "Sala Mare", temperature="sensor.sala_mare_temperature"),
        "101_sala": Room("101_sala", "101 Sală copii"),
        "p01": Room("p01", "P01"),
    }
    members = {
        "101_sala": ["climate.etaj1", "climate.zone1_2", "calendar.101"],
        "p01": ["switch.p01_relay", "switch.p01_boiler", "sensor.p01_temperature"],
    }
    topo.refresh(rooms, members, STATES)
    return topo


# ------------------------------------------------------------------ topology
def test_circuit_open():
    assert is_circuit_open(circuit("Winter"))
    assert is_circuit_open(circuit("Summer", 1.0))
    assert not is_circuit_open(circuit("Summer", 0.0))
    assert not is_circuit_open({"state": "unavailable", "attributes": {"preset_mode": "Winter"}})
    assert not is_circuit_open(None)


def test_seed_keeps_only_existing_first_circuits(tmp_path):
    topo = make_topology(tmp_path)
    assert [(b.id, b.circuits) for b in topo.boilers] == [("sala_plen", ["climate.sala_plen1"]), ("etaj_1", ["climate.etaj1"])]
    assert (tmp_path / "topology.json").exists()


def test_migrates_old_three_circuit_seed(tmp_path):
    old = {
        "boilers": [
            {"id": "sala_plen", "name": "Sala Plen", "circuits": ["climate.zone1", "climate.zone1_2", "climate.zone1_3"]},
            {"id": "demisol", "name": "Demisol", "circuits": ["climate.ariston_b4bfe94a5d38_1", "climate.ariston_b4bfe94a5d38_2", "climate.ariston_b4bfe94a5d38_3"]},
        ],
        "rooms": {"a": {"circuit": "climate.zone1", "category": "event"}, "b": {"circuit": "climate.zone1_2"}},
    }
    (tmp_path / "topology.json").write_text(json.dumps(old))
    topo = Topology(tmp_path / "topology.json")
    assert [(b.id, b.circuits) for b in topo.boilers] == [("sala_plen", ["climate.sala_plen1"]), ("demisol", ["climate.demisol1"])]
    saved = json.loads((tmp_path / "topology.json").read_text())
    assert saved["rooms"] == {"a": {"circuit": "climate.sala_plen1", "category": "event"}, "b": {}}
    assert Topology(tmp_path / "topology.json").boilers == topo.boilers  # idempotent


def test_guesses_from_area(tmp_path):
    topo = make_topology(tmp_path)
    p01 = topo.link("p01")
    assert p01.valve == "switch.p01_relay" and "valve" in p01.guessed
    assert topo.link("101_sala").boiler == "etaj_1"  # climate.etaj1 is in its Area
    assert topo.link("101_sala").circuit is None
    assert topo.link("sala_mare").temperature == "sensor.sala_mare_temperature"
    assert topo.issues("101_sala", {}) == ["no_circuit", "no_sensor"]


def test_update_room_links_and_resets(tmp_path):
    topo = make_topology(tmp_path)
    link = topo.update_room("sala_mare", {"circuit": "climate.sala_plen1", "comfort": "21"})
    assert link.boiler == "sala_plen" and link.circuit == "climate.sala_plen1" and link.comfort == 21.0
    assert "circuit" not in link.guessed
    assert [l.room_id for l in topo.rooms_on_circuit("climate.sala_plen1")] == ["sala_mare"]
    # Another boiler: its old circuit no longer applies.
    link = topo.update_room("sala_mare", {"boiler": "etaj_1"})
    assert link.boiler == "etaj_1" and link.circuit is None
    # None goes back to the guess.
    link = topo.update_room("p01", {"valve": None})
    assert link.valve == "switch.p01_relay"
    link = topo.update_room("p01", {"valve": "switch.p01_boiler"})
    assert link.valve == "switch.p01_boiler" and "valve" not in link.guessed
    # Saved across restarts.
    again = Topology(tmp_path / "topology.json")
    again.refresh(*topo._last)
    assert again.link("p01").valve == "switch.p01_boiler"
    assert again.link("sala_mare").boiler == "etaj_1"


@pytest.mark.parametrize(
    "values, error",
    [
        ({"circuit": "climate.nope"}, "unknown_circuit"),
        ({"boiler": "nope"}, "unknown_boiler"),
        ({"category": "sometimes"}, "bad_category"),
        ({"comfort": 40}, "bad_comfort"),
        ({"valve": "light.lamp"}, "bad_valve"),
        ({"temperature": 12}, "bad_temperature"),
        ({"color": "red"}, "unknown_field: color"),
    ],
)
def test_update_room_rejects(tmp_path, values, error):
    topo = make_topology(tmp_path)
    with pytest.raises(TopologyError, match=error):
        topo.update_room("p01", values)


# ------------------------------------------------------------------ data log
def test_record_change_and_heartbeat(tmp_path):
    log = DataLog(tmp_path / "h.db")
    assert log.record("k", 1.0, T0)
    assert not log.record("k", 1.0, T0 + 60)
    assert log.record("k", 1.5, T0 + 120)
    assert log.record("k", 1.5, T0 + 120 + HEARTBEAT_S)
    log.flush_sync()
    assert log.series("k", T0, T0 + 10_000) == [(T0, 1.0), (T0 + 120, 1.5), (T0 + 120 + HEARTBEAT_S, 1.5)]
    # step-hold: the value before the window leads the series
    assert log.series("k", T0 + 200, T0 + 300) == [(T0 + 120, 1.5)]
    log.close()
    again = DataLog(tmp_path / "h.db")
    assert again.last("k") == 1.5 and again.keys() == ["k"]


def test_prune_averages_old_rows(tmp_path):
    log = DataLog(tmp_path / "h.db")
    old = (T0 // BUCKET_S) * BUCKET_S
    for i, v in enumerate((10.0, 12.0)):
        log.record("k", v, old + i * 60)
    log.record("k", 20.0, T0 + 200 * 86400)
    log.flush_sync()
    assert log.prune(now=T0 + 200 * 86400) == 2
    assert log.series("k", old, old + 3600) == [(old, 11.0)]


def test_sessions_table(tmp_path):
    log = DataLog(tmp_path / "h.db")
    sid = log.add_session({"kind": "heat", "circuit": "climate.zone1", "room": "r", "start": T0, "end": T0 + 60})
    assert log.set_note(sid, "Test A")
    assert not log.set_note(999, "x")
    rows = log.sessions(circuit="climate.zone1")
    assert rows[0]["id"] == sid and rows[0]["note"] == "Test A"
    assert log.sessions(room="other") == []


# ------------------------------------------------------------------ analysis
def heating_series(dead_min=30, rate=2.0, t0=16.0, target=21.0, step_min=5, hours=4):
    out = []
    for m in range(-10, hours * 60 + 1, step_min):
        rise = max(0.0, (m - dead_min) / 60 * rate)
        out.append((T0 + m * 60, round(t0 + rise, 3)))
    return out


def test_analyze_heating():
    res = analyze_heating(heating_series(), T0, T0 + 4 * 3600, 21.0)
    assert res["t_start"] == 16.0
    assert res["dead_time_min"] == 40  # first 5-minute sample at least 0.2 °C up
    assert res["rate_c_per_h"] == pytest.approx(2.0, abs=0.01)
    assert res["reached_min"] == 180


def test_analyze_heating_no_rise():
    flat = [(T0 + m * 60, 16.0) for m in range(0, 60, 5)]
    res = analyze_heating(flat, T0, T0 + 3600, 21.0)
    assert res["dead_time_min"] is None and res["rate_c_per_h"] is None and res["reached_min"] is None


def test_analyze_cooling_tau():
    out_t, tau = 2.0, 10.0
    series = [(T0 + m * 60, out_t + 18 * math.exp(-(m / 60) / tau)) for m in range(0, 6 * 60 + 1, 10)]
    res = analyze_cooling(series, T0, T0 + 6 * 3600, out_t)
    assert res["tau_h"] == pytest.approx(tau, rel=0.01)
    assert analyze_cooling(series, T0, T0 + 3600, out_t)["tau_h"] is None  # too short


def test_n_open_weighted():
    hist = [(0, 1), (3600, 2), (5400, 1)]
    assert _n_open(hist, 7200) == (2, 1.25)
    assert _n_open([], 10) == (None, None)


def test_tracker_measures_a_heat_run(tmp_path):
    topo = make_topology(tmp_path, TWO_CIRCUITS)
    topo.update_room("sala_mare", {"circuit": "climate.sala_plen1", "comfort": 21})
    log = DataLog(tmp_path / "h.db")
    tracker = SessionTracker(log, topo, default_target=20.0)
    tracker.observe("climate.sala_plen1", False, T0 - 60, 0)  # first sight: baseline only
    assert tracker.runs == {}
    for ts, v in heating_series():
        log.record(room_key("sala_mare"), v, ts)
        log.record("outdoor", 3.0, ts)
    tracker.observe("climate.sala_plen1", True, T0, 1)
    tracker.observe("climate.zone1_2", False, T0 + 5, 1)  # baseline for the second circuit
    tracker.observe("climate.zone1_2", True, T0 + 3600, 2)
    tracker.observe("climate.sala_plen1", False, T0 + 4 * 3600, 1)
    runs = tracker.take_done(T0 + 4 * 3600)
    assert [r.kind for r in runs] == ["heat"]
    ids = tracker.finalize(runs)
    row = log.sessions()[0]
    assert len(ids) == 1 and row["room"] == "sala_mare" and row["boiler"] == "sala_plen"
    assert row["dead_time_min"] == 40 and row["rate_c_per_h"] == pytest.approx(2.0, abs=0.05)
    assert row["target"] == 21 and row["outdoor"] == 3.0
    assert row["n_open_max"] == 2 and row["n_open_avg"] == pytest.approx(1.75)
    assert row["end_reason"] == "closed"
    assert tracker.runs["climate.sala_plen1"].kind == "cool"


def test_tracker_cuts_long_runs_and_skips_short_ones(tmp_path):
    topo = make_topology(tmp_path, TWO_CIRCUITS)
    log = DataLog(tmp_path / "h.db")
    tracker = SessionTracker(log, topo, default_target=20.0)
    tracker.observe("climate.sala_plen1", False, T0, 0)
    tracker.observe("climate.sala_plen1", True, T0 + 10, 1)
    runs = tracker.take_done(T0 + 9 * 3600)
    assert runs[0].end_reason == "max_duration" and tracker.runs["climate.sala_plen1"].kind == "skip"
    assert len(tracker.finalize(runs)) == 1  # no room on the circuit: one row for the circuit itself
    tracker.observe("climate.sala_plen1", False, T0 + 10 * 3600, 0)  # closing a skipped run measures nothing
    tracker.observe("climate.sala_plen1", True, T0 + 10 * 3600 + 120, 1)  # cool run of 2 minutes
    tracker.observe("climate.sala_plen1", False, T0 + 10 * 3600 + 300, 0)  # heat run of 3 minutes
    assert tracker.finalize(tracker.take_done(T0 + 11 * 3600)) == []


def test_rename_circuits_in_log(tmp_path):
    log = DataLog(tmp_path / "h.db")
    log.record("circuit:climate.etaj_1:on", 1.0, T0)
    log.record("circuit:climate.etaj_1_2:on", 1.0, T0)  # a different circuit with a longer id
    log.flush_sync()
    log.add_session({"kind": "heat", "circuit": "climate.etaj_1", "start": T0, "end": T0 + 60})
    assert log.rename_circuits({"climate.etaj_1": "climate.etaj1"}) == 2
    assert log.keys() == ["circuit:climate.etaj1:on", "circuit:climate.etaj_1_2:on"]
    assert log.last("circuit:climate.etaj1:on") == 1.0 and log.sessions()[0]["circuit"] == "climate.etaj1"
    assert log.rename_circuits({"climate.etaj_1": "climate.etaj1"}) == 0
