# 01 — `contracts/` (contratos formales)

> **Revisión 2 — 2026-09-16, contra HEAD `433beca`** (rama `genesis/v2-foundation`).
> Lectura línea por línea de las 235 líneas de Python y los 17 esquemas.
> La revisión 1 (commit `28a5df6`, 2026-09-02) **no se hereda: se audita**. Cada
> afirmación suya lleva veredicto `CONFIRMADO` / `DESFASADO` / `CORREGIDO` / `REFUTADO`.

```
contracts/
├── __init__.py                    2 líneas — solo docstring
├── types/
│   ├── __init__.py                4 líneas — from .aeon_types import *
│   └── aeon_types.py            229 líneas — dataclasses del "organismo"
└── *.schema.json                 17 esquemas, 475 líneas
```

---

## 0. El hecho estructural de la capa

**`contracts/` contiene dos sistemas de contratos disjuntos.** Ninguno de los 17 esquemas
JSON corresponde a ninguna de las 9 dataclasses. No comparten nombres, campos ni consumidores.

| | dataclasses (`aeon_types.py`) | esquemas (`*.schema.json`) |
|---|---|---|
| Qué modelan | estado termodinámico/cognitivo del organismo | registros persistidos |
| Quién los consume | 6 ficheros, **todos de homeostasis** | `runtime/storage/contract_validation.py` |
| Cuántos están vivos | 9 de 9 definidos, ~4 con llamadores | **5 de 17** aplicados on-write |

Consecuencia operativa: **un cambio en `aeon_types.py` solo puede romper
`runtime/control/homeostasis/`.** El nombre del paquete promete un contrato central que no
existe; los contratos centrales reales son los 5 esquemas activos de CANON §13.

---

## 1. `types/aeon_types.py` (229 líneas)

Todas las dataclasses son `@dataclass(frozen=True, slots=True)` — inmutables y compactas.
Buena decisión: obliga a `dataclasses.replace` para cambiar estado, lo que deja el cambio
visible en el sitio que lo hace.

### Mapa de líneas (reverificado contra HEAD)

| Símbolo | Rev.1 decía | **Real hoy** | |
|---|---:|---:|---|
| `ComponentID` | 20 | **20** | ✓ |
| `SystemMode` | 22 | **22** | ✓ |
| `ComponentStatus` | 31 | **31** | ✓ |
| `Vector3D` | 40 | **41** | |
| `ThermodynamicState` | 53 | **54** | |
| `CognitiveState` | 71 | **72** | |
| `HealthStatus` | 87 | **88** | |
| `ActionLog` | 133 | **136** | |
| `SystemSnapshot` | 153 | **156** | |
| `OntologySpaces` | 176 | **179** | |
| `HomeostasisThresholds` | 191 | **194** | |
| `NeuralSignature` | 212 | **215** | |

La deriva desde `ActionLog` tiene causa identificada: la unificación de `HealthStatus`
añadió `thermal_gradient` y `cognitive_load` (hoy l.102-103). Aviso metodológico: parte de
la deriva es **imprecisión de origen**, no movimiento del código — ver §4.

### Hallazgos

#### [ALTA · NUEVO] `HealthStatus` guarda tres cantidades dos veces, una con tipo distinto

`HealthStatus` (l.88) **contiene** un `ThermodynamicState` (l.95) y un `CognitiveState`
(l.98), y además repite planos campos que ya viven dentro:

| Campo | Plano | Anidado | |
|---|---|---|---|
| `memory_load` | l.89 `float` | `cognitive_state.memory_load` l.74 `float` | duplicado |
| `entropy_rate` | l.96 `float` | `thermal_state.entropy_rate` l.58 `float` | duplicado |
| `thermal_gradient` | l.102 `float` | `thermal_state.thermal_gradient` l.60 `Vector3D` | **tipo distinto** |
| `stability_index` | l.99 `float` almacenado | `cognitive_state.stability_index` l.80 `@property` | uno derivado |
| `temperature` | l.93 `float` | `thermal_state.temperature_K` l.56 | **otra unidad** |

No hay invariante que los sincronice. Y `criticality_score()` (l.116-133) **lee de ambos
sitios en la misma fórmula**: plano en l.118, l.121, l.125; anidado en l.124, l.126, l.129.
El campo plano `self.stability_index` (l.99) **no lo usa nadie** y aun así se serializa.

Origen: es el precio de la unificación A4, que aplanó en el canónico los kwargs del
governor para eliminar un `AttributeError` latente.
`tests/regression/test_healthstatus_unification.py:25-27` **exige** que `thermal_gradient`
y `cognitive_load` existan planos — el test que protege la unificación congela la colisión.

