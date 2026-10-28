# RNFE v16

RNFE es un organismo cibernético digital autoevolutivo orientado a inteligencia general adaptable,
con cierre triádico, continuidad identitaria, viabilidad dinámica, memoria viva multiescala, ecología
de razón gobernada y herencia certificada (definición normativa: ver canon).

## Puntos de entrada de la documentación

| Documento | Rol |
|---|---|
| [`canon/normative/CANON_RNFE_v3_2_rc1.md`](canon/normative/CANON_RNFE_v3_2_rc1.md) | **SSOT** — canon normativo vigente |
| [`docs/analysis/00_INDEX.md`](docs/analysis/00_INDEX.md) | Auditoría línea-por-línea del código (estado real) |
| [`docs/strategy/2026-06-17_self_sustaining_cognitive_gain.md`](docs/strategy/2026-06-17_self_sustaining_cognitive_gain.md) | Roadmap estratégico actual |
| [`docs/history/`](docs/history/) | Snapshots históricos desfasados (fases/experimentos cerrados) |
| [`governance/adr/`](governance/adr/) | Decisiones de arquitectura |
| [`archive/README.md`](archive/README.md) | Política de cuarentena del código legacy |

## Estructura del código

- `runtime/` — sistema vivo (world, reality, organism, reasoning, control/msrc, storage, certification, memory, telemetry).
- `contracts/` — contratos de datos (JSON Schema) y tipos canónicos (`contracts/types/aeon_types.py`).
- `engines/` — modelos: `engines/hnet/` (propio) y `engines/mamba_vendor/` (vendorizado). Los paquetes raíz
  `hnet/` y `mamba_ssm/` son puentes de import hacia estos engines — no borrar.
- `scripts/` — campañas de benchmark y estudios (`run_*.py`, `benchmark_*.py`, `*_lib.py`).
- `tests/` — suite pytest (~145 archivos), organizada por subsistema.
- `canon/`, `governance/`, `docs/` — normativa, decisiones y análisis.
- `archive/` — cuarentena histórica (no se importa desde código vivo).
- `data/`, `rnfe_artifacts/` — salidas de experimentos (no versionadas en su mayoría).

## Cómo correr

```bash
# Entorno (Python 3.12)
python3 -m venv .venv
.venv/bin/pip install -r requirements.reasoning-core-causal.txt pytest 'psycopg[binary]'

# Tests
.venv/bin/python -m pytest tests/ -q
# Markers condicionales: requires_torch, requires_postgres, requires_cuda, requires_extended_bench

# Benchmarks (ejemplos)
.venv/bin/python scripts/benchmark_cognitive_gain_v2.py
.venv/bin/python scripts/run_adaptive_v2_intelligence_campaign.py

# CLI histórica (stack legacy en cuarentena)
.venv/bin/python aeon_main_loop.py
```
