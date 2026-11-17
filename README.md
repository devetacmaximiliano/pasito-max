# Pasito al máximo

Automatización **no oficial** de [Pasito](https://www.pasito.app/): mantiene tu cuenta en
el tope diario de Pasitos sin abrir la app. Un contenedor, la API oficial, ninguna
emulación de teléfono.

> Sin relación con Pasito ni con sus creadores. Usa la cuenta propia y las credenciales
> propias. Si te sirve, dejá una estrella; si se rompe, mandá un issue.

## El hallazgo

Pasito convierte **1 Pasito cada 1.000 pasos validados** y aplica un **tope de 15 Pasitos
por día** (`daily_pasito_cap`). El servidor recorta `validated_steps` a 15.000: caminar
30.000 no da más saldo ni más ranking.

Eso fija el objetivo del proyecto: llegar a **15.000 pasos diarios**, en incrementos
acumulativos y con una distribución horaria creíble, sin pasarse de lo que el backend
valida. El análisis completo — reglas, anti-fraude, flags y protocolo de boosts — está en
[docs/COMO-FUNCIONA.md](docs/COMO-FUNCIONA.md).

## Cómo funciona

1. Inicia sesión contra Supabase (`/auth/v1/token`, password grant) y persiste el refresh
   token rotativo.
2. Lee el tope vigente desde las feature flags del servidor (`daily_pasito_cap`) y
   calcula `cap × 1.000`.
3. Simula un día de caminata: 6–9 sesiones de 7–34 minutos a 92–126 pasos/minuto entre
   la mañana y la tarde, con pausas variables. Actualiza cada 2–4 minutos dentro de una
   sesión y queda en silencio entre ellas; el servidor es monotónico, nunca baja un
   total.
4. Recupera lo que falte si el contenedor estuvo caído y corta a las 23:45.
5. Los días pasados no acreditan Pasitos, así que sólo trabaja el día en curso.

Flags de magnitud: los envíos quedan lejos de `spike_detected` (> ~40.000 de salto) y
`excessive_steps` (> ~70.000 de raw). No requiere Play Integrity: el backend lo acepta
opcional.

## Instalación

Requisitos: Docker, Compose y una cuenta cuyos accesos te pertenezcan. Si la cuenta es de
Google o Apple, creá una contraseña primero (la app usa login por código al email; el
flujo OTP permite setearla).

```bash
cp bot/.env.example bot/.env
$EDITOR bot/.env          # email y contraseña
cd bot && docker compose up -d --build
docker compose logs -f
```

Verificación inmediata sin esperar el plan del día:

```bash
cd bot
docker compose exec bot python -m pasito_bot once
docker compose exec bot python -m pasito_bot status
```

Para dejarlo en una máquina siempre encendida: [bot/deploy/README.md](bot/deploy/README.md).

## Estructura

```
bot/                     contenedor: cliente, sesión, planificador, estado
bot/deploy/              instalación en una PC de casa y arranque automático
docs/COMO-FUNCIONA.md    ingeniería inversa, reglas y anti-fraude
```

## Qué no hace

- **Boosts geográficos**: están mapeados en el análisis, pero no implementados. Son la
  única vía legítima para superar los 15 Pasitos diarios y requieren presencia, reloj del
  servidor y lotes de intervalos.
- **Canjes**: son presenciales con PIN.
- **Desafíos, perfil y canjes**: el bot sólo escribe actividad.

## Riesgos

Los Términos de Pasito prohíben la simulación de actividad y de ubicación (cláusula x), y
habilitan a suspender la cuenta o anular Pasitos ante detección de fraude. El bot es
conservador, pero no es invisible: patrón diario idéntico, `device_id` propio y ausencia
de sensor real son huellas detectables.

Los Pasitos vencen a los 60 días y el canje tiene un límite de uno cada 15 días por
comercio: maxear sin canjear pierde valor.

La API no está documentada por Pasito y puede cambiar sin aviso. Cada actualización de la
app puede exigir ajustes acá.

## Licencia

MIT. Ver [LICENSE](LICENSE).
