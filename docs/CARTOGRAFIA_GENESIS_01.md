# Cartografía de Genesis

HEAD `364044e` · 2026-09-17 · rama `repair/disturbance-families` · `main` intacto en `cdac5ef`

**Qué es este documento.** Lo que se ha **medido** del código, con `fichero:línea` o con
una corrida ejecutada. Nunca el nombre de un módulo como evidencia. Donde algo no se pudo
verificar, se dice, en vez de rellenarse.

**Cómo caduca.** `scripts/cartografia_check.py` recalcula el sha256 de cada fichero que
este documento cita y lo compara con `docs/CARTOGRAFIA_MANIFIESTO.json`. Una sección cuyo
código cambió queda STALE y no se construye sobre ella hasta releerla. La lista de ficheros
no se mantiene a mano: sale de las citas del propio texto.

Desde el 2026-09-21 verifica además cada `fichero:línea`: inexistente, fuera de
rango o en blanco. El hash no puede ver que una cita se pudra mientras el
fichero registrado sigue igual — en el árbol de Terrario esa comprobación
encontró seis citas rotas a la primera pasada.

**Citas de otro árbol.** RNFE son tres árboles. Las citas con prefijo —`v16:…`, `v15:…`—
se vigilan igual que las locales. Existe esa capacidad porque su ausencia produjo R-015.

---

# I · Los tres árboles, y por qué esta sección va primera

`INFERENCIA` corregida a `HECHO EXPERIMENTAL` el 2026-09-17.

RNFE **no es este repositorio**. Son tres, con el mismo remoto y divergentes:

| | ruta | rol |
|---|---|---|
| **genesis-v2** | `/home/wis/Desarrollo/RNE_v16-genesis-v2` | este árbol. El andamiaje donde el ser va montado |
| **v16** | `/home/wis/Desarrollo/RNE_v16` | donde están los artefactos y el único entrenamiento real |
| **v15** | `/home/wis/dev/rnfe.v15` | el viejo |

Barrido de los tres, mismo comando en cada raíz
(`grep -rlE '\.backward\(\)|torch\.optim|optimizer\.step\(\)' --include='*.py'`):

| | genesis-v2 | v16 | v15 |
|---|---|---|---|
| ficheros que entrenan | 5 | 6 | 5 |
| órganos neurales | 13 | 8 | — |
| familias de razonamiento | 24 | 25 | 21 |
| **registro de parámetros adaptativos** | **1** | **0** | **0** |
| **artefactos entrenados** | **7** | **42 625** | **2 839** |

**El hecho estructural:** el control de hiperparámetros —`runtime/world/parameters.py`—
vive en el árbol con 7 artefactos. Los 42 625 y el único entrenamiento con provenance
viven en el otro. Nada los conecta.

Esta sección va primera porque su ausencia produjo una afirmación falsa sostenida durante
horas: «en RNFE nada aprende», medida con un comando correcto sobre un alcance equivocado.
Un cero dentro del alcance equivocado se lee igual que un cero real.

---

# II · El lazo de vida y quién es dueño de su estado

`HECHO DE CÓDIGO` + `HECHO DE TEST`.

**La reconstrucción del runner es estructural, no accidental.** `runtime/life/kernel.py:382`
pone `self._runner = None` cada `block_size` episodios — 8 por default. No la causa el tier
ejecutable, que está detrás de un flag apagado.

Consecuencia: **todo lo que viva en el runner muere cada 8 episodios.** Cuatro cosas vivían
ahí y ya no:

| estado | dónde vive ahora | commit |
|---|---|---|
| el lazo ρₜ (paciencia, cooldown, checkpoint, ventana de monitoreo) | kernel, checkpoint y los dos restores | `b4b5094` |
| la certificación anterior | se rederiva del ledger, `runtime/world/scenario_runner.py` | `50c3819` |
| Λ, el estado de hiperparámetros | kernel, checkpoint y los dos restores | `d22dd99` |
| la fisiología adoptada (los mandos que el lazo escribió) | viaja con el estado de autoevolución | `b4b5094` |

