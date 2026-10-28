---
description: "Architectural and workflow decisions worth recalling across sessions — each links to its source work note"
tags:
  - brain
---

# Key Decisions

## 2026-07-10 - Install Obsidian Mind as Project-Local Agent Memory

Decision: install Obsidian Mind under `ai/obsidian-mind/` and expose it through root agent bridge files instead of replacing RNFE project root files.

Status: accepted

Rationale: RNFE already has canonical docs, contracts, and runtime memory semantics. A project-local vault gives all agents persistent development memory while avoiding contamination of RNFE runtime architecture.

Related: [[RNFE v16 Project Memory]], [[North Star]]

## 2026-07-10 - Cierre de adjudicación y reconciliación con auditoría externa

Decision: verificar los 16 claims de la auditoría externa contra el árbol real (**21/21 CONFIRMADO**), rutearlos al backlog (`B39–B48` nuevos; C2→B48; convergentes anotan B2/B3/B38/A5), y cerrar el bloque A consolidando los 68 ítems (A1–A20 por recomendación + B1–B48) en **31 paquetes ordenados** (P0–P30).

Status: accepted — **PAUSA antes de despachar P0** (espera confirmación del orden).

Rationale: base de reparación = checkout `feat/reasoning-family-quality-deep` en `pre-repair` (main no contiene pre-repair, sin divergencia). Orden por dependencia + radio-SCC creciente; plan verificado adversarialmente (cobertura 68/68, 0 violaciones).

Related: [[Cierre de adjudicación y reconciliación externa 2026-07-10]], [[RNFE v16 — Backlog de Reparación]], [[RNFE v16 Project Memory]]

Architectural or workflow decisions worth recalling. Link to the full [[Decision Record]] when one exists.

-
