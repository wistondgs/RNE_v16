# 02 — `runtime/storage/` (capa de persistencia)

> **Revisión 2 — 2026-09-16, contra HEAD `433beca`.** Lectura línea por línea de los 13
> ficheros (5.382 líneas). Cada afirmación de la rev.1 lleva veredicto.
>
> **La rev.1 de este módulo es buena.** De sus 14 hallazgos, 4 ya se arreglaron, 6 siguen
> vigentes y ninguno era falso. Es un contraste con la partición 01, donde varias
> referencias eran imprecisas de origen.

```
runtime/storage/
├── __init__.py               104   singleton get_storage()
├── config.py                 107   StorageConfig.from_env + carga de .env
├── factory.py                 43   elige backend por modo
├── interfaces.py             303   10 Protocols → StorageBackend (37 métodos)
├── records.py                279   16 dataclasses persistentes
├── contract_validation.py    245   ← NUEVO desde la rev.1 (no existía en v15)
├── facade.py                 775   API estable; 3 puntos de enforcement
├── backends/
│   ├── sqlite_store.py      1503
│   ├── postgres_store.py    1427
│   └── hybrid_store.py       468   dual-write + lectura con fallback
└── migrations/
    └── sqlite_to_postgres.py 113   idempotente, solo el ledger
```

---

## 1. Arquitectura, verificada

**Los 3 backends implementan exactamente los 37 métodos del protocolo. Cero deriva de
firma** (comprobado mecánicamente). La deriva está en el **comportamiento**, no en la API.

`interfaces.py` compone `StorageBackend` (l.288-303) a partir de 10 Protocols. Buena
segregación, con una excepción: `T4TrajectoryStore` (l.198-285) agrupa **12 métodos** de
6 conceptos distintos (snapshots, ventanas, informes de flujo, renormalización, riesgo
constitucional, atlas de fallos).

Los 10 son `@runtime_checkable`, lo que solo comprueba **existencia de métodos**, no
firmas: `isinstance(x, StorageBackend)` es cierto para cualquier objeto con esos 37
nombres.

### Puntos de enforcement de contrato (los 3 que hay)

| Línea | Llamada | Contratos cubiertos |
|---|---|---|
| `facade.py:67` | `enforce_event` | `episode`, `proposal`, `rollback` (vía `EVENT_CONTRACTS`) |
| `facade.py:94` | `enforce_record("telemetry_snapshot")` | `telemetry_snapshot` |
| `facade.py:356` | `enforce_record("certificate")` | `certificate` |

Cubren los 5 contratos activos de CANON §13 y ninguno más. Correcto y consistente con
[01 — contracts](01_contracts.md).

---

## 2. Hallazgos vigentes

### [ALTA · CONFIRMADO] `_read_with_fallback` confunde «vacío» con «fallo»

`hybrid_store.py:107`. `if rows:` es falso para `[]`, que es una respuesta **correcta**.

**Reproducido en ejecución**, con los dos stores vivos y ninguno fallando:

```
primary  (autoridad, prefer_primary_reads=True): 0 filas
fallback:                                        1 fila vieja
h.list_events() → ['viejo.de.otra.corrida']
```

La respuesta correcta era `[]`. Devolvió datos del fallback **sin warning** (el warning de
la l.112 solo cubre la rama de excepción). Afecta a las 16 lecturas de lista.

Las lecturas puntuales (`get_session_bridge` l.200, `get_episode_certificate` l.260) usan
`is not None` y **están bien**. El defecto es exclusivo de las listas.

Arreglo: mover el `return` dentro del `try` y quitar el `if rows:`.

Lo señaló la rev.1 (`[RIESGO] _read_with_fallback…`) y sigue igual 3 meses después.

### [ALTA · NUEVO] SQLite no es un fallback de Postgres

Para el ledger, los dos backends guardan cosas distintas:

| | Postgres `ledger_events` | SQLite `events` |
|---|---|---|
| `event_id` | PK, se genera (l.76) | **se descarta** |
| `payload_hash` | `NOT NULL`, se computa (l.78) | **se descarta** |
| `run_id`, `source` | columnas | dentro del payload JSON |
| `legacy_db_path`/`legacy_event_id` | columnas + `UNIQUE` | **se descartan** |
| idempotencia | `ON CONFLICT DO NOTHING` (l.86) | **ninguna** |

`runtime/core/event_log_sqlite.py:99-102` inserta **tres columnas**. El facade acepta
`event_id=`, `legacy_db_path=`, `legacy_event_id=` (`facade.py:51-53`) y SQLite los tira
sin decir nada.

Consecuencias: el mismo evento escrito dos veces produce 2 filas en SQLite y 1 en
Postgres; y en `hybrid`, `postgres_store.py:115-116` **muta el objeto del llamador**
(`event.event_id = …`; `StoredEvent` es `slots=True` pero no `frozen`), así que el
`event_id` devuelto depende de qué store respondió.

