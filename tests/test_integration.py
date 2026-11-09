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
    r = await guest.get(f"/api/r/{tok}")
    assert r.status == 200
    data = await r.json()
    assert data["name"] == "Camera 204"
    assert data["climate"]["current"] == 21.4 and data["climate"]["target"] == 22.5
    assert data["climate"]["min"] == 18 and data["climate"]["max"] == 25
    assert data["humidity"] == 44 and data["outdoor"] == 6
    assert data["lead_minutes"] == 45
    first = data["events"][0]
    assert first["summary"] == "Ședința consiliului" and first["lead_minutes"] == 45
    assert data["events"][1]["lead_minutes"] == 30
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert r.headers["Referrer-Policy"] == "no-referrer"


async def test_invalid_token_and_page(env):
    _, portal, guest, _ = env
    r = await guest.get("/api/r/AAAAAAAAAAAAAAAAAAAAAA")
    assert r.status == 404
    assert (await r.json())["error"] == "invalid_code"
    page = await guest.get("/r/whatever")
    assert page.status == 200 and 'data-default-lang="ro"' in await page.text()


async def test_setpoint_clamped_and_rate_limited(env):
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    r = await guest.post(f"/api/r/{tok}/setpoint", json={"temperature": 30})
    assert r.status == 200 and (await r.json())["temperature"] == 25
    call = [c for c in fake.service_calls if c["service"] == "set_temperature"][-1]
    assert call["target"]["entity_id"] == "climate.camera_204" and call["service_data"]["temperature"] == 25
    r = await guest.post(f"/api/r/{tok}/setpoint", json={"temperature": 22})
    assert r.status == 429
    await asyncio.sleep(0.1)
    assert portal.states["climate.camera_204"]["attributes"]["temperature"] == 25
    assert portal.audit.tail(5)[0]["new"] == 25


async def test_mode_change_blocked_by_default(env):
    _, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    r = await guest.post(f"/api/r/{tok}/mode", json={"hvac_mode": "off"})
    assert r.status == 403


async def test_stream_pushes_updates(env):
    fake, portal, guest, _ = env
    tok = portal.tokens.token_for("camera_204")
    resp = await guest.get(f"/api/r/{tok}/stream")
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
    assert old not in new_url
    assert (await guest.get(f"/api/r/{old}")).status == 404
    assert (await guest.get("/api/r/" + new_url.rsplit("/", 1)[1])).status == 200
    svg = await admin.get("/qr/camera_101.svg")
    assert svg.status == 200 and "<svg" in await svg.text()
    sheet = await (await admin.get("/print")).text()
    assert sheet.count('class="card"') == 3

