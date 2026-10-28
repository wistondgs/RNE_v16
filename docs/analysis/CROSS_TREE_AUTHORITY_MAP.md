# Mapa de divergencia y autoridad — `genesis-v2` ↔ `v16` ↔ `v15`

**2026-09-16.** Identidad estructural, no semántica profunda. Producido para responder una
pregunta previa a cualquier auditoría o parche: **¿cuál árbol gobierna al organismo?**

> **Conclusión corta: no hay un único árbol autoridad.** Hay **dos autoridades vivas sobre
> dominios disjuntos**, nacidas de una bifurcación el **2026-07-10**, y **una zona de
> colisión sin resolver que es exactamente `runtime/neural`.**

---

## 0. Método y sus límites

| Fuente de evidencia | Usada para |
|---|---|
| Ancestría Git (`merge-base`, `--is-ancestor`) | topología y procedencia |
| SHA-256 por fichero | identidad / divergencia / exclusividad |
| Grafo de imports por AST | importadores vivos (excluye `tests/` y `archive/`) |
| Referencias desde `tests/` | cobertura |
| Artefactos, ledger, entorno ejecutable | capacidad de correr |
| Estado del árbol de trabajo vs HEAD | **reproducibilidad** |

**Explícitamente NO usado para decidir autoridad:** tamaño en disco, fecha, o presencia de
`.venv`.

**Tres límites que hay que tener presentes al leer:**

1. La comparación por fichero leyó el **sistema de ficheros**, no los commits. Para `v16`
   eso significa que comparé un árbol de trabajo con **256 cambios sin commitear** (ver §5).
2. El grafo de imports es estático (AST). **Comprobé que no hay importación dinámica** de
   `runtime.neural` en ninguno de los dos árboles (`importlib`, `import_module`, o el
   módulo citado por cadena): 0 coincidencias. La clasificación se sostiene.
3. No hay entorno ejecutable en `genesis-v2`, así que nada de lo que digo sobre su
   comportamiento en ejecución está medido; es lectura de código y de grafo.

---

## 1. Topología Git — resuelta

```
                          v15 HEAD  36cb2a29  2026-07-03  feat/bucle-a-activation
                              │
                              │  29 commits
                              ▼
                     ★ 34cd3a3  2026-07-10  BIFURCACIÓN
                     │   "docs(canon): A14 — estatus de promoción ratificado"
          ┌──────────┴───────────┐
          │                      │
  +44 commits              +121 commits
  +20.125 / −310           +53.327 / −667
          │                      │
          ▼                      ▼
   v16  6630258            genesis-v2  433beca
   2026-07-30              2026-09-07
   feat/reasoning-         genesis/v2-foundation
   family-quality-deep
```

Verificado: `433beca` **no** es ancestro de `6630258` ni al revés. **Son hermanos.**
`36cb2a29` (v15) es ancestro de ambos. Los tres comparten primer commit (2026-04-16) y
remoto (`github.com/Necktral/RNE_v16.git`).

**Corrijo una afirmación mía anterior.** Dije *"435 ficheros, +18.817 −51.662, neto
−32.845 líneas"*. Ese número era el `diff` **entre los dos HEAD**, y en esa dirección las
adiciones de `genesis-v2` se cuentan como borrados. La relación real, desde la
bifurcación, es **aditiva en ambas ramas**: ninguna borró el trabajo de la otra porque
nunca lo tuvo.

### Qué construyó cada rama desde la bifurcación

| genesis-v2 (121 commits) | ficheros | v16 (44 commits) | ficheros |
|---|---:|---|---:|
| `lab/genesis` | 91 | `runtime/symbolic` | 33 |
| `tests/genesis` | 69 | **`runtime/neural`** | 15 |
| **`runtime/neural`** | 24 | `tests/symbolic` | 12 |
| `docs/experimental` | 22 | `scripts/experiments` | 11 |
| `runtime/organism` | 16 | `runtime/world` | 9 |
| `runtime/storage` | 9 | `runtime/reasoning` | 7 |

**Las dos ramas tocaron `runtime/neural`.** Es la única superposición sustancial, y es la
zona que importa.

---

## 2. Matriz de identidad por paquete

| paquete | g-v2 | v16 | v15 | ident-3 | ident g/v | diverg. | excl. g-v2 | excl. v16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `contracts` | 3f · 235L | 3f · 235L | 3f · 235L | **3** | 0 | 0 | 0 | 0 |
| `runtime/storage` | 13f · 5.382L | 12f · 4.898L | 12f · 4.894L | 4 | 1 | **7** | 1 | 0 |
| `runtime/neural` | 24f · 6.169L | 15f · 3.226L | — | **0** | 0 | 7 | **17** | **8** |
| `lab/genesis` | 91f · 19.861L | — | — | 0 | 0 | 0 | **91** | 0 |
| `runtime/control` | 21f · 4.999L | 21f · 4.563L | 20f · 4.306L | 14 | 1 | 6 | 0 | 0 |
| `runtime/world` | 17f · 5.730L | 19f · 6.353L | 15f · 4.212L | 8 | 1 | 8 | 0 | 2 |
| `runtime/symbolic` | 9f · 561L | **41f · 5.486L** | 9f · 561L | 8 | 0 | 1 | 0 | **32** |

