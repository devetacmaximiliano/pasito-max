"""CLI del bot: run, once, status, login, flags."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

import httpx

from .auth import SessionManager
from .client import PasitoClient
from .config import Config, load
from .core import Runner
from .state import StateStore


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
    )


async def _build(cfg: Config):
    http = httpx.AsyncClient(follow_redirects=True)
    session = SessionManager(cfg, http)
    client = PasitoClient(cfg, http, session)
    return http, session, client


async def cmd_run(cfg: Config) -> int:
    http, _session, client = await _build(cfg)
    runner = Runner(cfg, client, StateStore(cfg.data_dir))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.stop)
    try:
        await runner.run_forever()
    finally:
        await http.aclose()
    return 0


async def cmd_once(cfg: Config) -> int:
    http, _session, client = await _build(cfg)
    runner = Runner(cfg, client, StateStore(cfg.data_dir))
    try:
        await runner.run_once()
    finally:
        await http.aclose()
    return 0


async def cmd_login(cfg: Config) -> int:
    http, session, _client = await _build(cfg)
    try:
        await session.token()
        print(f"login ok, user_id={session.user_id}")
    finally:
        await http.aclose()
    return 0


async def cmd_flags(cfg: Config) -> int:
    http, _session, client = await _build(cfg)
    try:
        print(json.dumps(await client.flags(), indent=2, ensure_ascii=False))
    finally:
        await http.aclose()
    return 0


def cmd_status(cfg: Config) -> int:
    path = Path(cfg.data_dir) / "state.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        print("sin estado todavía")
        return 1
    age = int(time.time() - path.stat().st_mtime)
    data["state_age_seconds"] = age
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pasito-bot")
    parser.add_argument("command", choices=["run", "once", "status", "login", "flags"], nargs="?", default="run")
    parser.add_argument("--dry-run", action="store_true", help="no envía, sólo simula")
    args = parser.parse_args(argv)

    cfg = load()
    if args.dry_run:
        cfg = type(cfg)(**{**cfg.__dict__, "dry_run": True})
    setup_logging(cfg.log_level)

    if args.command == "status":
        return cmd_status(cfg)
    fn = {
        "run": cmd_run,
        "once": cmd_once,
        "login": cmd_login,
        "flags": cmd_flags,
    }[args.command]
    try:
        return asyncio.run(fn(cfg))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
