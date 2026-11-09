"""Optional per-room PIN.

The admin sets (or clears) a 4-8 digit PIN per room. PINs are stored as salted
PBKDF2 hashes in /data/pins.json. A correct PIN gives the phone a signed, HttpOnly
cookie valid for `pin_remember_hours`; changing or clearing the PIN bumps the room's
version, which invalidates every cookie issued before.

Wrong guesses are limited per phone (pin_max_attempts per pin_lockout_minutes) and per
room (ROOM_FAILS_PER_HOUR), so a leaked QR code cannot be used to brute-force the PIN.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from .tokens import TokenStore

PIN_RE = re.compile(r"^\d{4,8}$")
ROOM_FAILS_PER_HOUR = 50
ITERATIONS = 120_000


class PinLocked(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"locked for {retry_after}s")
        self.retry_after = retry_after


class PinStore:
    def __init__(self, path: Path, tokens: TokenStore, *, remember_hours: int, max_attempts: int, lockout_minutes: int):
        self._path = path
        self._tokens = tokens
        self.remember_s = max(1, remember_hours) * 3600
        self.max_attempts = max(1, max_attempts)
        self.lockout_s = max(1, lockout_minutes) * 60
        self._pins: dict[str, dict] = {}
        self._fails: dict[tuple[str, str], deque] = defaultdict(deque)
        self._room_fails: dict[str, deque] = defaultdict(deque)
        if path.exists():
            self._pins = json.loads(path.read_text(encoding="utf-8"))

    # ----------------------------------------------------------------- admin
    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._pins, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def enabled(self, room_id: str) -> bool:
        return bool(self._pins.get(room_id, {}).get("hash"))

    def version(self, room_id: str) -> int:
        return int(self._pins.get(room_id, {}).get("version", 0))

    def set_pin(self, room_id: str, pin: str | None) -> None:
        if pin is not None and not PIN_RE.match(pin):
            raise ValueError("PIN must be 4 to 8 digits")
        entry = {"version": self.version(room_id) + 1}
        if pin is not None:
            salt = secrets.token_bytes(16)
            entry["salt"] = salt.hex()
            entry["hash"] = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, ITERATIONS).hex()
        self._pins[room_id] = entry
        self._save()
        for key in [k for k in self._fails if k[0] == room_id]:
            del self._fails[key]
        self._room_fails.pop(room_id, None)

    # ----------------------------------------------------------------- guest
    def _prune(self, q: deque, window: float, now: float) -> None:
        while q and now - q[0] > window:
            q.popleft()

    def check_locked(self, room_id: str, client: str) -> None:
        now = time.time()
        q = self._fails[(room_id, client)]
        self._prune(q, self.lockout_s, now)
        if len(q) >= self.max_attempts:
            raise PinLocked(int(self.lockout_s - (now - q[0])) + 1)
        rq = self._room_fails[room_id]
        self._prune(rq, 3600, now)
        if len(rq) >= ROOM_FAILS_PER_HOUR:
            raise PinLocked(int(3600 - (now - rq[0])) + 1)

    def verify(self, room_id: str, pin: str, client: str) -> tuple[bool, int]:
        """Returns (ok, attempts_left). Raises PinLocked."""
        self.check_locked(room_id, client)
        entry = self._pins.get(room_id) or {}
        if not entry.get("hash"):
            return True, self.max_attempts
        ok = False
        if PIN_RE.match(pin or ""):
            calc = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(entry["salt"]), ITERATIONS).hex()
            ok = hmac.compare_digest(calc, entry["hash"])
        if ok:
            self._fails.pop((room_id, client), None)
            return True, self.max_attempts
        now = time.time()
        self._fails[(room_id, client)].append(now)
        self._room_fails[room_id].append(now)
        left = self.max_attempts - len(self._fails[(room_id, client)])
        if left <= 0:
            raise PinLocked(self.lockout_s)
        return False, left

    # --------------------------------------------------------------- session
    def make_session(self, room_id: str) -> str:
        expires = int(time.time()) + self.remember_s
        sig = self._tokens.sign(f"pin:{room_id}:{self.version(room_id)}:{expires}")
        return f"{expires}.{sig}"

    def session_valid(self, room_id: str, cookie: str | None) -> bool:
        if not self.enabled(room_id):
            return True
        if not cookie or "." not in cookie:
            return False
        exp, sig = cookie.split(".", 1)
        if not exp.isdigit() or int(exp) < time.time():
            return False
        expected = self._tokens.sign(f"pin:{room_id}:{self.version(room_id)}:{exp}")
        return hmac.compare_digest(expected, sig)
