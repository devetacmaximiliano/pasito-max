"""Sesión de Supabase: login por contraseña y refresh rotativo persistido."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from .config import Config

log = logging.getLogger("pasito.auth")

REFRESH_MARGIN_SECONDS = 300


class AuthError(RuntimeError):
    pass


class SessionManager:
    def __init__(self, cfg: Config, http: httpx.AsyncClient) -> None:
        self._cfg = cfg
        self._http = http
        self._lock = asyncio.Lock()
        self._path = Path(cfg.data_dir) / "session.json"
        self._data: dict = self._load()

    # --- persistencia ---------------------------------------------------
    def _load(self) -> dict:
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self._data, fh)
        os.replace(tmp, self._path)

    # --- API de GoTrue --------------------------------------------------
    def _headers(self) -> dict:
        return {
            "apikey": self._cfg.anon_key,
            "Content-Type": "application/json",
            "User-Agent": self._cfg.user_agent,
        }

    async def _login(self) -> None:
        if not self._cfg.password:
            raise AuthError("sin contraseña y sin refresh token válido")
        resp = await self._http.post(
            f"{self._cfg.auth_url}/token?grant_type=password",
            headers=self._headers(),
            json={"email": self._cfg.email, "password": self._cfg.password},
        )
        if resp.status_code != 200:
            raise AuthError(f"login falló ({resp.status_code}): {resp.text[:200]}")
        self._store(resp.json())
        log.info("login ok")

    async def _refresh(self) -> bool:
        token = self._data.get("refresh_token")
        if not token:
            return False
        resp = await self._http.post(
            f"{self._cfg.auth_url}/token?grant_type=refresh_token",
            headers=self._headers(),
            json={"refresh_token": token},
        )
        if resp.status_code != 200:
            log.warning("refresh rechazado (%s): %s", resp.status_code, resp.text[:160])
            return False
        self._store(resp.json())
        log.info("refresh ok")
        return True

    def _store(self, payload: dict) -> None:
        access = payload.get("access_token")
        if not access:
            raise AuthError("respuesta de auth sin access_token")
        expires_at = payload.get("expires_at")
        if not expires_at:
            expires_at = int(time.time()) + int(payload.get("expires_in", 3600))
        self._data = {
            "access_token": access,
            "refresh_token": payload.get("refresh_token", ""),
            "expires_at": int(expires_at),
            "user_id": (payload.get("user") or {}).get("id", ""),
        }
        self._save()

    # --- uso ------------------------------------------------------------
    async def token(self) -> str:
        async with self._lock:
            expires_at = int(self._data.get("expires_at", 0))
            if self._data.get("access_token") and expires_at - REFRESH_MARGIN_SECONDS > time.time():
                return self._data["access_token"]
            if await self._refresh():
                return self._data["access_token"]
            await self._login()
            return self._data["access_token"]

    def invalidate(self) -> None:
        self._data["expires_at"] = 0

    @property
    def user_id(self) -> str:
        return self._data.get("user_id", "")
