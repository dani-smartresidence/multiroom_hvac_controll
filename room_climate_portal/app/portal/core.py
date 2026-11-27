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
from .datalog import DataLog
from .ha import HAClient, HAError
from .pins import PinStore
from .holds import DefaultsStore, HoldError, HoldStore, parse_hhmm
from .rooms import Room, _entity_area, clamp_setpoint, discover, load_overrides
from .schedule import build_events, next_precondition
from .sessions import SessionTracker, room_key
from .tokens import TokenStore
from .topology import Topology, is_circuit_open, is_valve_open, room_temperature

_LOGGER = logging.getLogger(__name__)

SCHEDULE_REFRESH_S = 300
DATALOG_INTERVAL_S = 60
PRUNE_INTERVAL_S = 86400
MAX_LEAD_MINUTES = 600
DEFAULT_LEAD_MINUTES = 120
DEFAULT_PRINT_CAPTION = "Scanează- Termostat"
MAX_CAPTION_LEN = 80
ALL_ROOMS = "*"  # room_settings key for values that apply to every room
REGISTRY_EVENTS = (
    "area_registry_updated",
    "entity_registry_updated",
    "device_registry_updated",
    "label_registry_updated",
    "floor_registry_updated",
)


def _float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def modes_of(attrs: dict) -> list:
    return attrs.get("hvac_modes") or []


def room_id_has_schedule(schedules: dict, room_id: str) -> bool:
    """True once the room's calendar was read, so a missing event really was removed."""
    return room_id in schedules


class RateLimited(Exception):
    pass


