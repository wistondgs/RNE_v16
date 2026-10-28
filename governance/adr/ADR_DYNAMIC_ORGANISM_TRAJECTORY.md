# ADR: trayectoria dinámica canónica del organismo

## Estado

Implementado en `integration/dynamic-organism-v1` como contrato interno aditivo. No
modifica el canon, el registro de regímenes ni el esquema de storage.

## Decisión

Cada episodio sano materializa dos resúmenes acotados `organism-dynamic-state-v1`
para Ω_t y Ω_t+1. Conservan hashes/referencias del mundo, organismo, memoria, órganos
neuronales, política, recursos, homeostasis, linaje y régimen; no copian blobs ni
convierten mediciones ausentes en valores favorables.

Después de transición factual, certificación, recompensa, experiencia y finalización
de los consumidores neuronales, `DynamicLifeChain` construye
`organism-life-transition-v1`. Su ID no depende del reloj y su hash enlaza el estado
anterior, el posterior y el hash de la transición previa. Sólo tras persistir mediante
el ledger existente como `organism.life_transition.committed` avanza el head y se
cierra `neural-symbiosis-trace-v2`.

Una escritura fallida no avanza la cadena y devuelve `status=incomplete` con reason
code. No se presenta como vida sana.

## Régimen y continuidad

El runner consulta `runtime.organism.regime_model` sin duplicar ni modificar su
registro. Registra compatibilidad, distancia estructural y factibilidad de transporte.

El checkpoint soberano conserva, dentro de su bloque neural aditivo, N3 y el head
dinámico: organismo, linaje, último estado/hash/ID, índice, epoch y versiones. Un nuevo
`run_id` es válido; otro organismo o linaje falla cerrado. Un checkpoint N3 legacy
restaura N3 y abre una epoch explícita con
`legacy_checkpoint_without_dynamic_chain`, sin inventar historia.

## Autoridad

La cadena describe lo ocurrido. No elige intervención, no certifica, no escribe MFM,
no cambia scheduler/MSRC y no concede autoridad a N1–N6.

## Ventanas y replay

`TrajectoryWindowBuilder` sólo acepta transiciones committed de un mismo organismo y
linaje, con índices, estados y hashes continuos dentro de una epoch. Su API no ofrece
shuffle, random split ni filas IID. El checkpoint conserva un historial reciente
acotado y lo revalida contra el head al restaurar.

`ShadowTrajectoryReplay` reconstruye el contexto histórico acotado guardado en cada
transición y crea un registro fresco de adapters. No recibe storage ni objetos vivos
del mundo/MFM/experience/scheduler; compara hashes de propuestas y reporta impacto
estimado, errores o evidencia insuficiente sin contaminar la cadena original.

El replay calcula diferencias de incertidumbre y de costes sólo cuando ambos lados
están medidos. Para N4 calcula acuerdo sólo si existe comparación histórica válida.
Cada ausencia lleva status/reason; una recompensa histórica se llama
`historical_reward`, nunca regret sin comparador contrafactual de recompensa.

## Adaptación longitudinal

`AdaptiveStateStore` mantiene `organ-adaptive-state-v1` por
`(organism, lineage, regime, organ, backend)`: participación, abstención, recibos,
recompensa sólo cuando existe, certificados sólo cuando existen, desacuerdo causal,
latencia online, coste, fallbacks, dwell e indicadores de cambio. Se actualiza después
de una transición committed y viaja en el checkpoint.

La aceptación usa exclusivamente `verdict_class`. Su tasa declara denominador
`accepted + rejected`; observed, compared, abstained y unavailable tienen contadores
separados y jamás se interpretan mediante substrings.

Los hashes de estado, transición, candidato, receipt y replay comparten un normalizador
JSON estricto: sólo escalares finitos, strings, listas/tuplas y mappings con claves
string. NaN, infinito, bytes, sets, dataclasses u objetos arbitrarios se rechazan; no
existe fallback a `repr`/`default=str`.

`AdaptationPlanner` es su consumidor real. Emite `adaptation-priority-v1` y su enum
cerrado sólo permite `collect_more_evidence`, `replay_candidate`, `hold` o
`quarantine_candidate`. No modifica pesos, no promueve modelos ni muta al organismo.
