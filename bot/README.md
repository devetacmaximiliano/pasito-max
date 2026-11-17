# pasito-bot

Contenedor que mantiene tu cuenta de Pasito en el tope diario de Pasitos sin tocar la
app: inicia sesión contra la API oficial, lee el tope vigente y sincroniza pasos a lo
largo del día con un ritmo plausible.

- Máximo útil: **15.000 pasos/día** (15 Pasitos × 1.000). Pasado ese punto el servidor
  recorta y no hay beneficio extra.
- No usa emulador, Health Connect ni Play Integrity.
- Sólo escribe actividad: no toca perfil, canjes, desafíos ni boosts.

Contexto y reglas completas: [`../docs/COMO-FUNCIONA.md`](../docs/COMO-FUNCIONA.md).

## Requisitos

- Docker y Docker Compose.
- Cuenta de Pasito con **email y contraseña** (si usás Google/Apple, seteá una
  contraseña desde “¿Olvidaste tu contraseña?”).
- Salida HTTPS a `api.pasito.app`.

## Puesta en marcha

```bash
cp .env.example .env
$EDITOR .env            # email y contraseña
docker compose up -d --build
docker compose logs -f
```

Verificación rápida sin esperar la rampa del día:

```bash
docker compose exec bot python -m pasito_bot once      # completa el objetivo ahora
docker compose exec bot python -m pasito_bot status
docker compose exec bot python -m pasito_bot flags      # tope vigente en el servidor
```

## Comandos

| Comando | Qué hace |
|---|---|
| `run` (default) | Bucle 24/7: rampa dentro de la ventana y catch-up si estuvo caído |
| `once` | Sincroniza el objetivo del día ya, en tandas de 1.500 |
| `login` | Fuerza login y guarda la sesión |
| `flags` | Imprime las feature flags (incluye `daily_pasito_cap`) |
| `status` | Estado local: validados, Pasitos de hoy, último error |
| `--dry-run` | Simula sin enviar |

## Funcionamiento

- **Objetivo dinámico**: lee `daily_pasito_cap` de las flags (hoy 15) y calcula
  `cap × 1.000`. Si el flag no está disponible, usa 15. `DAILY_CAP_OVERRIDE` lo fuerza.
- **Rampa**: ventana `07:30–21:30` (configurable) repartida en ticks; nunca envía de más
  ni retrocede (el servidor también es monotónico).
- **Catch-up**: al arrancar retoma lo que falte del día; si está muy atrasado acelera.
- **Sesión**: login por contraseña y refresh rotativo persistido en `/data`
  (`0600`). Tolera 401, 429 y 5xx con backoff.
- **Corte**: a las 23:45 deja de enviar; los días pasados no acreditan Pasitos.
- **Identidad**: `device_id` UUID estable y marca/modelo verosímiles, persistidos.

## Variables

| Variable | Default | Notas |
|---|---|---|
| `PASITO_EMAIL` | — | obligatoria |
| `PASITO_PASSWORD` | — | obligatoria salvo que ya haya refresh token válido |
| `TZ` | `America/Argentina/Buenos_Aires` | define el día y la ventana |
| `WINDOW_START` / `WINDOW_END` | `07:30` / `21:30` | reparto del envío |
| `CUTOFF` | `23:45` | último envío posible |
| `TICK_SECONDS` | `600` | cadencia base |
| `MAX_BURST_STEPS` | `1500` | pasos por envío |
| `DAILY_CAP_OVERRIDE` | `0` | 0 = leer del servidor |
| `DRY_RUN` | `0` | 1 = no envía |

## Llevarlo a otra máquina

```bash
./scripts/bundle.sh --with-env    # genera dist/pasito-bot-bundle.tar.gz con imagen y .env
```

En el destino: `tar xzf … && cd pasito-bot-bundle && ./scripts/install.sh`.
Detalle y automatización del arranque en [`deploy/README.md`](deploy/README.md).

## Datos persistentes

Volumen `pasito_data` → `/data`: `session.json` (refresh token) y `state.json`.
Si borrás el volumen, se pierde la sesión (el bot vuelve a loguearse) y el estado del
día (lo recupera del snapshot del servidor).

## Troubleshooting

- `login falló (400)`: credenciales o contraseña sin setear.
- `Sync date is outside the allowed window`: reloj/zona horaria del host desfasados.
- `flags no disponibles`: el bot sigue con el tope por defecto de 15.
- Healthcheck en `unhealthy`: mirá `docker compose logs`; suele ser red o credenciales.

## Riesgos

Los Términos de Pasito prohíben la simulación de actividad y de ubicación. El bot
respeta el tope y el ritmo para no disparar `spike_detected`/`excessive_steps`, pero la
cuenta puede ser auditada. Los boosts geográficos **no** están cubiertos todavía.
