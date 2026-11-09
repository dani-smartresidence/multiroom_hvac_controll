"""Room QR tokens.

Each room's token is HMAC-SHA256(secret, "<room_id>:<generation>") cut to 128 bits and
base64url-encoded (22 characters). Nothing but the secret and a generation counter per
room is stored, so the admin page can always re-print a room's current code, and
rotating a room just bumps its generation (the old code stops working at once).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path


class TokenStore:
    def __init__(self, path: Path):
        self._path = path
        self._secret: bytes = b""
        self._gen: dict[str, int] = {}
        self._cache: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._secret = bytes.fromhex(raw["secret"])
            self._gen = {k: int(v) for k, v in raw.get("generations", {}).items()}
        else:
            self._secret = secrets.token_bytes(32)
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"secret": self._secret.hex(), "generations": self._gen}, indent=2),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def generation(self, room_id: str) -> int:
        return self._gen.get(room_id, 0)

    def token_for(self, room_id: str) -> str:
        key = f"{room_id}:{self.generation(room_id)}"
        if key not in self._cache:
            mac = hmac.new(self._secret, key.encode(), hashlib.sha256).digest()[:16]
            self._cache[key] = base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
        return self._cache[key]

    def rotate(self, room_id: str) -> str:
        self._gen[room_id] = self.generation(room_id) + 1
        self._save()
        return self.token_for(room_id)

    def resolve(self, token: str, room_ids) -> str | None:
        """Return the room whose current token equals `token`, else None."""
        if not token or len(token) > 64:
            return None
        found = None
        for room_id in room_ids:
            if hmac.compare_digest(self.token_for(room_id), token):
                found = room_id
        return found

    def client_id(self, value: str) -> str:
        """Short pseudonymous id for audit logs (no raw IPs stored)."""
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()[:12]