Arreglo mínimo sin romper el test: declarar en el docstring la fuente de verdad de cada
cantidad duplicada. Arreglo completo: `@property` delegantes, lo que rompe el
`dataclasses.replace` de la l.38 del test y exige migrar el governor.

#### [MEDIA · NUEVO] `contracts.types` exporta numpy como API pública

`types/__init__.py:3` hace `import *` y `aeon_types.py` **no define `__all__`**. Medido:

```
símbolos públicos en contracts.types : 39
son contratos de verdad              : 13
fugados                              : 26
```

`contracts.types.np` **es numpy 2.2.6**; `contracts.types.defaultdict` es
`collections.defaultdict`.

Esto **bloquea la limpieza de imports muertos**: `thermodynamic_governor.py:10` y
`energy_sensors.py:10` hacen `import *` y podrían estar usando símbolos fugados sin
importarlos. Orden seguro: (1) `__all__`, (2) comprobar qué se rompe, (3) imports
nominales en el runtime, (4) recién entonces borrar los muertos.

#### [MEDIA · CONFIRMADO+] `NeuralSignature.verify()` puede mentir en silencio

`l.220-229`. Es la función cuyo trabajo es detectar que una red **no** es la misma red.
La rev.1 señaló 2 fragilidades; hay 6.

Silenciosas (las graves):
1. **Empareja por orden de inserción** (l.221-225): `zip` sobre `.values()` de dos dicts.
   Mismas capas en otro orden → compara capa 1 contra capa 3 y devuelve un número plausible
   y equivocado, sin excepción.
2. **`zip` trunca y el divisor no** (l.226): con `reference` más corto, `layer_match` sale
   infravalorado sin aviso, y `a.verify(b) != b.verify(a)`.

Ruidosas: 3. `min(a/b, b/a)` → `ZeroDivisionError` con firma 0.0. 4. `len()` → división por
cero con dict vacío.

De rango: 5. `activation_profile` se declara `Tuple[float,float,float]` (l.218) y solo se
usa `[0]` (l.228). 6. El resultado puede salir **negativo** o **>1** (`activation_match`
sin cota inferior, `temporal_coherence` sin cota superior).

**Cero llamadores vivos.** Está esperando a ser cableada, y el día que lo sea parecerá que
funciona. La decisión barata es arreglarla o borrarla.

#### [BAJA · NUEVO] `criticality_score()` mezcla unidades y satura

`l.116-133`. Dos representaciones de temperatura en la misma fórmula: `self.temperature`
sin normalizar (l.121) y `thermal_state.temperature_K / 373.15` normalizada (l.124). Si
`temperature` viene en grados, domina el `max` de la l.117-122 y `memory_load`/`cpu`/`gpu`
dejan de influir. El tipo no declara la unidad. `entropy_rate` (l.96) tampoco tiene cota.
`min(1.0, ...)` (l.133) satura: por encima de 1 el score deja de discriminar, justo en la
zona crítica. Cero llamadores vivos.

#### [BAJA · CONFIRMADO] `Vector3D.normalized()` divide por cero

`l.47-49`, sin guarda. El default de `ThermodynamicState.thermal_gradient` (l.60) es
exactamente `Vector3D(0,0,0)`. Idéntico a la rev.1: **14 días sin arreglar.** Cero
llamadores vivos.

#### [BAJA · CONFIRMADO] `ThermodynamicState.to_dict()` es lossy

`l.62-69`: 5 de 7 campos. Faltan `heat_dissipation` (l.59) y `thermal_gradient` (l.60).
La pérdida se propaga: `HealthStatus.to_dict()` (l.108-115) parte de `asdict(self)` —que
lo incluiría todo— y en la l.111 **sobrescribe** con la versión recortada. El filtro
`if not k.startswith('_')` (l.110) es un no-op.

#### [BAJA · CONFIRMADO+] Código muerto

12 imports sin uso (l.2-17: `astuple`, `Union`, `Callable`, `ClassVar`, `TypeVar`,
`Generic`, `Protocol`, `runtime_checkable`, `auto`, `datetime`, `defaultdict`, `log`) y el
shim completo de `StrEnum` (l.8-12), que nunca se usa: `ComponentStatus` (l.31) es un
`Enum` plano, así que `ComponentStatus.OPTIMAL == "optimal"` es `False`.

Ampliación: **piezas completas sin un solo llamador vivo** —
`HomeostasisThresholds.adaptive_adjust` (l.201), `OntologySpaces` entera (l.179),
`SystemSnapshot.compress` (l.163), `NeuralSignature.verify` (l.220),
`HealthStatus.criticality_score` (l.116).

Sobre `adaptive_adjust`: `adjustment = 0.01*(stress_level-0.5)` (l.202) da como mucho
±0.005 contra rangos de clamp de ~0.25 → ~50 llamadas a estrés máximo para recorrer el
rango; y `learning_rate` se pasa sin tocar (l.209).

