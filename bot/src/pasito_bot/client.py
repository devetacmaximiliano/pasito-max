"""Cliente HTTP mínimo contra la API de Pasito."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import date as date_cls

import httpx

from .auth import AuthError, SessionManager
from .config import Config

log = logging.getLogger("pasito.client")

DEFAULT_CAP = 15
MAX_ATTEMPTS = 4


class SyncRejected(RuntimeError):
    """400 con cuerpo {"error": ...}."""


class PasitoClient:
    def __init__(self, cfg: Config, http: httpx.AsyncClient, session: SessionManager) -> None:
        self._cfg = cfg
        self._http = http
        self._session = session

    def _headers(self, token: str) -> dict:
        return {
            "apikey": self._cfg.anon_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": self._cfg.user_agent,
            "X-Client-Info": self._cfg.user_agent,
        }

    async def _post(self, url: str, body: dict) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            token = await self._session.token()
            try:
                resp = await self._http.post(
                    url,
                    headers=self._headers(token),
                    json=body,
                    timeout=self._cfg.request_timeout,
                )
            except httpx.HTTPError as exc:
                last = exc
                log.warning("error de red (intento %s/%s): %s", attempt, MAX_ATTEMPTS, exc)
                await asyncio.sleep(min(60, 2 ** attempt) + random.random())
                continue

            if resp.status_code == 401:
                self._session.invalidate()
                if attempt == 1:
                    continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = _retry_after(resp, attempt)
                log.warning("%s en %s; espero %.1fs", resp.status_code, url, wait)
                await asyncio.sleep(wait)
                continue
            return resp
        raise AuthError(f"sin respuesta utilizable de {url}: {last}")

    async def flags(self) -> dict[str, object]:
        resp = await self._post(f"{self._cfg.rest_url}/rpc/get_feature_flags_for_current_user", {})
        if resp.status_code != 200:
            log.warning("flags no disponibles (%s)", resp.status_code)
            return {}
        out: dict[str, object] = {}
        for row in resp.json() or []:
            if not isinstance(row, dict) or not row.get("enabled"):
                continue
            key = row.get("flag_key")
            value = row.get("config_value")
            if key and value is not None:
                out[key] = value
        return out

    async def daily_cap(self) -> int:
        if self._cfg.cap_override:
            return self._cfg.cap_override
        try:
            value = (await self.flags()).get("daily_pasito_cap")
            cap = int(value) if value is not None else DEFAULT_CAP
        except (AuthError, ValueError, TypeError) as exc:
            log.warning("no pude leer el tope (%s); uso %s", exc, DEFAULT_CAP)
            return DEFAULT_CAP
        # Misma regla que el cliente oficial: por debajo de 100 se ignora.
        return cap if cap >= 100 else DEFAULT_CAP

    async def today_progress(self, day: date_cls) -> tuple[int, int] | None:
        resp = await self._post(f"{self._cfg.rest_url}/rpc/get_my_activity_snapshot_v2", {})
        if resp.status_code != 200:
            return None
        for row in resp.json().get("activity_history") or []:
            if row.get("date") == day.isoformat():
                return int(row.get("validated_steps") or 0), int(row.get("pasitos_earned") or 0)
        return 0, 0

    async def sync(self, steps: int, day: date_cls, meta: dict) -> dict:
        body = {
            "steps": int(steps),
            "date": day.isoformat(),
            "source": meta.get("source", "hc_only"),
            "opened_app": True,
            "device_id": meta["device_id"],
            "device_brand": meta["device_brand"],
            "app_version": "2.4.11",
            "sensor_steps": int(steps),
            "hc_steps_trusted": True,
        }
        resp = await self._post(f"{self._cfg.functions_url}/sync-activity", body)
        if resp.status_code == 400:
            try:
                message = resp.json().get("error", "invalid")
            except ValueError:
                message = resp.text[:120]
            raise SyncRejected(message)
        if resp.status_code != 200:
            raise SyncRejected(f"HTTP {resp.status_code}: {resp.text[:160]}")
        return resp.json()


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(900.0, max(1.0, float(raw)))
        except ValueError:
            pass
    return min(300.0, 5 * 2 ** attempt) + random.random()
