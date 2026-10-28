---
title: ADR_NEURAL_N0_RUNTIME
status: experimental
version: 1.2.0
date: 2026-07-11
owner: Codex
---

# ADR — N0 Runtime neuronal

## Contexto

RNFE no tenía una frontera común que impidiera carga eager, falsa autoridad o
fallos silenciosos de modelos. `lab_only` era metadato, no un gate general.

## Decisión

Crear `runtime/neural/` puro Python con modos off→experimental→shadow→provisional,
manifiestos SHA-256, registro lazy, presupuestos físicos, fallback y eventos.
Todo backend devuelve propuestas; el gate RNFE conserva autoridad.
Los eventos `neural-events-v1` se bufferizan de forma acotada si storage falla;
el health expone pérdidas, descartes y recuperación, sin tumbar la inferencia.

### Techo de autoridad ejecutable

La autoridad máxima de cada órgano forma parte del contrato tipado de admisión
mediante `AdmissionDecision.effective_mode_ceiling`. N0 aplica ese techo después de
validar la propuesta y antes de asignar `effective_output` o
`DecisionInfluence.BOUNDED_PROPOSAL`.

Una admisión puede declarar una propuesta semánticamente válida y, a la vez,
limitarla a `NeuralMode.SHADOW`. En ese caso el candidato y su traza permanecen
observables, pero la salida efectiva sigue siendo el fallback, la influencia es
`NONE` y el motivo registra el techo. `None` conserva el comportamiento anterior
de los órganos sin techo explícito. Un contrato inválido o un techo incompatible
falla cerrado a shadow, sin autoridad operacional. La decisión no depende del
nombre del órgano ni de strings de auditoría.

## Hipótesis falsable y coste

N0 permite ejecutar modelos sin alterar la ruta off y recuperarse de hash inválido,
OOM o presión. N0 añade cero VRAM en off; el perfil local limita residencia a 6 GiB,
reserva 1.5 GiB y corta a 80 %/82 °C.

## Rollback

`RNFE_NEURAL_MODE=off`; retirar el registro del backend. No hay migraciones.
