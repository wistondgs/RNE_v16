# Registro `PATCH-CANDIDATE`

**Nada de esto se aplica hasta que el mapa de autoridad se cierre con una decisión.**
Ver [`CROSS_TREE_AUTHORITY_MAP.md`](CROSS_TREE_AUTHORITY_MAP.md).

Motivo del registro en vez del parche: un arreglo correcto y pequeño aplicado al checkout
equivocado es trabajo perdido dos veces —no arregla el tronco y crea una divergencia más.
`contracts/` es **idéntico en los tres árboles**, así que cada parche ahí habría que
aplicarlo tres veces o arriesgarse a romper la única identidad limpia que queda.

Estado de todos: **`PENDIENTE — bloqueado por decisión de autoridad`**.

---

## PC-001 · `__all__` ausente en `aeon_types.py`

| | |
|---|---|
| **Archivo** | `contracts/types/aeon_types.py` (falta) · `contracts/types/__init__.py:3` (`import *`) |
| **Defecto** | 26 de 39 símbolos públicos de `contracts.types` no son contratos: `contracts.types.np` **es numpy 2.2.6**, `contracts.types.defaultdict` es `collections.defaultdict`. |
| **Prueba que lo demostraría** | `test_contracts_types_public_surface`: `assert set(dir(contracts.types)) - {'_*'} == CONTRATOS` con los 13 nombres reales. Falla hoy con 26 extras. |
| **Riesgo** | **Medio.** `runtime/control/homeostasis/{thermodynamic_governor,energy_sensors}.py:10` hacen `from …aeon_types import *`. Si usan algún símbolo fugado sin importarlo, poner `__all__` los rompe **en import time**. Es un fallo ruidoso e inmediato, no silencioso. |
| **Árboles afectados** | **los 3** (`contracts/` idéntico: sha256 iguales) |
| **Incompatibilidad cross-tree** | Ninguna en el fichero. Pero los **consumidores divergen**: `runtime/control` tiene 6 ficheros divergentes entre g-v2 y v16, así que hay que reejecutar la comprobación de rotura **por árbol**. |
| **Bloquea a** | PC-004 (no se pueden borrar los imports muertos antes de esto) |

## PC-002 · `Vector3D.normalized()` divide por cero

| | |
|---|---|
| **Archivo** | `contracts/types/aeon_types.py:47-49` |
| **Defecto** | Sin guarda de magnitud nula, y el default de `ThermodynamicState.thermal_gradient` (l.60) es exactamente `Vector3D(0,0,0)`. |
| **Prueba** | `assert Vector3D(0,0,0).normalized() == Vector3D(0,0,0)` — hoy lanza `ZeroDivisionError`. |
| **Riesgo** | **Muy bajo.** Cero llamadores vivos en los tres árboles. |
| **Árboles afectados** | los 3 |
| **Incompatibilidad cross-tree** | Ninguna. |
| **Nota** | Señalado ya en la rev.1 de 2026-06-10. **Sigue igual.** El coste es 1 línea; lo que falta es decidir si el contrato es «devolver cero» o «lanzar `ValueError` explícito». |

## PC-003 · `ThermodynamicState.to_dict()` pierde 2 de 7 campos

| | |
|---|---|
| **Archivo** | `contracts/types/aeon_types.py:62-69` |
| **Defecto** | Omite `heat_dissipation` y `thermal_gradient`. La pérdida se propaga: `HealthStatus.to_dict()` parte de `asdict(self)` —completo— y en la l.111 **lo sobrescribe** con la versión recortada. |
| **Prueba** | `assert set(ThermodynamicState().to_dict()) == {f.name for f in fields(ThermodynamicState)}`. |
| **Riesgo** | **Bajo, pero no nulo.** Añadir dos claves cambia la forma de un dict que se serializa. Si algo aguas abajo hace `==` sobre el dict, o lo hashea, el hash cambia. **Hay que buscar consumidores antes.** |
| **Árboles afectados** | los 3 |
| **Incompatibilidad cross-tree** | `thermal_gradient` colisiona en nombre con el campo **plano** `HealthStatus.thermal_gradient: float` (l.102), que es de **tipo distinto** (`Vector3D` vs `float`). Serializar los dos deja dos claves homónimas en niveles distintos del mismo JSON. **Resolver H-001 antes que esto.** |

## PC-004 · Imports muertos y shim `StrEnum` sin uso

