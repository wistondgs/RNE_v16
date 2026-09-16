# Auditoría forense de la base viva — `aeon_event_log.db`

**2026-09-16. Inspección estrictamente de solo lectura. No se corrigió nada.**

Objetivo: comprobar si el esquema efectivo de los 665 MB corresponde al contrato que el
código cree estar ejecutando, dado que **no existe versionado formal de esquema**
(`CREATE TABLE IF NOT EXISTS` + dos `ALTER TABLE` a mano, sin tabla de versión).

## 0. Disciplina aplicada

| Requisito | Cómo se cumplió |
|---|---|
| Abrir estrictamente read-only | URI `file:…?mode=ro` + `PRAGMA query_only=ON` (verificado = 1) |
| No migraciones | no se ejecutó ningún `CREATE`/`ALTER`/`INSERT` |
| No `VACUUM`, no `REINDEX` | no invocados |
| No cambiar PRAGMAs persistentes | solo `query_only`, que es de conexión |
| Hash/tamaño/mtime antes y después | ver abajo |

La base está en **modo rollback journal** (`write_version = 1`), no WAL, y no había
`-wal`/`-shm`/`-journal`: cierre limpio previo. Por eso `mode=ro` es seguro aquí sin
necesidad de copiar el fichero.

```
                     ANTES                              DESPUÉS
sha256    ecdfde43c24e60244f9dfce71898e29262dd9ed9a0c3cbcf5658d3f2305990a0   (idéntico)
tamaño    665.362.432 bytes                                                  (idéntico)
mtime     2026-07-06T13:45:55.218790                                         (idéntico)

INTACTA: True        ficheros colaterales creados: ninguno
```

Cabecera: `page_size` 4096 · 162.442 páginas · `file_change_counter` 114.034.

---

## 1. Las tres nociones de esquema

### `S_live` — lo que hay en el fichero

**18 tablas** (17 reales + `sqlite_sequence`), **32 índices**, **0 claves foráneas**.

| tabla | filas | | tabla | filas |
|---|---:|---|---|---:|
| `events` | **33.246** | | `trajectory_windows` | 663 |
| `reasoning_traces` | 27.754 | | `trajectory_flow_reports` | 663 |
| `constitutional_risk_states` | 12.447 | | `reality_bench_runs` | 495 |
| `memory_records` | 11.068 | | `reality_assessments` | 126 |
| `artifacts` | 4.187 | | `failure_atlas_events` | **0** |
| `episode_certificates` | 4.149 | | `renormalization_events` | **0** |
| `organism_snapshots` | 4.149 | | `sessions` | **0** |
| `promotion_decisions` | 4.149 | | `telemetry_snapshots` | **0** |
| | | | `transfer_assessments` | **0** |

### `S_declared` — lo que el código crea

Extraído de `runtime/storage/backends/sqlite_store.py` y `runtime/core/event_log_sqlite.py`,
materializado en una base `:memory:` y comparado columna a columna.

### `S_expected` — lo que las dataclasses de `records.py` prometen

---

## 2. Resultado 1 — `S_live ≡ S_declared`. Cero deriva.

**Las 16 tablas auxiliares coinciden exactamente** con el DDL del código, en número de
columnas, tipos, `NOT NULL`, defaults y claves primarias. Y coinciden **en los dos
árboles** (`genesis-v2` y `v16`).

```
problemas estructurales detectados: 0
```

Incluidas las dos columnas añadidas a mano por el parche `PRAGMA table_info` + `ALTER
TABLE` de `sqlite_store.py:336-348`: `constitutional_risk_states.prev_state_id` y
`.step_index INTEGER NOT NULL DEFAULT 0` **sí están** en la base, junto con el índice
`idx_risk_states_run_traj_scope_step`. La migración manual corrió.

**Esto es un resultado negativo y es una buena noticia.** La ausencia de versionado de
esquema no ha causado deriva **todavía**. El riesgo que señalé sigue siendo real —
`CREATE TABLE IF NOT EXISTS` no aplica columnas nuevas a una tabla existente— pero no se
ha materializado en esta base.

## 3. Resultado 2 — `S_expected ≠ S_live` en exactamente un sitio: el ledger

De los 17 tipos de record, **16 mapean perfectamente**. Uno no:

| dataclass | tabla | campos | columnas | hueco |
|---|---|---:|---:|---|
| **`StoredEvent`** | **`events`** | **9** | **4** | `run_id`, `source`, `legacy_db_path`, `legacy_event_id`, `event_id`, `payload_hash` |

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT,
    timestamp TEXT NOT NULL
)
```

**Seis de los nueve campos del tipo no tienen columna donde vivir.** `run_id` y `source`
se embuten dentro del JSON del payload; los otros cuatro —`event_id`, `payload_hash`,
`legacy_db_path`, `legacy_event_id`— **se descartan en la escritura**. Es la confirmación
a nivel de esquema de
[H-018](CROSS_TREE_AUTHORITY_MAP.md): el ledger SQLite no tiene identidad de evento ni
hash de integridad, y por tanto **no se puede verificar ni deduplicar**.

Nótese que la tabla más importante del sistema es la única cuyo tipo y cuyo
almacenamiento no coinciden.

## 4. Resultado 3 — hallazgos que solo la base viva podía dar

### 3.1 · Cero claves foráneas en toda la base

`configure_sqlite_connection` activa `foreign_keys=ON` en cada conexión y lo documenta
como *"integridad referencial"*. **No hay ni una `FOREIGN KEY` declarada.** El PRAGMA no
hace nada.

Cuatro relaciones existen solo por convención de nombre, sin que nada las imponga:
`promotion_decisions.certificate_id` → `episode_certificates`,
`memory_records.certificate_id` → `episode_certificates`,
`trajectory_flow_reports.window_id` → `trajectory_windows`,
`constitutional_risk_states.prev_state_id` → sí misma.

### 3.2 · `events` no tiene ningún índice

33.246 filas, y `list_events` consulta
`WHERE event_type IN (…) AND COALESCE(json_extract(payload,'$.run_id'), …) = ?`.
Sin índice sobre `event_type` y con un predicado `json_extract` —no indexable sin índice
de expresión— **cada lectura filtrada es un recorrido completo con parseo de JSON por
fila**. Degrada linealmente con el ledger.

`sessions` tampoco tiene índice explícito, pero está vacía.

### 3.3 · Cinco tablas nunca se escribieron

`telemetry_snapshots`, `sessions`, `transfer_assessments`, `renormalization_events`,
`failure_atlas_events`.

Dos son esperables: `sessions` es capacidad reservada B23, y `transfer_assessments` es
posterior. Pero:

- **`telemetry_snapshots` es uno de los 5 contratos ACTIVOS de CANON §13** y tiene cero
  filas. El contrato que sí se hace cumplir al escribir no ha tenido ni una escritura.
- **`renormalization_events` y `failure_atlas_events` están vacías mientras el resto de la
  cadena T4 sí corrió** (`trajectory_windows` 663, `trajectory_flow_reports` 663,
  `constitutional_risk_states` 12.447). Parte de la maquinaria T4 dispara y parte nunca.

### 3.4 · El ledger es una campaña de 41 horas, no historia acumulada

```
events               2026-07-05T02:33:44  →  2026-07-06T19:45:55
memory_records       2026-07-05T02:33:44  →  2026-07-06T18:19:47
episode_certificates 2026-07-05T02:33:44  →  2026-07-06T18:19:47
```

**4.149 episodios**, cifra que aparece idéntica en 9 tablas y 7 tipos de evento. Solo
**11 tipos de evento distintos** en 33.246 filas.

Y la fecha importa para la autoridad: **el ledger es anterior a la bifurcación
genesis-v2 / v16 (2026-07-10)**. Es evidencia sobre el tronco común, no sobre ninguna de
las dos ramas.

### 3.5 · H-012 REFUTADO en los datos reales

Afirmé que `runtime/organism/experience.py:216` escribe `scale="experience"`, violando el
enum del contrato. En el código es cierto. **En la base no hay ni una fila así:**

```
micro   4.149     meso   4.149     macro  2.770        (total 11.068)
```

O sea: el subsistema de experiencia **nunca ha escrito en esta base**. La violación es
**latente, no materializada**, y **no hace falta migración**. Bajo la severidad.

### 3.6 · H-013 CONFIRMADO, y peor de lo que pensaba

```
filas de memoria                        : 11.068
con no_interference = 1                 : 11.068
CON marcador no_interference_computed   :      0
SIN marcador                            : 11.068
```

**Las 11.068 memorias del ledger son exactamente las afirmaciones falsas indistinguibles
que el paquete B24 vino a impedir.** El arreglo protege las escrituras futuras; el corpus
existente quedó sin marcar. Cualquier análisis sobre esta base leerá
`no_interference = 1` en 11.068 filas sin forma de saber que ninguna fue medida.

Si esta base se usa alguna vez como evidencia, **hace falta un marcado retroactivo** —o
declarar la base entera como pre-B24 en su procedencia.

---

## 5. Resumen

| Pregunta | Respuesta |
|---|---|
| ¿`S_live` corresponde a `S_declared`? | **Sí, exactamente**, en los dos árboles |
| ¿`S_live` corresponde a `S_expected`? | **No, en el ledger**: faltan 6 de 9 campos de `StoredEvent` |
| ¿Hay deriva por falta de versionado? | **No todavía**; el riesgo sigue abierto |
| ¿La base quedó intacta? | **Sí** — mismo sha256, mismo tamaño, mismo mtime, sin colaterales |

**Nada corregido, como corresponde.**