Lecturas inmediatas:

- **`contracts/` es idéntico en los tres árboles.** Mis 10 hallazgos de la partición 01
  valen para los tres — y cualquier parche habría que aplicarlo tres veces.
- **`lab/genesis` existe solo en `genesis-v2`.** 19.861 líneas sin equivalente.
- **`runtime/symbolic` es el recíproco**: 32 ficheros y ~4.900 líneas que solo existen en
  `v16`. `genesis-v2` conserva la versión pre-bifurcación de 561 líneas.
- **`runtime/storage`**: 7 de 13 divergentes, y las versiones de `v16` son **idénticas a
  las de v15** → `v16` **no tocó storage desde la bifurcación**; todo el trabajo de
  storage es de `genesis-v2`.

---

## 3. `runtime/neural` — dos subsistemas con el mismo nombre

**Cero ficheros idénticos.** No existía en v15: ambas ramas lo construyeron desde cero,
en paralelo, después del 2026-07-10.

| genesis-v2 — arquitectura de **órganos** | LOC | v16 — pipeline de **entrenamiento N4** | LOC |
|---|---:|---|---:|
| `organs/n4_causal.py` | 892 | `training/n4_ranking.py` | 1.362 |
| `runtime.py` | 721 | `hypothesis_generator.py` | 306 |
| `integration/coordinator.py` | 635 | `training/n4_campaign.py` | 285 |
| `integration/adapters.py` | 554 | `training/candidate_labeler.py` | 228 |
| `integration/contracts.py` | 546 | `organs/n4_causal.py` | 223 |
| `organs/n5_ingest.py` | 410 | `contracts.py` | 173 |
| `contracts.py` | 426 | `n4_hypothesis_provider.py` | 162 |
| `organs/n1_router.py` | 311 | `training/evidence_collector.py` | 140 |
| `organs/{n2,n3,n6}`, `registry`, `resources`, … | ~700 | `calibration.py`, `mci_graph_builder.py`, … | ~280 |

Los 7 ficheros homónimos divergen fuerte: `runtime.py` **721 vs 74**, `contracts.py`
**426 vs 173**, `organs/n4_causal.py` **892 vs 223**.

### Clasificación por cableado real

| | genesis-v2 | v16 |
|---|---|---|
| LOC total | 6.169 | 3.226 |
| **LOC con importador vivo** | **1.613 (26 %)** | **2.350 (73 %)** |
| `ACTIVE` | 5 ficheros | **8 ficheros** |
| `SHADOW` (solo tests) | 5 | 2 |
| `INTERNO` (solo dentro de `neural`) | 4 | 1 |
| **`UNKNOWN` (cero importadores, cero tests)** | **10** | 4 |
| flags `RNFE_NEURAL_*` | **11** | 0 |

En `genesis-v2` están en `UNKNOWN` —cero importadores y cero tests— **el router N1 (311),
N2 (106), N3 (92), N6 (122), el coordinator (635), census, observability, benchmark,
`_math` y `n1_dataset`**. `n4_causal` (892) y `organs/__init__` son `SHADOW`.

**Esto responde empíricamente a «la red neuronal está apagada».** En `genesis-v2` no está
apagada: **el 74 % nunca se conectó**. Hay 11 variables de entorno para configurar órganos
que ningún código vivo importa. Es «la pieza está y el cable no», medido y a escala de
paquete.

En `v16` ocurre lo contrario: menos código y **73 % cableado**, con tests, y es la línea
de trabajo activa de esa rama (sus 5 últimos commits son todos `n4: …`).

---

## 4. El ledger vivo: de qué es evidencia

`RNE_v16/aeon_event_log.db`, 665.362.432 bytes, `sha256 ecdfde43c24e…`. Inspección
**estrictamente de solo lectura**, huella idéntica antes y después, sin ficheros
colaterales. Detalle completo en [`LIVE_DB_FORENSICS.md`](LIVE_DB_FORENSICS.md).

| | |
|---|---|
| ventana temporal | **2026-07-05T02:33 → 2026-07-06T19:45** (≈41 h) |
| episodios | **4.149** (cifra repetida en 9 tablas y 7 tipos de evento) |
| eventos | 33.246, de solo **11 tipos distintos** |
| mtime | 2026-07-06 |

**El ledger es anterior a la bifurcación (2026-07-10).** Por tanto **no es evidencia sobre
ninguna de las dos ramas**: es evidencia sobre el tronco común. Tenerlo en `v16` no le da
autoridad a `v16`; le tocó por estar en ese directorio.

