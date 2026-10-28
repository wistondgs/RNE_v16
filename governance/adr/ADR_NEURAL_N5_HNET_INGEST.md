---
title: ADR_NEURAL_N5_HNET_INGEST
status: experimental
version: 1.1.0
date: 2026-07-10
owner: Codex
---

# ADR — N5 Ingestión H-Net

## Decisión

Puerto H-Net inyectable y servicio real texto/bytes→chunks→sinks SMG/MFM. Sin
modelo certificado se usa un chunker determinista Unicode y no se declara H-Net.
H-Net entrega fronteras `after_unit` en bytes UTF-8. N5 conserva esa procedencia,
la convierte a offsets de codepoint sólo en límites válidos y registra ambos
espacios; token offsets requieren un mapa explícito.

## Hipótesis y coste

Mejor F1 de frontera que el chunker, con corpus RNFE retenido y máximo 4 GiB VRAM.

## Dependencias y rollback

Peso, hash, MIT, commit vendor exacto y caller vivo son obligatorios. Cualquier
ausencia vuelve al chunker; memoria recibe candidatos, nunca promoción directa.