**El mundo también viaja ya** (H-047, ola 6). `self.scenario` se sigue construyendo desde
un **nombre** —eso no cambió— pero su estado ya no muere con el runner:
`runtime/world/scenario.py` da a la clase base `CognitiveScenario` un
`export_world_state` / `restore_world_state` que los cuatro escenarios del árbol heredan,
porque todos guardan su mundo en un único `self._state` que es un dataclass.

Medido antes: el paso 7 cerraba en `0.98 / cooling False / alarm True` y el 8 nacía en
`0.82 / False / False`. Después: 2 fronteras de bloque, **0 entran con el mundo virgen**,
continuidad exacta 2/2.

**El invariante no vive en el `__init__`.** El escenario nace virgen y el kernel le entrega
el mundo justo después, igual que con el estado neural y el del lazo. Lo que I-05 exige es
que el mundo con el que **entra** el primer episodio del bloque nuevo sea el que dejó el
anterior; ahí se mide.

**Ranura propia, no dentro del organismo.** El checkpoint tiene cuatro claves de primer
nivel —`world_state`, `parameter_state`, `autoevolution_state`, `neural_state`— porque una
campaña causal interviene `do(D)` sobre el mundo y `do(A)` sobre el organismo por separado.

**Y un mundo POR ESCENARIO** (H-051). `world_state` es un **mapa nombre→mundo**, no un
payload suelto. Con `config.scenarios` de más de uno el kernel rota entre ellos cada bloque,
y una sola ranura le empujaba al escenario entrante el mundo del saliente — la comprobación
estricta lo cazó (`world_state_scenario_mismatch`) en vez de cargar campos que significan
otra cosa. Un checkpoint escrito entre H-047 y H-051 lleva el formato plano y se **migra**
envolviéndolo en su entrada, porque descartarlo devolvería al organismo a un mundo virgen.

Medido: 24 pasos con dos escenarios visitan 9 episodios cada uno, el kernel guarda los dos
mundos y los dos vuelven del checkpoint. Prueba: `tests/world/test_world_multiscenario.py`.

Pruebas: `tests/organism/test_autoevolution_state.py` · `tests/life/test_autoevolution_continuity.py`
· `tests/life/test_certificate_continuity.py` · `tests/world/test_world_continuity.py` · `tests/world/test_world_multiscenario.py`.

El tripwire `xfail(strict)` que la ola 2 dejó nombrando H-047 **disparó** con `XPASS` al
cerrarse el ownership del mundo, y se retiró la marca.

**El estado viaja atrás; el ledger no.** Un refugio restaura un estado ANTERIOR del lazo,
y ese estado puede creer que una propuesta sigue en monitoreo cuando el ledger ya registró
su desenlace: medido, `mod-24dbd0b9` recibió **dos** `autoevolution.committed`, rompiendo
`∀ p ∈ APPLIED, ∃! outcome`. Apareció al volver continuo el mundo, que cambió la
trayectoria de viabilidad lo bastante para alcanzar un camino antes inalcanzable.
`runtime/life/kernel.py` reconcilia contra el ledger antes de adoptar el estado
restaurado: una propuesta que allí ya cerró se adopta cerrada, sin segundo evento
terminal, y su ventana se descarta con un evento propio no terminal.

---

# III · La autoridad de parámetros y el ledger de Λ

`HECHO DE CÓDIGO` + `HECHO EXPERIMENTAL`.

**Sólo hay DOS hiperparámetros adaptativos declarados**, de ~127 configuraciones
(100 `RNFE_*`, 3 `AEON_*`, 24 campos de config): `memory_retrieval_limit` y
`memory_filter_mode`. Contrato completo en `runtime/world/parameters.py`, con una taxonomía
de nueve clases para que nada se vuelva adaptable por descuido. `memory_retrieval_limit`
se queda **sin máximo** a propósito.

**Una sola capa materializa.** `runtime/world/scenario_runner.py:357`
`apply_parameter_intent` es lo único que escribe un parámetro adaptativo. Valida el
conjunto entero antes de escribir nada y devuelve `accepted | rejected | no_op`.