Y no es historia operacional acumulada: es **una campaña de dos días**.

---

## 5. Reproducibilidad — el criterio que decide más que ningún otro

| | genesis-v2 | v16 |
|---|---|---|
| ficheros sin commitear | **5** (3 son mis ediciones de doc) | **256** |
| — modificados | 3 | 77 |
| — **borrados** | 0 | **102** |
| — sin seguimiento | 2 (docs del usuario, 6 sep) | 77 |
| `.py` de `runtime/contracts/lab/engines` sin commitear | 0 | **121** |
| árbol de trabajo ≡ HEAD | **sí** | **no** |

`v16` está **a mitad de una reestructuración sin commitear**: 102 borrados y 77 sin
seguimiento concentrados en `runtime/symbolic` (32 borrados) y `runtime/neural` (8
borrados, 9 en sus tests). Su último commit es del 2026-07-30 y el árbol se tocó por
última vez ese mismo día.

**Consecuencia dura: el estado en disco de `v16` no existe en ningún commit.** No se puede
clonar, ni checkoutear, ni reproducir en otra máquina. Si ese disco se pierde, se pierde.

`genesis-v2` sí es reproducible desde git.

---

## 6. Veredicto de autoridad

**No hay un tronco único.** Hay dos autoridades sobre dominios disjuntos, y una disputada.

| Dominio | Autoridad | Por qué (evidencia, no tamaño ni fecha) |
|---|---|---|
| `contracts/` | **empate — idéntico en los 3** | sha256 iguales |
| `runtime/storage`, capa epistémica, contratos activos | **genesis-v2** | único con `contract_validation.py`; `v16` tiene la versión de v15 y **cero enforcement**; todo el trabajo B17/B24/B46 es exclusivo suyo |
| `lab/genesis` | **genesis-v2** | exclusivo, 19.861 L |
| `runtime/symbolic` | **v16** | exclusivo, 32 ficheros, ~4.900 L |
| **`runtime/neural`** | **DISPUTADO — sin resolver** | dos implementaciones disjuntas; v16 tiene el cableado (73 %) y el entorno; genesis-v2 tiene la arquitectura (26 %) y la continuidad del desarrollo |
| Capacidad de ejecutar | **v16** | `.venv` con torch; `genesis-v2` no tiene entorno |
| Reproducibilidad | **genesis-v2** | árbol ≡ HEAD; `v16` tiene 121 `.py` sin commitear |
| Evidencia experimental | **ninguna de las dos** | el ledger y los 47 GB son **pre-bifurcación** |

### Lo que esto implica para el objetivo declarado

Pediste reparar «N1 y la red neuronal que está apagada». Con el mapa delante:

- **N1 solo existe en `genesis-v2`** (`organs/n1_router.py`, 311 L) y está en `UNKNOWN`:
  cero importadores vivos, cero tests. No hay nada que «reparar» en el sentido de arreglar
  algo roto — **hay que conectarlo o descartarlo.**
- **Lo que sí corre hoy es el pipeline N4 de `v16`**, que `genesis-v2` no tiene.
- Las dos cosas no se pueden hacer a la vez sin decidir antes qué pasa con
  `runtime/neural`.

---

## 7. Lo que sigue `UNKNOWN` y hay que resolver

1. **¿Fue deliberada la bifurcación o es un accidente de directorios?** No hay ADR que la
   explique. `governance/adr/` recibió 10 ficheros en `genesis-v2` desde la bifurcación;
   ninguno menciona a `v16`.
2. **¿Qué se estaba reestructurando en `v16` el 30 de julio?** 102 borrados sin commitear
   sin mensaje que los explique.
3. **¿Los 47 GB de `rnfe_artifacts` corresponden a la campaña de julio o hay más?** No
   inventariados.
4. **¿Alguna de las dos ramas está en el remoto?** No comprobado (sin red).

---

## 8. Orden de lectura recalculado

El orden secuencial por capas queda **anulado**. Lo que decide ahora es la disputa.

| # | Objetivo | Por qué primero |
|---|---|---|
| 1 | **Resolver `runtime/neural`** — comparar semánticamente las dos implementaciones (9.395 L entre ambas) | es la única colisión real y es tu objetivo declarado |
| 2 | `lab/genesis` (19.861 L, genesis-v2) | exclusivo, sin auditoría previa, y es Génesis |
| 3 | `runtime/symbolic` (5.486 L, v16) | exclusivo, sin auditoría previa, invisible desde genesis-v2 |
| 4 | Decidir el destino de `v16`: commitear la reestructuración, o descartarla | mientras no se haga, `v16` no es un objeto estable que auditar |
| 5 | Resto del runtime, sobre el árbol que quede como tronco | |

**Antes del punto 1 hace falta una decisión tuya**, porque la comparación semántica de las
dos ramas de `runtime/neural` cuesta lo mismo que auditar 10.000 líneas nuevas y solo vale
la pena si el resultado va a usarse para unificar.
