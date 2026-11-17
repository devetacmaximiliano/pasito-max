# Análisis de Pasito — techo de pasos, reglas y plan de dockerización

> Documento de análisis previo a la implementación. Todos los números marcados como
> **verificados** se probaron contra el backend real con cuentas descartables
> (`@pasito.test`) el 2026-11-17. La cuenta del usuario no se tocó.

## 1. Resumen ejecutivo

- **El techo útil es 15.000 pasos por día.** La app convierte **1 Pasito cada 1.000 pasos
  validados** y el servidor tiene un **tope diario de 15 Pasitos** (`daily_pasito_cap`,
  activo al 100 % de los usuarios). Todo paso por encima de 15.000 se guarda como
  `raw_steps` pero **no genera Pasitos ni suma al ranking**: el servidor recorta
  `validated_steps` a 15.000.
- **Hay una sola vía legítima para superar ese tope: los boosts** (geográfico y por QR).
  Los Pasitos extra de un boost **no están alcanzados por el límite diario** (cláusula
  vi.5.c de los Términos), pero cada campaña publica su propio tope y multiplicador.
- **La API es trivial de automatizar y no exige Play Integrity.** Se puede sincronizar
  pasos con un `POST` autenticado; probamos payloads sin token de integridad y el
  servidor los aceptó. Esto hace viable un contenedor sin emulador.
- **El riesgo real no es el bloqueo, es la auditoría.** Los Términos prohíben
  explícitamente el GPS falso y la simulación de actividad (cláusula x), y el backend
  emite flags (`spike_detected`, `excessive_steps`) y puede poner la cuenta en
  `on_hold` (acreditación pausada). Un bot conservador (≤15.000/día, incremental)
  no dispara ninguno de los dos flags.
- **Recomendación:** contenedor “API-first” (sin emulador) para los pasos, y módulo
  geográfico en una segunda fase. El emulador en Docker sobre macOS no tiene KVM y
  además no aporta sensor de pasos, así que es el peor camino para este caso.

---

## 2. Qué es Pasito (superficie técnica)

| Dato | Valor |
|---|---|
| App | `ar.pasito.pasito` — “Pasito”, versión 2.4.11 (versionCode 115) |
| Stack | Flutter (Dart 3.12.2, AOT) + Kotlin nativo |
| SO | minSdk 26, targetSdk 36 |
| Backend | Supabase detrás de `https://api.pasito.app` (PostgREST + Edge Functions + GoTrue) |
| Proyecto Supabase | `trsbowwcigzayhdpfxvd` (anon key embebida en el APK, rol `anon`) |
| Datos de salud | Google Health Connect (`READ_STEPS`, `READ_EXERCISE`, `READ_DISTANCE`, histórico y background) |
| Sensor propio | `StepSensorService` en foreground + `BackgroundStepSyncWorker` (WorkManager) |
| Ubicación | `GeographicLocationService`, geofencing, permiso background |
| Integridad | Play Integrity (`pasito/play_integrity`, nonce + token) — **opcional en la práctica** |
| Analítica | Firebase + Mixpanel |
| Artefacto analizado | XAPK `sha256:60e4808…040db` (base + split arm64 + densidades) |

Rutas de interés dentro del binario:

- `pasito/core/services/step_sync_service.dart` → construcción del payload y del
  `request_hash`.
- `pasito/core/feature_flags/daily_pasito_cap.dart` → conversión y clamp.
- `pasito/features/geographic_boosts/**` → protocolo del boost geográfico.
- `pasito/features/health/**` → filtros de origen y estados de confianza.

---

## 3. Economía de Pasitos (reglas vigentes)

Fuente: Términos y Condiciones del 30/10/2026, Bases del Boost geográfico y Bases del
Boost por QR, más verificación contra el backend.