| | |
|---|---|
| **Archivo** | `contracts/types/aeon_types.py:2-17` |
| **Defecto** | 12 imports sin uso + el bloque `try/except StrEnum` (l.8-12) que nunca se usa. |
| **Prueba** | `ruff F401` sobre el fichero. |
| **Riesgo** | **Alto mientras no exista `__all__`** — ver PC-001. Después: trivial. |
| **Árboles afectados** | los 3 |
| **Orden** | **estrictamente después de PC-001.** |

---

## PC-005 · El contrato de lectura del store híbrido no distingue tres estados

| | |
|---|---|
| **Archivo** | `runtime/storage/backends/hybrid_store.py:107` (g-v2) · `:86` (v16) |
| **Defecto** | `if rows:` colapsa **respuesta válida = conjunto vacío** con **el backend no respondió**. Devuelve memoria antigua del fallback aunque la autoridad haya contestado correctamente «no existe». |
| **Estado de la prueba** | **Ya reproducido en ejecución**, con los dos stores vivos y ninguno fallando: primary (autoridad) con 0 filas → devuelve la fila vieja del fallback, sin warning. |
| **Prueba de regresión** | `test_hybrid_respects_authoritative_empty`: primary vacío + fallback con datos ⇒ `list_events() == []`. |
| **Riesgo del arreglo** | **Medio, y hay que mirarlo antes.** Si alguna ruta escribe solo en el fallback y depende de que la lectura lo encuentre, hoy funciona **por el defecto**. Arreglarlo la rompe. Hay que auditar esas rutas primero. |
| **Árboles afectados** | **g-v2 y v16: presente en los dos, nunca arreglado en ninguno.** Señalado ya en la rev.1 (2026-06-10). |
| **Incompatibilidad cross-tree** | `hybrid_store.py` diverge entre árboles (468 vs 412 líneas): el parche no se puede aplicar por `patch`, hay que reescribirlo en cada uno. |

**Este no se arregla con un cambio de *truthiness*.** Lo que hay que corregir es el
**contrato de lectura**, que debe distinguir tres estados que hoy son dos:

```
SUCCESS_EMPTY   ≠   UNAVAILABLE   ≠   ERROR
```

- `SUCCESS_EMPTY` — la autoridad respondió y no hay registros. **Es una respuesta. Se devuelve.**
- `UNAVAILABLE` — la autoridad no pudo responder. **Solo aquí** se recurre al fallback, y
  el resultado debe venir marcado con su procedencia degradada.
- `ERROR` — fallo que no debe enmascararse con datos de nadie.

Y el resultado debería decir **qué store respondió**. Hoy es indistinguible, que es lo que
convierte la divergencia de PC-006 en respuestas incorrectas silenciosas.

## PC-006 · `StorageFacade` promete una equivalencia que los backends no cumplen

| | |
|---|---|
| **Archivo** | `runtime/storage/backends/sqlite_store.py:350` · `runtime/core/event_log_sqlite.py:99-102` · `postgres_store.py:75-116` |
| **Defecto** | No son dos implementaciones del mismo modelo de datos: **son dos modelos distintos detrás de una interfaz**. Postgres conserva `event_id`, `payload_hash`, provenance legacy e **idempotencia** (`ON CONFLICT DO NOTHING`); SQLite **descarta los cuatro campos y no tiene ninguna clave**. |
| **Confirmado en el esquema real** | La base viva lo demuestra: `StoredEvent` tiene 9 campos y `events` tiene 4 columnas. Es **el único** de los 17 records donde `S_expected ≠ S_live`. Ver [`LIVE_DB_FORENSICS.md`](LIVE_DB_FORENSICS.md). |
| **Prueba** | `test_backend_roundtrip_parity`: escribir un `StoredEvent` con los 9 campos, releer, y exigir igualdad campo a campo **en los dos backends**. Falla hoy en SQLite en 4 campos. Y `test_append_is_idempotent`: escribir dos veces ⇒ 1 fila. Falla hoy en SQLite. |
| **Riesgo del arreglo** | **Alto.** Añadir `event_id`, `payload_hash` y un `UNIQUE` a `events` es una **migración de esquema sobre 33.246 filas existentes**, y no hay versionado formal de esquema que la soporte. |
| **Árboles afectados** | los 2 con storage (idéntico problema; `v16` = versión v15) |
| **Incompatibilidad cross-tree** | `sqlite_store.py` diverge (1.503 vs 1.442). Y la migración tocaría la base viva, que es **pre-bifurcación** y compartida conceptualmente por ambas ramas. |

## PC-007 · `payload_hash` almacenado y nunca verificado

