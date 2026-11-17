"""Generador de un día de caminata verosímil.

Modela sesiones con duración, ritmo y pausas variables en vez de una rampa lineal.
El plan es determinístico por (día, dispositivo): un reinicio no cambia el patrón.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .config import Config

# Franjas donde es más probable salir a caminar (hora local).
SLOTS = ((7, 9), (11, 14), (17, 20))
GAP_RANGE = (16, 48)          # minutos entre sesiones
DURATION_RANGE = (7, 34)      # minutos por sesión
PACE_RANGE = (92, 126)        # pasos por minuto
MIN_BUDGET = 450
MAX_BUDGET = 4300


@dataclass
class Session:
    start: datetime
    end: datetime
    budget: int

    @property
    def minutes(self) -> float:
        return max(1.0, (self.end - self.start).total_seconds() / 60)


def seed_for(day: str, device_id: str) -> str:
    return f"pasito-plan:{day}:{device_id[:8]}"


def build(day: datetime, cfg: Config, nominal: int, device_id: str) -> list[Session]:
    """Reparte `nominal` en franjas (mañana, mediodía, tarde) sin excederse."""
    rng = random.Random(seed_for(day.date().isoformat(), device_id))

    def at(hour: int, minute: int) -> datetime:
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    wstart = max(at(cfg.window_start.hour, cfg.window_start.minute), at(7, 0))
    wend = at(cfg.window_end.hour, cfg.window_end.minute)
    if wend <= wstart:
        wend = at(23, 0)

    if cfg.pattern == "commute":
        return _commute(day, cfg, nominal, rng, at, wstart, wend)

    # Cuotas por franja: mañana y tarde pesan más que el mediodía.
    share_a = rng.uniform(0.26, 0.38)
    share_b = rng.uniform(0.14, 0.26)
    quotas = [int(nominal * share_a), int(nominal * share_b)]
    quotas.append(max(0, nominal - sum(quotas)))

    sessions: list[Session] = []
    for (sh, eh), quota in zip(SLOTS, quotas):
        if quota <= 0:
            continue
        slot_start = max(at(sh, 0), wstart)
        slot_end = min(at(eh, 0), wend)
        if slot_start >= slot_end - timedelta(minutes=6):
            continue
        cursor = slot_start + timedelta(minutes=rng.uniform(0, 12))
        left = quota
        while left > 350 and cursor < slot_end - timedelta(minutes=5):
            pace = rng.uniform(*PACE_RANGE)
            max_minutes = (slot_end - cursor).total_seconds() / 60
            duration = min(rng.uniform(*DURATION_RANGE), max_minutes)
            budget = min(left, int(duration * pace / 10) * 10)
            if budget < 300:
                break
            duration = budget / pace  # el ritmo manda: reajusto la duración
            end = cursor + timedelta(minutes=duration)
            sessions.append(Session(cursor, end, budget))
            left -= budget
            cursor = end + timedelta(minutes=rng.uniform(*GAP_RANGE))

    if not sessions:
        sessions = [Session(wstart + timedelta(minutes=10), wstart + timedelta(minutes=80), nominal)]
        return sessions

    # Si las franjas no alcanzaron, estiro la última caminata (ritmo intacto).
    deficit = nominal - sum(x.budget for x in sessions)
    while deficit > 0 and sessions:
        last = sessions[-1]
        room = (wend - last.end).total_seconds() / 60
        if room < 1.5:
            break
        pace = rng.uniform(*PACE_RANGE)
        add = min(deficit, int(room * pace / 10) * 10)
        if add < 50:
            break
        last.budget += add
        last.end += timedelta(minutes=add / pace)
        deficit -= add
    return sessions


def _commute(day, cfg, nominal, rng, at, wstart, wend) -> list[Session]:
    """Ida y vuelta al trabajo: dos bloques largos, uno a la mañana y otro a la tarde."""
    start_out = at(cfg.commute_out.hour, cfg.commute_out.minute) + timedelta(minutes=rng.uniform(-5, 6))
    start_back = at(cfg.commute_back.hour, cfg.commute_back.minute) + timedelta(minutes=rng.uniform(-5, 6))

    share = rng.uniform(0.47, 0.53)
    out_budget = int(nominal * share / 10) * 10
    back_budget = nominal - out_budget

    sessions: list[Session] = []
    for start, budget in ((start_out, out_budget), (start_back, back_budget)):
        pace = rng.uniform(112, 124)          # ritmo de commuting, sostenido pero humano
        minutes = max(cfg.commute_minutes, budget / pace)
        start = max(wstart, start)
        end = min(wend, start + timedelta(minutes=minutes))
        sessions.append(Session(start, end, min(budget, int((end - start).total_seconds() / 60 * pace))))

    diff = nominal - sum(x.budget for x in sessions)
    if diff:
        sessions[-1].budget += diff
    return sessions


def dump(sessions: list[Session]) -> list[dict]:
    return [
        {"start": s.start.isoformat(), "end": s.end.isoformat(), "budget": s.budget}
        for s in sessions
    ]


def load(raw: object) -> list[Session]:
    if not isinstance(raw, list):
        return []
    out: list[Session] = []
    for item in raw:
        try:
            out.append(
                Session(
                    datetime.fromisoformat(item["start"]),
                    datetime.fromisoformat(item["end"]),
                    int(item["budget"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            return []
    return out


def planned_until(sessions: list[Session], now: datetime) -> int:
    """Pasos que deberían estar acumulados a esta hora."""
    done = 0
    for s in sessions:
        if now >= s.end:
            done += s.budget
        elif now > s.start:
            fraction = (now - s.start).total_seconds() / max(1.0, (s.end - s.start).total_seconds())
            done += int(s.budget * min(1.0, fraction))
            break
        else:
            break
    return done


def active(sessions: list[Session], now: datetime) -> bool:
    return any(s.start <= now < s.end for s in sessions)


def _demo() -> int:
    """Uso: python -m pasito_bot.planner --demo [YYYY-MM-DD]"""
    from .config import load

    import sys

    cfg = load()
    day = datetime.now(cfg.tz)
    if len(sys.argv) > 2:
        day = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=cfg.tz)
    sessions = build(day, cfg, 15000, "demo-device")
    total = 0
    for s in sessions:
        total += s.budget
        print(f"{s.start:%H:%M}-{s.end:%H:%M}  {s.minutes:5.1f} min  {s.budget:5d} pasos  ({s.budget / s.minutes:5.1f}/min)")
    print(f"total: {total} pasos en {len(sessions)} sesiones")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
