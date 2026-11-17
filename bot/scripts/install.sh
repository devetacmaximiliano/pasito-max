#!/usr/bin/env bash
# Instala y arranca el bot desde un bundle ya desempaquetado.
set -euo pipefail

cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Falta Docker." >&2; exit 1; }
docker compose version >/dev/null || { echo "Falta docker compose." >&2; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Completá .env (email y contraseña) y volvé a correr este script." >&2
  exit 1
fi
chmod 600 .env

if [[ -f image.tar.gz ]]; then
  echo "Cargando imagen..."
  docker load -i image.tar.gz
fi

echo "Levantando servicio..."
docker compose up -d

echo "Esperando healthcheck..."
for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{.State.Health.Status}}' pasito-bot 2>/dev/null || echo starting)
  [[ "$status" == "healthy" ]] && break
  sleep 5
done

docker compose ps
docker compose logs --tail 15
