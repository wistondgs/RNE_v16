# EA1_P3A_H1_ACTION_LEAK_FIREWALL_REPORT_V1

## A. Exact base, branch and target

- Repository: `Necktral/RNE_v16`
- Mandatory base and starting HEAD: `b2e01ae792f4e690587f4add5aabeaca020ae49f`
- Base parent: `ae1d7f3ba558004bddcbdcb150b388c423f604c7`
- Branch: `codex/ea1-p3a-action-leak-firewall-v1`
- Starting worktree: clean, with no untracked runtime artifacts.
- P3A preflight regression: `45 passed`.
- Final implementation SHA: reported in the handoff because this report is included in that same single commit.

The branch was created directly from P3A. Commit `f59c07191b065adb48b38fc949ec65f0d388b4df` was not used as base or modified.

## B. Original counterexample reproduced

Before changing source, the independent first-two probe was run over the fixed matrix:

- families: S2 and S5;
- splits: DEV and DRY;
- seeds: 1 through 100;
- total: 400 fixtures.

Result:

- predicted set: public positions `(0, 1)`;
- exact successes: `400/400`;
- failures: `0/400`;
- exact-set accuracy: `1.0`.

Of the 15 possible fixed position pairs, `(0,1)` was the sole perfect pair; all other pairs scored `0/400` before the fix.

## C. Root cause

`make_smoke_fixture` created the canonical action pool, shuffled it once, assigned the hidden discriminating role to the first two elements, and published that same shuffled list. Thus one data structure simultaneously represented hidden role order and public presentation order:

`single shuffled list → hidden roles + public tuple`.

The reviewer finding therefore matched the actual implementation. No root-cause substitution was needed.

## D. Exact changed files

1. `runtime/experiments/ea1/scenarios.py`
   - separates hidden action order from public presentation order;
   - preserves the historical hidden stream and complete hidden world;
   - adds one deterministic permutation helper.
2. `tests/experiments/ea1/test_action_leak_firewall.py`
   - adds H1-only structural, leakage, metadata, reproducibility, equivariance and causal-integrity gates.
3. `docs/experiments/ea1/EA1_P3A_H1_ACTION_LEAK_FIREWALL_REPORT_V1.md`
   - records implementation and QA evidence.

No ledger, F1A, MCI, C3, VOI, revision adapter, evaluator or acquisition file changed.

## E. Hidden-role generation

The generator now first creates a canonical pool of six action identities. Hidden role order is then produced by a dedicated deterministic permutation object using the historical domain:

`f"{family.value}:{seed}:{split}"`.

The first two elements of this private order remain the two discriminating interventions. S5 low/high polarity, H1/H2 hidden predictions, oracle action and immediate-reward assignment all continue to use this same hidden order.

Keeping this historical domain is deliberate: an H1 test reconstructs the P3A algorithm independently and compares the complete hidden dictionary for all 400 fixed fixtures. Equality is exact for:

- structural class;
- hidden precondition;
- two discriminating and four nondiscriminating IDs;
- potential outcomes;
- H1/H2 prediction tables;
- oracle action;
- passive Bayes factor;
- immediate rewards.

Result: complete hidden world unchanged in `400/400` cases.

## F. Public-order generation

Public presentation is generated separately from the same canonical action pool with a second `random.Random` instance and a distinct deterministic domain:

`f"{family.value}:{seed}:{split}:public-order-v1"`.

The arm receives only the final public action tuple. It does not receive either RNG object, either permutation domain, the hidden order, an inverse mapping or a hidden-role index.

For the same family/seed/split, action semantics, hidden roles and public order replay exactly. No global RNG or process entropy participates in those values. The pre-existing sealed commitment nonce is outside the presentation-order mechanism.

## G. Public ID and metadata analysis

Public action identity remains the P3A identity:

`stable_id("action", {"scenario": scenario_id, "slot": canonical_slot})`.

The canonical slot identifies the intervention definition; it is not the index in the hidden permutation and is not derived from discriminating status. Labels (`probe-1` through `probe-6`) and public channel parameters are likewise unchanged from P3A.

Across the fixed 400-fixture matrix, every public label appears as discriminating in some fixtures and nondiscriminating in others. Every public position also contains both roles.

Serialized `PublicScenario` payloads were scanned for:

- `hidden_role`;
- `discriminator` / `discriminating`;
- `secret_rank`;
- `source_slot`;
- `hidden_index`;
- `evaluator_class`;
- `role_assignment_seed`;
- `inverse_mapping`.

