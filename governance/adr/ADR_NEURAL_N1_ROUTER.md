---
title: ADR_NEURAL_N1_ROUTER
status: experimental
version: 1.1.0
date: 2026-07-10
owner: Codex
---

# ADR — N1 Enrutador de familias

## Decisión

Usar un MLP compacto con catálogo versionado y hard masks para proponer familias
opcionales. Nunca altera backbone ni elude validadores. Sólo se entrena con pares
contrafactuales reales, separados por generador y semilla.
Ranking, activación y presupuesto son salidas distintas. Catálogo v2 incorpora
NESY, EVO_SEARCH, IMAGINATION y A12. Sin utilidad positiva, calibración válida o
incertidumbre aceptable, la decisión obligatoria es `ABSTAIN`.

## Hipótesis y coste

Debe reducir regret frente al scheduler determinista/reward-guided sin perder más
de 1 pp de cierre. Objetivo menor a un millón de parámetros y 1 GiB de VRAM.

## Dependencias y rollback

P23 antes del hook; P19 y causalidad antes de influencia. Shadow/off restaura la
secuencia autoritativa y el catálogo anterior permanece disponible por versión.