### [MEDIA · NUEVO] El hash de integridad del ledger no lo verifica nadie

`postgres_store.py:37-39` computa un SHA-256 de JSON canónico, lo guarda en columna
`NOT NULL` y lo devuelve al leer. **No existe en el repo ni una comparación entre un
`payload_hash` guardado y uno recomputado.** Un hash que no se verifica no es integridad:
es un campo que aparenta serlo.

### [MEDIA · NUEVO] Los dos backends fallan distinto ante un `created_at` corrupto

`created_at` es `TEXT` en ambos y nada valida su formato (ni el dataclass, ni el esquema
—sin `format`—, ni el DDL).

- **SQLite** (medido): `strftime` da `NULL`, la fila nunca expira y **sigue visible**. El
  purgado del resto funciona. La guarda `strftime(...) IS NOT NULL` de `sqlite_store.py:52`
  no cambia el resultado (`NULL > ttl` ya es falso): es explicitud, no corrección.
- **Postgres** (lectura de código, no ejecutado): `created_at::timestamptz`
  (`postgres_store.py:44`) **lanza** sobre texto inválido. No es "la fila no expira": es que
  `purge_expired_memory_records()` no purga **nada**, y como el mismo fragmento se usa en
  lectura, `retrieve_memory_records()` también lanza. **Una fila corrupta deja ciego al
  organismo sobre toda su memoria.**

### [MEDIA · NUEVO] El runtime escribe un `scale` que su contrato prohíbe

`contracts/memory_record.schema.json:19` cierra el enum a `{micro, meso, macro}`;
`runtime/organism/experience.py:28,216` escribe `"experience"`. No falla porque
`memory_record` no es contrato activo, el DDL no tiene `CHECK`
(`sqlite_store.py:183`) y el round-trip del subsistema es autoconsistente
(`experience.py:244` relee con el mismo valor). El día que se promueva el contrato, cada
escritura de experiencia lanza `ContractViolationError` en modo `strict`.

### [MEDIA · NUEVO] `list_events` pierde 4 de 9 campos y ordena por claves distintas

`sqlite_store.py:375-381` reconstruye 5 de los 9 campos de `StoredEvent`. Y:

- `row.get("event", "unknown")` convierte un tipo ausente en el literal `"unknown"`;
- un payload no-dict se envuelve en `{"value": …}` sin aviso;
- SQLite ordena por **rowid** (`event_log_sqlite.py:125` + `[::-1]`), Postgres por
  **`event_ts`** (`postgres_store.py:141`), que el llamador puede fijar
  (`facade.py:48`). Los dos son "cronológico" por magnitudes distintas.

### [MEDIA · CORREGIDO a medias] Dual-write no estricto: hay log, no hay integridad

La rev.1 decía que tragaba fallos **sin loguear**. Ya no: `hybrid_store.py:75-89` emite
`logger.warning` en los tres caminos y
`tests/storage/test_hybrid_dual_write_observability.py` lo cubre.

Queda lo otro: no hay cola de reintento, ni marca de pendiente, ni reconciliación. Con
`strict_dual_write=False` (default, `config.py:90`) los dos stores divergen y el único
rastro es una línea de log — no consultable, no cruzable con la lectura.

### [BAJA · CONFIRMADO] `register_artifact` lee el fichero entero aunque no haga falta

`facade.py:150`: `content = path.read_bytes()` se ejecuta **siempre**, incluso con
`sha256` y `size_bytes` ya provistos. Peor: si el llamador pasa un `sha256`, se **confía
sin verificar** (l.151) — se paga el coste de leer y se salta la comprobación.
`materialize_artifact` escribe el fichero (l.198) y acto seguido `register_artifact` lo
vuelve a leer: doble E/S por artefacto.

### [BAJA · CONFIRMADO] Tabla `runs` huérfana

`backends/postgres/schema.sql:1-7` define `runs(run_id, status, started_at, ended_at,
context_json)`. **Cero lecturas y cero escrituras** en todo el código vivo.

### [BAJA · CONFIRMADO] `TransferAssessmentStore` no se re-exporta

`__init__.py:11-21` re-exporta 9 de los 10 Protocols. Falta `TransferAssessmentStore`
(verificado: 0 apariciones).

### [BAJA · CONFIRMADO] Formato de timestamp inconsistente

`records.utc_now_iso()` produce ISO **con** offset (`…+00:00`);
`event_log_sqlite.py:95` usa `datetime.utcnow().isoformat()` — **naive, sin offset**, y
además deprecado en Python 3.12. Las dos formas no se ordenan lexicográficamente entre sí.
En la práctica el facade siempre pasa timestamp, así que la ruta solo se activa en
llamadas directas a `log_event`.

### [BAJA · NUEVO] Modo de storage inválido = silencio