No forbidden metadata was present.

## H. 400-fixture positional probe

The reviewer-equivalent probe was rerun outside the test file after the fix over the same fixed matrix.

- first-two successes: `40/400`;
- failures: `360/400`;
- exact-set accuracy: `0.10`;
- perfect: no.

Every public position contained discriminating actions in some fixtures and nondiscriminating actions in others.

## I. All 15 fixed-position-pair probes

Exact hidden-set identification counts after the fix:

| Pair | Successes / 400 |
|---|---:|
| (0,1) | 40 |
| (0,2) | 14 |
| (0,3) | 24 |
| (0,4) | 29 |
| (0,5) | 34 |
| (1,2) | 21 |
| (1,3) | 28 |
| (1,4) | 34 |
| (1,5) | 17 |
| (2,3) | 29 |
| (2,4) | 22 |
| (2,5) | 32 |
| (3,4) | 33 |
| (3,5) | 26 |
| (4,5) | 17 |

Perfect fixed pairs: none. The leak was not moved to another pair.

## J. S2 integrity

- Passive observation remains `MID` and insufficient.
- Hidden precondition remains sealed.
- Exactly two H1/H2 intervention predictions differ.
- Exactly four actions remain nondiscriminating.
- Potential outcomes are exactly those of P3A for the same fixture identity.
- All six actions retain cost `1`, risk `0.25` and reversibility `True`.

No superiority measurement was run.

## K. S5 integrity

- Passive Bayes factor remains exactly `1.0`.
- Passive observation remains `MID`.
- Exactly two interventions separate the hidden rivals.
- Low/high causal outcomes and oracle identity are exactly unchanged for every fixed fixture.
- Public position no longer reveals the discriminating set.

## L. P3A regression and QA

QA was executed in the required order:

1. Original exploit before fix: `400/400` reproduced.
2. Single fixture/publication fix implemented.
3. H1 targeted suite: `6 passed`.
4. External positional and metadata probe: first-two `40/400`; no perfect pair.
5. S2/S5 integrity: included in the six H1 tests over 400 fixtures.
6. Existing P3A suite unchanged: `45 passed`.
7. F1A targeted rerun was not required because no F1A file/import surface changed.
8. Full repository: `1590 passed, 30 skipped, 32 xfailed, 1 xpassed`, 12 pre-existing warnings, zero failures, in `610.39s`.

## M. No scientific changes

The patch changes only how the already-defined public actions are ordered. It does not change:

- number or semantics of actions;
- number or identity of hidden roles for any fixed fixture;
- costs, risks or reversibility;
- intervention outcomes or hidden prediction tables;
- priors, epochs, budget or sample design;
- scenario-family definitions;
- VOI or acquisition gates;
- Holm correction or analysis plan.

All controls continue to receive the single common `PublicScenario.actions` tuple. There is no C3-specific presentation.

## N. No CONFIRM

Only DEV and DRY fixture construction was used. No CONFIRM seed, `n=216`, confirmatory manifest, confirmatory outcome or campaign was generated or opened.

## O. Verdict

`EA1_P3A_H1_PASS`

### Final questions

1. **¿Se reprodujo `400/400` antes del fix?** SÍ.
2. **¿Qué mecanismo exacto causaba el leakage?** Una única lista barajada asignaba `actions[0:2]` como hidden discriminators y luego se publicaba sin una permutación independiente.
3. **¿El hidden role assignment es ahora independiente del public presentation ordering?** SÍ: canonical pool → hidden historical permutation, y separadamente canonical pool → public-order-v1 permutation.
4. **¿Algún public ID conserva información del hidden slot?** NO. Conserva sólo la identidad canónica de la intervención; cada identidad/label ocupa ambos roles en la matriz fija.
5. **¿Cuántas veces acierta ahora `positions[0:2]` sobre 400 fixtures?** `40/400` (`0.10`).
6. **¿Algún otro par fijo logra `400/400`?** NO; el máximo es `40/400`.
7. **¿Siguen existiendo exactamente dos discriminantes por epoch?** SÍ, junto con cuatro no discriminantes.
8. **¿Cambió alguna semántica causal S2/S5?** NO; el hidden world completo coincide con P3A en 400/400.
9. **¿Cambió alguna decisión del preregistro?** NO.
10. **¿Se ejecutó CONFIRM?** NO.
