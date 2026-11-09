"""Add-on options and paths."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Options:
    public_url: str = "http://homeassistant.local:8080"
    default_language: str = "ro"
    room_label: str = "qr_room"
    lead_time_label: str = "precondition_lead"
    outdoor_sensor: str = ""
    min_temp: float = 18.0
    max_temp: float = 25.0
    temp_step: float = 0.5
    default_target_temp: float = 21.0
    default_lead_minutes: int = 45
    schedule_days: int = 7
    allow_mode_change: bool = False
    publish_precondition_sensors: bool = True
    rate_limit_seconds: int = 3
    max_changes_per_hour: int = 60
    trust_proxy_headers: bool = False
    help_text: str = "Întrebați la recepție."

    @classmethod
    def load(cls, path: Path) -> "Options":
        data: dict = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        opts = cls(**{k: v for k, v in data.items() if k in known and v is not None})
        opts.public_url = opts.public_url.rstrip("/")
        if opts.default_language not in ("ro", "en"):
            opts.default_language = "ro"
        return opts


@dataclass
class Paths:
    data: Path = field(default_factory=lambda: Path(os.environ.get("PORTAL_DATA_DIR", "/data")))
    config: Path = field(default_factory=lambda: Path(os.environ.get("PORTAL_CONFIG_DIR", "/config")))

    @property
    def options(self) -> Path:
        return self.data / "options.json"

    @property
    def tokens(self) -> Path:
        return self.data / "tokens.json"

    @property
    def audit(self) -> Path:
        return self.data / "audit.jsonl"

    @property
    def rooms_override(self) -> Path:
        return self.config / "rooms.yaml"


@dataclass
class HAConnection:
    ws_url: str
    rest_url: str
    token: str

    @classmethod
    def from_env(cls) -> "HAConnection":
        sup = os.environ.get("SUPERVISOR_TOKEN")
        if sup:
            return cls("ws://supervisor/core/websocket", "http://supervisor/core/api", sup)
        # Local development against a normal HA instance with a long-lived token.
        base = os.environ.get("HA_URL", "http://localhost:8123").rstrip("/")
        token = os.environ.get("HA_TOKEN", "")
        ws = base.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        return cls(ws, base + "/api", token)