**No borrar hasta resolver el `__all__`.**

#### [BAJA · CONFIRMADO+] `OntologySpaces.total_dimensions()` no cuenta dimensiones

`l.185-191`: suma **magnitudes** de cuatro `Vector3D` y castea a `int`. La respuesta
correcta a "dimensiones totales" de cuatro `Vector3D` es 12, constante. `temporal_depth`
—el único campo que sí es un conteo— no participa. Clase entera sin llamadores.

### Alcance real (live vs. vestigial)

`aeon_types` se importa **solo** desde:

- `runtime/control/homeostasis/{life_monitor:12, thermodynamic_governor:10+31,
  energy_sensors:10, homeo_controller:12, shutdown_logic:8}.py`
- `runtime/legacy/homeo_controller.py:3` — **cuarentena**
- 3 tests de regresión

> **`DESFASADO`** — la rev.1 listaba `runtime/core/homeo_controller.py`. **Ese fichero no
> existe**: se movió a `runtime/legacy/`. La rev.1 tampoco lo incluía en su lista.

---

## 2. Los 17 esquemas JSON

| Schema | required clave | Activo | Observa |
|---|---|:-:|---|
| `episode` | episode_id, timestamp, context, result | ✅ | |
| `proposal` | proposal_id, origin, change, risk | ✅ | |
| `certificate` | 13 campos, incl. continuity/ioc/risk | ✅ | 3 rangos no aplicados |
| `rollback` | rollback_id, target, reason, timestamp | ✅ | conforma 1 de 4 writers |
| `telemetry_snapshot` | snapshot_id, timestamp, metrics | ✅ | |
| `artifact_index` | artifact_id, sha256, size, paths | ❌ | |
| `event` | event_type, payload, timestamp | ❌ | |
| `memory_record` | scale∈{micro,meso,macro}, no_interference | ❌ | enum no aplicado |
| `eml_candidate` | expr, depth, fit/stability/composite | ❌ | |
| `eml_run` | top_candidates → `$ref` | ❌ | `$ref` no resuelve |
| `msrc_scale_decision` | action.*, estimate.* | ❌ | 12 required anidados |
| `msrc_transition_event` | estimado vs real, deltas | ❌ | el mejor documentado |
| `reality_assessment` | closure_passed, collapse_detected | ❌ | |
| `reasoning_trace` | trace_id, step_index, family | ❌ | |
| `session_bridge` | session_id, episode_id, channel | ❌ | B23, capacidad reservada |
| `tool_request` / `tool_result` | request_id, tool/status | ❌ | B20, capacidad reservada |

### Hallazgos

#### [MEDIA · NUEVO] "Contrato" significa dos cosas distintas

Solo 5 de 17 se aplican on-write (`runtime/storage/contract_validation.py:47-50`,
`ACTIVE_CONTRACTS`). Los otros 12 son ficheros de esquema sin enforcement.

**Está declarado, no oculto**: el módulo dice en su docstring (l.1-26) qué no valida y que
es a propósito —"subesquemas anidados, `minimum`/`maximum`, `items`, `pattern`, `$ref`,
`additionalProperties: false`"— cita `CANON §13`
(`canon/normative/CANON_RNFE_v3_2_rc1.md:402-408`) y remite al backlog P7.

Consecuencias concretas:

1. **`certificate` declara 3 rangos que nadie aplica** (l.28-30, `minimum:0 maximum:1`). Es
   contrato activo y decide `promotion_candidate`. *Mitigado hoy*:
   `runtime/certification/certificate_builder.py:44-49` y `ioc_proxy.py:16` los acotan en
   el productor. Riesgo real bajo **mientras el productor sea uno**.
2. **`msrc_scale_decision` declara 12 `required` anidados inexigibles** (l.24, l.49-60):
   el validador es de raíz.
3. **El `$ref` de `eml_run` (l.23) no resuelve nunca**: ruta relativa, **0 de 17 esquemas
   declaran `$id`**, y el validador no implementa `$ref`.
4. **El contrato activo de `rollback` se cumple en 1 de 4 caminos**, según declara
   `contract_validation.py:60-79`, que nombra los 3 writers no conformes
   (`life.rollback` — `runtime/life/kernel.py:677`, `autoevolution.rollback`,
   `msrc.rollback`) y advierte de que mapearlos sin arreglarlos mataría al organismo en la
   ruta de rollback. Trabajo identificado como **B60**, con tripwire en
   `tests/storage/test_contract_validation.py`.

#### [BAJA · NUEVO] La convención de `description` existe y no se propagó