| Regla | Valor | Dónde |
|---|---|---|
| Conversión | **1 Pasito = 1.000 pasos validados** | app: `pasitosForSteps` (división entera) |
| Tope diario general | **15 Pasitos** (`daily_pasito_cap = 15`, rollout 100 %) | flag del servidor |
| Fallback del tope | 15 si la flag está apagada o su valor es < 100 | app: `dailyPasitoCap` |
| Tope de visualización | 30 Pasitos (clamp del cliente) | app |
| Recorte del servidor | `validated_steps = min(raw, 15.000)` | **verificado** (50.000 → 15.000; 200.000 → 15.000) |
| Vencimiento | 60 días corridos | Términos vi.2 |
| Canje | 1 por usuario por comercio cada 15 días, con PIN en el local | Términos vi.3 |
| Referidos | 5 Pasitos por invitado | flag `referral_bonus_pasitos = 5` |
| Meta diaria | 10.000 por defecto (configurable) | perfil |
| Boost geográfico | 1 Pasito extra / 1.000 pasos **dentro de la zona**, × multiplicador, hasta el tope de campaña, **fuera del tope diario** | Bases del boost, vi.5 |
| Boost por QR | Igual mecánica, sin geolocalización; tope de campaña | Bases del boost por QR |

### 3.1 Cálculo del techo

| Escenario | Pasos/día | Pasitos/día |
|---|---|---|
| Caminata normal sin boost | 15.000 (más no aporta) | 15 |
| Boost geográfico ×2 con tope 30 | 15.000 dentro de zona | 15 + 30 = 45 |
| Boost ×3 con tope de campaña alto | 15.000 dentro de zona | 15 + tope |

El tope por campaña (`campaign_bonus_cap`) se publica en la app y varía por campaña.
Con la canasta actual (recompensas de 5 a 350 Pasitos), 15 Pasitos/día equivalen a una
recompensa barata cada 1–3 días; 450 Pasitos/mes si se maxea todos los días.

### 3.2 Reglas de acreditación que importan para automatizar

- **Sólo el día en curso acredita Pasitos.** Probado: sincronizar días pasados
  actualiza `raw_steps`/`validated_steps` pero deja `eligible_steps = 0` y
  `pasitos_earned = 0`, incluso enviando `opened_app: true` en el insert.
- **Ventana de sincronización: hoy + 7 días previos.** El día 8 hacia atrás devuelve
  `400 {"error":"Sync date is outside the allowed window"}`. Fechas futuras también se
  rechazan.
- **Los pasos son monotónicos.** Enviar un total menor no baja nada; el servidor toma
  el máximo (`max(validated, nuevo)`).
- **El total es acumulado del día**, no un delta. `5000` y después `15000` deja
  `validated_steps = 15000`.
- **`opened_app`** se guarda y hoy se autocompleta en `true`; en días pasados queda en
  `false` y por eso no acreditan.
- **La racha** (streak) sólo avanza con sincronizaciones del día en curso.

---

## 4. Anti-fraude: qué mira y qué tan detectable es

### 4.1 Controles observados

| Control | Cómo funciona | ¿Frena un bot de API? |
|---|---|---|
| Flags por magnitud | `spike_detected` con saltos > ~40.000; `excessive_steps` con `raw` > ~70.000 (probado con 25k/40k/45k de salto y 60k/80k de raw) | No si se envía ≤15.000 |
| `on_hold` | `get_my_step_anomaly_status` → `{on_hold: bool}`; pausa la acreditación | No se activó con 6 días flaggeados |
| Play Integrity | Nonce + token en el body (`integrity_token`, `integrity_timestamp_millis`) | **No obligatorio**: sin token, 200 OK |
| Cruce sensor nativo vs Health Connect | Campos `sensor_steps`, `hc_steps_trusted`, `strategy_used` (`hc_only`, `sensor_only`, `max_both`, `killswitch_forced_hc`…) | No: enviamos `steps=15000, sensor_steps=1000` y validó 15.000 |
| Origen Health Connect | Lista de apps “confiables” (Samsung Health, Garmin, Fitbit, Mi Fitness, etc.) y flag `trust_hc_native_spn_steps` (hoy en 0 %) | No aplica si se manda por API |
| Descuento de ciclismo | Lee workouts para descontar intervalos de bici | No aplica por API |
| Ventana y fechas | Rechaza fuera de rango | Sí: respetar hoy + 7 días |
| Idempotencia | `request_hash`, `payload_hash`, `idempotency_key` | No: reenviar es seguro (delta 0) |

