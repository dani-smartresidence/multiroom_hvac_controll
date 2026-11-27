"""The heating plant: boilers, their circuits, and which circuit heats which room.

A boiler has up to three circuits (one HA climate entity each). A room is heated by one circuit,
may have its own valve (a switch) on the manifold, and one temperature sensor. The admin page edits
these links; whatever the admin has not set is guessed from the room's Area (a ``*_relay`` switch
becomes the valve, a circuit entity placed in the Area picks the boiler). Saved in
/data/topology.json. Nothing here controls anything yet: it tells the data log what to record and
which samples belong to which heating session.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CATEGORIES = ("event", "frost", "none")
OPEN_PRESETS = ("Winter",)

# The Vox Domini plant: only the first circuit of each boiler is used. Only circuits that exist in HA
# are kept, so other sites start empty and fill /data/topology.json by hand.
DEFAULT_BOILERS = [
    {"id": "sala_plen", "name": "Sala Plen", "circuits": ["climate.salamare1"]},
    {"id": "parter", "name": "Parter", "circuits": ["climate.parter1"]},
    {"id": "etaj_1", "name": "Etaj 1", "circuits": ["climate.etaj1"]},
    {"id": "demisol", "name": "Demisol", "circuits": ["climate.demisol1"]},
]
# Entity ids before the boilers' first circuits were renamed in HA (0.14.0).
RENAMED_CIRCUITS = {
    "climate.zone1": "climate.salamare1",
    "climate.zone2": "climate.parter1",
    "climate.etaj_1": "climate.etaj1",
    "climate.ariston_b4bfe94a5d38_1": "climate.demisol1",
}
# The three circuits per boiler seeded by 0.12.0 and 0.13.0.
OLD_SEEDS = [
    ["climate.zone1", "climate.zone1_2", "climate.zone1_3"],
    ["climate.zone2", "climate.zone2_2", "climate.zone2_3"],
    ["climate.etaj_1", "climate.etaj_1_2", "climate.etaj_1_3"],
    ["climate.ariston_b4bfe94a5d38_1", "climate.ariston_b4bfe94a5d38_2", "climate.ariston_b4bfe94a5d38_3"],
]
LINK_FIELDS = ("boiler", "circuit", "valve", "temperature", "category", "comfort")


class TopologyError(ValueError):
    pass


@dataclass
class Boiler:
    id: str
    name: str
    circuits: list[str] = field(default_factory=list)


@dataclass
class RoomLink:
    room_id: str
    boiler: str | None = None
    circuit: str | None = None
    valve: str | None = None
    temperature: str | None = None
    category: str = "event"
    comfort: float | None = None
    guessed: list[str] = field(default_factory=list)  # fields not set by the admin

    def as_dict(self) -> dict:
        return asdict(self)


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def is_circuit_open(state: dict | None) -> bool:
    """A boiler circuit heats while its preset is Winter or the boiler reports a heat request."""
    if not state or state.get("state") in ("unavailable", "unknown"):
        return False
    attrs = state.get("attributes") or {}
    if attrs.get("preset_mode") in OPEN_PRESETS:
        return True
    return (_num(attrs.get("heat_request")) or 0) > 0


def is_valve_open(state: dict | None) -> bool:
    return bool(state) and state.get("state") == "on"


class Topology:
    def __init__(self, path: Path):
        self._path = path
        self.boilers: list[Boiler] = []
        self._saved_rooms: dict[str, dict] = {}
        self._seeded = False
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.boilers = [Boiler(b["id"], b.get("name") or b["id"], list(b.get("circuits") or [])) for b in raw.get("boilers") or []]
                self._saved_rooms = {str(k): dict(v) for k, v in (raw.get("rooms") or {}).items()}
                self._seeded = True
            except (ValueError, KeyError, TypeError):
                self.boilers, self._saved_rooms = [], {}
            if self._migrate():
                self._save()
        self.links: dict[str, RoomLink] = {}
        self._last: tuple = ({}, {}, {})

    def _migrate(self) -> bool:
        """Old seeds kept three circuits per boiler under the old entity ids: keep the first, renamed."""
        changed = False
        for b in self.boilers:
            if b.circuits in OLD_SEEDS:
                b.circuits = b.circuits[:1]
                changed = True
            renamed = [RENAMED_CIRCUITS.get(c, c) for c in b.circuits]
            if renamed != b.circuits:
                b.circuits, changed = renamed, True
        for saved in self._saved_rooms.values():
            if saved.get("circuit") in RENAMED_CIRCUITS:
                saved["circuit"], changed = RENAMED_CIRCUITS[saved["circuit"]], True
        known = set(self.circuits)
        for rid, saved in list(self._saved_rooms.items()):
            if saved.get("circuit") and saved["circuit"] not in known:
                del saved["circuit"]  # a second or third circuit that is no longer used
                changed = True
        return changed

    # ------------------------------------------------------------------ boilers
    def seed_boilers(self, states: dict[str, dict]) -> None:
        """First start only: keep the default boilers whose circuits exist in HA."""
        if self._seeded:
            return
        for b in DEFAULT_BOILERS:
            circuits = [c for c in b["circuits"] if c in states]
            if circuits:
                self.boilers.append(Boiler(b["id"], b["name"], circuits))
        self._seeded = True
        if self.boilers:
            self._save()

    def boiler(self, boiler_id: str | None) -> Boiler | None:
        return next((b for b in self.boilers if b.id == boiler_id), None)

    def boiler_of_circuit(self, entity_id: str) -> Boiler | None:
        return next((b for b in self.boilers if entity_id in b.circuits), None)

    @property
    def circuits(self) -> list[str]:
        return [c for b in self.boilers for c in b.circuits]

    def open_circuits(self, boiler_id: str, states: dict[str, dict]) -> list[str]:
        b = self.boiler(boiler_id)
        return [c for c in (b.circuits if b else []) if is_circuit_open(states.get(c))]

    # -------------------------------------------------------------------- rooms
    def refresh(self, rooms: dict, members: dict[str, list[str]], states: dict[str, dict]) -> None:
        """Rebuild every room's link: the admin's values, else guesses from the room's Area."""
        self._last = (rooms, members, states)
        self.seed_boilers(states)
        links = {}
        for rid, room in rooms.items():
            area = members.get(rid, [])
            guess = {
                "valve": next((e for e in sorted(area) if e.startswith("switch.") and e.endswith("_relay")), None),
                "temperature": room.temperature,
                "boiler": next((b.id for b in self.boilers if any(c in area for c in b.circuits)), None),
                "circuit": None,
                "category": "event",
                "comfort": None,
            }
            saved = self._saved_rooms.get(rid, {})
            values = {f: saved[f] if f in saved else guess[f] for f in LINK_FIELDS}
            guessed = [f for f in LINK_FIELDS if f not in saved and guess[f] is not None]
            links[rid] = RoomLink(rid, guessed=guessed, **values)
        self.links = links

    def link(self, room_id: str) -> RoomLink | None:
        return self.links.get(room_id)

    def rooms_on_circuit(self, circuit: str) -> list[RoomLink]:
        return [l for l in self.links.values() if l.circuit == circuit]

    def update_room(self, room_id: str, values: dict) -> RoomLink:
        """Save the admin's values for a room. A value of None clears it back to the guess."""
        if room_id not in self.links:
            raise TopologyError("unknown_room")
        saved = dict(self._saved_rooms.get(room_id) or {})
        for key, value in values.items():
            if key not in LINK_FIELDS:
                raise TopologyError(f"unknown_field: {key}")
            if value in (None, ""):
                saved.pop(key, None)
                continue
            saved[key] = self._check(key, value)
        if "circuit" in saved:
            owner = self.boiler_of_circuit(saved["circuit"])
            if owner is None:
                raise TopologyError("unknown_circuit")
            if "boiler" in values and "circuit" not in values and saved.get("boiler") != owner.id:
                saved.pop("circuit")  # the boiler changed, its old circuit no longer applies
            else:
                saved["boiler"] = owner.id
        if saved:
            self._saved_rooms[room_id] = saved
        else:
            self._saved_rooms.pop(room_id, None)
        self._save()
        self.refresh(*self._last)
        return self.links[room_id]

    def _check(self, key: str, value):
        if key == "boiler":
            if not self.boiler(str(value)):
                raise TopologyError("unknown_boiler")
            return str(value)
        if key == "circuit":
            if str(value) not in self.circuits:
                raise TopologyError("unknown_circuit")
            return str(value)
        if key == "category":
            if value not in CATEGORIES:
                raise TopologyError("bad_category")
            return value
        if key == "comfort":
            f = _num(value)
            if f is None or not 5 <= f <= 30:
                raise TopologyError("bad_comfort")
            return f
        domain = {"valve": ("switch.",), "temperature": ("sensor.", "climate.")}[key]
        if not isinstance(value, str) or not value.startswith(domain):
            raise TopologyError(f"bad_{key}")
        return value

    def issues(self, room_id: str, states: dict[str, dict]) -> list[str]:
        link = self.links.get(room_id)
        if not link or link.category == "none":
            return []
        out = []
        if not link.circuit:
            out.append("no_circuit")
        if not link.temperature:
            out.append("no_sensor")
        elif (states.get(link.temperature) or {}).get("state") in (None, "unknown", "unavailable"):
            out.append("sensor_offline")
        return out

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        data = {"boilers": [asdict(b) for b in self.boilers], "rooms": self._saved_rooms}
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)


def room_temperature(link: RoomLink | None, states: dict[str, dict]) -> float | None:
    """The room's temperature from its sensor (a sensor state, or a climate's current_temperature)."""
    if not link or not link.temperature:
        return None
    st = states.get(link.temperature)
    if not st:
        return None
    if link.temperature.startswith("climate."):
        return _num((st.get("attributes") or {}).get("current_temperature"))
    return _num(st.get("state"))