Las cuatro fuentes producen **intenciones**, no escrituras:

```
runtime/organism/autoevolution.py:354   _write_knobs — el lazo ρₜ, con su acción
runtime/life/kernel.py                  el tier ejecutable (flag apagado por default)
runtime/organism/ecology.py:180         driver paralelo: su propio runner
runtime/world/scenario_runner.py        bootstrap — no es mutación
```

Medido (H-048): la autoridad de mutación efectiva **ya era 1** en los dos regímenes. El
defecto real era que el bootstrap se repetía en cada reconstrucción.

**El ledger.** `runtime/world/scenario_runner.py:417` `_emit_parameter_mutation` persiste
cada mutación con `{source, reason, proposal_id, changes:{old,new}, hash_before,
hash_after, outcome, episode_id, organism_id}`. Los hashes de Λ son deterministas y **sin
timestamps**. Medido: cadena sin huecos, y el brazo con `block_size=1` produce un ledger
**idéntico** al de `block_size=50`.

Pruebas: `tests/life/test_parameter_authority.py` · `tests/life/test_parameter_provenance.py`.

---

# IV · El régimen de referencia y sus dos umbrales que no son el mismo

`HECHO EXPERIMENTAL`, 60 pasos, dos brazos, configuración default.

`runtime/life/reference_manifest.py` emite los doce campos que exige el punto de partida.
Lo no capturable se declara `NOT_CAPTURED` **dentro de los datos**, con su motivo. Su hash
identifica el **régimen**, no la corrida: excluye identificadores acuñados y la ruta del
intérprete.

**Dos márgenes distintos con el mismo nombre.** Confundirlos cuesta una lectura entera:

```
runtime/life/vitals.py:30     el supervisor: quarantine si margen<0.15 O identidad<0.45
runtime/life/vitals.py:99     sin episodio, cae al margen CRUDO del organism_state
runtime/organism/viability.py:125   el del episodio es COMPUESTO: 0.30×crudo + …
runtime/organism/autoevolution.py:478   el trigger del lazo lee el COMPUESTO
```

R_AE se mide sobre el compuesto. La cuarentena la decide el otro.

**Dos pestillos de la misma familia.** `runtime/life/kernel.py:768` documenta el primero,
en la rama de rollback, ya reparado — *«un pestillo del que no se sale. Medido: muerte en
el paso 32»*. El segundo estaba en la rama de cuarentena, `runtime/life/kernel.py:713`, y
se reparó hoy: su contador vivía detrás de `self._experience is not None`, que depende de
`RNFE_EXPERIENCE`, apagada por default.

| | antes | después (`364044e`) |
|---|---|---|
| episodios en 60 pasos | 31 | **54** |
| cuarentena | 29, cola absorbente | 6, en dos rachas de 3 |
| R_AE (margen), soporte declarado | 0.2581 (n=31) | 0.4074 (n=54) |
| reproducibilidad de trayectoria | idéntica | idéntica |

Los 29/6 pasos sin episodio son `NOT_EVALUABLE`, **nunca 0**.

Prueba: `tests/life/test_quarantine_not_absorbing.py` · `tests/life/test_reference_manifest.py`.

---

# V · Lo neural: qué hay aquí, y qué de ello alcanza al organismo

`HECHO DE CÓDIGO`, barrido completo de `runtime/neural/`.

**Los pesos no se mueven.** `runtime/neural/organs/n3_temporal.py:26` los carga con
`json.load`. Barrido de todo el subárbol
(`grep -rnE '\.backward\(\)|requires_grad|\.data\s*=|optimizer\.step\(\)' runtime/neural/`):
**cero resultados**.

La organ hace un paso hacia delante de RNN con pesos congelados y **estado recurrente que
sí persiste** por `(organism_id, scenario_id)`. La red percibe y recuerda; **nadie le da
error**. El checkpoint lo dice en su propio docstring: *«no incluye modelos ni buffers»*.

