---
date: 2026-07-10
description: "Backlog consolidado de reparación de RNFE v16: 68 ítems (A1–A20 por recomendación + B1–B48) en 31 paquetes ordenados por dependencia y radio-SCC, tras reconciliar la auditoría externa."
project: RNFE v16 reparación
status: active
quarter: Q3-2026
tags:
  - work-note
  - rnfe
  - reparacion
---

# RNFE v16 — Backlog de Reparación

## Context

Cierre del bloque A de adjudicación tras la [[Cierre de adjudicación y reconciliación externa 2026-07-10|reconciliación con la auditoría externa]]. Consolida los **68 ítems** de la fase de reparación —los 20 adjudicados `A1–A20` resueltos por su recomendación, más el backlog directo `B1–B48` (incluye `B39–B48` nacidos de la auditoría externa)— en **31 paquetes** ejecutables, ordenados de modo que ninguna dependencia se viole y el radio de impacto en el SCC de cinco `{certification, organism, reality, reasoning, world}` crezca de menor a mayor.

Fuentes autoritativas (fuera del vault): `RNE_v16_analysis/reparacion/adjudicacion.md` (ítems + recomendaciones) y `RNE_v16_analysis/externa/verificacion_claims.md` (veredictos C1–C16).

> [!success] Verificación adversarial del plan — APROBADO_CON_OBSERVACIONES
> Cobertura **68/68** (cada ítem en exactamente un paquete, verificado por conteo). **0** faltantes · **0** duplicados · **0** violaciones de dependencia · **0** paquetes sobredimensionados. Quedan 3 coordinaciones blandas (abajo), ninguna bloqueante.

## Clasificación de los A-items (regla de cierre: cada A a su recomendación)

- **Doctrina** (opción 2 — edita `canon/`, sin código, 13): `A1, A4, A7, A10, A11, A12, A13, A14, A15, A16, A17, A19, A20`.
- **Código** (opción 1 — corrige runtime, 6): `A2, A3, A5, A6, A8, A9`.
- **Frontera** — `A18`: su recomendación (opción 2) renombra schema+records+audit_logger (artefactos de runtime, no `canon/`) → paquete `mixto`.
- `A8` (código) viaja empaquetado con la consagración doctrinal de `A11` por regla dura.
- **C13** (plan Fase 0 / WS0–WS7) es descriptivo, no defecto: no entra como ítem; su fusión con el ROADMAP viaja en P1 (un solo plan activo).

## Orden de despacho propuesto

`P0 → P1 → P2 → … → P30` (secuencial). Las pistas **doctrina** y **código** pueden solaparse: solo P14/P15/P16/P17 y los `depends_on` listados esperan a sus prereqs.

### Fase 1 — Prereqs doctrinales de la cúspide (radio SCC nulo)

| Paquete | Título | Pista/Clase | Ítems | Dep |
|---|---|---|---|---|
| **P0** | Cúspide axiomática + doctrina de certificación | doctrina/profundo | A15, A14, A1 | — |
| **P1** | Re-emisión del ROADMAP: fase, PMV y contratos de escenario | doctrina/profundo | A20, A19, A17 | — |

### Fase 2 — Código mecánico de radio nulo/bajo + higiene que habilita doctrina

| Paquete | Título | Pista/Clase | Ítems | Dep |
|---|---|---|---|---|
| **P2** | Islas de código muerto y módulos huérfanos | código/mecánico | B13, B14, B15, B16, B9 | — |
| **P3** | Higiene documental + gobernanza + verificación pendiente + cartógrafo life/conjunction | mixto/mecánico | B37, B33, B38 | — |
| **P4** | Desacoplamientos estructurales de bajo radio | código/mecánico | B10, B8 | — |
| **P5** | Endurecimiento de la provisión GPU | código/mecánico | B47 | — |
| **P6** | Backends de storage aislados | código/mecánico | B3, B46, B2, B23 | — |
| **P7** | Activación del contrato activo mínimo (CANON §13) | código/mecánico | B17, B18, B19, B20 | — |
| **P8** | Memoria MFM-lite interna | código/mecánico | B25, B28, B30 | — |
| **P9** | Honestidad de mediciones y assessment | código/mecánico | B1, B21, B24 | — |
| **P10** | Rollback real de MSRC | código/profundo | A3, B32 | — |
| **P11** | Registro de regímenes y benchmark de borde | código/mecánico | B26, B22 | P1 |
| **P12** | Runner: correcciones mecánicas localizadas | código/mecánico | B5, B6, B7, B31 | — |

### Fase 3 — Consagración doctrinal (habilitada por A3 en P10 y el cartógrafo en P3)

| Paquete | Título | Pista/Clase | Ítems | Dep |
|---|---|---|---|---|
| **P13** | Doctrina SSOT del razonamiento: contrato de motores y señales | doctrina/mecánico | A4, A7 | — |
| **P14** | Familias de razonamiento en el canon | doctrina/mecánico | A13, A16 | P0 |
| **P15** | Doctrina MSRC vinculante + rename de schema | mixto/mecánico | A12, A18 | P0, P10 |
| **P16** | Constitución T5 vinculante + kill-switch auditado | mixto/profundo | A11, A8 | P0 |
| **P17** | Gobernanza vinculante de life+conjunction | doctrina/profundo | A10 | P0, P3 |

### Fase 4 — Código dentro del SCC, radio-SCC estrictamente creciente