`config.py:76-78`: `RNFE_STORAGE_MODE=postgress` (typo) cae a `"sqlite"` **sin warning ni
error**. `contract_validation.get_mode()` sí avisa ante un modo inválido. Mismo patrón, dos
comportamientos — y el de storage es el peligroso: escribir a un SQLite local creyendo
estar en Postgres.

### [BAJA · NUEVO] `_load_dotenv_once` carga más de lo que dice

`config.py:24-61`. El docstring dice *"para variables RNFE/AEON aún no definidas"*, pero
la l.57 (`if key and key not in os.environ`) **no filtra por prefijo**: mete en
`os.environ` cualquier clave del `.env`. Divergencia doc↔código.

### [BAJA · NUEVO] La migración rellena silenciosamente los payloads corruptos

`migrations/sqlite_to_postgres.py:25-34`: un payload que no parsea se migra como `{}`. El
evento llega a Postgres con contenido vacío y **sin marca de que se perdió**. Es
exactamente lo que la doctrina B24 del propio repo prohíbe: rellenar lo no medible con un
default plausible. Debería viajar un marcador en los datos.

Además, el contador que devuelve (`migrated`, l.86) cuenta **filas procesadas**, no
insertadas: una segunda corrida imprime el mismo número aunque `ON CONFLICT DO NOTHING`
no inserte nada.

### [BAJA · NUEVO] No hay versionado de esquema

`sqlite_store.py:82-350` usa `CREATE TABLE IF NOT EXISTS` más dos parches manuales
`PRAGMA table_info` + `ALTER TABLE` (l.336-348, para `prev_state_id` y `step_index`). No
hay tabla de versión de esquema. Consecuencia: **una columna añadida a un `CREATE TABLE`
nunca se aplica a una base que ya existe** — solo se aplican las dos parcheadas a mano. El
DDL del código y el de un `.db` viejo pueden divergir en silencio.

**Comprobación pendiente y barata**, que no hice por no tocar datos vivos: comparar las
columnas del código contra las de `aeon_event_log.db` (635 MB, árbol `RNE_v16`).

---

## 3. Lo que se arregló desde la rev.1

| Hallazgo rev.1 | Estado |
|---|---|
| `list_events` filtra `run_id` **después** del `LIMIT` | **`CORREGIDO`** — `event_log_sqlite.py:113-122` filtra en SQL antes del `LIMIT`, con comentario que cita la paridad con Postgres |
| SQLite sin WAL ni `busy_timeout` | **`CORREGIDO`** — `configure_sqlite_connection` (B38-C12) aplica `WAL`, `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON`, desde una única fuente |
| Upsert parcial en `write_transfer_assessment` | **`CORREGIDO`** — Postgres actualiza todas las columnas **salvo `created_at`** (l.862-871) y SQLite se alineó (B46, `sqlite_store.py:993-998`) |
| Dual-write traga fallos **sin loguear** | **`CORREGIDO`** — warnings + tests |

> **Aviso de método.** Estuve a punto de reportar el primero de esos como vigente: había
> leído `archive/legacy_src2/core/event_log_sqlite.py:37-55`, que sí tiene el defecto. El
> fichero vivo es `runtime/core/event_log_sqlite.py`. En un repo con `archive/` de 14.489
> líneas conteniendo copias casi idénticas, **comprobar siempre qué fichero está vivo**.

---

## 4. Lo que está bien construido

- **B24 — el mejor patrón del repo.** `facade.py:437-446` inyecta
  `metadata={"no_interference_computed": False}` porque *"la declaración tiene que viajar
  EN LOS DATOS, no en la prosa"*. Resuelve que `no_interference` sea un campo nunca
  computado y aun así persistido. **Verifiqué que no tiene fuga**: los 4 escritores de
  memoria declaran `storage: StorageFacade` (`experience.py:205`,
  `mfm_lite/episode_store.py:17`), así que ninguno esquiva el marcador.
- **`contract_validation.py`** declara qué no valida y por qué (ver partición 01).
- **`configure_sqlite_connection`** — fuente única de PRAGMAs, documentada con el motivo
  de cada uno.
- **La migración es idempotente de verdad**: `event_id` determinista
  (`legacy::<path>::<rowid>`) + `UNIQUE (legacy_db_path, legacy_event_id)`.
- **B46** documenta la semántica de `created_at` en re-escritura y alineó los dos backends.

---

## 5. Prioridad sugerida

1. `_read_with_fallback`: `if rows:` → devolver la respuesta del store autoridad (1 línea)
2. Decidir si el ledger debe ser verificable → cablea el `payload_hash` y arrastra la
   paridad de SQLite
3. Cast tolerante de `created_at` en Postgres, o validar el formato al escribir
4. `scale="experience"`: ampliar el enum o mover a `metadata.origin`
5. Warning ante `RNFE_STORAGE_MODE` inválido (1 línea)
6. Re-exportar `TransferAssessmentStore`, quitar la tabla `runs` (limpieza)
