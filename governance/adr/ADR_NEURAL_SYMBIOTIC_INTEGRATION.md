# ADR: integración simbiótica neuronal N0–N6

## Estado

Implementado y endurecido en `integration/dynamic-organism-v1`. La evidencia normativa sigue
en el canon; este ADR describe solamente el cableado ejecutable y sus límites.

## Decisión

`ScenarioEpisodeRunner` llama una única frontera,
`SymbioticNeuralCoordinator`. El coordinador resuelve un registro canónico N1–N6 y
usa N0 para ejecutar referencias CPU,
propaga una identidad causal común y transforma resultados en evidencia. No agenda
familias, selecciona intervenciones, certifica, promociona memoria ni aplica cambios.

El contrato `neural-symbiosis-trace-v2` enlaza identidad, input hash, candidato,
recibos tipados del consumidor, fallback, coste, resultado y certificado. El lector
conserva compatibilidad con v1, pero sus strings decorativos no satisfacen completitud
v2. Todo se persiste en el ledger existente; un fallo de storage queda en el
health/buffer de N0 y en `receipt.persisted=false`.

Cada `neural-consumer-receipt-v1` enlaza el hash vigente del candidato con hashes de
entrada/salida del consumidor, evidencia, veredicto, identidad causal y un efecto de
autoridad cerrado. Un consumidor desconocido, una identidad/hash incorrectos, una
marca temporal anterior al candidato o autoridad excesiva fallan cerrados. N1, N2,
N4 y N6 permanecen como máximo en `evidence_only`.

El veredicto es tipado mediante `ConsumerVerdictClass`: accepted, rejected,
abstained, observed, compared, unavailable, persistence_degraded o invalid. El detalle
humano no gobierna contadores ni autoridad. La lectura v1 mapea solamente formas
conocidas; una forma desconocida se vuelve `invalid` y no satisface completitud.

La traza separa `semantic_complete` de `durably_complete`. `trace_complete` queda como
alias documentado de la primera. Durabilidad exige evento final confirmado, receipts
embebidos, buffer vacío y cero descartes; `persistence_degraded` hace visible cualquier
pendiente o pérdida sin impedir que el organismo termine de procesar el episodio.

El coordinador no contiene productores `_n1`…`_n6`. Cada entrada del registro tiene
un único adaptador, capacidad, techo de autoridad, fallback y consumidor declarados;
un registro incompleto o duplicado falla durante la construcción.

## Auditoría canónica de adaptadores

| Órgano | Adaptador vivo | Implementación efectiva | Clasificación honesta |
|---|---|---|---|
| N1 | `N1Adapter` | `N1ReferencePolicy` | referencia determinista, no MLP entrenado |
| N2 | `N2Adapter` | `runtime.reasoning.families.nesy` + evidencia DED/LOT-F | propuesta neuro-simbólica shadow |
| N3 | `N3Adapter` | filtro temporal y estado versionado del adaptador | referencia, Mamba2 inactivo |
| N4 | `N4Adapter` | `CausalMessagePassingBackend` con grafo tipado v1 | referencia congelada, no entrenada |
| N5 | `N5Adapter` | `DeterministicChunker` | fallback determinista, H-Net inactivo |
| N6 | `N6Adapter` | propuesta estructural acotada + sandbox sin apply | referencia shadow, sin mutación |

El camino N4 vivo usa el mismo backend y esquema tipado que el laboratorio. La carga
embebida `load_frozen_reference_contract()` sólo instala pesos constantes mínimos para
validar el contrato: no abre artefactos, no descarga y no afirma entrenamiento.

La referencia viva atraviesa además `CausalPredictionAdmission` mediante el puerto
genérico de N0. Un rechazo conserva el candidato bruto para auditoría, mantiene el
fallback como salida efectiva y no concede influencia. La polaridad episódica deriva
exclusivamente de `factual_delta - counterfactual_delta`: `supports_choice` nunca fija
signo. Efecto cero o evidencia incomparable no producen aristas causales. Las aristas
episódicas son `canonical=false`; cuando existe firma causal, se agrega otra arista con
ID y provenance propios, separada de `goal_alignment`.

N3 diferencia `measured`, `defaulted`, `unmeasured` y `not_applicable`; una ausencia
no se convierte en cero, no genera tendencia y no aumenta el conteo de mediciones.

## Flujo vivo

1. N5 segmenta observación, fórmula y memoria autorizada con offsets deterministas;
   el runner materializa candidatos en SMG y los deja en el contexto que MFM condensa.
2. N3 actualiza estado con clave `(organism_id, scenario_id, lineage_id)` y su salida
   entra al siguiente contexto, a MFM candidata y a auditoría de continuidad.
3. N1 propone familias; el scheduler conserva la selección autoritativa. Después se
   registra propuesta, selección, intersección, recompensa y certificado.
4. N2 produce una proposición y la somete a los resultados reales de DED, LOT-F y
   NESY. Solo queda evidencia shadow aceptada o rechazada.
5. N4 formula una relación causal tipada desde el snapshot vivo y se compara con
   CAU, CTF y C-GWM. El desacuerdo llega a certificación y experiencia sin autoridad.
6. N6 propone o se abstiene según viabilidad/coste, pasa por evaluación sandbox y
   siempre conserva `applied=false`; no existe `apply_fn` en esta frontera.

