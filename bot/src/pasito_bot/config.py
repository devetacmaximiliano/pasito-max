"""Configuración por entorno. Sin dependencias externas."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

# Anon key pública del proyecto Supabase de Pasito (embebida en el APK).
DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRyc2Jvd3djaWd6YXloZHBmeHZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMyNzAzMjIsImV4cCI6MjA4ODg0NjMyMn0."
    "Mrp06Gs7gbefMffq5tBD03TSUYgDrn77GaJJSVTYYGQ"
)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        raise SystemExit(f"{name} debe ser un entero, no {raw!r}")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        raise SystemExit(f"{name} debe ser numérico")


def _time(name: str, default: str) -> time:
    raw = os.getenv(name, default).strip()
    try:
        hh, mm = raw.split(":")
        return time(int(hh), int(mm))
    except ValueError:
        raise SystemExit(f"{name} debe tener formato HH:MM, no {raw!r}")


@dataclass(frozen=True)
class Config:
    api_base: str
    anon_key: str
    email: str
    password: str
    tz: ZoneInfo
    data_dir: str
    window_start: time
    window_end: time
    cutoff: time
    tick_seconds: int
    max_burst_steps: int
    steps_per_pasito: int
    cap_override: int
    pattern: str
    fraction_min: float
    fraction_max: float
    commute_out: time
    commute_back: time
    commute_minutes: int
    commute_from: str
    commute_to: str
    dry_run: bool
    log_level: str
    request_timeout: float = 25.0
    user_agent: str = "supabase-dart/2.14.0 (Dart 3.12.2)"

    @property
    def auth_url(self) -> str:
        return f"{self.api_base}/auth/v1"

    @property
    def rest_url(self) -> str:
        return f"{self.api_base}/rest/v1"

    @property
    def functions_url(self) -> str:
        return f"{self.api_base}/functions/v1"


def load() -> Config:
    email = os.getenv("PASITO_EMAIL", "").strip()
    password = os.getenv("PASITO_PASSWORD", "").strip()
    if not email:
        raise SystemExit("Falta PASITO_EMAIL")

    return Config(
        api_base=os.getenv("PASITO_API_BASE", "https://api.pasito.app").rstrip("/"),
        anon_key=os.getenv("PASITO_ANON_KEY", DEFAULT_ANON_KEY).strip(),
        email=email,
        password=password,
        tz=ZoneInfo(os.getenv("TZ", "America/Argentina/Buenos_Aires")),
        data_dir=os.getenv("DATA_DIR", "/data"),
        window_start=_time("WINDOW_START", "07:30"),
        window_end=_time("WINDOW_END", "21:30"),
        cutoff=_time("CUTOFF", "23:45"),
        tick_seconds=_int("TICK_SECONDS", 600, minimum=60),
        max_burst_steps=_int("MAX_BURST_STEPS", 1500, minimum=100),
        steps_per_pasito=_int("STEPS_PER_PASITO", 1000, minimum=1),
        cap_override=_int("DAILY_CAP_OVERRIDE", 0),
        pattern=os.getenv("PATTERN", "sessions").strip().lower(),
        fraction_min=min(1.0, max(0.5, _float("DAILY_FRACTION_MIN", 0.97))),
        fraction_max=min(1.0, max(0.5, _float("DAILY_FRACTION_MAX", 1.0))),
        commute_out=_time("COMMUTE_OUT", "09:00"),
        commute_back=_time("COMMUTE_BACK", "15:00"),
        commute_minutes=_int("COMMUTE_MINUTES", 60, minimum=20),
        commute_from=os.getenv("COMMUTE_FROM", "-38.00550,-57.54260"),
        commute_to=os.getenv("COMMUTE_TO", "-38.03350,-57.52150"),
        dry_run=_bool("DRY_RUN"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
