---
title: ADR_NEURAL_N6_KAN_LTC_EVOLUTION
status: experimental
version: 1.0.0
date: 2026-07-10
owner: Codex
---

# ADR — N6 KAN, LTC y evolución estructural

## Decisión

KAN spline exportable a SymPy, LTC estable sobre vitals y mutaciones de whitelist
entregadas a sandbox/certificación. EVO_SEARCH continúa como baseline de intervención.

## Hipótesis y coste

KAN supera EML-SR/lineal y LTC mejora anticipación vital sin oscilación. N6 completo
no supera 3 GiB VRAM ni aplica cambios sin evidencia global A-M0.

## Dependencias y rollback

P29 exige `apply_fn`, veredicto y rollback reales. Sin ellos el gate devuelve
`applied=false`. Fallo de aplicación invoca el token de rollback inmediatamente.