## Censo de código vivo

| Componente | Clasificación | Caller vivo | Consumidor vivo |
|---|---|---|---|
| N0 | LIVE | ScenarioEpisodeRunner/coordinador | N1–N6 y trace health |
| N1 | SHADOW_CONSUMED | coordinador | comparación scheduler + resultado |
| N2 | SHADOW_CONSUMED | coordinador | DED + LOT-F + NESY + certificación |
| N3 | LIVE | coordinador | siguiente episodio + MFM + continuidad |
| N4 | SHADOW_CONSUMED | coordinador | CAU/CTF/C-GWM + certificación + experiencia |
| N5 | LIVE | coordinador | SMG + MFM + reasoning context |
| N6 | SHADOW_CONSUMED | coordinador | sandbox + certificación + autoevolution evidence |
| NESY | SHADOW_CONSUMED | verificador N2 / scheduler deep | N2 trace / PROB |
| EVO_SEARCH | REFERENCE_ONLY | scheduler deep | PROB |
| IMAGINATION/A11 | REFERENCE_ONLY | scheduler deep | A12 / PROB |
| A12 | REFERENCE_ONLY | scheduler/guard gated | override guard |
| CAU, CTF, DED | LIVE | MetaScheduler | reasoning, N2/N4, certificación |
| C-GWM | LIVE | ScenarioEpisodeRunner | transición factual y comparador N4 |
| LOT-F | LIVE | ScenarioEpisodeRunner | DED, N2 y certificación |
| MFM, SMG | LIVE | runner / PromotionGate | reasoning, memoria y certificación |
| scheduler | LIVE | ScenarioEpisodeRunner | intervención gobernada y certificación |
| certification | LIVE | ScenarioEpisodeRunner | promoción, experiencia y autoevolución |
| experience | LIVE cuando está habilitado | ScenarioEpisodeRunner | sesgo futuro |
| autoevolution | LIVE | ScenarioEpisodeRunner | linaje y knobs gobernados |

La matriz ejecutable y el gate de callers/consumidores viven en
`runtime/neural/integration/census.py`; documentación no se usa como prueba.

## Backends retirados de perfiles activos

- H-Net: reference-only hasta artefacto, hash, licencia y evidencia real.
- Mamba2: deshabilitado; N3 se declara `reference_temporal_filter`.
- MLP N1 sin entrenamiento: no dirige el scheduler; se usa una propuesta heurística
  determinista y declarada.
- N4 message-passing sin entrenamiento: el camino vivo usa su backend canónico como
  referencia contractual congelada, nunca como claim predictivo aprendido.

## Autoridad

- N1, N2, N4 y N6 tienen techo SHADOW.
- Integración no implica promoción.
- `neural_symbiosis` es metadata aditiva y no entra en `verdict`, `risk_score` ni
  `promotion_candidate`.
- OFF no llama productores ni adquiere artefactos.
- La presión alta conserva N5/N3 CPU y degrada N1/N2/N4/N6 de forma visible.

## Consolidación con MSRC

MSRC sigue siendo la única autoridad de escala. `LifeKernel` transmite el mismo
snapshot normalizado que reciben vitales y reasoning, añadiendo únicamente
`msrc_budget_available` y `msrc_scale_id`. El coordinador no elige escala ni define
umbrales; N0 aplica su presupuesto neuronal configurado.

Si MSRC falla, el siguiente episodio recibe `msrc_budget_available=false` y N0 no
ejecuta ningún órgano sin presupuesto. Una recuperación posterior de MSRC reabre el
presupuesto sin intervención manual. Las decisiones y transiciones MSRC incorporan
el mismo `run_id`, `episode_id` y `trace_group_id` que la traza simbiótica.

El checkpoint soberano incluye `n3-temporal-checkpoint-v1`: únicamente estado
determinista y claves `(organism_id, scenario_id, lineage_id)`, nunca pesos, modelos o
buffers. Esto conserva continuidad N3 entre corridas con nuevo `run_id`.

## Clasificación del gate estático anti-stub

La búsqueda obligatoria `return .*idle|if False|pass$|NotImplemented` no encuentra
coincidencias en el coordinador ni en sus perfiles activos. Las coincidencias restantes
se clasifican así:

- `runtime/legacy/*`: DEAD respecto al runtime vivo; no tiene importadores fuera de
  `runtime/legacy` y no forma parte del perfil simbiótico.
- `imagination` y `a12`: REFERENCE_ONLY en baseline; sus `idle` son kill-switches de
  overlays deep no activados, no órganos contados como vivos.
- `EpistemeMeter.apply_noise` y `Hook.__call__`: errores explícitos para capacidades no
  implementadas/abstractas; no tienen caller en el flujo simbiótico.
- `FormulaNode` y `BackendRegistryError`: clases base/excepción sin cuerpo; no producen
  outputs de órgano.
- Los `pass` restantes están exclusivamente en manejadores de excepción best-effort
  (`host_sampler`, continuidad, teacher, ecology, experience, storage config) y no son
  retornos sintéticos de un órgano.

No queda `if False` en `ScenarioEpisodeRunner`; `trajectory_window` usa ahora la ventana
real de trayectoria.
