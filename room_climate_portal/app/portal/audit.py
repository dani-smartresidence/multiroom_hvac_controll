"""Append-only audit log of guest changes (JSON lines in /data)."""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
KEEP_LINES = 20000


class AuditLog:
    def __init__(self, path: Path):
        self._path = path

    def write(self, **entry) -> None:
        entry = {"ts": time.time(), **entry}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self._path.stat().st_size > MAX_BYTES:
            self._trim()

    def _trim(self) -> None:
        lines = deque(self._path.read_text(encoding="utf-8").splitlines(), maxlen=KEEP_LINES)
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tail(self, limit: int = 200, room_id: str | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        out: deque = deque(maxlen=limit)
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if room_id is None or row.get("room") == room_id:
                    out.append(row)
        return list(reversed(out))
