import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from portal.config import Options
from portal.rooms import Room, clamp_setpoint, discover
from portal.schedule import build_events, lead_minutes_from_state, next_precondition, parse_lead, parse_target
from portal.tokens import TokenStore

TZ = ZoneInfo("Europe/Bucharest")


def test_parse_target_and_lead():
    assert parse_target("target: 22") == 22.0
    assert parse_target("Țintă = 21,5") == 21.5
    assert parse_target("nothing") is None
    assert parse_lead("precondition: 60") == 60
    assert parse_lead("Precondiționare: 30") == 30


def test_lead_minutes_units():
    assert lead_minutes_from_state({"state": "45.0", "attributes": {}}, 10) == 45
    assert lead_minutes_from_state({"state": "1.5", "attributes": {"unit_of_measurement": "h"}}, 10) == 90
    assert lead_minutes_from_state({"state": "unavailable", "attributes": {}}, 10) == 10
    assert lead_minutes_from_state(None, 10) == 10


def test_build_events_precondition_start():
    now = datetime(2026, 11, 9, 13, 31, tzinfo=TZ)
    raw = [
        {"summary": "A", "start": "2026-11-09T14:00:00+02:00", "end": "2026-11-09T16:00:00+02:00", "description": "target: 22"},
        {"summary": "B", "start": "2026-11-10T09:00:00+02:00", "end": "2026-11-10T11:00:00+02:00", "description": "precondition: 85"},
        {"summary": "past", "start": "2026-11-09T08:00:00+02:00", "end": "2026-11-09T09:00:00+02:00"},
        {"summary": "allday", "start": "2026-11-11", "end": "2026-11-12"},
    ]
    evs = build_events(raw, lead_minutes=45, default_target=21, tz=TZ, now=now)
    assert [e["summary"] for e in evs] == ["A", "B", "allday"]
    assert evs[0]["precondition_start"] == "2026-11-09T13:15:00+02:00"
    assert evs[0]["target"] == 22
    assert evs[1]["precondition_start"] == "2026-11-10T07:35:00+02:00"
    assert evs[1]["target"] == 21
    assert evs[2]["all_day"] and evs[2]["precondition_start"] is None
    assert next_precondition(evs, now)["summary"] == "A"


def test_clamp():
    room = Room(id="r", name="r", min_temp=18, max_temp=25, step=0.5)
    assert clamp_setpoint(room, 30, {}) == 25
    assert clamp_setpoint(room, 10, {}) == 18
    assert clamp_setpoint(room, 22.3, {}) == 22.5
    assert clamp_setpoint(room, 24, {"max_temp": 23}) == 23


def test_tokens(tmp_path):
    store = TokenStore(tmp_path / "t.json")
    tok = store.token_for("room_1")
    assert len(tok) == 22
    assert store.resolve(tok, ["room_1", "room_2"]) == "room_1"
    assert store.resolve("x" * 22, ["room_1"]) is None
    # stable across reloads
    assert TokenStore(tmp_path / "t.json").token_for("room_1") == tok
    new = store.rotate("room_1")
    assert new != tok
    assert store.resolve(tok, ["room_1"]) is None
    assert TokenStore(tmp_path / "t.json").resolve(new, ["room_1"]) == "room_1"


def test_discover_from_fake_registry():
    from fake_ha import FakeHA

    fake = FakeHA()
    rooms = discover(
        areas=fake.areas, floors=fake.floors, entities=fake.entities, devices=fake.devices,
        states=fake.states, overrides={"camera_102": {"max_temp": 23, "subtitle": "Birou"}}, options=Options(),
    )
    assert list(rooms) == ["camera_101", "camera_102", "camera_204"]
    r204 = rooms["camera_204"]
    assert r204.climate == "climate.camera_204"
    assert r204.calendar == "calendar.camera_204"
    assert r204.lead_time == "input_number.camera_204_precondition_minutes"
    assert r204.humidity == "sensor.camera_204_humidity"
    assert r204.subtitle == "Etaj 2"
    assert rooms["camera_101"].climate == "climate.camera_101_trv"  # via device area
    assert rooms["camera_101"].lead_time == "sensor.camera_101_precondition_minutes"  # by name
    assert "missing_calendar" in rooms["camera_102"].issues
    assert rooms["camera_102"].max_temp == 23 and rooms["camera_102"].subtitle == "Birou"


