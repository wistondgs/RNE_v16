---
title: ADR_NEURAL_N2_RECURSIVE_NESY
status: experimental
version: 1.0.0
date: 2026-07-10
owner: Codex
---

# ADR — N2 Neural-simbólico recursivo

## Decisión

Recurrencia de pesos compartidos, máximo 16 pasos, que selecciona candidatos de
un espacio acotado. Cada candidato pasa DED y LOTF; rechazo y halt quedan trazados.

## Hipótesis y coste

Más candidatos correctos/verificados que NESY determinista en test retenido, sin
autoridad neural. Límite de 10 M parámetros y 2 GiB de VRAM.

## Rollback

Desactivar N2 conserva NESY determinista. Un fallo de cualquier verificador rechaza
el candidato; no existe reparación silenciosa.
