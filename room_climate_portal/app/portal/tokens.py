"""Room QR tokens.

Each room's token is HMAC-SHA256(secret, "<room_id>:<generation>") cut to 128 bits and
base64url-encoded (22 characters). Nothing but the secret and a generation counter per
room is stored, so the admin page can always re-print a room's current code, and
rotating a room just bumps its generation (the old code stops working at once).

Readable codes (the default since 0.6.0): a room's link is built from its floor and name,
e.g. "demisol-d01-sala-repetitii-inchinare". The code is fixed the first time a room is seen,
so renaming the area in HA does not break printed QR codes; "Readable code" on the admin page
rebuilds it from the current name. While a room uses a readable code, its random code of the
same generation keeps working too, so QR codes printed before the switch still open the room.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from pathlib import Path

CUSTOM_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
RESERVED = {"api", "static", "healthz"}


class CodeError(ValueError):
    pass


def slugify(text: str, max_len: int = 64) -> str:
    """'Demisol', 'D01 - Sala repetiții închinare' -> 'demisol-d01-sala-repetitii-inchinare'."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:max_len].rstrip("-")


class TokenStore:
    def __init__(self, path: Path, readable: bool = False):
        self._path = path
        self.readable = readable
        self._secret: bytes = b""
        self._gen: dict[str, int] = {}
        self._custom: dict[str, str] = {}
        self._slug: dict[str, str] = {}  # readable code per room, fixed once assigned
        self._random: set[str] = set()  # rooms switched to a random code on purpose
        self._cache: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._secret = bytes.fromhex(raw["secret"])
            self._gen = {k: int(v) for k, v in raw.get("generations", {}).items()}
            self._custom = {k: str(v) for k, v in raw.get("custom", {}).items()}
            self._slug = {k: str(v) for k, v in raw.get("readable", {}).items()}
            self._random = set(raw.get("random", []))
        else:
            self._secret = secrets.token_bytes(32)
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "secret": self._secret.hex(),
                    "generations": self._gen,
                    "custom": self._custom,
                    "readable": self._slug,
                    "random": sorted(self._random),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def generation(self, room_id: str) -> int:
        return self._gen.get(room_id, 0)

    def is_custom(self, room_id: str) -> bool:
        return room_id in self._custom

    def kind(self, room_id: str) -> str:
        if room_id in self._custom:
            return "custom"
        if self.readable and room_id not in self._random and room_id in self._slug:
            return "readable"
        return "random"

    def readable_from(self, room_id: str, subtitle: str, name: str, taken: set[str]) -> str:
        base = slugify(f"{subtitle} {name}") or slugify(room_id)
        if len(base) < 4:
            base = slugify(f"{base} {room_id}")
        if len(base) < 4:
            base = f"{base}-room".lstrip("-")
        base = base[:60].rstrip("-")
        code, n = base, 2
        while code in taken or code in RESERVED:
            code, n = f"{base}-{n}", n + 1
        return code

    def _taken(self, except_room: str | None = None) -> set[str]:
        used = {c.lower() for r, c in self._custom.items() if r != except_room}
        used |= {c for r, c in self._slug.items() if r != except_room}
        return used

    def assign_readable(self, rooms: dict[str, tuple[str, str]]) -> None:
        """Give rooms seen for the first time a readable code: {room_id: (subtitle, name)}."""
        changed = False
        for room_id in sorted(rooms):
            if room_id not in self._slug:
                self._slug[room_id] = self.readable_from(room_id, *rooms[room_id], self._taken())
                changed = True
        if changed:
            self._save()

    def use_readable(self, room_id: str, subtitle: str, name: str) -> str:
        """Back to a readable code, rebuilt from the room's current floor and name."""
        self._custom.pop(room_id, None)
        self._random.discard(room_id)
        self._slug[room_id] = self.readable_from(room_id, subtitle, name, self._taken(room_id))
        self._gen[room_id] = self.generation(room_id) + 1
        self._save()
        return self.token_for(room_id)

    def random_token(self, room_id: str) -> str:
        key = f"{room_id}:{self.generation(room_id)}"
        if key not in self._cache:
            mac = hmac.new(self._secret, key.encode(), hashlib.sha256).digest()[:16]
            self._cache[key] = base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
        return self._cache[key]

    def set_custom(self, room_id: str, code: str | None, room_ids) -> str:
        """Use an admin-chosen code for the room (None = back to a new random code)."""
        if code is None:
            return self.rotate(room_id)
        code = code.strip()
        if not CUSTOM_RE.match(code):
            raise CodeError("Use 4 to 64 characters: letters, digits, - or _.")
        if code.lower() in RESERVED:
            raise CodeError(f"'{code}' is reserved.")
        for other in room_ids:
            if other != room_id and hmac.compare_digest(self.token_for(other).lower(), code.lower()):
                raise CodeError(f"Room {other} already uses this code.")
        self._custom[room_id] = code
        self._gen[room_id] = self.generation(room_id) + 1
        self._save()
        return code

    def token_for(self, room_id: str) -> str:
        if room_id in self._custom:
            return self._custom[room_id]
        if self.kind(room_id) == "readable":
            return self._slug[room_id]
        return self.random_token(room_id)

    def rotate(self, room_id: str) -> str:
        """New random code; the old code (random, readable or custom) stops working."""
        self._custom.pop(room_id, None)
        if self.readable:
            self._random.add(room_id)
        self._gen[room_id] = self.generation(room_id) + 1
        self._save()
        return self.token_for(room_id)

    def resolve(self, token: str, room_ids) -> str | None:
        """Return the room whose current token equals `token`, else None."""
        if not token or len(token) > 64:
            return None
        found = None
        for room_id in room_ids:
            current = self.token_for(room_id)
            if current.lower() == token.lower() if self.kind(room_id) == "readable" else hmac.compare_digest(current, token):
                found = room_id
            elif self.kind(room_id) == "readable" and hmac.compare_digest(self.random_token(room_id), token):
                found = room_id  # QR code printed before the switch to readable codes
        return found

    def sign(self, message: str) -> str:
        return hmac.new(self._secret, message.encode(), hashlib.sha256).hexdigest()

    def client_id(self, value: str) -> str:
        """Short pseudonymous id for audit logs (no raw IPs stored)."""
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()[:12]
