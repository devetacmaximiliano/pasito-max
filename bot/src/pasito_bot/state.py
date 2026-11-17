"""Estado diario persistido y identidad de dispositivo estable."""

from __future__ import annotations

import json
import os
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path

DEVICES = [
    ("samsung", "SM-S911B"),
    ("samsung", "SM-A546E"),
    ("samsung", "SM-S921B"),
    ("Google", "Pixel 8"),
    ("Google", "Pixel 7a"),
    ("motorola", "moto g84 5G"),
    ("Xiaomi", "2312DRA50G"),
    ("Xiaomi", "22111317G"),
]

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class DayState:
    day: str
    target: int = 0
    sent: int = 0
    validated: int = 0
    pasitos_today: int = 0
    last_send_at: float = 0.0
    last_ok_at: float = 0.0
    last_error: str = ""
    device_id: str = ""
    device_brand: str = ""
    device_model: str = ""
    done: bool = False
    extra: dict = field(default_factory=dict)


class StateStore:
    def __init__(self, data_dir: str) -> None:
        self._dir = Path(data_dir)
        self._path = self._dir / "state.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> DayState:
        try:
            raw = json.loads(self._path.read_text())
            state = DayState(**{k: v for k, v in raw.items() if k in DayState.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            state = DayState(day="")
        self._ensure_device(state)
        return state

    @staticmethod
    def _ensure_device(state: DayState) -> None:
        if state.device_id and UUID_RE.match(state.device_id) and state.device_brand:
            return
        brand, model = random.choice(DEVICES)
        state.device_id = str(uuid.uuid4())
        state.device_brand = brand
        state.device_model = model

    def save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self.state.__dict__, fh)
        os.replace(tmp, self._path)

    def roll(self, today: date_cls) -> DayState:
        key = today.isoformat()
        if self.state.day != key:
            device = (self.state.device_id, self.state.device_brand, self.state.device_model)
            self.state = DayState(day=key)
            self.state.device_id, self.state.device_brand, self.state.device_model = device
            self.save()
        return self.state