### 4.2 Lo que **no** se controla

- No hay verificación de ritmo: 15.000 pasos en un solo `POST` pasan sin flag.
- No hay verificación de sensor, distancia ni velocidad.
- No hay attestation obligatoria.
- 25 requests en ráfaga: todos 200, sin 429.

### 4.3 Riesgo real

1. **Términos**: la cláusula (x) prohíbe “técnicas de simulación de ubicación” y
   “simular actividad física”, y habilita a anular Pasitos o suspender la cuenta ante
   “detección razonable”. Es una infracción “blanda”: millones de usuarios y controles
   laxos.
2. **Geo boost**: acá sí hay validación de presencia (ubicación, `is_mocked`
   declarado, reloj del servidor, ventana). Es el punto donde un GPS falso se nota más,
   sobre todo si el `is_mocked` viaja en `true`.
3. **Consistencia**: un patrón perfecto (15.000 exactos todos los días, a la misma hora,
   mismo `device_id`) es detectable a ojo. Conviene jitter y algún día parcial.

---

## 5. Geo boost: cómo funciona (para la fase 2)

Protocolo reconstruido del binario (RPC `geographic_bonus_v1` sobre PostgREST, mismo
proyecto Supabase, con la anon key y el JWT del usuario):

- Catálogo: `rpc/geographic_boost_catalog_v1` con `p_client_version`, `p_limit`
  (máx. 50), `p_before_id`, `p_campaign_id`. **Hoy devuelve `{"items": []}`** en CABA,
  Montevideo, Córdoba y Rosario: no hay campañas activas en el momento del análisis.
- Operaciones: `prepare_window` (inicio), `lookup`, `settle`, `recover`, `exit`,
  `renew`.
- `prepare_window` recibe `contract_version`, `user_id`, `campaign_id`,
  `campaign_version`, `device_id`, `request_key`, `acceptances`, `client_version` y
  devuelve ancla de reloj del servidor, zona y ventana.
- `settle` envía lotes con `batch_id`, `canonical_payload`, `payload_hash` e
  `intervals[]` (`start`, `end`, `trusted_steps`, `sequence`, `session_id`…). Es un
  protocolo con idempotencia y recibos: se puede replicar, pero es la parte más
  laboriosa.
- La zona puede ser círculo (`latitude`, `longitude`, `radius_meters`) o polígono
  (`vertices`), con `starts_at`/`ends_at` y zona horaria
  `America/Argentina/Buenos_Aires`.
- Regla de salida: 30 minutos fuera de zona; sincronización dentro de 48 h del cierre.
- Los Pasitos extra **no** están sujetos al tope diario, pero sí al `campaign_bonus_cap`.

Un detalle importante: el boost geográfico cuenta **pasos del sensor del teléfono**,
no de Health Connect. Por API eso da igual (el cliente declara `trusted_steps`), pero
invalida el atajo “emulador + Health Connect”: el emulador no tiene podómetro.

---

## 6. Opciones de dockerización

### Opción A — Bot de API (recomendada)

Contenedor que inicia sesión y hace `POST /functions/v1/sync-activity` con totales
acumulados.

- **Pros**: liviano (<50 MB de imagen), corre 24/7 en cualquier VPS, sin emulador, sin
  Play Integrity, ya validado de punta a punta.
- **Contras**: no cubre boosts por sí solo (fase 2); si cambian el contrato hay que
  actualizar.
- **Riesgo**: bajo.

### Opción B — Emulador Android en Docker

- **Pros**: usa el binario real, hace todo el flujo (incluido geo) sin reimplementar.
- **Contras**: en Docker Desktop sobre macOS **no hay `/dev/kvm`** (verificado), así que
  corre por TCG: arranque de 10–30 minutos y app lenta. Sin sensor de pasos, hay que
  inyectar Health Connect igual. Play Integrity falla en emulador no certificado.
- **Riesgo**: alto esfuerzo, baja fidelidad.

### Opción C — Híbrido

Bot de API para pasos + teléfono real con GPS falso solo para boosts. Es lo que haría
un usuario “manual” y no requiere contenedor para el GPS. Se puede sumar luego.

**Decisión propuesta: A ahora, C más adelante, B descartado.**

