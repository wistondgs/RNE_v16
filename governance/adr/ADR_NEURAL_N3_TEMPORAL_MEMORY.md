---
title: ADR_NEURAL_N3_TEMPORAL_MEMORY
status: experimental
version: 1.0.0
date: 2026-07-10
owner: Codex
---

# ADR — N3 Memoria temporal

## Decisión

Puerto SSM version-neutral con estado por organismo+escenario+modelo. Sólo propone
prioridad, importancia, riesgo y continuidad; MFM sigue siendo autoridad y fallback.

## Hipótesis y coste

Debe superar MFM, Markov/lineal y GRU en recuperación retenida sin contaminación
cross-scenario. Perfil objetivo menor a 3 GiB de VRAM.

## Dependencias y rollback

P-CADENA/P21 y procedencia Mamba2 certificada. Hasta entonces opera sólo el SSM de
referencia en laboratorio. Unload borra estado volátil y MFM mantiene continuidad.
