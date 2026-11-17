# Instalación en la PC de casa

El bot corre 24/7 y sincroniza solo. Esta guía asume una PC con Linux (Debian/Ubuntu o
similar); en Windows usá WSL2 con Docker Desktop y los mismos pasos dentro de la distro.

> Antes de mover: en la Mac corré `docker compose down` en `bot/`. Dos instancias
> simultáneas no duplican Pasitos, pero dejan estados y sesiones desordenados.

## 1. Preparar la PC destino

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"     # cerrá y abrí sesión después
```

La PC debe quedar encendida y sin suspensión:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

## 2. Trasladar el bundle

Desde la Mac, en `bot/`:

```bash
./scripts/bundle.sh --with-env      # incluye .env; sin el flag, copiala aparte
```

Copiá `dist/pasito-bot-bundle.tar.gz` por USB, `scp` o el medio que prefieras, verificá
el SHA256 y en la PC destino:

```bash
tar xzf pasito-bot-bundle.tar.gz
cd pasito-bot-bundle
./scripts/install.sh
```

Si no incluiste `.env`, creala antes con `EMAIL` y `PASSWORD` (la contraseña es la que
se generó para el bot; el login de Google sigue siendo tuyo y no se toca).

## 3. Arranque automático

El compose ya usa `restart: unless-stopped`, así que con Docker habilitado el
contenedor vuelve solo tras un reinicio. Si preferís control explícito, deshabilitá
Docker al boot y usá una unidad:

```ini
# /etc/systemd/system/pasito-bot.service
[Unit]
Description=Pasito bot
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/pasito-bot
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now pasito-bot
```

## 4. Zona horaria

El plan diario usa la hora local del contenedor. El compose fija
`TZ=America/Argentina/Buenos_Aires`; si la PC está en otra zona, cambiala en
`docker-compose.yml` para que la ventana 07:30–21:30 siga siendo la tuya.

## 5. Operación

```bash
docker compose logs -f                                  # actividad
docker compose exec bot python -m pasito_bot status     # estado del día
docker compose exec bot python -m pasito_bot once       # forzar el objetivo de hoy
docker compose down                                     # frenar
```

El volumen `pasito_data` guarda la sesión y el estado. El healthcheck marca
`unhealthy` si pasa la ventana sin sincronizar.

## 6. Actualizar

```bash
git pull                      # o reemplazá los archivos
docker compose up -d --build
```

Si cambia el contrato de la API, mirá los logs: los errores de validación aparecen como
`sync rechazado` y no reintentan solos.

## Seguridad

- `.env` con `chmod 600` y fuera de cualquier repo público: tiene la contraseña.
- El contenedor no publica puertos, corre sin root, rootfs read-only y sin capabilities.
- Si sospechás de la contraseña, cambiala en la app y actualizá `.env` + `docker
  compose up -d --force-recreate`.

## Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `login falló (400)` | contraseña desactualizada o email mal escrito |
| `Sync date is outside the allowed window` | reloj/TZ de la PC desfasados |
| Queda `unhealthy` | sin red o credenciales inválidas: `docker compose logs` |
| No envía nada de día | la PC durmió: revisá §1 |