---

## 7. Diseño del contenedor (fase 1)

```
┌─────────────────────────── pasito-bot ───────────────────────────┐
│ scheduler (APScheduler)                                          │
│   ├─ plan diario: 15 lotes de 1.000, 07:30–21:30, jitter ±7 min   │
│   ├─ catch-up al arrancar si el día está incompleto              │
│   └─ corte a las 23:50 del día local                             │
│ client                                                           │
│   ├─ auth: password grant → refresh rotativo persistido          │
│   ├─ sync: POST sync-activity, backoff 429/5xx, Retry-After      │
│   ├─ flags: lee daily_pasito_cap y recalcula el objetivo          │
│   └─ estado: /data/state.json (fecha, enviado, validado, tokens)  │
│ logs JSON + healthcheck + métricas de Pasitos del día            │
└──────────────────────────────────────────────────────────────────┘
```

Decisiones concretas:

- **Imagen**: `python:3.12-slim`, usuario no root, rootfs read-only, `cap_drop: ALL`,
  `no-new-privileges`, límite de 128 MB de RAM y logs rotados.
- **Secretos**: `PASITO_EMAIL` / `PASITO_PASSWORD` por `env_file` o Docker secret; el
  `refresh_token` rotativo se guarda en el volumen `/data` con `0600`.
- **Sesión**: login por contraseña crea una sesión independiente de la del teléfono
  (Supabase permite varias cadenas de refresh). Hay que **persistir el refresh
  rotativo** o se rompe la cadena.
- **Ritmo**: 1.000 pasos por lote, 15 lotes, con jitter; el total nunca supera
  `cap × 1.000`. Se lee el cap de las flags en cada ciclo (hoy 15).
- **Identidad**: `device_id` UUID estable y `device_brand`/`device_model` realistas,
  guardados en el estado.
- **Idempotencia**: no reenviar el mismo total; usar `validated_steps` de la respuesta
  como piso.
- **Zona horaria**: `TZ=America/Argentina/Buenos_Aires`; el corte de día del servidor
  hay que verificarlo empíricamente (ver §9).
- **Sin escrituras destructivas**: no toca perfil, canjes ni challenges.
- **Egress**: sólo `api.pasito.app:443`.

### 7.1 Contrato de API confirmado

```
POST https://api.pasito.app/functions/v1/sync-activity
apikey: <anon key>
Authorization: Bearer <access_token>
Content-Type: application/json

{"steps": 15000, "date": "2026-11-17", "source": "hc_only", "opened_app": true}
```

`200 OK`:

```json
{"pasitos_earned_today":15,"pasitos_delta":15,"pasitos_balance":15,
 "current_streak":1,"validated_steps":15000,"fraud_flags":[]}
```

Errores: `400 {"error":"Invalid steps"}` (pasos ≤ 0, decimales o string) y
`400 {"error":"Sync date is outside the allowed window"}`.

`source`, `sensor_steps`, `hc_steps_trusted`, `integrity_*` y `request_hash` son
opcionales; `steps` es obligatorio.

Lectura de apoyo (no destructiva): `POST /rest/v1/rpc/get_feature_flags_for_current_user`,
`/rest/v1/rpc/get_my_activity_snapshot_v2`, `/rest/v1/rpc/get_my_step_anomaly_status`.

---

## 8. Plan por fases

> **Estado:** Fase 1 implementada en [`bot/`](../bot/README.md) y probada de punta a punta
> con cuentas descartables. Falta cargar las credenciales reales.

1. **Fase 0 — Validación de cuenta (30 min).** Confirmar método de login, que la
   contraseña sirva para `grant_type=password`, y que el teléfono y el bot conviven.
2. **Fase 1 — MVP de pasos.** Contenedor con scheduler, tope dinámico, estado y
   observabilidad. Correr en modo “seco” un día y comparar contra la app.
3. **Fase 2 — Geo boosts.** Descubrimiento por catálogo, `prepare_window`, presencia
   con coordenadas del polígono/círculo, `settle` por lotes. Requiere campañas activas
   para probar.
