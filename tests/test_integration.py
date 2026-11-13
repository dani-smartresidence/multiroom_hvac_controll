"""End to end: the portal against the fake HA, through the real HTTP apps."""
import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from fake_ha import TOKEN, FakeHA
from portal.config import HAConnection, Options, Paths
from portal.core import Portal
from portal.ha import HAClient
from portal.web import build_admin_app, build_guest_app


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_OPEN", "1")
    fake = FakeHA()
    ha_server = TestServer(fake.app())
    await ha_server.start_server()
    base = str(ha_server.make_url("")).rstrip("/")
    session = aiohttp.ClientSession()
    conn = HAConnection(base.replace("http", "ws") + "/api/websocket", base + "/api", TOKEN)
    ha = HAClient(conn, session)
    opts = Options(public_url="https://climate.example.ro", outdoor_sensor="sensor.outdoor_temperature")
    portal = Portal(opts, Paths(data=tmp_path / "data", config=tmp_path / "cfg"), ha)
    task = asyncio.create_task(ha.run_forever())
    for _ in range(100):
        if portal.ready and portal.schedules:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)
    guest = TestClient(TestServer(build_guest_app(portal)))
    admin = TestClient(TestServer(build_admin_app(portal)))
    await guest.start_server()
    await admin.start_server()
    yield fake, portal, guest, admin
    await guest.close()
    await admin.close()
    await ha.stop()
    task.cancel()
    await session.close()
    await ha_server.close()


async def test_room_snapshot(env):
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    r = await guest.get(f"/camera/api/{tok}")
    assert r.status == 200
    data = await r.json()
    assert data["name"] == "Camera 204"
    assert data["climate"]["current"] == 21.4 and data["climate"]["target"] == 22.5
    assert data["climate"]["min"] == 16 and data["climate"]["max"] == 25
    assert data["humidity"] == 44 and data["outdoor"] == 6
    assert data["lead_minutes"] == 45
    first = data["events"][0]
    assert first["summary"] == "Ședința consiliului" and first["lead_minutes"] == 45
    assert data["events"][1]["lead_minutes"] == 30
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert r.headers["Referrer-Policy"] == "no-referrer"


async def test_invalid_token_and_page(env):
    _, portal, guest, _ = env
    r = await guest.get("/camera/api/AAAAAAAAAAAAAAAAAAAAAA")
    assert r.status == 404
    assert (await r.json())["error"] == "invalid_code"
    page = await guest.get("/camera/AAAAAAAAAAAAAAAAAAAAAA")
    text = await page.text()
    assert page.status == 200 and 'data-default-lang="ro"' in text and 'data-base="/camera"' in text
    assert 'src="/camera/static/app.js?v=' in text
    assert (await guest.get("/camera/static/app.js")).status == 200


async def test_setpoint_clamped_and_rate_limited(env):
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    r = await guest.post(f"/camera/api/{tok}/setpoint", json={"temperature": 30})
    assert r.status == 200 and (await r.json())["temperature"] == 25
    call = [c for c in fake.service_calls if c["service"] == "set_temperature"][-1]
    assert call["target"]["entity_id"] == "climate.camera_204" and call["service_data"]["temperature"] == 25
    r = await guest.post(f"/camera/api/{tok}/setpoint", json={"temperature": 22})
    assert r.status == 429
    await asyncio.sleep(0.1)
    assert portal.states["climate.camera_204"]["attributes"]["temperature"] == 25
    assert portal.audit.tail(5)[0]["new"] == 25


async def test_mode_change_blocked_by_default(env):
    _, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    r = await guest.post(f"/camera/api/{tok}/mode", json={"hvac_mode": "off"})
    assert r.status == 403


async def test_stream_pushes_updates(env):
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    resp = await guest.get(f"/camera/api/{tok}/stream")
    line = await resp.content.readline()
    assert json.loads(line[6:])["room"]["climate"]["current"] == 21.4
    await resp.content.readline()
    attrs = dict(fake.states["climate.camera_204"]["attributes"], current_temperature=21.9)
    await fake.set_state("climate.camera_204", "heat", attrs)
    line = await asyncio.wait_for(resp.content.readline(), 5)
    assert json.loads(line[6:])["room"]["climate"]["current"] == 21.9
    resp.close()


