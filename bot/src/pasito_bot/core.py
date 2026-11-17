"""Lógica de sincronización: plan de sesiones, catch-up y cortes de seguridad."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta

from . import planner
from .client import PasitoClient, SyncRejected
from .config import Config
from .planner import Session
from .state import DayState, StateStore

log = logging.getLogger("pasito.core")

SOURCE = "max_both"
CAP_TTL_SECONDS = 3 * 3600
CATCHUP_THRESHOLD = 1200


class Runner:
    def __init__(self, cfg: Config, client: PasitoClient, store: StateStore) -> None:
        self._cfg = cfg
        self._client = client
        self._store = store
        self._cap = 0
        self._cap_at = 0.0
        self._seeded_day = ""
        self._stop = asyncio.Event()

    # --- utilidades -----------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def _now(self) -> datetime:
        return datetime.now(self._cfg.tz)

    async def _cap_value(self) -> int:
        if self._cap and time.time() - self._cap_at < CAP_TTL_SECONDS:
            return self._cap
        self._cap = max(1, await self._client.daily_cap())
        self._cap_at = time.time()
        log.info("tope diario: %s Pasitos (%s pasos)", self._cap, self._cap * self._cfg.steps_per_pasito)
        return self._cap

    def _nominal(self, state: DayState, cap: int) -> int:
        """Objetivo nominal del día, estable entre reinicios y algo bajo el tope."""
        ceiling = cap * self._cfg.steps_per_pasito
        stored = state.extra.get("nominal")
        if isinstance(stored, int) and 0 < stored <= ceiling:
            return stored
        fraction = random.uniform(self._cfg.fraction_min, self._cfg.fraction_max)
        nominal = max(1, min(ceiling, int(ceiling * fraction / 50) * 50))
        state.extra["nominal"] = nominal
        self._store.save()
        return nominal

    async def _seed(self, state: DayState, today) -> None:
        if self._seeded_day == state.day:
            return
        self._seeded_day = state.day
        progress = await self._client.today_progress(today)
        if progress:
            validated, pasitos = progress
            state.validated = max(state.validated, validated)
            state.pasitos_today = max(state.pasitos_today, pasitos)
            log.info("estado inicial del día: validados=%s pasitos=%s", state.validated, pasitos)

    def _plan(self, state: DayState, now: datetime, target: int) -> list[Session]:
        if self._cfg.pattern == "ramp":
            return []
        sessions = planner.load(state.extra.get("plan"))
        if sessions and state.extra.get("plan_day") == state.day:
            return sessions
        sessions = planner.build(now, self._cfg, target, state.device_id)
        state.extra["plan"] = planner.dump(sessions)
        state.extra["plan_day"] = state.day
        self._store.save()
        log.info(
            "plan del día: %s sesiones, %s pasos (nominal %s)",
            len(sessions), sum(s.budget for s in sessions), target,
        )
        return sessions

    def _desired(self, now: datetime, target: int, sessions: list[Session]) -> int:
        if sessions:
            return min(target, planner.planned_until(sessions, now))
        return min(target, self._desired_ramp(now, target))

    def _desired_ramp(self, now: datetime, target: int) -> int:
        start = now.replace(
            hour=self._cfg.window_start.hour, minute=self._cfg.window_start.minute, second=0, microsecond=0
        )
        end = now.replace(hour=self._cfg.window_end.hour, minute=self._cfg.window_end.minute, second=0, microsecond=0)
        cutoff = now.replace(hour=self._cfg.cutoff.hour, minute=self._cfg.cutoff.minute, second=0, microsecond=0)
        if now < start:
            return 0
        if now >= end or now >= cutoff:
            return target
        return int(target * (now - start) / (end - start)) // 100 * 100

    def _window_open(self, now: datetime) -> bool:
        start = now.replace(
            hour=self._cfg.window_start.hour, minute=self._cfg.window_start.minute, second=0, microsecond=0
        )
        cutoff = now.replace(hour=self._cfg.cutoff.hour, minute=self._cfg.cutoff.minute, second=0, microsecond=0)
        return start <= now < cutoff

    # --- un envío -------------------------------------------------------
    async def _send(self, steps: int, state: DayState, today) -> bool:
        meta = {"source": SOURCE, "device_id": state.device_id, "device_brand": state.device_brand}
        if self._cfg.dry_run:
            log.info("[dry-run] enviaría %s pasos (%s)", steps, today)
            state.validated = steps
            return True
        try:
            data = await self._client.sync(steps, today, meta)
        except SyncRejected as exc:
            state.last_error = str(exc)
            self._store.save()
            if "outside the allowed window" in str(exc):
                log.warning("fecha fuera de ventana; reintento tras cambio de día")
                return False
            log.error("sync rechazado: %s", exc)
            return False
        state.sent = max(state.sent, steps)
        state.validated = max(state.validated, int(data.get("validated_steps") or steps))
        state.pasitos_today = max(state.pasitos_today, int(data.get("pasitos_earned_today") or 0))
        state.last_send_at = time.time()
        state.last_ok_at = state.last_send_at
        state.last_error = ""
        flags = data.get("fraud_flags") or []
        if flags:
            log.warning(
                "flags=%s validados=%s pasitos_hoy=%s",
                ",".join(flags), state.validated, state.pasitos_today,
            )
        else:
            log.info("ok validados=%s pasitos_hoy=%s", state.validated, state.pasitos_today)
        self._store.save()
        return True

    # --- ticks ----------------------------------------------------------
    async def tick(self) -> None:
        now = self._now()
        today = now.date()
        state = self._store.roll(today)
        await self._seed(state, today)

        cap = await self._cap_value()
        nominal = self._nominal(state, cap)
        sessions = self._plan(state, now, nominal)
        target = min(nominal, sum(s.budget for s in sessions)) if sessions else nominal
        target = min(target, cap * self._cfg.steps_per_pasito)
        state.target = target

        if state.pasitos_today >= cap or state.validated >= target:
            if not state.done:
                state.done = True
                if not self._cfg.dry_run:
                    self._store.save()
                log.info("objetivo alcanzado: %s/%s Pasitos", state.pasitos_today, cap)
            return

        desired = self._desired(now, target, sessions)
        if desired <= state.validated:
            return

        burst = min(self._cfg.max_burst_steps, desired - state.validated, target - state.validated)
        steps = min(target, state.validated + burst)
        steps = steps // 10 * 10 or steps
        if steps <= state.validated:
            return
        await self._send(steps, state, today)

    async def run_once(self, chunks: int = 20) -> None:
        """Sincroniza el objetivo completo ya mismo, en tandas."""
        today = self._now().date()
        state = self._store.roll(today)
        await self._seed(state, today)
        cap = await self._cap_value()
        nominal = self._nominal(state, cap)
        target = min(nominal, cap * self._cfg.steps_per_pasito)
        state.target = target
        state.done = False
        self._store.save()
        for _ in range(chunks):
            if state.validated >= target or state.pasitos_today >= cap:
                break
            burst = min(self._cfg.max_burst_steps, target - state.validated)
            if burst <= 0:
                break
            ok = await self._send(min(target, state.validated + burst), state, today)
            if not ok:
                break
            await asyncio.sleep(random.uniform(2, 5))
        state.done = state.validated >= target or state.pasitos_today >= cap
        if not self._cfg.dry_run:
            self._store.save()

    async def run_forever(self) -> None:
        log.info(
            "bot iniciado: patrón=%s, ventana %s–%s (corte %s) %s, tick %ss, ráfaga máx %s",
            self._cfg.pattern,
            self._cfg.window_start.strftime("%H:%M"),
            self._cfg.window_end.strftime("%H:%M"),
            self._cfg.cutoff.strftime("%H:%M"),
            self._cfg.tz,
            self._cfg.tick_seconds,
            self._cfg.max_burst_steps,
        )
        await self._startup_catchup()
        while not self._stop.is_set():
            try:
                if self._window_open(self._now()):
                    await self.tick()
            except Exception:  # noqa: BLE001 - el loop no debe morir
                log.exception("fallo en el tick")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._sleep_seconds())
            except asyncio.TimeoutError:
                pass

    async def _startup_catchup(self) -> None:
        now = self._now()
        if not self._window_open(now):
            log.info("fuera de ventana; espero")
            return
        for _ in range(10):
            await self.tick()
            await asyncio.sleep(random.uniform(1.5, 3.5))
            now = self._now()
            if not self._window_open(now):
                return
            if not self._store.state.validated:
                return
            if self._store.state.pasitos_today >= (await self._cap_value()):
                return

    def _sleep_seconds(self) -> float:
        now = self._now()
        if not self._window_open(now):
            start = now.replace(
                hour=self._cfg.window_start.hour, minute=self._cfg.window_start.minute, second=0, microsecond=0
            )
            target = start if now < start else start + timedelta(days=1)
            return min(1800.0, max(60.0, (target - now).total_seconds()))

        state = self._store.state
        sessions = planner.load(state.extra.get("plan"))
        desired = self._desired(now, state.target or 0, sessions)
        if desired - state.validated > CATCHUP_THRESHOLD:
            return 15.0
        if sessions and planner.active(sessions, now):
            return random.uniform(120, 240)
        return random.uniform(300, 600)
