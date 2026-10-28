---
title: ADR_NEURAL_N4_CAUSAL_GRAPH
status: experimental
version: 2.1.0
date: 2026-07-11
owner: Codex
---

# ADR — N4 Grafo neural causal tipado

## Contexto y principio rector

N4 es un órgano de propuesta bajo A-M0. Debe enriquecer la evidencia causal sin
degradar la coherencia global de A-M4 ni crear una falsa herencia bajo A-M8. CAU,
CTF, C-GWM, LOT-F, DED, la constitución y la certificación conservan autoridad.
Este ADR no habilita un hook vivo ni modifica firmas causales canónicas.

## Decisión

El contrato `n4-causal-graph-v1` representa snapshots causales de solo lectura.
Todos los nodos incluyen id estable, tipo, vector de características, procedencia,
identidad de escenario, timestamp opcional y versión. Tipos permitidos:

- `world_variable`, `observation`, `intervention`, `sign`;
- `evidence`, `memory`, `goal`, `constraint`.

Todas las aristas incluyen id estable, origen, destino, tipo, fuerza firmada,
confianza, procedencia, marca canónica y versión. Tipos permitidos:

- `causal_positive`, `causal_negative`, `temporal`, `support`;
- `contradiction`, `counterfactual`, `semantic`, `morphism`.

Las relaciones entre escenarios solo son válidas mediante una arista `morphism`.
Tipos desconocidos, ids duplicados, aristas colgantes, NaN/Inf, confianza inválida,
causalidad sin signo, procedencia ausente, identidad de escenario inconsistente o
versión incompatible fallan cerrado.

## Salida y representación del efecto

El contrato de salida es `n4-causal-proposal-v1`. Para cada relación predicha
incluye efecto esperado firmado en `[-1, 1]`, magnitud absoluta, incertidumbre,
confianza, estimación acotada del siguiente estado, ids de soporte, identidad/hash
del modelo, versión del grafo e indicación OOD/evidencia insuficiente.

El efecto usa dirección explícita y magnitud acotada por `tanh`; no usa un escalar
sigmoid como efecto causal. La incertidumbre procede de una cabeza independiente y
no se identifica con la magnitud. El artefacto v1 exige cuatro salidas mínimas:
estado, modulación de efecto, confianza e incertidumbre.

## Desacuerdo con la firma canónica

N4 informa uno de estos estados estructurados:

- `aligned`;
- `weak_disagreement`;
- `direction_conflict`;
- `missing_canonical_edge`;
- `unsupported_prediction`;
- `insufficient_evidence`.

Un conflicto de dirección permanece explícito y reduce la confianza de admisión;
nunca se promedia con la firma canónica. OOD o evidencia insuficiente requieren el
fallback de las autoridades causales deterministas.

## Backend de referencia y procedencia

`CausalMessagePassingBackend` es un backend CPU compacto para validar contratos.
Cada salida declara `classification`, `trained`, `frozen` y `experimental`, además
del hash de artefacto y manifiesto. El artefacto incluido en tests es `reference`,
no entrenado, congelado y experimental; no se presenta como GNN entrenada.

El contrato v0 permanece únicamente como adaptador de fixtures LAB, marcado
`legacy_reference_v0`; se rechaza en frontera LIVE, declara el mismo techo tipado
`SHADOW` y no constituye integración.

## Autoridad y admisión

La salida estricta no contiene mutaciones, acciones, autorizaciones, certificados,
decisiones de cierre, salida efectiva ni intervención seleccionada. Una propuesta
N4 puede ser estructuralmente válida sin adquirir autoridad: toda admisión válida,
estricta o legacy, declara `effective_mode_ceiling=NeuralMode.SHADOW`. N0 aplica el
techo antes de producir cualquier salida efectiva o influencia.

La admisión puede rechazar una forma inválida, registrar shadow, marcar desacuerdo
y reducir confianza. No puede:

- alterar C-GWM o una firma causal canónica;
- reemplazar CAU o CTF;
- elegir una intervención;
- autorizar una acción, cierre o certificado;
- modificar memoria, estado del organismo o scheduler.

Aunque el runtime genérico disponga de modo `provisional`, N4 permanece limitado a
laboratorio/shadow por contrato ejecutable. Incluso con contexto causal LIVE
completo y una propuesta admitida, N0 conserva el fallback, influencia `NONE` y
modo efectivo `SHADOW`. Cambiar una variable de entorno, aportar otro modelo o
reducir ECE no eleva ese techo: una promoción futura requiere modificar y revisar
el contrato versionado.

## Presupuesto físico

El perfil de referencia fija límites duros de 512 nodos, 4096 aristas, 16 384
valores de características y cuatro pasos de message passing. Cada artefacto puede
reducirlos, nunca ampliarlos. El backend es CPU y reporta RAM estimada y VRAM cero.
El benchmark exige asignación Python pico menor o igual a 64 MiB para sus grafos
sintéticos; N0 conserva además los gates físicos globales.

## Evidencia y promoción

`runtime/neural/lab/n4_benchmark.py` cubre efecto positivo, efecto negativo, cadena,
collider, confusor ambiguo, contradicción, firma canónica ausente, morfismo entre
escenarios, desacuerdo factual/contrafactual y OOD. Repite cada caso tres veces para
comprobar reproducibilidad determinista; esas repeticiones no son modelos
independientes ni evidencia de generalización multisemilla.

El reporte `n4-contract-benchmark-v2` separa:

- `contract_metrics`: consistencia del signo ya codificado, reglas de desacuerdo,
  rechazo malformado, invariantes de autoridad, repetibilidad, fallback y trazas;
- `predictive_metrics`: aprendizaje de efectos, generalización causal, predicción
  retenida y generalización externa quedan `not_evaluated`; la ECE observada se
  conserva sin suavizar y `promotion_eligible` es siempre `false` para este backend.

La consistencia del signo no demuestra predicción causal: tanto la dirección del
backend de referencia como la expectativa contractual provienen de
`signed_strength`. El benchmark reporta además identidad/hash de artefacto,
latencia, asignación Python pico, RAM/VRAM estimadas y cero influencia operacional.

La promoción futura requiere ratificación explícita del cambio de techo, integración
causal revisada, benchmark externo con modelos/semillas realmente independientes,
los gates generales N0/A-M0, ECE admisible y `OrganismImpactReport` sin daño
significativo. Este backend de referencia no aporta aprendizaje causal, evidencia
externa, calibración suficiente ni autoridad de promoción.

## Rollback

El rollback es poner N4 en `off` o retirar su manifiesto/registro. No existen
migraciones, mutaciones de grafo ni estado neural persistente que revertir. En
shadow, el fallback determinista sigue siendo la salida efectiva y las propuestas
solo dejan trazas neuronales versionadas.