class Portal:
    def __init__(self, options: Options, paths: Paths, ha: HAClient):
        self.options = options
        self.paths = paths
        self.ha = ha
        self.tokens = TokenStore(paths.tokens, readable=options.readable_codes)
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
        self.holds = HoldStore(paths.holds)
        self.defaults = DefaultsStore(paths.defaults)
        self.access = DefaultsStore(paths.access)  # {room: {"view_only": bool}}
        self.room_settings = DefaultsStore(paths.room_settings)  # {room: {"lead_minutes": int}}
        self._running_events: dict[tuple, dict] = {}  # (room, start, summary) -> event, while it heats
        self.topology = Topology(paths.topology)
        self.datalog = DataLog(paths.heating_db)
        self.sessions = SessionTracker(self.datalog, self.topology, options.default_target_temp)
        self._plant_index: dict[str, list[tuple[str, str | None]]] = {}  # entity -> [(kind, room/circuit)]
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
        self.tokens.assign_readable({r.id: (r.subtitle, r.name) for r in self.rooms.values()})
        index: dict[str, set[str]] = defaultdict(set)
        for room in self.rooms.values():
            for ent in room.entities:
                index[ent].add(room.id)
        if self.options.outdoor_sensor:
            index[self.options.outdoor_sensor].update(self.rooms)
        self._entity_rooms = dict(index)
        members: dict[str, list[str]] = defaultdict(list)
        dev_by_id = {d["id"]: d for d in devices}
        for entry in entities:
            area = None if entry.get("disabled_by") else _entity_area(entry, dev_by_id)
            if area:
                members[area].append(entry["entity_id"])
        self.topology.refresh(self.rooms, members, self.states)
        self._index_plant()
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
            if entity_id == room.calendar:
                asyncio.create_task(self.refresh_schedule(rid))
            else:
                self.broadcast(rid, {"type": "room", "room": self.snapshot(rid)})
        if entity_id in self._plant_index:
            try:
                self._log_entity(entity_id, int(time.time()))
            except Exception:  # noqa: BLE001  logging must never break the portal
                _LOGGER.exception("Cannot log %s", entity_id)

    # -------------------------------------------------------------- plant + log
    def _index_plant(self) -> None:
        index: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
        for circuit in self.topology.circuits:
            index[circuit].append(("circuit", circuit))
        for link in self.topology.links.values():
            if link.valve:
                index[link.valve].append(("valve", link.room_id))
            if link.temperature:
                index[link.temperature].append(("temp", link.room_id))
        if self.options.outdoor_sensor:
            index[self.options.outdoor_sensor].append(("outdoor", None))
        self._plant_index = dict(index)

    def _log_entity(self, entity_id: str, ts: int) -> None:
        state = self.states.get(entity_id)
        attrs = (state or {}).get("attributes") or {}
        for kind, ref in self._plant_index.get(entity_id, ()):
            if kind == "circuit":
                is_open = is_circuit_open(state)
                self.datalog.record(f"circuit:{ref}:on", 1.0 if is_open else 0.0, ts)
                self.datalog.record(f"circuit:{ref}:heat_request", _float(attrs.get("heat_request")), ts)
                self.datalog.record(f"circuit:{ref}:target", _float(attrs.get("temperature")), ts)
                boiler = self.topology.boiler_of_circuit(ref)
                n_open = len(self.topology.open_circuits(boiler.id, self.states)) if boiler else int(is_open)
                self.sessions.observe(ref, is_open, ts, n_open)
            elif kind == "valve":
                self.datalog.record(f"valve:{entity_id}", 1.0 if is_valve_open(state) else 0.0, ts)
            elif kind == "temp":
                self.datalog.record(room_key(ref), room_temperature(self.topology.link(ref), self.states), ts)
            elif kind == "outdoor":
                self.datalog.record("outdoor", _float((state or {}).get("state")), ts)

    def sample_plant(self, ts: int | None = None) -> None:
        """Log every plant entity now; unchanged values are written only as a heartbeat."""
        ts = int(ts if ts is not None else time.time())
        for entity_id in list(self._plant_index):
            self._log_entity(entity_id, ts)

    async def datalog_loop(self) -> None:
        last_prune = 0.0
        while True:
            await asyncio.sleep(DATALOG_INTERVAL_S)
            if not (self.ha.connected.is_set() and self.ready):
                continue
            try:
                await self.log_tick()
                if time.time() - last_prune > PRUNE_INTERVAL_S:
                    last_prune = time.time()
                    await asyncio.to_thread(self.datalog.prune)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Data log failed")

    async def log_tick(self, now: int | None = None) -> list[int]:
        now = int(now if now is not None else time.time())
        self.sample_plant(now)
        runs = self.sessions.take_done(now)
        await self.datalog.flush()
        return await asyncio.to_thread(self.sessions.finalize, runs) if runs else []

    def update_link(self, room_id: str, values: dict, client: str = "admin"):
        link = self.topology.update_room(room_id, values)
        self._index_plant()
        self.audit.write(room=room_id, action="plant_link", client=client, **{k: values[k] for k in values})
        return link

    def plant(self) -> dict:
        """Boilers with live circuit state, and every room's link, for the admin page."""
        boilers = []
        for b in self.topology.boilers:
            circuits = []
            for c in b.circuits:
                st = self.states.get(c) or {}
                attrs = st.get("attributes") or {}
                circuits.append(
                    {
                        "entity_id": c,
                        "name": attrs.get("friendly_name") or c,
                        "zone": attrs.get("zone_number"),
                        "available": bool(st) and st.get("state") not in ("unavailable", "unknown"),
                        "open": is_circuit_open(st),
                        "preset_mode": attrs.get("preset_mode"),
                        "heat_request": _float(attrs.get("heat_request")),
                        "target": _float(attrs.get("temperature")),
                        "rooms": [l.room_id for l in self.topology.rooms_on_circuit(c)],
                    }
                )
            boilers.append({"id": b.id, "name": b.name, "circuits": circuits, "open": sum(c["open"] for c in circuits)})
        rooms = []
        for rid, room in self.rooms.items():
            link = self.topology.link(rid)
            if link is None:
                continue
            rooms.append(
                {
                    **link.as_dict(),
                    "name": room.name,
                    "subtitle": room.subtitle,
                    "temp_now": room_temperature(link, self.states),
                    "valve_open": is_valve_open(self.states.get(link.valve)) if link.valve else None,
                    "issues": self.topology.issues(rid, self.states),
                }
            )
        candidates = {
            "valves": sorted(e for e in self.states if e.startswith("switch.")),
            "sensors": sorted(
                e for e, st in self.states.items()
                if e.startswith("sensor.") and (st.get("attributes") or {}).get("device_class") == "temperature"
            ),
        }
        return {"boilers": boilers, "rooms": rooms, "candidates": candidates, "default_target": self.options.default_target_temp}

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

    def lead_source(self, room: Room) -> str:
        """Where the room's lead time comes from: "room" (set for this room) or "all" (the all-rooms value)."""
        return "room" if isinstance((self.room_settings.get(room.id) or {}).get("lead_minutes"), int) else "all"

    def default_lead_minutes(self) -> int:
        saved = (self.room_settings.get(ALL_ROOMS) or {}).get("lead_minutes")
        return saved if isinstance(saved, int) else DEFAULT_LEAD_MINUTES

    def lead_minutes(self, room: Room) -> int:
        """Pre-heat/pre-cool lead before each event, set on the admin page. Calendar events never
        carry one: the room's own value wins, else the value for all rooms (120 min out of the box)."""
        saved = (self.room_settings.get(room.id) or {}).get("lead_minutes")
        return saved if isinstance(saved, int) else self.default_lead_minutes()

    @staticmethod
    def _check_lead(minutes) -> None:
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 0 <= minutes <= MAX_LEAD_MINUTES:
            raise ValueError("bad lead time")

    async def set_lead_minutes_all(self, minutes: int | None, client: str = "admin") -> int:
        """Admin page: one lead time for every room (replaces each room's own); None = 120 min."""
        if minutes is None:
            self.room_settings.clear(ALL_ROOMS, "lead_minutes")
        else:
            self._check_lead(minutes)
            self.room_settings.update(ALL_ROOMS, lead_minutes=minutes)
        for rid in list(self.room_settings.data):
            if rid != ALL_ROOMS and "lead_minutes" in (self.room_settings.get(rid) or {}):
                self.room_settings.clear(rid, "lead_minutes")
        new = self.default_lead_minutes()
        self.audit.write(room="all", action="lead_time", new=new, source="all", client=client)
        await self.refresh_all_schedules()
        return new

    # ------------------------------------------------------------ print caption
    def default_print_caption(self) -> str:
        saved = (self.room_settings.get(ALL_ROOMS) or {}).get("print_caption")
        return saved if isinstance(saved, str) else DEFAULT_PRINT_CAPTION

    def print_caption(self, room_id: str) -> str:
        """Text printed under the room's QR code: the room's own, else the one for all rooms."""
        saved = (self.room_settings.get(room_id) or {}).get("print_caption")
        return saved if isinstance(saved, str) else self.default_print_caption()

    def has_own_caption(self, room_id: str) -> bool:
        return isinstance((self.room_settings.get(room_id) or {}).get("print_caption"), str)

    @staticmethod
    def _clean_caption(text) -> str:
        if not isinstance(text, str):
            raise ValueError("bad caption")
        text = " ".join(text.split())
        if len(text) > MAX_CAPTION_LEN:
            raise ValueError("caption too long")
        return text

    def set_print_caption(self, room_id: str, text: str | None) -> str:
        """Admin page: the room's print caption; None goes back to the text for all rooms."""
        if text is None:
            self.room_settings.clear(room_id, "print_caption")
        else:
            self.room_settings.update(room_id, print_caption=self._clean_caption(text))
        new = self.print_caption(room_id)
        self.audit.write(room=room_id, action="print_caption", new=new, client="admin")
        return new

    def set_print_caption_all(self, text: str | None) -> str:
        """Admin page: the caption for every room (replaces each room's own text); None = built-in default."""
        if text is None:
            self.room_settings.clear(ALL_ROOMS, "print_caption")
        else:
            self.room_settings.update(ALL_ROOMS, print_caption=self._clean_caption(text))
        for rid in list(self.room_settings.data):
            if rid != ALL_ROOMS and self.has_own_caption(rid):
                self.room_settings.clear(rid, "print_caption")
        new = self.default_print_caption()
        self.audit.write(room="all", action="print_caption", new=new, client="admin")
        return new

    async def set_lead_minutes(self, room_id: str, minutes: int | None, client: str = "admin") -> int:
        """Admin page: the room's lead time in minutes, or None to go back to the value for all rooms."""
        room = self.rooms[room_id]
        old = self.lead_minutes(room)
        if minutes is None:
            self.room_settings.clear(room_id, "lead_minutes")
        else:
            self._check_lead(minutes)
            self.room_settings.update(room_id, lead_minutes=minutes)
        new = self.lead_minutes(room)
        self.audit.write(room=room_id, action="lead_time", old=old, new=new, source=self.lead_source(room), client=client)
        await self.refresh_schedule(room_id)
        return new

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

        current = num(attrs.get("current_temperature"))
        if current is None and room.temperature:
            current = state_num(self.states.get(room.temperature))
        heating_on, action_known = self._heating_on(room, cl, current)
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
                "preset_mode": attrs.get("preset_mode"),
                "preset_modes": attrs.get("preset_modes") or [],
                "hvac_action": attrs.get("hvac_action"),
                "heating_on": heating_on,
                "action_known": action_known,
                "current": current,
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
            "holds": [HoldStore.public(h) for h in self.holds.for_room(room.id)],
            "hold_default_minutes": self.options.hold_default_minutes,
            "hold_max_hours": self.options.hold_max_hours,
            "default_target": min(max(self.options.default_target_temp, lo), hi),
            "view_only": self.view_only(room.id),
            "guest_presets": [
                {"key": key, "preset": preset, "on": attrs.get("preset_mode") == preset}
                for key, preset in self._guest_presets().items()
                if preset in (attrs.get("preset_modes") or [])
            ],
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

    async def set_temperature(self, room_id: str, value: float, client: str, admin: bool = False) -> float:
        room = self.rooms[room_id]
        if not room.climate:
            raise HAError("no_climate", "room has no thermostat")
        st = self.states.get(room.climate) or {}
        attrs = st.get("attributes") or {}
        target = clamp_setpoint(room, value, attrs)
        if not admin:
            self._check_rate(room_id, client)
        old = attrs.get("temperature")
        data: dict = {"temperature": target}
        mode = None if admin else self._heat_mode(room)
        if mode:  # thermostat is off: a change from the guest page switches heating on
            data["hvac_mode"] = mode
        await self.ha.call_service("climate", "set_temperature", data, entity_id=room.climate)
        self.audit.write(room=room_id, action="set_temperature", old=old, new=target, client=client)
        if admin:
            saved = self.defaults.get(room_id) or {}
            self.defaults.update(
                room_id,
                temperature=target,
                hvac_mode=saved.get("hvac_mode") or (st.get("state") if st.get("state") in modes_of(attrs) else None),
                preset_mode="",  # a manual setpoint replaces the preset on most thermostats
            )
        hold = self.holds.active(room_id)
        if hold:
            hold["target"] = target
            self.holds.save()
        elif not admin:  # staff changes from the admin page are not switched off by a timer
            # A change from the page is manual heating: it switches itself off later.
            now = datetime.now(self.tz)
            self.holds.add(room_id, now, self._default_end(room_id, now), target, "manual", True)
        self.broadcast(room_id, {"type": "room", "room": self.snapshot(room_id)})
        return target

    # ------------------------------------------------------------ manual heating
    def _event_running(self, room_id: str, at: datetime) -> dict | None:
        """Event that is preconditioning or in progress at `at`."""
        for ev in self.schedules.get(room_id, []):
            if ev["all_day"]:
                continue
            pre = datetime.fromisoformat(ev["precondition_start"] or ev["start"])
            if pre <= at < datetime.fromisoformat(ev["end"]):
                return ev
        return None

    def _default_end(self, room_id: str, now: datetime) -> datetime:
        end = now + timedelta(minutes=self.options.hold_default_minutes)
        ev = self._event_running(room_id, now)
        if ev and datetime.fromisoformat(ev["end"]) > end:
            end = datetime.fromisoformat(ev["end"])
        return end

    def _limit_end(self, start: datetime, end: datetime) -> datetime:
        if end <= start:
            raise HoldError("end_before_start")
        if end - start > timedelta(hours=self.options.hold_max_hours):
            raise HoldError("too_long")
        return end

    def _heat_mode(self, room: Room) -> str | None:
        st = self.states.get(room.climate or "") or {}
        modes = (st.get("attributes") or {}).get("hvac_modes") or []
        if st.get("state") not in (None, "off", "unavailable", "unknown"):
            return None  # already on
        for m in ("heat", "heat_cool", "auto"):
            if m in modes:
                return m
        return None

    async def _apply_on(self, room: Room, target: float | None) -> float | None:
        """Switch heating on: heat mode if off, the Încălzire preset (home) when the thermostat has it,
        and the temperature if one was chosen (None = the preset's own temperature)."""
        st = self.states.get(room.climate or "") or {}
        attrs = st.get("attributes") or {}
        mode = self._heat_mode(room)
        heat_preset = self.options.guest_preset_heat
        has_preset = heat_preset in (attrs.get("preset_modes") or [])
        if has_preset:
            if mode:
                await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
                mode = None
            if attrs.get("preset_mode") != heat_preset:
                await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": heat_preset}, entity_id=room.climate)
            if target is None:
                return None
        if target is None:
            cur = attrs.get("temperature")
            target = float(cur) if isinstance(cur, (int, float)) and st.get("state") != "off" else self.options.default_target_temp
        target = clamp_setpoint(room, target, attrs)
        data: dict = {"temperature": target}
        if mode:
            data["hvac_mode"] = mode
        await self.ha.call_service("climate", "set_temperature", data, entity_id=room.climate)
        return target

    async def _apply_off(self, room: Room, reason: str) -> None:
        now = datetime.now(self.tz)
        if self._event_running(room.id, now):
            self.audit.write(room=room.id, action="hold_end_kept_for_event", client="timer")
            return
        eco = self.options.guest_preset_eco
        attrs = (self.states.get(room.climate or "") or {}).get("attributes") or {}
        if self.options.manual_end == "eco" and eco in (attrs.get("preset_modes") or []):
            mode = self._heat_mode(room)
            if mode:
                await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
            await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": eco}, entity_id=room.climate)
            self.audit.write(room=room.id, action="hold_end_eco", new=eco, reason=reason, client="timer")
            return
        await self._restore(room, reason)

    async def _restore(self, room: Room, reason: str) -> None:
        """Back to the room's admin-page settings; without any, off or setback per the options."""
        st = self.states.get(room.climate or "") or {}
        default = self.defaults.get(room.id)
        if default and default.get("hvac_mode") in modes_of(st.get("attributes") or {}):
            mode, temp = default["hvac_mode"], default.get("temperature")
            preset = default.get("preset_mode") or ""
            if preset not in ((st.get("attributes") or {}).get("preset_modes") or []):
                preset = ""
            if mode == "off":
                await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": "off"}, entity_id=room.climate)
            elif preset and preset != "none":
                # The preset brings its own temperature (e.g. away), so only the mode and the preset are set.
                await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
                await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": preset}, entity_id=room.climate)
                self.audit.write(room=room.id, action="restore_default", mode=mode, preset=preset, reason=reason, client="timer")
                return
            else:
                if preset == "none" and (st.get("attributes") or {}).get("preset_mode") not in (None, "none"):
                    await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": "none"}, entity_id=room.climate)
                data: dict = {"hvac_mode": mode}
                if isinstance(temp, (int, float)):
                    data["temperature"] = clamp_setpoint(room, temp, st.get("attributes") or {})
                    await self.ha.call_service("climate", "set_temperature", data, entity_id=room.climate)
                else:
                    await self.ha.call_service("climate", "set_hvac_mode", data, entity_id=room.climate)
            self.audit.write(room=room.id, action="restore_default", new=temp, mode=mode, reason=reason, client="timer")
            return
        modes = modes_of(st.get("attributes") or {})
        if self.options.hold_end_action == "off" and "off" in modes:
            await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": "off"}, entity_id=room.climate)
            self.audit.write(room=room.id, action="heating_off", reason=reason, client="timer")
        else:
            await self.ha.call_service(
                "climate", "set_temperature", {"temperature": self.options.setback_temp}, entity_id=room.climate
            )
            self.audit.write(room=room.id, action="setback", new=self.options.setback_temp, reason=reason, client="timer")

    async def hold_action(self, room_id: str, data: dict, client: str) -> dict:
        room = self.rooms[room_id]
        if not room.climate:
            raise HAError("no_climate", "room has no thermostat")
        now = datetime.now(self.tz)
        action = data.get("action")
        active = self.holds.active(room_id)

        def target_from(value) -> float:
            if value is None:
                st = self.states.get(room.climate) or {}
                cur = (st.get("attributes") or {}).get("temperature")
                if st.get("state") not in (None, "off") and isinstance(cur, (int, float)):
                    return float(cur)
                return self.options.default_target_temp
            return float(value)

        def end_from(start: datetime) -> datetime:
            if data.get("until"):
                return self._limit_end(start, parse_hhmm(data["until"], now, self.tz, after=start))
            if data.get("minutes") is not None:
                minutes = int(data["minutes"])
                if minutes < 5:
                    raise HoldError("too_short")
                return self._limit_end(start, start + timedelta(minutes=minutes))
            return self._default_end(room_id, start)

        if action == "start":
            self._check_rate(room_id, client)
            end = end_from(now)
            chosen = data.get("temperature")
            applied = await self._apply_on(room, float(chosen) if chosen is not None else None)
            target = applied if applied is not None else target_from(None)
            if active:
                self.holds.remove(active["id"])
            hold = self.holds.add(room_id, now, end, target, "manual", True)
            self.audit.write(room=room_id, action="heating_on", new=target, until=hold["end"], client=client)
        elif action in ("extend", "until"):
            if not active:
                raise HoldError("no_active")
            start = datetime.fromisoformat(active["start"])
            if action == "extend":
                new_end = datetime.fromisoformat(active["end"]) + timedelta(minutes=int(data.get("minutes", 60)))
            else:
                new_end = parse_hhmm(data.get("until"), now, self.tz)
            active["end"] = self._limit_end(start, new_end).isoformat()
            self.holds.save()
            self.audit.write(room=room_id, action="heating_until", until=active["end"], client=client)
        elif action == "stop":
            if not active:
                raise HoldError("no_active")
            self._check_rate(room_id, client)
            self.holds.remove(active["id"])
            await self._apply_off(room, "stopped")
        elif action == "plan":
            start = parse_hhmm(data.get("start"), now, self.tz)
            end = self._limit_end(start, parse_hhmm(data.get("until") or data.get("end"), now, self.tz, after=start))
            if start - now > timedelta(hours=24):
                raise HoldError("too_far")
            self.holds.check_planned(room_id, start, end)
            st = self.states.get(room.climate) or {}
            target = clamp_setpoint(room, target_from(data.get("temperature")), st.get("attributes") or {})
            self.holds.add(room_id, start, end, target, "planned", False)
            self.audit.write(room=room_id, action="heating_planned", new=target, start=start.isoformat(), until=end.isoformat(), client=client)
        elif action == "cancel":
            hold = next((h for h in self.holds.for_room(room_id) if h["id"] == data.get("id") and not h.get("active")), None)
            if not hold:
                raise HoldError("not_found")
            self.holds.remove(hold["id"])
            self.audit.write(room=room_id, action="heating_plan_cancelled", client=client)
        else:
            raise HoldError("bad_action")
        snap = self.snapshot(room_id)
        self.broadcast(room_id, {"type": "room", "room": snap})
        return snap

    async def hold_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            if not (self.ready and self.ha.connected.is_set()):
                continue
            try:
                await self.process_holds()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Manual heating timer failed")

    async def process_holds(self) -> None:
        now = datetime.now(self.tz)
        for hold in list(self.holds.holds):
            room = self.rooms.get(hold["room"])
            if room is None or not room.climate:
                continue
            start = datetime.fromisoformat(hold["start"])
            end = datetime.fromisoformat(hold["end"])
            changed = False
            if not hold.get("active") and start <= now < end:
                current = self.holds.active(room.id)
                if current:
                    self.holds.remove(current["id"])
                await self._apply_on(room, hold["target"])
                hold["active"] = True
                self.holds.save()
                self.audit.write(room=room.id, action="heating_on", new=hold["target"], until=hold["end"], client="plan")
                changed = True
            if now >= end:
                self.holds.remove(hold["id"])
                if hold.get("active"):
                    await self._apply_off(room, "timer")
                changed = True
            if changed:
                self.broadcast(room.id, {"type": "room", "room": self.snapshot(room.id)})
        if self.options.restore_after_events:
            await self._process_event_ends(now)

    async def _process_event_ends(self, now: datetime) -> None:
        """When a calendar event's heating ends (or the event is removed), go back to the room defaults."""
        current: dict[tuple, dict] = {}
        for room_id, events in self.schedules.items():
            for ev in events:
                if ev["all_day"]:
                    continue
                key = (room_id, ev["start"], ev["summary"])
                current[key] = ev
                if datetime.fromisoformat(ev["precondition_start"] or ev["start"]) <= now < datetime.fromisoformat(ev["end"]):
                    self._running_events[key] = ev
        for key, ev in list(self._running_events.items()):
            latest = current.get(key, ev)
            ended = now >= datetime.fromisoformat(latest["end"])
            removed = key not in current and room_id_has_schedule(self.schedules, key[0])
            if not (ended or removed):
                continue
            del self._running_events[key]
            room = self.rooms.get(key[0])
            if room is None or not room.climate:
                continue
            if self.holds.active(room.id) or self._event_running(room.id, now):
                continue  # manual heating or the next event takes over
            await self._restore(room, "event_end" if ended else "event_removed")
            self.broadcast(room.id, {"type": "room", "room": self.snapshot(room.id)})

    async def set_mode(self, room_id: str, mode: str, client: str, admin: bool = False) -> str:
        room = self.rooms[room_id]
        if not room.climate or not (room.allow_mode_change or admin):
            raise PermissionError("mode change not allowed")
        st = self.states.get(room.climate) or {}
        modes = (st.get("attributes") or {}).get("hvac_modes") or []
        if mode not in modes:
            raise ValueError("unsupported mode")
        if not admin and mode == "off":
            raise PermissionError("only the admin page can turn a thermostat off")
        if not admin:
            self._check_rate(room_id, client)
        await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
        self.audit.write(room=room_id, action="set_hvac_mode", old=st.get("state"), new=mode, client=client)
        if admin:
            saved = self.defaults.get(room_id) or {}
            target = saved.get("temperature")
            if target is None:
                target = (st.get("attributes") or {}).get("temperature")
            self.defaults.update(room_id, hvac_mode=mode, temperature=target if isinstance(target, (int, float)) else None)
        active = self.holds.active(room_id)
        if mode == "off" and active:
            self.holds.remove(active["id"])
        self.broadcast(room_id, {"type": "room", "room": self.snapshot(room_id)})
        return mode

    def _heating_on(self, room: Room, cl: dict, current: float | None) -> tuple[bool, bool]:
        """Is the room being heated right now? Only a reported hvac_action of "heating" counts."""
        attrs = cl.get("attributes") or {}
        action = attrs.get("hvac_action")
        return action == "heating", bool(action)

    def view_only(self, room_id: str) -> bool:
        return bool((self.access.get(room_id) or {}).get("view_only"))

    def set_view_only(self, room_id: str, value: bool) -> None:
        self.access.update(room_id, view_only=bool(value))
        self.audit.write(room=room_id, action="view_only" if value else "changes_allowed", client="admin")
        self.broadcast(room_id, {"type": "room", "room": self.snapshot(room_id)})

    def _guest_presets(self) -> dict[str, str]:
        return {"heat": self.options.guest_preset_heat, "eco": self.options.guest_preset_eco}

    async def guest_preset(self, room_id: str, key: str, client: str) -> dict:
        """Room page buttons: Încălzire (home preset) starts manual heating, Eco (away preset) ends it.
        Guests can never turn the thermostat off; that stays on the admin page."""
        room = self.rooms[room_id]
        if not room.climate:
            raise HAError("no_climate", "room has no thermostat")
        preset = self._guest_presets().get(key)
        st = self.states.get(room.climate) or {}
        attrs = st.get("attributes") or {}
        if not preset or preset not in (attrs.get("preset_modes") or []):
            raise ValueError("unsupported preset")
        self._check_rate(room_id, client)
        mode = self._heat_mode(room)
        if mode:  # thermostat is off: both buttons switch heating on
            await self.ha.call_service("climate", "set_hvac_mode", {"hvac_mode": mode}, entity_id=room.climate)
        await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": preset}, entity_id=room.climate)
        self.audit.write(room=room_id, action="guest_preset", old=attrs.get("preset_mode"), new=preset, client=client)
        active = self.holds.active(room_id)
        now = datetime.now(self.tz)
        if key == "heat" and not active:
            target = attrs.get("temperature")
            target = float(target) if isinstance(target, (int, float)) else self.options.default_target_temp
            self.holds.add(room_id, now, self._default_end(room_id, now), target, "manual", True)
        elif key == "eco" and active:
            self.holds.remove(active["id"])  # Eco is the guest's way of "turning off"
        snap = self.snapshot(room_id)
        self.broadcast(room_id, {"type": "room", "room": snap})
        return snap

    async def set_preset(self, room_id: str, preset: str, client: str) -> str:
        """Admin page: thermostat preset (away, eco, comfort, ...). Remembered as part of the room settings."""
        room = self.rooms[room_id]
        if not room.climate:
            raise PermissionError("no thermostat")
        st = self.states.get(room.climate) or {}
        attrs = st.get("attributes") or {}
        if preset not in (attrs.get("preset_modes") or []):
            raise ValueError("unsupported preset")
        await self.ha.call_service("climate", "set_preset_mode", {"preset_mode": preset}, entity_id=room.climate)
        self.audit.write(room=room_id, action="set_preset", old=attrs.get("preset_mode"), new=preset, client=client)
        saved = self.defaults.get(room_id) or {}
        mode = saved.get("hvac_mode") or (st.get("state") if st.get("state") in modes_of(attrs) else None)
        self.defaults.update(room_id, preset_mode=preset, hvac_mode=mode)
        self.broadcast(room_id, {"type": "room", "room": self.snapshot(room_id)})
        return preset

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
