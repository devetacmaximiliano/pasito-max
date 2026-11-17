"""Healthcheck del contenedor."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import load

MAX_AGE_SECONDS = 3 * 3600


def main() -> int:
    cfg = load()
    now = datetime.now(cfg.tz)
    state_path = Path(cfg.data_dir) / "state.json"

    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        # Sin estado todavía: sólo es sano antes de la ventana.
        start = now.replace(hour=cfg.window_start.hour, minute=cfg.window_start.minute, second=0, microsecond=0)
        print(f"sin estado; {'antes' if now < start else 'dentro/fuera'} de ventana")
        return 0 if now < start else 1

    if state.get("done"):
        print("objetivo del día cumplido")
        return 0

    last_ok = float(state.get("last_ok_at") or 0)
    if last_ok and time.time() - last_ok < MAX_AGE_SECONDS:
        print("sync reciente")
        return 0

    start = now.replace(hour=cfg.window_start.hour, minute=cfg.window_start.minute, second=0, microsecond=0)
    cutoff = now.replace(hour=cfg.cutoff.hour, minute=cfg.cutoff.minute, second=0, microsecond=0)
    if start <= now < cutoff:
        print(f"sin sync desde hace {int(time.time() - last_ok) if last_ok else 'siempre'}s")
        return 1
    print("fuera de ventana")
    return 0


if __name__ == "__main__":
    sys.exit(main())
