# Cartografía de Genesis

HEAD `364044e` · 2026-09-17 · rama `repair/disturbance-families` · `main` intacto en `cdac5ef`

**Qué es este documento.** Lo que se ha **medido** del código, con `fichero:línea` o con
una corrida ejecutada. Nunca el nombre de un módulo como evidencia. Donde algo no se pudo
verificar, se dice, en vez de rellenarse.

**Cómo caduca.** `scripts/cartografia_check.py` recalcula el sha256 de cada fichero que
este documento cita y lo compara con `docs/CARTOGRAFIA_MANIFIESTO.json`. Una sección cuyo
código cambió queda STALE y no se construye sobre ella hasta releerla. La lista de ficheros
no se mantiene a mano: sale de las citas del propio texto.

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

**La reconstrucción del runner es estructural, no accidental.** `runtime/life/kernel.py:367`
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

**Lo que sigue muriendo: el mundo.** `self.scenario` se construye en el constructor del
runner a partir de un **nombre**, así que el mundo vuelve a su estado inicial cada bloque.
Medido con el `block_size=8` por default: la temperatura observada vuelve a 0.82 en los
pasos 8 y 16. Es violación de I-05 del Canon 2.1 de Terrario («mundo declarado = mundo
ejecutado»). **No reparado** — tripwire en `xfail(strict)` en
`tests/life/test_certificate_continuity.py`.

Pruebas: `tests/organism/test_autoevolution_state.py` · `tests/life/test_autoevolution_continuity.py`
· `tests/life/test_certificate_continuity.py`.

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

**Dos pestillos de la misma familia.** `runtime/life/kernel.py:753` documenta el primero,
en la rama de rollback, ya reparado — *«un pestillo del que no se sale. Medido: muerte en
el paso 32»*. El segundo estaba en la rama de cuarentena, `runtime/life/kernel.py:698`, y
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