| | |
|---|---|
| **Archivo** | `runtime/storage/backends/postgres_store.py:37-39` (cómputo), `:78` (escritura), `:156` (lectura) |
| **Defecto** | El hash se computa, se guarda en columna `NOT NULL`, se devuelve — y **no existe en el repo ni una comparación con un hash recomputado**. No es integridad: es metadato que aparenta integridad. |
| **Lo que debería existir** | `verify( H(canonicalize(payload)), payload_hash )` en el camino de lectura. **Ante desajuste, jamás devolver el registro como memoria válida en silencio**: emitir `ledger.integrity.mismatch` con el `event_id` y marcar el registro como no confiable en los datos que se devuelven. |
| **Prueba** | `test_tampered_payload_is_detected`: alterar el payload de una fila por SQL directo, releer por el facade, y exigir que **no** vuelva como registro válido. |
| **Riesgo** | **Bajo en el cómputo, alto en la política.** Verificar es barato; decidir qué hacer ante desajuste es una decisión de producto —¿se bloquea la lectura? ¿se devuelve marcado?— y no puede tomarla el parche. |
| **Árboles afectados** | Postgres existe en los dos; **SQLite no tiene la columna en ninguno**, así que en SQLite el arreglo depende de PC-006. |

## PC-008 · `foreign_keys=ON` sin una sola clave foránea

| | |
|---|---|
| **Archivo** | `runtime/core/event_log_sqlite.py:22-23` (el PRAGMA y su docstring) · todo el DDL de `sqlite_store.py` |
| **Defecto** | El PRAGMA se activa en cada conexión y se documenta como *"integridad referencial"*. **La base viva tiene 0 claves foráneas.** El PRAGMA no hace nada. Cuatro relaciones existen solo por convención de nombre. |
| **Prueba** | `PRAGMA foreign_key_list(t)` vacío para las 17 tablas — ya verificado sobre la base viva. |
| **Riesgo** | **Alto si se añaden las FK a una base con datos**: 11.068 memorias y 4.149 decisiones de promoción tendrían que satisfacerlas retroactivamente, y nadie ha comprobado que lo hagan. |
| **Árboles afectados** | los 2 |
| **Acción mínima sin riesgo** | Corregir el **docstring**, que hoy promete algo que no ocurre. |

## PC-009 · `events` sin índice

| | |
|---|---|
| **Archivo** | DDL de `events`, `runtime/core/event_log_sqlite.py:56,73` |
| **Defecto** | 33.246 filas, ningún índice. `list_events` filtra por `event_type IN (…)` y por `json_extract(payload,'$.run_id')` → **recorrido completo con parseo de JSON por fila**, degradando linealmente. |
| **Prueba** | `EXPLAIN QUERY PLAN` sobre la consulta real: hoy `SCAN events`. |
| **Riesgo** | **Bajo.** Crear índices no cambia semántica. Pero un índice de expresión sobre `json_extract` requiere SQLite ≥ 3.9 y encarece la escritura, que es el camino caliente del organismo. Hay que medir antes. |
| **Árboles afectados** | los 2 |

---

## PC-010 · Marcado retroactivo de las 11.068 memorias sin `no_interference_computed`

| | |
|---|---|
| **Defecto** | El arreglo B24 es **hacia delante**. Las 11.068 filas de la base viva tienen `no_interference = 1` y **cero** llevan el marcador. Son exactamente las afirmaciones indistinguibles que B24 vino a impedir. |
| **Prueba** | Ya medido: `SELECT COUNT(*) … WHERE metadata LIKE '%no_interference_computed%'` ⇒ **0 de 11.068**. |
| **Riesgo** | **Es una escritura sobre la base viva.** No se hace sin decisión explícita y sin copia previa. |
| **Alternativa sin tocar datos** | Declarar la base entera como **pre-B24** en su procedencia, en un fichero junto a ella. Más barato y suficiente si la base no se va a usar como evidencia. |

---

## Principio transversal que sale de todo esto

`no_interference_computed=False` no es un apaño puntual: es el estándar. Lo que viaja no
debe ser el dato solo, sino

$$\text{dato} + \text{evidencia} + \text{estado epistemológico}$$

Aplicable a: métricas no validadas para constructo · inferencias causales parciales ·
hashes no verificados (PC-007) · estados provenientes de fallback (PC-005) · provenance
incompleta (PC-006) · resultados de simulación · capacidades solo declaradas · resultados
en modo `shadow`.

Es lo que impide que el organismo convierta *algo observado* en *algo demostrado* por
pérdida de procedencia.