**14 de 17 esquemas no tienen `description` ninguna.** Los 3 que sí
(`msrc_transition_event`, `tool_request`, `tool_result`) son los que alguien tocó durante
una reparación, y son excelentes. Arreglo más barato posible para el punto anterior: una
línea de `description` en cada esquema no activo diciendo que no se valida on-write.

#### [DISEÑO · CONFIRMADO] `additionalProperties: true` en los 17

Contratos permisivos: un `continuity_score` mal escrito pasa como propiedad adicional
válida. (Y el validador tampoco implementa `additionalProperties: false`, así que ponerlo
no cambiaría nada hoy.)

#### [DISEÑO · CONFIRMADO] Enum `action_type` duplicado

Las dos listas de 7 acciones (`msrc_scale_decision` l.28-36 y `msrc_transition_event`
l.27-35) están duplicadas literalmente. Añadir una acción exige editar ambos esquemas y
`control/msrc/scale_policy_engine.py`.

#### [`CORREGIDO`] Dialectos mixtos de JSON Schema

La rev.1 afirmaba que `msrc_scale_decision` y `msrc_transition_event` usaban draft-07.
**Era cierto** (verificado con `git show 28a5df6:contracts/msrc_transition_event.schema.json`)
y **ya se arregló**: hoy los 17 usan draft 2020-12.

---

## 3. Lo que está bien construido

Se anota en positivo porque una auditoría que solo lista faltas no sirve para decidir.

- **`runtime/storage/contract_validation.py` es ejemplar.** Declara sus límites como
  decisión, no como olvido; cita el canon; nombra el backlog; y en l.60-79 pone una
  advertencia con nombre —"PELIGRO — NO completes `EVENT_CONTRACTS`"— que explica por qué
  el arreglo ingenuo mata al organismo en la ruta que más se necesita, protegida por un
  tripwire en tests. Es documentación que hace trabajo.
- **`msrc_transition_event.schema.json`** documenta por qué `real_*` puede ser `null`,
  **prohíbe** rellenarlo con un 0.0 inventado (l.50), y avisa de que estimado y real no
  comparten unidad (l.4). Nombra la doctrina y sus otros dos sitios: `unmeasured_vitals`
  (`control/homeostasis/life_monitor.py`) y `unverified_fields` (`life/contracts.py`).
- **`frozen=True, slots=True`** en las 9 dataclasses.
- **La unificación A4** resolvió un `AttributeError` latente real y dejó regresión.

El patrón: **donde alguien pasó a reparar, la calidad es alta y está anotada; donde no, el
código está sin tocar.** Los 3 esquemas con `description` son los 3 reparados.

---

## 4. Aviso metodológico sobre la revisión 1

Las referencias `file:line` de la rev.1 **ya eran inexactas el día que se escribieron**:

| Símbolo | Rev.1 decía | Real **en el commit de la rev.1** |
|---|---:|---:|
| `class ActionLog` | 133 | **134** |
| `class SystemSnapshot` | 153 | **154** |
| `class NeuralSignature` | 212 | **213** |

No es deriva del código: es imprecisión de origen.

Más importante: la rev.1 **auditó otro árbol**. Su cabecera declara `rnfe.v15`
(`/home/wis/dev/rnfe.v15`), rama `work/external-reasoner-latency-checkpoint` —inexistente
aquí—, fecha 2026-06-10. Medido: `rnfe.v15` tiene 587 ficheros `.py` / 106.341 líneas;
este repo tiene **858 / 166.758**. Hay **+60.417 líneas que no ha auditado nadie**.

Para esta partición eso **no la invalida**: `diff` entre los dos `aeon_types.py` da **0
líneas distintas**, así que los veredictos de arriba se sostienen. Pero no se puede asumir
la misma suerte en las 16 particiones restantes.

El ratio global —2.155 líneas de análisis para 166.758 de código— corresponde a una
**inspección**, no a una lectura. La rev.1 es un buen mapa y un mal inventario: se usa para
orientarse, no se cita.

---

## Resumen del módulo

- La capa es **sana en intención** y **más pequeña de lo que su nombre sugiere**: las
  dataclasses son el sistema de tipos de homeostasis, no el contrato central del sistema.
- Deuda accionable, en orden de reparación (el orden importa: 1 desbloquea 6):
  1. `__all__` en `aeon_types.py` — barato, reversible
  2. guarda de cero en `Vector3D.normalized` — 1 línea
  3. completar `ThermodynamicState.to_dict` — 2 líneas
  4. documentar la fuente de verdad de los campos duplicados de `HealthStatus`
  5. decidir `NeuralSignature`: arreglar o borrar
  6. limpieza de imports muertos — solo después de 1
- Decisión pendiente de producto: qué hacer con los 12 esquemas no activos.
