#!/usr/bin/env bash
# Empaqueta el bot para llevarlo a otra máquina sin build ni red.
# Uso: ./scripts/bundle.sh [--with-env]
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE="pasito-bot:local"
OUT="dist"
NAME="pasito-bot-bundle"

WITH_ENV=0
[[ "${1:-}" == "--with-env" ]] && WITH_ENV=1

if [[ ! -f .env ]]; then
  echo "Falta .env; copiá .env.example y completá las credenciales." >&2
  exit 1
fi

export BUILDX_CONFIG="${BUILDX_CONFIG:-$PWD/.buildx}"
docker build -q -t "$IMAGE" .

rm -rf "$OUT/$NAME"
mkdir -p "$OUT/$NAME/scripts"
cp docker-compose.yml Dockerfile requirements.txt README.md .env.example "$OUT/$NAME/"
cp deploy/README.md "$OUT/$NAME/DEPLOY.md"
cp scripts/install.sh "$OUT/$NAME/scripts/"

if [[ $WITH_ENV -eq 1 ]]; then
  cp .env "$OUT/$NAME/.env"
  chmod 600 "$OUT/$NAME/.env"
  echo "Incluida .env (contiene la contraseña)"
else
  echo "Sin .env: tendrás que copiarla aparte"
fi

docker save "$IMAGE" | gzip -1 > "$OUT/$NAME/image.tar.gz"

tar -C "$OUT" -czf "$OUT/$NAME.tar.gz" "$NAME"
( cd "$OUT" && shasum -a 256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )

echo
echo "Listo: $OUT/$NAME.tar.gz"
ls -lh "$OUT/$NAME.tar.gz"
cat "$OUT/$NAME.tar.gz.sha256"
echo
echo "Pasos en la máquina destino:"
echo "  tar xzf $NAME.tar.gz && cd $NAME && ./scripts/install.sh"