async def test_precondition_sensor_published(env):
    fake, portal, _, _ = env
    pub = fake.published["sensor.camera_204_next_precondition"]
    ev = portal.schedules["camera_204"][0]
    assert pub["state"] == ev["precondition_start"]
    assert pub["attributes"]["device_class"] == "timestamp"
    assert pub["attributes"]["target_temperature"] == 22
    assert pub["attributes"]["climate_entity"] == "climate.camera_204"


async def test_admin_rotate_invalidates_old_code(env):
    _, portal, guest, admin = env
    old = portal.tokens.token_for("camera_101")
    rooms = await (await admin.get("/api/rooms")).json()
    assert {r["id"] for r in rooms} == {"camera_101", "camera_102", "camera_204"}
    r = await admin.post("/api/rooms/camera_101/rotate")
    new_url = (await r.json())["url"]
    assert old not in new_url and "/camera/" in new_url
    assert (await guest.get(f"/camera/api/{old}")).status == 404
    assert (await guest.get("/camera/api/" + new_url.rsplit("/", 1)[1])).status == 200
    svg = await admin.get("/qr/camera_101.svg")
    assert svg.status == 200 and "<svg" in await svg.text()
    sheet = await (await admin.get("/print")).text()
    assert sheet.count('class="card"') == 3



async def test_pin_flow(env):
    _, portal, guest, admin = env
    tok = portal.tokens.token_for("camera_204")
    r = await admin.post("/api/rooms/camera_204/pin", json={"pin": "12x4"})
    assert r.status == 400
    r = await admin.post("/api/rooms/camera_204/pin", json={"pin": "4821"})
    assert r.status == 200 and (await r.json())["pin_enabled"] is True

    r = await guest.get(f"/camera/api/{tok}")
    assert r.status == 401
    body = await r.json()
    assert body["error"] == "pin_required" and body["name"] == "Camera 204"
    assert (await guest.post(f"/camera/api/{tok}/setpoint", json={"temperature": 22})).status == 401
    assert (await guest.get(f"/camera/api/{tok}/stream")).status == 401

    r = await guest.post(f"/camera/api/{tok}/pin", json={"pin": "0000"})
    assert r.status == 403 and (await r.json())["attempts_left"] == 4
    r = await guest.post(f"/camera/api/{tok}/pin", json={"pin": "4821"})
    assert r.status == 200
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Path=/camera/" in cookie and "SameSite=Strict" in cookie
    assert (await guest.get(f"/camera/api/{tok}")).status == 200

    # Other rooms are unaffected; changing the PIN logs the phone out.
    assert (await guest.get(f"/camera/api/{portal.tokens.token_for('camera_101')}")).status == 200
    await admin.post("/api/rooms/camera_204/pin", json={"pin": "9999"})
    assert (await guest.get(f"/camera/api/{tok}")).status == 401
    await admin.post("/api/pin_all", json={"pin": None})
    assert (await guest.get(f"/camera/api/{tok}")).status == 200


async def test_pin_lockout(env):
    _, portal, guest, admin = env
    tok = portal.tokens.token_for("camera_101")
    await admin.post("/api/rooms/camera_101/pin", json={"pin": "123456"})
    for _ in range(4):
        assert (await guest.post(f"/camera/api/{tok}/pin", json={"pin": "000000"})).status == 403
    r = await guest.post(f"/camera/api/{tok}/pin", json={"pin": "000000"})
    assert r.status == 429
    r = await guest.post(f"/camera/api/{tok}/pin", json={"pin": "123456"})
    assert r.status == 429 and (await r.json())["retry_after"] > 0