**Lo que existe y no alcanza al lazo de vida** — importadores medidos, no supuestos:

| | alcance desde `runtime/life/` |
|---|---|
| `runtime/evolution/predictive_coder.py` (AdamW, `backward()`) | **0** — sus únicos importadores están en `archive/` |
| `runtime/evolution/EvolutionaryRehabilitationCenter.py` (Adam) | **0** — idem |
| `runtime/legacy/train.py` | **0** |
| `runtime/neural/training/n1_dataset.py` | **0** — su único importador es su propio test |

**El entrenamiento real está en el otro árbol.** `v16:runtime/neural/training/n4_ranking.py`
y `v16:runtime/neural/training/n4_campaign.py`, con sus scripts
`v16:scripts/train_n4_ranking.py` y `v16:scripts/evaluate_n4_ranking_ablation.py`.

El artefacto promotable es una regla lineal de **seis coeficientes sobre seis features con
nombre** —`empirical_gain`, `holdout_support`, `coverage`, `simplicity`, `stability`,
`invariant_safety`—, AdamW, 300 épocas, 30 399 muestras, Platt ajustado sólo con
validation, holdout `brier 0.0586 / ece 0.00863`. Su esquema es
`n4-ranking-artifact.v1`; el órgano de **este** árbol,
`runtime/neural/organs/n4_causal.py`, espera `n4-reference-artifact-v1`. **No son el
mismo esquema.**

Su gate científico **no pasó**: la ablación congelada mejoró Recall@1 y MAE gain top-1 y
empeoró Recall@2, MRR y NDCG. Eso no es un veredicto fallido; es una superficie de
respuesta multiobjetivo a la que se le hizo una pregunta de promoción.

**La ranura existe y está vacía a propósito.** `runtime/world/parameters.py` declara la
clase `MODEL_PARAMETER` —pesos y arquitectura de un órgano— sin ningún parámetro dentro.
Esos seis coeficientes son el primer caso bien planteado de «hiperparámetros sobre los
pesos»: pocos, nombrados, versionados y ya calibrados.


---

# VI · El harness de gemelos causales

`HECHO DE CÓDIGO` + `HECHO EXPERIMENTAL`.

`runtime/life/twins.py` demuestra `X₀ᴬ = X₀ᴮ` **antes** de intervenir, y se niega a
continuar si no se cumple. Sin eso, una diferencia posterior no es atribuible a nada.

**Un gemelo se construye, no se copia.** Un organismo con tensores que son nodos de grafo
no admite `deepcopy`, y reconstruir es además más fuerte: la identidad se comprueba en vez
de heredarse.

La huella cubre las seis piezas longitudinales que el kernel posee: `organism`, `lineage`,
`parameters`, `world`, `autoevolution`, `neural`. La pieza `world` no existía hasta cerrar
H-047 — dos gemelos podían tener la misma huella y mundos distintos.

**Igualdad salvo renombrado.** Medido sobre dos gemelos construidos igual, divergían en 4
de 6 piezas y **todas** las diferencias eran identificadores acuñados dentro de los
payloads —`lin-…`, `life-…`, `episode-…`—: 267 campos en el estado neural y ni uno de
fisiología. No se borran: se canonizan a su ordinal de aparición, de forma consistente en
toda la estructura, así que dos payloads son iguales si lo son salvo un renombrado
coherente. Las claves que terminan en `run_id` se excluyen por **regla**, no por lista: la
lista cerrada ya falló con `dynamic_chain.last_run_id`.

**Observar no muta.** La huella lee sólo payloads ya exportados; no invoca al organismo ni
al mundo. Terrario midió el coste de lo contrario: percibir una sonda avanzaba el estado
recurrente y el contador, y el ORDEN de los exámenes pasaba a formar parte del resultado.

`do(U)` pasa por `apply_parameter_intent`, no por asignación, así que queda en el ledger
con su procedencia y sus hashes de Λ. Una intervención sin rastro es indistinguible de una
deriva.

Prueba: `tests/life/test_twin_harness.py`.

