# Análisis profundo del código — Índice maestro

> ## ⚠ Revisión 2 en curso — 2026-09-16
>
> Todo lo que sigue es la **revisión 1**, y su procedencia declarada no coincide con el
> árbol donde vive: se escribió el **2026-06-10** contra **`rnfe.v15`**
> (`/home/wis/dev/rnfe.v15`) en la rama `work/external-reasoner-latency-checkpoint`, que
> **no existe en este checkout**. Se commiteó aquí el 2026-09-02 (`28a5df6`).
>
> | árbol | ficheros `.py` | líneas |
> |---|---:|---:|
> | `rnfe.v15` (lo auditado) | 587 | 106.341 |
> | este repo (`genesis/v2-foundation`) | **858** | **166.758** |
>
> **+271 ficheros y +60.417 líneas nunca auditados.** Además, varias referencias
> `file:line` de la rev.1 ya eran inexactas al escribirse.
>
> **Regla de la rev.2:** ninguna afirmación de la rev.1 se hereda. Cada una se reverifica
> contra HEAD y recibe veredicto `CONFIRMADO` / `DESFASADO` / `CORREGIDO` / `REFUTADO`, o
> se marca `NUEVO` si no existía.
>
> | # | Partición | Estado rev.2 |
> |---|---|---|
> | 01 | `contracts/` | ✅ reescrito contra HEAD `433beca` |
> | 02 | `runtime/storage/` | ✅ reescrito contra HEAD `433beca` |
> | 03-17 | resto | ⬜ pendiente |

> **Mandato:** análisis línea por línea de **todo** el código del repositorio (incluido el
> Mamba vendoreado de terceros, `archive/` legacy y `tests/`).
> **Fuente de verdad: el CÓDIGO.** Los `.md` históricos (PHASE*, EXPERIMENT*, HARDENING_ROADMAP,
> GRID_5X5_*, etc.) están **desfasados** y se tratan como no confiables; se anotan las
> contradicciones doc↔código como hallazgos.

Fecha de inicio: 2026-06-10 · Rama: `work/external-reasoner-latency-checkpoint`

---

## 1. Naturaleza del proyecto

`rnfe.v15` es la base de código de investigación de una **arquitectura cognitiva tipo "organismo
digital" (AEON)**. El sistema modela un agente autónomo con:

- **Homeostasis termodinámica** (temperatura, potencia, entropía → modos del sistema).
- **Razonamiento multi-familia** con un *meta-scheduler* y un **razonador externo** (LLM) opcional.
- **Control multi-escala de recursos (MSRC)** que decide subir/bajar de "escala" según presión de VRAM, riesgo, etc.
- **Gobernanza del organismo**: constitución, corte (court), riesgo, linaje, viabilidad, auto-modificación con rollback.
- **Capa "reality"**: estado de creencia, continuidad, colapso, certificación de episodios.
- **Mundos/escenarios** (grid térmico) para correr episodios.
- **Persistencia** dual SQLite/Postgres con un *facade* unificado.

## 2. Mapa: código vivo vs. shims vs. terceros

### Código original VIVO (lo que escribió el proyecto)
| Paquete | LOC aprox | Rol |
|---|---|---|
| `runtime/` | ~33.7K | Núcleo del organismo (ver desglose abajo) |
| `engines/hnet/` | ~2.5K | Modelo H-Net propio |
| `scripts/` | ~6.9K | Campañas de benchmark / inspección |
| `exocortex/` | ~0.7K | Canales CLI + herramientas + adaptadores |
| `lab/` | ~0.5K | Validación (fase0_cert, validate_core_existence) |
| `contracts/` | ~0.2K + 17 JSON | Contratos formales (tipos + JSON schemas) |
| `tests/` | ~25.8K | Suite de tests |