async def test_admin_custom_code(env):
    _, portal, guest, admin = env
    old = portal.tokens.token_for("camera_204")
    r = await admin.post("/api/rooms/camera_204/code", json={"code": "c204"})
    row = await r.json()
    assert r.status == 200 and row["custom_code"] and row["url"].endswith("/camera/c204")
    assert (await guest.get(f"/camera/api/{old}")).status == 404
    assert (await guest.get("/camera/api/c204")).status == 200
    assert (await guest.get("/camera/c204")).status == 200
    r = await admin.post("/api/rooms/camera_101/code", json={"code": "C204"})
    assert r.status == 400 and "already uses" in (await r.json())["error"]
    r = await admin.post("/api/rooms/camera_204/code", json={"code": None})
    assert not (await r.json())["custom_code"]
    assert (await guest.get("/camera/api/c204")).status == 404


async def test_assets_are_versioned(env):
    _, _, guest, admin = env
    html = await (await admin.get("/")).text()
    assert "static/admin.js?v=" in html and "__V__" not in html
    r = await admin.get("/static/admin.js")
    assert r.status == 200 and r.headers["Cache-Control"] == "no-cache"
    page = await (await guest.get("/camera/AAAAAAAAAAAAAAAAAAAAAA")).text()
    assert "/camera/static/app.js?v=" in page
    assert (await guest.get("/camera/static/app.js")).headers["Cache-Control"] == "no-cache"


def _set_end(portal, room_id, minutes_from_now):
    from datetime import datetime, timedelta
    h = portal.holds.active(room_id)
    h["end"] = (datetime.now(portal.tz) + timedelta(minutes=minutes_from_now)).isoformat()