---

# VII · `lab/genesis/` · la fábrica de capacidades · Atlas 05

Lectura del 2026-09-21. **Las seis secciones anteriores mapean `runtime/`** —el
organismo y su andamiaje— y no mencionan `lab/genesis/` ni una vez: cero
ficheros vigilados de 19 861 líneas. Esta sección cubre ese hueco y no repite
nada de ellas.

Corrección de nombres que conviene dejar dicha: este repositorio se llama
`RNE_v16-genesis-v2`, su cartografía se llama «de Genesis» y mapea el runtime,
mientras el directorio literalmente llamado `lab/genesis/` estaba sin mapear. El
nombre del repositorio no determina la ontología de sus subsistemas.

## 7.1 · Qué entra · el espacio de capacidades es aritmética univariada

Una capacidad **no es una entrada en un registro mutable: es un artefacto de
programa inmutable**
([contracts.py:101](lab/genesis/acquisition/contracts.py:101)), con identidad
estructural de AST y sin una línea de Python embebida ni ejecutada.

El lenguaje es cerrado y pequeño
([dsl.py:18](lab/genesis/acquisition/dsl.py:18)):

```
X · CONST · ADD · SUB · MUL_CONST · ABS · SQUARE        7 operadores
una sola variable entera · evaluación total y acotada
```

Y las tareas confirmatorias son seis, nombradas de antemano
([confirmation.py:17](lab/genesis/acquisition/confirmation.py:17)):

```
affine-0  affine-1  ·  abs_affine-0  abs_affine-1  ·  quadratic_simple-0  quadratic_simple-1
```

**Eso es el espacio de adquisición: expresiones enteras univariadas.** No es una
crítica —el propio módulo lo declara: «no es evidencia sobre búsqueda ilimitada
o abierta»
([complete_frontier.py:10](lab/genesis/acquisition/complete_frontier.py:10))—
pero hay que decirlo antes que nada, porque «Genesis adquiere capacidades»
significa exactamente esto y no otra cosa.

## 7.2 · Qué transforma · las reglas tienen nombre y versión

Los cuatro invariantes del método están declarados como constantes, no
escondidos en una función
([contracts.py:24](lab/genesis/acquisition/contracts.py:24)–[27](lab/genesis/acquisition/contracts.py:27)):

```
DATASET_SPLITS              TRAIN · AUDIT · HIDDEN · TRANSFER
CANDIDATE_RANKING_RULE      training_error_then_mdl_then_canonical_program_hash-v1
PROMOTION_RULE              train_exact_audit_once_exact_no_leakage-v1
HUMAN_INTERVENTION_POLICY   no_interactive_corrective_selection-v1
```

La síntesis es **enumerativa determinista y sólo sobre TRAIN**
([synthesis.py:16](lab/genesis/acquisition/synthesis.py:16)), y su identificador
de semántica dice algo que casi nadie escribe: `FIRST_SEEN_BEHAVIOR_REPRESENTATIVE-v1`
existe «para documentar la semántica histórica **en vez de afirmar que la regla
del primer representante fuera correcta para ordenar**». Se congeló una regla
que se sabe imperfecta para poder replicar la evidencia que produjo, y se
escribió al lado la versión ordenada (`ranked_synthesis.py`, 672 líneas).

El ledger de evidencia es una cadena de hashes con verificación
([ledger.py:27](lab/genesis/evidence/ledger.py:27),
[:49](lab/genesis/evidence/ledger.py:49)): cada evento encadena con el anterior
y `verify` recorre la cadena entera.

## 7.3 · Qué produce · una campaña canónica corrió, y promovió

En `rnfe_artifacts/` hay cuatro campañas. Tres son un `LAUNCH` y nada más. La
cuarta, `m7h2b1-e0614aa`, corrió de verdad: **5 560 ficheros, 24 MB**, con CAS,
journals por tarea, y ranuras de auditoría de un solo uso.

Su desenlace, leído de los artefactos:

```
tareas completadas     1 de 6        abs_affine-0
evaluación             AUDIT · 5/5 correctas · exact_pass: true
receta de promoción    genesis-m7-v2-promotion-receipt-h2b1 · status: PROMOTED
tareas sin empezar     5             abs_affine-1 · affine-0/1 · quadratic_simple-0/1
```

**La cadena entera funcionó una vez, de punta a punta.** Frontera auditada →
campaña sellada → síntesis → compromiso de candidato → reclamo de ranura de
auditoría → evaluación exacta → **promoción**.

Y después el lanzador desapareció. El registro de la interrupción es lo más
honesto del subsistema:

```
observed_state    launcher_process_not_present_before_second_journal
recovery_action   NONE
reason            el escritor de journals es create-only y el runner rechaza un
                  journal existente en vez de reconstruir una clausura en
                  memoria. Cambiar eso después de consumir una campaña canónica
                  violaría el congelado de H2B1.
```

Es decir: **un corte de proceso gastó una ranura canónica, y las reglas de
congelado prohibieron correctamente rescatarla.** No se reparó a posteriori para
salvar la corrida. Eso es disciplina, y es también el coste exacto de no poder
reanudar.

## 7.4 · Quién lo consume · nadie

Medido sobre todo el árbol:

| Pregunta | Respuesta |
|---|---|
| ¿Importa `lab/genesis` algo fuera de `lab/` y `tests/`? | **0 ficheros** en `runtime/`, `engines/`, `scripts/`, `exocortex/`, `governance/`, `ingest/` |
| ¿Menciona el runtime `ProgramSkillArtifact` o `PromotionReceipt`? | **0 ficheros** |
| ¿Lee alguien las campañas de `rnfe_artifacts/`? | 2 ficheros nombran la ruta, y son la raíz de almacenamiento del runtime y un default de CLI — ninguno lee una campaña |
| ¿Cuántos tests lo ejercitan? | **70** |

La frase «un G1 promovido es exactamente G0 más esa habilidad concreta» existe
en el docstring de los contratos
([contracts.py:6](lab/genesis/acquisition/contracts.py:6)) y **no existe como
código**: no hay función que componga un organismo con la habilidad promovida.
El artefacto se promueve; no se entrega a nadie.

> **El hecho arquitectónico:** Genesis adquiere, audita y promueve programas con
> una disciplina de evidencia mejor que la de casi todo lo demás del proyecto, y
> lo promovido **no llega al organismo**. La receta `PROMOTED` es el último
> eslabón que existe.

Esto no invalida Genesis. Lo sitúa: hoy es un **laboratorio de adquisición
cerrado sobre sí mismo**, con su propio ledger, su propio congelado y sus
propias ranuras de un solo uso. Lo que falta no es rigor — es la arista que va
de la receta de promoción a `runtime/`.

## 7.5 · Lo que no se sabe

1. **K2** · Si el aislamiento es deliberado. No hay ADR en `canon/normative` que
   diga «Genesis no se integra todavía», y tampoco uno que prometa la arista.
   Sin eso, «aislamiento deliberado» e «integración incompleta» son
   indistinguibles desde el código.
2. **K2** · Qué haría falta para que una habilidad promovida entrase en el
   organismo. El DSL produce funciones `int → int`; ningún punto del runtime
   consume una función así.
3. **K2** · Por qué las tres campañas v3 se detuvieron en `LAUNCH`. El ledger
   registra el lanzamiento y ningún evento posterior.
4. **K1** · `ranked_synthesis.py` corrige la regla de ordenación de v1. Si
   alguna campaña se ejecutó bajo la regla nueva no consta en `rnfe_artifacts/`.

---

# VIII · RNE · qué persiste, qué puede cambiar, y qué tendría que tocar Genesis · Atlas 06

Lectura del 2026-09-21. **§I–§VI ya cubren** el lazo de vida y la propiedad del
estado, la autoridad de parámetros y el ledger de Λ, el régimen de referencia,
lo neural y el harness de gemelos. Esta sección **no los repite**: completa lo
que falta y contesta una pregunta que el Atlas 05 dejó planteada —

