---
title: Campaña de órganos neuronales N0-N6
status: active
version: 1.2.0
date: 2026-07-11
owner: Codex
principle: A-M0
---

# Campaña N0→N6 — organismo integral y simbiótico

## 1. Ley de diseño

A-M0 gobierna toda decisión de esta campaña: un órgano no se promueve por una
métrica local. Debe mejorar o preservar cierre, certificación, continuidad,
viabilidad, coherencia, seguridad, herencia y presupuesto físico del organismo.
La reparación de Fable y el crecimiento neural son especializaciones simbióticas;
los puertos entre ambas son parte del diseño, no muros.

## 2. Arquitectura

`runtime/neural/` contiene contratos puros, registro lazy, gate de modos,
admisión física, backends y adaptadores. Los modelos sólo producen propuestas.
Kernel, scheduler, mundo, MFM, gates y certificadores existentes conservan
autoridad. `off` no abre artefactos ni emite eventos; `experimental` es de
laboratorio; `shadow` observa la frontera viva sin cambiarla; `provisional`
requiere gate, presupuesto y enlace causal.

La autoridad máxima es parte del contrato tipado de admisión. N0 aplica el techo
del órgano antes de producir una salida efectiva: una propuesta puede ser válida y
trazable sin obtener influencia. N4 declara actualmente techo `SHADOW`; ni un modo
`provisional` configurado ni un contexto causal enlazado pueden elevarlo.

La ausencia de P-CADENA no bloquea investigación: marca la inferencia como
`unlinked` y degrada provisional a shadow. Pesos o dependencias ausentes siempre
producen fallback explícito; el runtime no descarga nada.

## 3. Estado real por órgano

| Paquete | Implementado en la campaña | Condición pendiente para frontera viva |
|---|---|---|
| N0 | Contratos, manifiesto/hash, registro lazy, recursos, modos, eventos v1, buffer/health de persistencia y reporte A-M0 | Extensión P25/B47 para telemetría GPU absoluta y caller vivo coordinado |
| N1 | MLP JSON reproducible, catálogo v2, `ABSTAIN`, hard masks, ranking/activación/presupuesto separados y dataset contrafactual | Hook scheduler coordinado; dataset diverso, entrenador y artefacto calibrado |
| N2 | Recurrencia compartida 4–16 pasos y verificación DED+LOTF por candidato | Hook NESY coordinado y benchmark retenido |
| N3 | Puerto SSM, backend de referencia con estado por organismo/escenario y autoridad MFM | P-CADENA/P21; revisión/licencia/dependencias Mamba2 |
| N4 | Grafo causal tipado, efectos firmados, desacuerdo explícito y techo ejecutable `SHADOW`; backend de referencia solo valida contrato | Modelo entrenado/calibrado, evidencia externa, ratificación del techo e integración causal coordinada |
| N5 | Chunker Unicode, contrato byte/codepoint/token, conversión UTF-8 segura, puerto H-Net byte-level y caller hacia sinks | Revisión/pesos H-Net y adaptadores SMG/MFM vivos de Fable |
| N6 | KAN exportable, LTC y gate estructural con whitelist/rollback | P29 con `apply_fn` real y certificación de sandbox |

Un backend de referencia valida matemáticamente el contrato, pero no se confunde
con el modelo objetivo. En particular, el SSM de referencia no se declara Mamba2;
`Mamba2Backend` mantiene un stop condition explícito hasta resolver procedencia.
El benchmark N4 repite casos deterministas: no presenta esas repeticiones como
robustez multisemilla ni su consistencia de signo como aprendizaje causal.

## 4. Datos, artefactos y promoción

N1 sólo acepta pares con igual estado inicial, generador y semilla, donde la única
diferencia sea familia on/off. Los campos históricos `family_delta_*` se rechazan
como etiquetas causales. Train/validation/test se agrupan por generador+semilla.
El umbral mínimo inicial es 300 pares, 50 contextos, 3 generadores y 3 familias.

Pesos viven bajo `RNFE_ARTIFACT_ROOT/neural/`; el repositorio conserva manifiesto,
model card y reporte, no pesos grandes. Cada promoción exige tres semillas o
modelos realmente independientes cuando corresponda, CI95 positivo, pérdida de
cierre no mayor a 1 punto porcentual, ECE <= 0.10, cero
violaciones y `OrganismImpactReport` favorable. Tras cada órgano se versiona y
recalibra el catálogo N1; nunca se agregan salidas silenciosamente.

El catálogo N1 v2 cubre HEUR, DIA_ADV, FAL_GUARD, IND, EML_SR, PLAN, OPT,
NESY, EVO_SEARCH, IMAGINATION y A12. El softmax sólo ordena: activar exige
utilidad esperada positiva, probabilidad y calibración válidas e incertidumbre
admitida. Si no, N1 emite `ABSTAIN` y conserva el scheduler autoritativo.

H-Net opera nativamente con probabilidades por byte UTF-8. N5 registra unidad y
semántica del offset y sólo convierte límites que coinciden con una frontera de
codepoint; un límite dentro de un carácter multibyte se rechaza sin redondeo.
Las trazas N0 usan `neural-events-v1`; si storage falla, un buffer acotado conserva
eventos y publica `neural.trace.persistence_failed` al recuperarse.

## 5. Coordinación y secuencia

El orden de integración es N0→N1→N2→N3→N4→N5→N6. Codex mantiene adaptadores y
ADR en `governance/adr/`; Fable mantiene sustratos y realiza hooks compartidos en
una ventana sin ediciones simultáneas. Después de cada unión se rebasa reparación,
se ejecuta la suite completa y se compara el impacto global antes de continuar.