async def test_setpoint_starts_manual_heating_that_turns_off(env):
    from datetime import datetime
    fake, portal, guest, _ = env
    await fake.set_state("climate.camera_102", "off", fake.states["climate.camera_102"]["attributes"])
    await asyncio.sleep(0.1)
    tok = portal.tokens.token_for("camera_102")
    r = await guest.post(f"/camera/api/{tok}/setpoint", json={"temperature": 22})
    assert r.status == 200
    call = [c for c in fake.service_calls if c["service"] == "set_temperature"][-1]
    assert call["service_data"] == {"temperature": 22, "hvac_mode": "heat"}  # switched on from off
    hold = portal.holds.active("camera_102")
    left = datetime.fromisoformat(hold["end"]) - datetime.now(portal.tz)
    assert 119 * 60 < left.total_seconds() <= 120 * 60
    data = await (await guest.get(f"/camera/api/{tok}")).json()
    assert data["holds"][0]["active"] and data["hold_default_minutes"] == 120

    _set_end(portal, "camera_102", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert portal.holds.active("camera_102") is None
    assert fake.states["climate.camera_102"]["state"] == "off"


async def test_hold_actions(env):
    from datetime import datetime, timedelta
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_102")
    url = f"/camera/api/{tok}/hold"
    r = await guest.post(url, json={"action": "start", "minutes": 60, "temperature": 23})
    assert r.status == 200
    room = (await r.json())["room"]
    h = room["holds"][0]
    assert h["target"] == 23 and h["kind"] == "manual"
    end1 = datetime.fromisoformat(h["end"])
    r = await guest.post(url, json={"action": "extend", "minutes": 30})
    end2 = datetime.fromisoformat((await r.json())["room"]["holds"][0]["end"])
    assert end2 - end1 == timedelta(minutes=30)
    target = (datetime.now(portal.tz) + timedelta(hours=3)).strftime("%H:%M")
    r = await guest.post(url, json={"action": "until", "until": target})
    assert (await r.json())["room"]["holds"][0]["end"][11:16] == target
    r = await guest.post(url, json={"action": "extend", "minutes": 60 * 20})
    assert r.status == 400 and (await r.json())["error"] == "too_long"
    r = await guest.post(url, json={"action": "bogus"})
    assert r.status == 400

    await asyncio.sleep(3.1)  # rate limit between thermostat changes
    r = await guest.post(url, json={"action": "stop"})
    assert r.status == 200 and (await r.json())["room"]["holds"] == []
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_102"]["state"] == "off"

    start = (datetime.now(portal.tz) + timedelta(hours=1)).strftime("%H:%M")
    end = (datetime.now(portal.tz) + timedelta(hours=2)).strftime("%H:%M")
    r = await guest.post(url, json={"action": "plan", "start": start, "until": end, "temperature": 21.5})
    assert r.status == 200
    planned = (await r.json())["room"]["holds"][0]
    assert not planned["active"] and planned["kind"] == "planned"
    r = await guest.post(url, json={"action": "plan", "start": start, "until": end})
    assert (await r.json())["error"] == "overlap"

    # The planned period starts: heating turns on at its temperature.
    portal.holds.holds[0]["start"] = (datetime.now(portal.tz) - timedelta(seconds=5)).isoformat()
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert portal.holds.active("camera_102")["id"] == planned["id"]
    st = fake.states["climate.camera_102"]
    assert st["state"] == "heat" and st["attributes"]["temperature"] == 21.5

    r = await guest.post(url, json={"action": "plan", "start": start, "until": end})
    pid = [h for h in (await r.json())["room"]["holds"] if not h["active"]][0]["id"]
    r = await guest.post(url, json={"action": "cancel", "id": pid})
    assert [h["id"] for h in (await r.json())["room"]["holds"]] == [planned["id"]]


async def test_hold_end_keeps_heating_during_event(env):
    fake, portal, guest, _ = env
    # camera_204 is preconditioning for an event that starts in 29 min (lead 45 min).
    tok = portal.tokens.token_for("camera_204")
    r = await guest.post(f"/camera/api/{tok}/hold", json={"action": "start", "minutes": 30})
    assert r.status == 200
    _set_end(portal, "camera_204", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert portal.holds.active("camera_204") is None
    assert fake.states["climate.camera_204"]["state"] == "heat"
    assert not [c for c in fake.service_calls if c["service"] == "set_hvac_mode"]


async def test_hold_needs_pin(env):
    _, portal, guest, admin = env
    rid = "camera_102"
    r = await admin.post(f"/api/rooms/{rid}/pin", json={"pin": "4321"})
    assert r.status == 200
    tok = portal.tokens.token_for(rid)
    r = await guest.post(f"/camera/api/{tok}/hold", json={"action": "start"})
    assert r.status == 401


async def test_admin_rooms_show_hold(env):
    _, portal, guest, admin = env
    tok = portal.tokens.token_for("camera_102")
    await guest.post(f"/camera/api/{tok}/hold", json={"action": "start", "minutes": 60})
    rows = {r["id"]: r for r in await (await admin.get("/api/rooms")).json()}
    assert rows["camera_102"]["hold"]["active"] and rows["camera_102"]["planned"] == 0
    assert rows["camera_204"]["hold"] is None


async def test_admin_sets_temperature_and_mode(env):
    fake, portal, guest, admin = env
    r = await admin.post("/api/rooms/camera_204/temperature", json={"temperature": 30})
    assert r.status == 200 and (await r.json())["target"] == 25  # clamped to the room max
    # No rate limit for staff, and no auto-off timer.
    r = await admin.post("/api/rooms/camera_204/temperature", json={"temperature": 21})
    assert r.status == 200 and (await r.json())["target"] == 21
    assert portal.holds.active("camera_204") is None
    r = await admin.post("/api/rooms/camera_204/mode", json={"hvac_mode": "off"})
    row = await r.json()
    assert r.status == 200 and row["hvac_mode"] == "off" and row["hvac_modes"] == ["off", "heat"]
    assert fake.states["climate.camera_204"]["state"] == "off"
    r = await admin.post("/api/rooms/camera_204/mode", json={"hvac_mode": "cool"})
    assert r.status == 400
    r = await admin.post("/api/rooms/camera_204/temperature", json={"temperature": "x"})
    assert r.status == 400
    # Guests still cannot change the mode.
    tok = portal.tokens.token_for("camera_204")
    assert (await guest.post(f"/camera/api/{tok}/mode", json={"hvac_mode": "heat"})).status == 403


async def test_timer_end_restores_admin_settings(env):
    fake, portal, guest, admin = env
    await admin.post("/api/rooms/camera_102/temperature", json={"temperature": 19})
    row = await (await admin.post("/api/rooms/camera_102/mode", json={"hvac_mode": "heat"})).json()
    assert row["default"] == {"hvac_mode": "heat", "temperature": 19, "preset_mode": ""}
    tok = portal.tokens.token_for("camera_102")
    await guest.post(f"/camera/api/{tok}/hold", json={"action": "start", "minutes": 60, "temperature": 23})
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_102"]["attributes"]["temperature"] == 23
    _set_end(portal, "camera_102", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    st = fake.states["climate.camera_102"]
    assert st["state"] == "heat" and st["attributes"]["temperature"] == 19
    assert portal.audit.tail(1)[0]["action"] == "restore_default"


async def test_event_end_restores_admin_settings(env):
    from datetime import datetime, timedelta
    fake, portal, _, admin = env
    await admin.post("/api/rooms/camera_204/temperature", json={"temperature": 18})
    await admin.post("/api/rooms/camera_204/mode", json={"hvac_mode": "off"})
    await fake.set_state("climate.camera_204", "heat", fake.states["climate.camera_204"]["attributes"])  # event heating
    await asyncio.sleep(0.1)
    now = datetime.now(portal.tz)
    await portal.process_holds()  # the first event is preconditioning now: it is tracked
    assert portal.schedules["camera_204"][0]["summary"] in [k[2] for k in portal._running_events]
    assert fake.states["climate.camera_204"]["state"] == "heat"  # nothing changes while it runs
    ev = portal.schedules["camera_204"][0]
    ev["end"] = (now - timedelta(seconds=1)).isoformat()
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_204"]["state"] == "off"
    assert not portal._running_events


async def test_admin_preset_and_restore(env):
    fake, portal, guest, admin = env
    rows = {r["id"]: r for r in await (await admin.get("/api/rooms")).json()}
    assert rows["camera_101"]["preset_modes"] == ["none", "home", "away", "eco", "comfort"]
    assert rows["camera_204"]["preset_modes"] == []
    r = await admin.post("/api/rooms/camera_101/preset", json={"preset_mode": "away"})
    row = await r.json()
    assert r.status == 200 and row["preset_mode"] == "away"
    assert row["default"]["preset_mode"] == "away" and row["default"]["hvac_mode"] == "heat"
    assert (await admin.post("/api/rooms/camera_101/preset", json={"preset_mode": "party"})).status == 400
    # Manual heating, then the timer ends: back to the away preset (room settings mode).
    portal.options.manual_end = "room_settings"
    tok = portal.tokens.token_for("camera_101")
    await guest.post(f"/camera/api/{tok}/hold", json={"action": "start", "minutes": 60, "temperature": 23})
    await asyncio.sleep(0.1)
    await fake.set_state("climate.camera_101_trv", "heat", dict(fake.states["climate.camera_101_trv"]["attributes"], preset_mode="none"))
    await asyncio.sleep(0.1)
    _set_end(portal, "camera_101", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_101_trv"]["attributes"]["preset_mode"] == "away"
    assert portal.audit.tail(1)[0]["preset"] == "away"
    # A temperature set on the admin page replaces the remembered preset.
    row = await (await admin.post("/api/rooms/camera_101/temperature", json={"temperature": 20})).json()
    assert row["default"]["preset_mode"] == "" and row["default"]["temperature"] == 20


async def test_guest_presets_and_no_off(env):
    fake, portal, guest, admin = env
    tok = portal.tokens.token_for("camera_101")
    data = await (await guest.get(f"/camera/api/{tok}")).json()
    assert [p["key"] for p in data["guest_presets"]] == ["heat", "eco"]
    assert (await (await guest.get(f"/camera/api/{portal.tokens.token_for('camera_204')}")).json())["guest_presets"] == []
    # Thermostat off (set by the admin): Încălzire turns heating on with the home preset and starts manual heating.
    await admin.post("/api/rooms/camera_101/mode", json={"hvac_mode": "off"})
    r = await guest.post(f"/camera/api/{tok}/preset", json={"preset": "heat"})
    assert r.status == 200
    await asyncio.sleep(0.1)
    st = fake.states["climate.camera_101_trv"]
    assert st["state"] == "heat" and st["attributes"]["preset_mode"] == "home"
    assert portal.holds.active("camera_101")["kind"] == "manual"
    await asyncio.sleep(3.1)
    r = await guest.post(f"/camera/api/{tok}/preset", json={"preset": "eco"})
    assert r.status == 200 and portal.holds.active("camera_101") is None
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_101_trv"]["attributes"]["preset_mode"] == "away"
    assert fake.states["climate.camera_101_trv"]["state"] == "heat"
    assert (await guest.post(f"/camera/api/{tok}/preset", json={"preset": "off"})).status == 400
    # Guests can never turn the thermostat off, even with mode changes allowed.
    portal.rooms["camera_101"].allow_mode_change = True
    assert (await guest.post(f"/camera/api/{tok}/mode", json={"hvac_mode": "off"})).status == 403


async def test_manual_end_goes_to_eco(env):
    fake, portal, guest, admin = env
    await admin.post("/api/rooms/camera_101/preset", json={"preset_mode": "comfort"})  # room settings: comfort
    tok = portal.tokens.token_for("camera_101")
    await guest.post(f"/camera/api/{tok}/preset", json={"preset": "heat"})
    _set_end(portal, "camera_101", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_101_trv"]["attributes"]["preset_mode"] == "away"
    assert portal.audit.tail(1)[0]["action"] == "hold_end_eco"
    # A room without presets still goes back to its admin settings.
    await admin.post("/api/rooms/camera_102/temperature", json={"temperature": 19})
    tok2 = portal.tokens.token_for("camera_102")
    await guest.post(f"/camera/api/{tok2}/hold", json={"action": "start", "minutes": 60, "temperature": 23})
    _set_end(portal, "camera_102", -1)
    await portal.process_holds()
    await asyncio.sleep(0.1)
    assert fake.states["climate.camera_102"]["attributes"]["temperature"] == 19


async def test_view_only_room(env):
    fake, portal, guest, admin = env
    tok = portal.tokens.token_for("camera_101")
    row = await (await admin.post("/api/rooms/camera_101/view_only", json={"view_only": True})).json()
    assert row["view_only"] is True
    data = await (await guest.get(f"/camera/api/{tok}")).json()
    assert data["view_only"] is True and data["climate"]["current"] == 20.1  # status still visible
    for path, body in (("setpoint", {"temperature": 22}), ("preset", {"preset": "heat"}),
                       ("hold", {"action": "start"}), ("mode", {"hvac_mode": "heat"})):
        r = await guest.post(f"/camera/api/{tok}/{path}", json=body)
        assert r.status == 403 and (await r.json())["error"] == "view_only", path
    # The admin can still change it.
    assert (await admin.post("/api/rooms/camera_101/temperature", json={"temperature": 22})).status == 200
    await admin.post("/api/view_only_all", json={"view_only": False})
    assert (await guest.post(f"/camera/api/{tok}/setpoint", json={"temperature": 21})).status == 200
    await admin.post("/api/view_only_all", json={"view_only": True})
    assert all(portal.view_only(r) for r in portal.rooms)


async def test_heating_inferred_without_hvac_action(env):
    fake, portal, guest, _ = env
    attrs = dict(fake.states["climate.camera_101_trv"]["attributes"])
    attrs.pop("hvac_action", None)
    attrs.pop("current_temperature", None)
    await fake.set_state("climate.camera_101_trv", "heat", dict(attrs, preset_mode="home"))
    await asyncio.sleep(0.1)
    tok = portal.tokens.token_for("camera_101")
    c = (await (await guest.get(f"/camera/api/{tok}")).json())["climate"]
    assert c["heating_on"] is True and c["action_known"] is False and c["current"] is None
    await fake.set_state("climate.camera_101_trv", "heat", dict(attrs, preset_mode="away"))
    await asyncio.sleep(0.1)
    assert (await (await guest.get(f"/camera/api/{tok}")).json())["climate"]["heating_on"] is False
    # Reported hvac_action always wins.
    await fake.set_state("climate.camera_101_trv", "heat", dict(attrs, preset_mode="away", hvac_action="heating"))
    await asyncio.sleep(0.1)
    assert (await (await guest.get(f"/camera/api/{tok}")).json())["climate"]["heating_on"] is True