> ¿qué tendría que modificar Genesis para convertir una receta `PROMOTED` en
> una capacidad del organismo?

## 8.1 · Hay tres superficies que pueden cambiar, y ninguna acepta un programa

| Superficie | Qué acepta | Estado |
|---|---|---|
| **mandos adaptativos** · `apply_parameter_intent` ([scenario_runner.py:357](runtime/world/scenario_runner.py:357)) | **dos escalares**: `memory_retrieval_limit`, `memory_filter_mode` | **funciona**, con ledger y procedencia (§III) |
| **`MODEL_PARAMETER`** ([parameters.py:42](runtime/world/parameters.py:42)) | pesos y arquitectura de un órgano | **declarada y vacía a propósito** (§V) |
| **componentes mutables** · `SelfModificationPipeline` ([self_modification.py:15](runtime/organism/self_modification.py:15)) | seis políticas y parámetros | **cableada** desde R1 |

Genesis promueve un **artefacto de programa `int → int`** de siete operadores.
**Ninguna de las tres acepta un programa.** La más cercana —`MODEL_PARAMETER`—
está declarada para pesos y arquitectura, no para una función, y está vacía.

Ésa es la respuesta, y no es «falta cablear»: es que **el destinatario no existe
como tipo**.

## 8.2 · El lazo ρₜ · la superficie que sí funciona, y lo que mueve

`autoevolution.py` cierra el lazo y dice su propia historia
([:3](runtime/organism/autoevolution.py:3)): «Hasta R1,
`SelfModificationPipeline` existía pero **nada lo invocaba**: el organismo no
podía proponerse cambios». R1 lo cableó al lazo episódico:

```
degradación sostenida → diagnóstico → propuesta ρₜ → precheck constitucional
→ sandbox → gate de seguridad S-I-E → aplicar sobre mandos REALES
→ ventana de post_window vigilando ΔIoC → commit o ROLLBACK ejecutable
```

Tres propiedades que conviene tener separadas de la promesa:

* **El rollback es ejecutable**, no declarativo: si la media de ΔIoC sale
  negativa se revierten los mandos **y** el estado del organismo al checkpoint
  pre-modificación, y el rollback queda en el linaje.
* **El linaje deja de ser pasivo**: génesis, modificaciones aceptadas y
  rollbacks se registran en `LineageState` y como eventos en storage.
* **Los mandos se alcanzan por closures** para no acoplar `organism → world`.

Y lo que ese lazo puede mover son **dos parámetros de comportamiento del
runner**. Todo el aparato —constitución, sandbox, posterior, gate, ventana,
rollback, linaje— gobierna un límite de recuperación de memoria y un modo de
filtrado.

Eso no es una crítica: es la medida de la distancia entre el mecanismo y su
carga útil actual.

## 8.3 · La partición mutable/inmutable ya está declarada

`self_modification.py` fija de antemano qué puede tocarse
([:15](runtime/organism/self_modification.py:15),
[:23](runtime/organism/self_modification.py:23)):

```
MUTABLES (primera fase)          INMUTABLES (aprobación superior)
  transport_parameters             baseline_semantics
  selection_policy                 constitutional_invariants
  benchmark_policy_experimental    baseline_fixed
  reasoning_activation_policy      constitutional_purity_minimum
  memory_scoring_secondary_weights lineage_identity_anchor
  analogical_lab_parameters
```

Ocho etapas, de `proposal_generation` a `lineage_update`, con
`accept | quarantine | reject` en el medio
([:90](runtime/organism/self_modification.py:90)).

**La partición es la pieza que un integrador necesitaría** y ya existe: dice qué
clase de cosa puede cambiar sin aprobación superior. Lo que no dice es cómo
entraría un programa, porque ninguna de las seis lo es.

## 8.4 · Qué persiste, y en qué unidad