| Paquete | Título | Pista/Clase | Ítems | Dep |
|---|---|---|---|---|
| **P18** | Compatibilidad macro de memoria (primer código en el SCC) | código/profundo | A6, B27 | — |
| **P19** | Gobernanza de secuencias del scheduler | código/profundo | A2 | — |
| **P20** | Migración del ledger core↔storage | código/profundo | B11 | — |
| **P21** | Flujo de datos experiencia/maestro (auditoría externa) | código/profundo | B42, B43, B44, B45 | — |
| **P22** | Canal de configuración explícito de ecology | código/profundo | B34 | P16 |
| **P23** | Identidad e invariante de bloqueo del life kernel | código/profundo | B39, B48, B41 | — |
| **P24** | Alcanzar tier_3 externo por la vía gobernada | código/profundo | B40 | P14 |
| **P25** | Telemetría al camino vivo | código/profundo | B12 | — |
| **P26** | Exocortex al camino vivo | código/profundo | B35 | — |
| **P27** | Integración de runtime/evolution | código/profundo | B36 | — |
| **P28** | Decision-hub del runner: memoria influye intervención | código/profundo | B4 | — |
| **P29** | Autoevolución: gate por veredicto + sandbox que simula | código/profundo | A5 | P0, P1, P17 |
| **P30** | Enchufe de engines tras guard | código/profundo | A9, B29 | — |

## Dependencias duras respetadas

Cúspide `A15`+`A14`, `A20`+`A19` primero (P0, P1) · `A15` sanea antes de A10–A14: A13(P14)/A12(P15)/A11(P16)/A10(P17) dep P0 · `A20`→`A5`: P29 dep P1 · `A3`→`A12`: P15 dep P10 · `A17` gatea `B26`: P11 dep P1 · `A9` gatea `B29`: mismo paquete P30 (B29 tras A9) · frente único `B17–B20`: P7 · `B39`+`B48` juntos: P23 · `A8` con `A11`: P16 · derivadas: `B34`→A11 (P22 dep P16), `B40`→A13/A16 (P24 dep P14), cartógrafo (sub-ítem B38, P3)→A10 (P17 dep P3), `A5`→A1(cert)/A10(anclaje self_modify→act). Sin ciclos.

## Coordinaciones a vigilar (observaciones del verificador, no bloqueantes)

> [!warning] Tres deps blandas — coordinar, no reordenar
> 1. **`B19` (P7) ↔ `A18` (P15)** tocan ambos `msrc_transition_event`: B19 unifica el dialecto draft-07/2020-12 y agrega el chequeo schemas↔`records.py`; A18 renombra después `real_time_cost`/`real_artifact_cost`. Riesgo de rework en los tests de B19. **Sugerencia:** que A18 preceda a B19, o coordinar la pasada sobre ese schema.
> 2. **"Radio-SCC", no "membresía".** P11/P12 ya tocan `reality`/`world` (miembros del SCC) antes de P18; la monotonía se sostiene leyendo *radio de blast por el hub*, no pertenencia. Explicitarlo para no afirmar falso.
> 3. **`P21` (B42–B45) ↔ `P23` (B41)** comparten el namespace `organism_id` de la memoria de experiencia: B41 cambia la *derivación* de `organism_id`, B42–B45 el flujo/filtrado. Ortogonales pero acoplados por datos — vigilar.

## Estado de ejecución

> [!info] P0 — INGESTA-CANON: **DESPACHADO** (2026-07-10) a `ejecutor-profundo`
> Reconstruye `canon/normative/RNFE_canon_matematico_f2_4_v3_0.md` desde el genoma matemático (`canon_inbox/`: f2_2, f2_3, f2_4, f2_1-addendum), re-ancla la cadena de autoridad (depends_on v3_1→v3_2 en SSOT_RAZONAMIENTOS, ROADMAP_v2, blueprint), propone promociones A14 y reporta la doble capa de A1. Autorización de escritura solo en canon/ + 3 frontmatters; sin commit; termina en PAUSA para ratificación humana.

### Reorden acordado (aplicar al llegar a fase 2)
- **P-SEG (nuevo, adelantado por riesgo):** paquete de seguridad del gate `B48 + B39` a `ejecutor-profundo`, ANTES de los backends de storage. Tocan las mismas líneas (`kernel.py:455-513`); B39 replica el patrón correcto que ya existe en la rama de paso (500-513) en las 3 ramas transformadoras; B48 = invariante total de bloqueo + separación `validation_tier`/`execution_tier`. Separar limpio de **B41** (organism_id queda en fase 4 — B39 propaga el id que EXISTA, no cambia su definición). Tests obligatorios del hueco H5 (hoy sin cobertura). `auditor-reparacion` al cierre.

### Encolados (NO despachar hasta ratificación)
- **P1 = B (re-emisión del ROADMAP; A20/A19/A17)** → `ejecutor-profundo`, escritura en `canon/provisional`. Para cuando se ratifique P0. Declara la FASE VIGENTE con el campo marcado `PENDIENTE-HUMANO` (el número lo fija el humano); absorbe/supersede el plan Fase 0/WS0→WS7 con tabla WS↔paquete (WS3≈CADENA-CAUSAL, WS1/WS2≈B3/B38, WS7≈consagración SSOT); A19: thermal_homeostasis = PMV; A17: 4 escenarios + taxonomía de 5 morfismos a SCENARIO_CONTRACTS. PAUSA con ROADMAP + tabla WS↔paquete.

**Foco de revisión al volver P0:** cómo resolvió la **doble capa de A1** (certificado MIDE C^cont / promoción GATEA) — de ahí cuelga toda la doctrina posterior.

## Related

- [[Cierre de adjudicación y reconciliación externa 2026-07-10]]
- [[RNFE v16 Project Memory]]
- [[Key Decisions]]
- [[North Star]]