Desglose `runtime/`:
`organism/` (4.5K) · `reality/` (4.6K) · `world/` (3.8K) · `core/` (2.4K) · `storage/` (1.5K, **el más central, 25 importadores**) ·
`evolution/` (1.5K) · `certification/` (1.3K) · `control/` (msrc `scale_policy_engine` 1.2K + homeostasis) ·
`reasoning/` (scheduler_meta/policy 936, families/ext_open_thinker 534) ·
menores: `lotf`, `smg`, `telemetry`, `symbolic`, `agents`, `memory`, `utils`.

### Terceros vendoreados (NO escrito por el proyecto)
- `engines/mamba_vendor/` (~9.5K) — Mamba SSM con kernels Triton.

### Shims / aliases legacy (reexportan a `runtime.*`, **sin lógica propia**)
- Directorios raíz: `cognition/`, `core/`, `episteme/`, `evolution/`, `homeostasis/`,
  `persistence/`, `training/`, `utils/`, `agents/`, `hnet/`, `mamba_ssm/`.
- **Todo `src/`** (`src.aeon_fenix.*`, `src.cognition.*`, etc.).
- Entradas raíz `aeon_main_loop.py`, `fase0_cert.py`, `generate.py` → reexportan a `exocortex`/`lab`.

### Legacy archivado
- `archive/` (~14.5K) — código histórico.

## 3. Metodología

1. Recorrido **bottom-up por capas de dependencia**: contratos → storage → core → world →
   reality → organism → reasoning → control → evolution/certification → resto runtime →
   engines (hnet, mamba) → scripts → exocortex/lab → tests → archive.
2. Por cada módulo: lectura íntegra, anotación de hallazgos con referencia `archivo:línea`,
   clasificados en **[BUG]**, **[RIESGO]**, **[MUERTO]** (código/imports muertos),
   **[DOC]** (contradicción con la documentación), **[DISEÑO]** (observación de diseño).
3. Un documento por módulo (`NN_<modulo>.md`). Síntesis cruzada al final.

## 4. Progreso

| # | Módulo | Estado | Doc |
|---|---|---|---|
| 01 | `contracts/` | ✅ hecho | [01_contracts.md](01_contracts.md) |
| 02 | `runtime/storage/` | ✅ hecho | [02_storage.md](02_storage.md) |
| 03 | `runtime/core/` | ✅ hecho | [03_core.md](03_core.md) |
| 04 | `runtime/world/` | ✅ hecho | [04_world.md](04_world.md) |
| 05 | `runtime/reality/` | ✅ hecho | [05_reality.md](05_reality.md) |
| 06 | `runtime/organism/` | ✅ hecho | [06_organism.md](06_organism.md) |
| 07 | `runtime/reasoning/` | ✅ hecho | [07_reasoning.md](07_reasoning.md) |
| 08 | `runtime/control/` (MSRC + homeostasis) | ✅ hecho | [08_control.md](08_control.md) |
| 09 | `runtime/evolution/` + `certification/` | ✅ hecho | [09_evolution_certification.md](09_evolution_certification.md) |
| 10 | `runtime/` resto (lotf, smg, telemetry, symbolic, agents, memory, utils) | ✅ hecho | [10_runtime_rest.md](10_runtime_rest.md) |
| 11 | `engines/hnet/` | ✅ hecho | [11_engines_hnet.md](11_engines_hnet.md) |
| 12 | `engines/mamba_vendor/` | ✅ hecho | [12_engines_mamba_vendor.md](12_engines_mamba_vendor.md) |
| 13 | `scripts/` | ✅ hecho | [13_scripts.md](13_scripts.md) |
| 14 | `exocortex/` + `lab/` | ✅ hecho | [14_exocortex_lab.md](14_exocortex_lab.md) |
| 15 | `tests/` | ✅ hecho | [15_tests.md](15_tests.md) |
| 16 | `archive/` | ✅ hecho | [16_archive.md](16_archive.md) |
| 17 | Síntesis cruzada | ✅ hecho | [17_SYNTHESIS.md](17_SYNTHESIS.md) |
| 19 | `runtime/conjunction/` + gate en `LifeKernel` | ✅ hecho | [19_operational_conjunction.md](19_operational_conjunction.md) |