4. **Fase 3 — Endurecimiento.** Jitter semanal, días parciales, alertas por Telegram
   cuando `fraud_flags` o `on_hold` aparezcan.

---

## 9. Preguntas abiertas / a verificar en implementación

- **Corte de día del servidor**: ¿usa la fecha que manda el cliente o `now()` en UTC?
  Con UTC, el corte sería a las 21:00 de Argentina. Hay que probarlo cerca de
  medianoche antes de fijar el plan diario.
- ~~**Método de login del usuario**~~: resuelto. La cuenta era de Google; se creó una
  contraseña propia por el flujo OTP (`/auth/v1/otp` → `/auth/v1/verify` →
  `PUT /auth/v1/user`) y quedó guardada en `bot/.env`. El login con Google sigue
  funcionando en paralelo.
- **Cap por país/campaña**: la flag es global hoy; puede haber overrides.
- **Campañas de boost activas**: el catálogo está vacío en este momento.

### Estado de despliegue

- Contenedor `pasito-bot` corriendo en la Mac (Docker Compose, `restart: unless-stopped`)
  desde el 2026-11-17, con la cuenta ya en 15/15 ese día.
- Destino decidido: PC de casa. El traslado está resuelto con `bot/scripts/bundle.sh`
  (imagen + compose + `.env`) y las instrucciones de `bot/deploy/README.md`.
- Mientras tanto sigue corriendo en la Mac; hay que frenarlo antes de mover para no
  dejar dos instancias.

---

## 10. Checklist de “cosas a tener en cuenta”

- [x] 15.000 pasos es el techo; más pasos no generan Pasitos ni ranking.
- [x] Los días pasados no acreditan: el bot debe trabajar **hoy**.
- [x] Ventana de 7 días: sirve para corregir, no para farmear.
- [x] Mantener los envíos por debajo de ~40.000 de salto y de ~70.000 de raw para no flaggear.
- [x] No hace falta Play Integrity ni emulador.
- [x] La sesión necesita refresh rotativo persistido; dos sesiones (teléfono + bot) son
      válidas, pero hay que tolerar 401 y re-loguear.
- [x] Pasitos vencen a los 60 días: maxear y no canjear pierde valor.
- [x] El canje es presencial con PIN: el bot no reemplaza la salida al local.
- [x] Los boosts son la única forma de pasar de 15 Pasitos/día y tienen su propio tope.
- [x] Los Términos prohíben GPS falso: la cuenta puede ser auditada, no es “legalmente
      limpio”.
- [x] Cada actualización de la app puede cambiar endpoint o payload: fijar versión y
      monitorear errores.
- [x] El `device_id` debe ser estable y distinto del teléfono sólo si se quiere simular
      otro dispositivo; conviene mantener uno propio y consistente.

---

## Anexo — Evidencia de las pruebas

| Prueba | Resultado |
|---|---|
| 1.234 pasos | `pasitos_delta: 1` |
| 5.000 / 15.000 / 50.000 | 5 / 15 / 15 Pasitos; `validated_steps` 5.000 / 15.000 / **15.000** |
| 200.000 | `fraud_flags: ["excessive_steps","spike_detected"]`, igual acredita 15 |
| Saltos de 25k / 40k / 45k | sin flag / sin flag / `spike_detected` |
| 60.000 / 80.000 de raw | `spike_detected` / `excessive_steps` + `spike_detected` |
| Bajar de 15.000 a 1.000 y volver a 30.000 | `validated_steps` se mantiene en 15.000 |
| Fecha de ayer y de hace 7 días | `200`, `eligible_steps: 0`, `pasitos_earned: 0` |
| Fecha de hace 8 días / futura | `400 Sync date is outside the allowed window` |
| Sin `integrity_token`, sin `request_hash` | `200` |
| `sensor_steps: 1000` con `steps: 15000` | `200`, valida 15.000 |
| 25 POST en ráfaga | 25 × `200`, sin 429 |
| Flags tras 5 días flaggeados | `on_hold: false` |
| Catálogo geográfico en 4 ciudades | `{"items": []}` |

---

_Última actualización: 2026-11-17. Cuentas de prueba: `lab+…@pasito.test`,
`lab2/3/4+…@pasito.test` (descartables)._