def test_normalize_base():
    from portal.config import normalize_base
    assert normalize_base("/camera") == "/camera"
    assert normalize_base("camera/") == "/camera"
    assert normalize_base("") == ""
    assert normalize_base("/") == ""


def test_custom_codes(tmp_path):
    import pytest
    from portal.tokens import CodeError

    store = TokenStore(tmp_path / "t.json")
    rooms = ["a", "b"]
    assert store.set_custom("a", "camera204-x7k", rooms) == "camera204-x7k"
    assert store.resolve("camera204-x7k", rooms) == "a"
    assert TokenStore(tmp_path / "t.json").token_for("a") == "camera204-x7k"
    for bad in ("abc", "has space", "api", "x" * 65, "ăbcd"):
        with pytest.raises(CodeError):
            store.set_custom("b", bad, rooms)
    with pytest.raises(CodeError):
        store.set_custom("b", "CAMERA204-X7K", rooms)  # same as room a, ignoring case
    store.rotate("a")
    assert store.resolve("camera204-x7k", rooms) is None and len(store.token_for("a")) == 22


def test_parse_hhmm_and_hold_store(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from portal.holds import HoldError, HoldStore, parse_hhmm

    tz = ZoneInfo("Europe/Bucharest")
    now = datetime(2026, 11, 9, 14, 10, tzinfo=tz)
    assert parse_hhmm("16:30", now, tz) == datetime(2026, 11, 9, 16, 30, tzinfo=tz)
    assert parse_hhmm("09:00", now, tz) == datetime(2026, 11, 10, 9, 0, tzinfo=tz)
    start = datetime(2026, 11, 9, 23, 0, tzinfo=tz)
    assert parse_hhmm("01:00", now, tz, after=start) == datetime(2026, 11, 10, 1, 0, tzinfo=tz)
    with pytest.raises(HoldError):
        parse_hhmm("25:99", now, tz)
    with pytest.raises(HoldError):
        parse_hhmm(None, now, tz)

    store = HoldStore(tmp_path / "holds.json")
    store.add("r1", parse_hhmm("18:00", now, tz), parse_hhmm("20:00", now, tz), 22, "planned", False)
    with pytest.raises(HoldError, match="overlap"):
        store.check_planned("r1", parse_hhmm("19:00", now, tz), parse_hhmm("21:00", now, tz))
    store.check_planned("r1", parse_hhmm("20:00", now, tz), parse_hhmm("21:00", now, tz))
    store.check_planned("r2", parse_hhmm("19:00", now, tz), parse_hhmm("21:00", now, tz))
    assert len(HoldStore(tmp_path / "holds.json").for_room("r1")) == 1  # persisted


def test_readable_codes(tmp_path):
    from portal.tokens import slugify
    assert slugify("Demisol D01 - Sala repetiții închinare") == "demisol-d01-sala-repetitii-inchinare"
    assert slugify("107- Sală tehnică răcire") == "107-sala-tehnica-racire"
    store = TokenStore(tmp_path / "t.json", readable=True)
    old_random = store.token_for("d01")  # before the room was seen: random
    store.assign_readable({"d01": ("Demisol", "D01 - Sala sport"), "d02": ("Demisol", "D01 - Sala sport"), "x": ("", "P")})
    assert store.token_for("d01") == "demisol-d01-sala-sport"
    assert store.token_for("d02") == "demisol-d01-sala-sport-2"
    assert len(store.token_for("x")) >= 4
    rooms = ["d01", "d02", "x"]
    assert store.resolve("demisol-d01-sala-sport", rooms) == "d01"
    assert store.resolve("Demisol-D01-Sala-Sport", rooms) == "d01"
    assert store.resolve(old_random, rooms) == "d01"  # old printed sticker still works
    # Renaming the area does not change the code; "Readable code" rebuilds it.
    store.assign_readable({"d01": ("Demisol", "D01 - Sala mare")})
    assert TokenStore(tmp_path / "t.json", readable=True).token_for("d01") == "demisol-d01-sala-sport"
    new = store.use_readable("d01", "Demisol", "D01 - Sala mare")
    assert new == "demisol-d01-sala-mare" and store.resolve("demisol-d01-sala-sport", rooms) is None
    # New random code revokes the readable one.
    rnd = store.rotate("d01")
    assert store.kind("d01") == "random" and store.resolve("demisol-d01-sala-mare", rooms) is None
    assert store.resolve(rnd, rooms) == "d01"
