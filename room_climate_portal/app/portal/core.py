"""The portal: keeps the room map, HA state cache and schedules, and fans updates out."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .audit import AuditLog
from .config import Options, Paths
from .ha import HAClient, HAError
from .pins import PinStore
from .rooms import Room, clamp_setpoint, discover, load_overrides
from .schedule import build_events, lead_minutes_from_state, next_precondition
from .tokens import TokenStore

_LOGGER = logging.getLogger(__name__)

SCHEDULE_REFRESH_S = 300
REGISTRY_EVENTS = (
    "area_registry_updated",
    "entity_registry_updated",
    "device_registry_updated",
    "label_registry_updated",
    "floor_registry_updated",
)


class RateLimited(Exception):
    pass


class Portal:
    def __init__(self, options: Options, paths: Paths, ha: HAClient):
        self.options = options
        self.paths = paths
        self.ha = ha
        self.tokens = TokenStore(paths.tokens)
        self.audit = AuditLog(paths.audit)
        self.pins = PinStore(
            paths.pins,
            self.tokens,
            remember_hours=options.pin_remember_hours,
            max_attempts=options.pin_max_attempts,
            lockout_minutes=options.pin_lockout_minutes,
        )
        self.rooms: dict[str, Room] = {}
        self.states: dict[str, dict] = {}
        self.schedules: dict[str, list[dict]] = {}
        self.tz = ZoneInfo("UTC")
        self._watchers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._entity_rooms: dict[str, set[str]] = {}
        self._last_change: dict[str, float] = {}
        self._client_changes: dict[str, deque] = defaultdict(deque)
        self._rediscover_task: asyncio.Task | None = None
        self._schedule_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._published: dict[str, tuple] = {}
        self.ready = False
        ha.on_connect = self._on_connect
        ha.on_disconnect = self._on_disconnect

    # ------------------------------------------------------------------ HA sync
    async def _on_connect(self) -> None:
        config = await self.ha.call({"type": "get_config"})
        try:
            self.tz = ZoneInfo(config.get("time_zone") or "UTC")
        except Exception:  # noqa: BLE001
            self.tz = ZoneInfo("UTC")
        await self.ha.subscribe_events("state_changed", self._on_state_changed)
        for ev in REGISTRY_EVENTS:
            try:
                await self.ha.subscribe_events(ev, self._on_registry_changed)
            except HAError as err:
                _LOGGER.debug("Cannot subscribe to %s: %s", ev, err)
        states = await self.ha.call({"type": "get_states"})
        self.states = {s["entity_id"]: s for s in states}
        await self.rediscover()
        self._published.clear()
        await self.refresh_all_schedules()
        self.broadcast_all({"type": "connection", "connected": True})

    def _on_disconnect(self) -> None:
        self.broadcast_all({"type": "connection", "connected": False})

    async def rediscover(self) -> None:
        async def lst(kind: str) -> list[dict]:
            try:
                return await self.ha.call({"type": f"config/{kind}_registry/list"})
            except HAError as err:
                _LOGGER.warning("Cannot list %s registry: %s", kind, err)
                return []

        areas, floors, entities, devices = await asyncio.gather(
            lst("area"), lst("floor"), lst("entity"), lst("device")
        )
        self.rooms = discover(
            areas=areas,
            floors=floors,
            entities=entities,
            devices=devices,
            states=self.states,
            overrides=load_overrides(self.paths.rooms_override),
            options=self.options,
        )
        index: dict[str, set[str]] = defaultdict(set)
        for room in self.rooms.values():
            for ent in room.entities:
                index[ent].add(room.id)
        if self.options.outdoor_sensor:
            index[self.options.outdoor_sensor].update(self.rooms)
        self._entity_rooms = dict(index)
        self.ready = True
        _LOGGER.info("Discovered %d rooms", len(self.rooms))
        for room in self.rooms.values():
            if room.issues:
                _LOGGER.warning("Room %s: %s", room.id, "; ".join(room.issues))

    def _on_registry_changed(self, _event: dict) -> None:
        # Debounce bursts of registry events into one rediscovery.
        if self._rediscover_task and not self._rediscover_task.done():
            self._rediscover_task.cancel()

        async def later():
            await asyncio.sleep(2)
            await self.rediscover()
            await self.refresh_all_schedules()
            for rid in self.rooms:
                self.broadcast(rid, {"type": "room", "room": self.snapshot(rid)})

        self._rediscover_task = asyncio.create_task(later())

    async def _on_state_changed(self, event: dict) -> None:
        data = event.get("data") or {}
        entity_id = data.get("entity_id")
        new = data.get("new_state")
        if not entity_id:
            return
        if new is None:
            self.states.pop(entity_id, None)
        else:
            self.states[entity_id] = new
        for rid in self._entity_rooms.get(entity_id, ()):
            room = self.rooms.get(rid)
            if room is None:
                continue
            if entity_id in (room.calendar, room.lead_time):
                asyncio.create_task(self.refresh_schedule(rid))
            else:
                self.broadcast(rid, {"type": "room", "room": self.snapshot(rid)})

    # ---------------------------------------------------------------- schedules
    async def schedule_loop(self) -> None:
        while True:
            await asyncio.sleep(SCHEDULE_REFRESH_S)
            if self.ha.connected.is_set():
                try:
                    await self.refresh_all_schedules()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Schedule refresh failed")

    async def refresh_all_schedules(self) -> None:
        await asyncio.gather(*(self.refresh_schedule(r) for r in list(self.rooms)), return_exceptions=True)

    def lead_minutes(self, room: Room) -> int:
        st = self.states.get(room.lead_time) if room.lead_time else None
        return lead_minutes_from_state(st, self.options.default_lead_minutes)

    async def refresh_schedule(self, room_id: str) -> None:
        room = self.rooms.get(room_id)
        if room is None:
            return
        async with self._schedule_locks[room_id]:
            now = datetime.now(self.tz)
            raw: list[dict] = []
            if room.calendar:
                end = now + timedelta(days=self.options.schedule_days)
                try:
                    resp = await self.ha.call_service(
                        "calendar",
                        "get_events",
                        {"start_date_time": now.isoformat(), "end_date_time": end.isoformat()},
                        entity_id=room.calendar,
                        return_response=True,
                    )
                    raw = ((resp or {}).get(room.calendar) or {}).get("events") or []
                except HAError as err:
                    _LOGGER.warning("Cannot read %s: %s", room.calendar, err)
                    raw = []
            self.schedules[room_id] = build_events(
                raw,
                lead_minutes=self.lead_minutes(room),
                default_target=self.options.default_target_temp,
                tz=self.tz,
                now=now,
            )
        await self._publish_precondition_sensor(room)
        self.broadcast(room_id, {"type": "room", "room": self.snapshot(room_id)})

    async def _publish_precondition_sensor(self, room: Room) -> None:
        if not self.options.publish_precondition_sensors:
            return
        ev = next_precondition(self.schedules.get(room.id, []), datetime.now(self.tz))
        entity_id = f"sensor.{room.id}_next_precondition"
        state = ev["precondition_start"] if ev else "unknown"
        attrs = {
            "device_class": "timestamp",
            "friendly_name": f"{room.name} next precondition",
            "icon": "mdi:thermometer-auto",
            "room": room.id,
            "climate_entity": room.climate,
            "event_summary": ev["summary"] if ev else None,
            "event_start": ev["start"] if ev else None,
            "event_end": ev["end"] if ev else None,
            "target_temperature": ev["target"] if ev else None,
            "lead_minutes": ev["lead_minutes"] if ev else None,
        }
        key = (state, tuple(sorted((k, str(v)) for k, v in attrs.items())))
        if self._published.get(entity_id) == key:
            return
        try:
            await self.ha.set_state(entity_id, state, attrs)
            self._published[entity_id] = key
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Cannot publish %s: %s", entity_id, err)

    # ----------------------------------------------------------------- snapshot
    def snapshot(self, room_id: str) -> dict:
        room = self.rooms[room_id]
        cl = self.states.get(room.climate or "") or {}
        attrs = cl.get("attributes") or {}

        def num(v):
            return float(v) if isinstance(v, (int, float)) else None

        hum = self.states.get(room.humidity or "") if room.humidity else None
        out = self.states.get(self.options.outdoor_sensor) if self.options.outdoor_sensor else None

        def state_num(st):
            try:
                return float(st["state"]) if st else None
            except (TypeError, ValueError):
                return None

        lo = max(room.min_temp, num(attrs.get("min_temp")) or room.min_temp)
        hi = min(room.max_temp, num(attrs.get("max_temp")) or room.max_temp)
        return {
            "id": room.id,
            "name": room.name,
            "subtitle": room.subtitle,
            "connected": self.ha.connected.is_set(),
            "time_zone": str(self.tz),
            "climate": {
                "available": bool(cl) and cl.get("state") not in ("unavailable", "unknown"),
                "hvac_mode": cl.get("state"),
                "hvac_modes": attrs.get("hvac_modes") or [],
                "hvac_action": attrs.get("hvac_action"),
                "current": num(attrs.get("current_temperature")),
                "target": num(attrs.get("temperature")),
                "min": lo,
                "max": hi,
                "step": room.step,
                "unit": "°C",
            },
            "allow_mode_change": room.allow_mode_change,
            "humidity": state_num(hum),
            "outdoor": state_num(out),
            "lead_minutes": self.lead_minutes(room),
            "schedule_days": self.options.schedule_days,
            "events": self.schedules.get(room.id, []),
            "help_text": self.options.help_text,
            "default_language": self.options.default_language,
        }

    # -------------------------------------------------------------- fan-out
    def watch(self, room_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._watchers[room_id].add(q)
        return q

    def unwatch(self, room_id: str, q: asyncio.Queue) -> None:
        self._watchers[room_id].discard(q)

    def broadcast(self, room_id: str, message: dict) -> None:
        for q in list(self._watchers.get(room_id, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def broadcast_all(self, message: dict) -> None:
        for rid in list(self._watchers):
            self.broadcast(rid, message)

    def watcher_count(self, room_id: str) -> int:
        return len(self._watchers.get(room_id, ()))

    # ---------------------------------------------------------------- actions
    def _check_rate(self, room_id: str, client: str) -> None:
        now = time.monotonic()
        last = self._last_change.get(room_id, 0)
        if now - last < self.options.rate_limit_seconds:
            raise RateLimited("room")
        window = self._client_changes[client]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= self.options.max_changes_per_hour:
            raise RateLimited("client")
        self._last_change[room_id] = now
        window.append(now)

    async def set_temperature(self, room_id: str, value: float, client: str) -> float:
        room = self.rooms[room_id]
        if not room.climate:
            raise HAError("no_climate", "room has no thermostat")
        st = self.states.get(room.climate) or {}
        attrs = st.get("attributes") or {}
        target = clamp_setpoint(room, value, attrs)
        self._check_rate(room_id, client)
        old = attrs.get("temperature")
        await self.ha.call_service("climate", "set_temperature", {"temperature": target}, entity_id=room.climate)
        self.audit.write(room=room_id, action="set_temperature", old=old, new=target, client=client)
        return target

    async def set_mode(self, room_id: str, mode: str, client: str) -> str:
        room = self.rooms[room_id]
        if not room.allow_mode_change or not room.climate:
            raise PermissionError("mode change not allowed")
        st = self.states.get(room.climate) or {}
        modes = (st.get("attributes") or {}).get("hvac_modes") or []
        if mode not in modes:
            raise ValueError("unsupported mode")
        self._check_rate(room_id, client)
        await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
        self.audit.write(room=room_id, action="set_hvac_mode", old=st.get("state"), new=mode, client=client)
        return mode

    # ------------------------------------------------------------------ tokens
    def room_for_token(self, token: str) -> str | None:
        return self.tokens.resolve(token, self.rooms.keys())

    def room_url(self, room_id: str) -> str:
        return f"{self.options.public_url}{self.options.base_path}/{self.tokens.token_for(room_id)}"

    def set_pin(self, room_id: str, pin: str | None) -> None:
        self.pins.set_pin(room_id, pin)
        self.audit.write(room=room_id, action="pin_set" if pin else "pin_removed", client="admin")
        # Phones holding a session for the old PIN must enter the new one.
        self.broadcast(room_id, {"type": "reauth"})
