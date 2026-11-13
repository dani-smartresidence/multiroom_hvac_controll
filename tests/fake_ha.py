"""A small stand-in for Home Assistant's websocket + REST API, for tests and local demos.

Run it on its own:  python3 tests/fake_ha.py  (listens on :8123, token "test-token")
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import WSMsgType, web

TOKEN = "test-token"
TZ = ZoneInfo("Europe/Bucharest")


def _at(day_offset: int, hh: int, mm: int, now: datetime) -> str:
    d = (now + timedelta(days=day_offset)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return d.isoformat()


class FakeHA:
    def __init__(self, now: datetime | None = None):
        now = now or datetime.now(TZ)
        self.now = now
        self.service_calls: list[dict] = []
        self.published: dict[str, dict] = {}
        self.clients: set[web.WebSocketResponse] = set()
        self.subs: dict[web.WebSocketResponse, dict[int, str]] = {}
        self.floors = [{"floor_id": "etaj_2", "name": "Etaj 2"}, {"floor_id": "etaj_1", "name": "Etaj 1"}]
        self.areas = [
            {"area_id": "camera_204", "name": "Camera 204", "floor_id": "etaj_2", "labels": ["qr_room"]},
            {"area_id": "camera_101", "name": "Camera 101", "floor_id": "etaj_1", "labels": ["qr_room"]},
            {"area_id": "camera_102", "name": "Camera 102", "floor_id": "etaj_1", "labels": ["qr_room"]},
            {"area_id": "receptie", "name": "Recepție", "floor_id": "etaj_1", "labels": []},
        ]
        self.devices = [{"id": "dev_trv_101", "area_id": "camera_101"}]
        self.entities = [
            {"entity_id": "climate.camera_204", "area_id": "camera_204", "labels": []},
            {"entity_id": "calendar.camera_204", "area_id": "camera_204", "labels": []},
            {"entity_id": "input_number.camera_204_precondition_minutes", "area_id": "camera_204", "labels": ["precondition_lead"]},
            {"entity_id": "sensor.camera_204_humidity", "area_id": "camera_204", "labels": []},
            # Room 101: thermostat linked through its device's area, calculated lead time sensor.
            {"entity_id": "climate.camera_101_trv", "area_id": None, "device_id": "dev_trv_101", "labels": []},
            {"entity_id": "calendar.camera_101", "area_id": "camera_101", "labels": []},
            {"entity_id": "sensor.camera_101_precondition_minutes", "area_id": "camera_101", "labels": []},
            # Room 102: no calendar yet -> reported as an issue.
            {"entity_id": "climate.camera_102", "area_id": "camera_102", "labels": []},
            {"entity_id": "climate.receptie", "area_id": "receptie", "labels": []},
            {"entity_id": "sensor.outdoor_temperature", "area_id": None, "labels": []},
        ]

        def climate(eid, cur, tgt, action="heating", mode="heat"):
            return {
                "entity_id": eid, "state": mode,
                "attributes": {"current_temperature": cur, "temperature": tgt, "hvac_action": action,
                               "hvac_modes": ["off", "heat"], "min_temp": 7, "max_temp": 35,
                               "friendly_name": eid},
            }

        self.states = {
            "climate.camera_204": climate("climate.camera_204", 21.4, 22.5),
            "climate.camera_101_trv": climate("climate.camera_101_trv", 20.1, 21.0, "idle"),
            "climate.camera_102": climate("climate.camera_102", 19.0, 20.0),
            "climate.receptie": climate("climate.receptie", 22.0, 22.0),
            "input_number.camera_204_precondition_minutes": {"entity_id": "input_number.camera_204_precondition_minutes", "state": "45.0", "attributes": {"unit_of_measurement": "min"}},
            "sensor.camera_101_precondition_minutes": {"entity_id": "sensor.camera_101_precondition_minutes", "state": "85", "attributes": {"unit_of_measurement": "min"}},
            "sensor.camera_204_humidity": {"entity_id": "sensor.camera_204_humidity", "state": "44", "attributes": {"device_class": "humidity", "unit_of_measurement": "%"}},
            "sensor.outdoor_temperature": {"entity_id": "sensor.outdoor_temperature", "state": "6.0", "attributes": {"unit_of_measurement": "°C"}},
            "calendar.camera_204": {"entity_id": "calendar.camera_204", "state": "off", "attributes": {}},
            "calendar.camera_101": {"entity_id": "calendar.camera_101", "state": "off", "attributes": {}},
        }
        n = now
        self.states["climate.camera_101_trv"]["attributes"].update(preset_modes=["none", "away", "eco", "comfort"], preset_mode="none")
        self.calendars = {
            "calendar.camera_204": [
                {"summary": "Ședința consiliului", "start": (n + timedelta(minutes=29)).replace(second=0, microsecond=0).isoformat(),
                 "end": (n + timedelta(minutes=149)).replace(second=0, microsecond=0).isoformat(), "description": "target: 22"},
                {"summary": "Atelier de echipă", "start": (n + timedelta(hours=4)).replace(minute=30, second=0, microsecond=0).isoformat(),
                 "end": (n + timedelta(hours=6)).replace(minute=0, second=0, microsecond=0).isoformat(), "description": "target: 21,5\nprecondition: 30"},
                {"summary": "Prezentare client", "start": _at(1, 9, 0, n), "end": _at(1, 11, 0, n), "description": "target: 22\nprecondition: 85"},
                {"summary": "Sesiune de instruire", "start": _at(1, 13, 0, n), "end": _at(1, 17, 0, n), "description": "țintă: 21\nprecondition: 40"},
                {"summary": "Curățenie generală", "start": (n + timedelta(days=2)).date().isoformat(), "end": (n + timedelta(days=3)).date().isoformat(), "description": ""},
            ],
            "calendar.camera_101": [
                {"summary": "Check-in oaspete", "start": _at(1, 15, 0, n), "end": _at(3, 11, 0, n), "description": "target: 22.5"},
            ],
        }

    # ------------------------------------------------------------------ server
    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/websocket", self.ws)
        app.router.add_post("/api/states/{entity_id}", self.rest_state)
        return app

    async def rest_state(self, request: web.Request) -> web.Response:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return web.Response(status=401)
        body = await request.json()
        eid = request.match_info["entity_id"]
        self.published[eid] = body
        await self.set_state(eid, body["state"], body.get("attributes", {}))
        return web.json_response({"entity_id": eid, **body})

    async def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        old = self.states.get(entity_id)
        new = {"entity_id": entity_id, "state": state, "attributes": attributes}
        self.states[entity_id] = new
        await self.fire("state_changed", {"entity_id": entity_id, "old_state": old, "new_state": new})

    async def fire(self, event_type: str, data: dict) -> None:
        for ws, subs in list(self.subs.items()):
            for sid, et in subs.items():
                if et == event_type and not ws.closed:
                    await ws.send_json({"id": sid, "type": "event", "event": {"event_type": event_type, "data": data}})

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required", "ha_version": "2026.11.0"})
        msg = await ws.receive_json()
        if msg.get("access_token") != TOKEN:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok", "ha_version": "2026.11.0"})
        self.clients.add(ws)
        self.subs[ws] = {}
        try:
            async for raw in ws:
                if raw.type != WSMsgType.TEXT:
                    continue
                await self.handle(ws, json.loads(raw.data))
        finally:
            self.clients.discard(ws)
            self.subs.pop(ws, None)
        return ws

    async def handle(self, ws, msg: dict) -> None:
        mid, typ = msg["id"], msg["type"]

        async def ok(result=None):
            await ws.send_json({"id": mid, "type": "result", "success": True, "result": result})

        async def err(code, message):
            await ws.send_json({"id": mid, "type": "result", "success": False, "error": {"code": code, "message": message}})

        if typ == "get_config":
            return await ok({"time_zone": str(TZ), "unit_system": {"temperature": "°C"}})
        if typ == "get_states":
            return await ok(list(self.states.values()))
        if typ == "subscribe_events":
            self.subs[ws][mid] = msg.get("event_type")
            return await ok(None)
        if typ == "config/area_registry/list":
            return await ok(self.areas)
        if typ == "config/floor_registry/list":
            return await ok(self.floors)
        if typ == "config/entity_registry/list":
            return await ok(self.entities)
        if typ == "config/device_registry/list":
            return await ok(self.devices)
        if typ == "call_service":
            self.service_calls.append(msg)
            dom, svc = msg["domain"], msg["service"]
            target = (msg.get("target") or {}).get("entity_id")
            data = msg.get("service_data") or {}
            if dom == "calendar" and svc == "get_events":
                start = datetime.fromisoformat(data["start_date_time"])
                end = datetime.fromisoformat(data["end_date_time"])
                evs = []
                for ev in self.calendars.get(target, []):
                    es = datetime.fromisoformat(ev["start"]) if len(ev["start"]) > 10 else datetime.fromisoformat(ev["start"]).replace(tzinfo=TZ)
                    ee = datetime.fromisoformat(ev["end"]) if len(ev["end"]) > 10 else datetime.fromisoformat(ev["end"]).replace(tzinfo=TZ)
                    if ee > start and es < end:
                        evs.append(ev)
                return await ok({"context": {}, "response": {target: {"events": evs}}})
            if dom == "climate" and svc == "set_temperature":
                st = self.states.get(target)
                if not st:
                    return await err("not_found", f"{target} not found")
                attrs = dict(st["attributes"], temperature=data["temperature"])
                await ok({"context": {}})
                await self.set_state(target, data.get("hvac_mode", st["state"]), attrs)
                return
            if dom == "climate" and svc == "set_preset_mode":
                st = self.states[target]
                if data["preset_mode"] not in st["attributes"].get("preset_modes", []):
                    return await err("invalid", "bad preset")
                await ok({"context": {}})
                attrs = dict(st["attributes"], preset_mode=data["preset_mode"])
                if data["preset_mode"] == "away":
                    attrs["temperature"] = 16
                await self.set_state(target, st["state"], attrs)
                return
            if dom == "climate" and svc == "set_hvac_mode":
                st = self.states[target]
                await ok({"context": {}})
                await self.set_state(target, data["hvac_mode"], st["attributes"])
                return
            return await err("not_found", f"Service {dom}.{svc} not found")
        return await err("unknown_command", typ)


async def _serve(port: int) -> None:
    fake = FakeHA()
    runner = web.AppRunner(fake.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"fake HA on :{port}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(_serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8123))