`OrganAdaptiveState` ([adaptive_state.py:20](runtime/organism/adaptive_state.py:20))
es el estado longitudinal por `(organism_id, lineage_id, regime_id, organ_id,
backend_id)`: participación, abstención, aceptación, rechazo, residuo de
calibración, desacuerdo causal, latencias, coste, fallbacks, permanencia en
régimen, indicadores de cambio de punto.

Es **contabilidad de comportamiento del órgano**, no contenido aprendido. Y
encaja con §V: los pesos no se mueven, el estado recurrente sí persiste, y nadie
le da error a la red.

Las acciones de adaptación admisibles son cuatro y están cerradas:
`collect_more_evidence · replay_candidate · hold · quarantine_candidate`.
Ninguna instala nada.

## 8.5 · El «sin regresión» existe, y está del lado aislado

El contrato pide, para el Retention Ledger: qué registra, unidad de capacidad,
línea base, tolerancias, presupuesto global de degradación, dependencias
causales, retiro condicionado, recertificación, linaje.

**No existe ninguna clase `RetentionLedger` en el árbol.** Lo que existe es
`lab/genesis/retention/` ([__init__.py:3](lab/genesis/retention/__init__.py:3)):

```
RetentionAuditPackage · RetentionSurface
BaselineMeasurementReceipt · RetentionDecisionReceipt · RetentionVerdict
RetentionReverificationRequest        ← recertificación
RetentionObservationReceipt           ← medición observada, payload externo
EpistemicStateRef · RetentionEpistemicView · RetentionSurfaceAssessment
RuleAStar · RetentionEvaluation
RetentionFamilyPolicy                 ← presupuesto global: `epsilon_family_total`
RetentionReplay
```

La unidad es `capability_id`; el presupuesto global de degradación es
`epsilon_family_total` ([family.py:9](lab/genesis/retention/family.py:9)), con
una política agregada **conservadora: «los miembros no concluyentes nunca se
omiten»**.

**Y `runtime/` no lo consume: cero ficheros.** Sus únicos consumidores son sus
seis módulos hermanos y ocho tests.

> Es la misma frontera que el Atlas 05: el mecanismo que decidiría si una
> capacidad puede integrarse **sin regresión** está construido, y está del lado
> que no toca al organismo.

## 8.6 · La respuesta, en una frase

Para convertir una receta `PROMOTED` en capacidad del organismo harían falta
tres cosas, y **sólo una existe**:

```
1. un TIPO de destino que acepte un programa        NO EXISTE
   (MODEL_PARAMETER es para pesos y arquitectura, y está vacía)
2. un canal de escritura con procedencia            EXISTE — apply_parameter_intent
3. un juicio de no-regresión                        EXISTE — lab/genesis/retention,
                                                     sin consumidor en runtime
```

El lazo ρₜ demuestra que 2 y 3 **pueden** funcionar juntos: aplica sobre mandos
reales, vigila ΔIoC y revierte. Lo hace con escalares porque es lo único que hay
del otro lado.

## 8.7 · Lo que no se sabe

1. **K2** · Si la ranura `MODEL_PARAMETER` se dejó vacía esperando los seis
   coeficientes de N4 (§V) o cualquier artefacto promovible. El código declara
   la clase y no dice para qué.
2. **K1** · El contrato de conocimiento nombra reparaciones abiertas —CI-VERDAD,
   atomicidad, autoridad de writers— que **no aparecen en ningún árbol**:
   `CI-VERDAD` da 0 coincidencias en genesis-v2 **y** en v16. `CADENA-CAUSAL` sí
   existe, en `canon/provisional/ROADMAP_RNFE_v2.md` —provisional, no
   normativo—. O viven sólo en la conversación, o tienen otro nombre en código.
3. **K2** · Si la partición mutable/inmutable de `self_modification` está
   alineada con las nueve clases de `parameters.py`. Son dos taxonomías de lo
   que puede cambiar, escritas en sitios distintos, y nadie las ha cruzado.
4. **K3** · Qué significaría «sin regresión» para una capacidad que el organismo
   no tenía. La retención mide degradación contra una línea base; una capacidad
   nueva no tiene línea base que degradar.
