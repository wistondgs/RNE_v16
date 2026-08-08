# EA1-C Preregistration V1

Status: `FROZEN_BEFORE_CONFIRMATORY_DATA`

Protocol version: `EA1-C-v1`

Baseline: `dc1e4393621301310f5252e9f8154d66ccaa1975`

Audit reference: `6630258da9d49eccc269f1814ca29efec44f73c6`

## 1. Purpose and claim

EA1-C tests the following claim:

> RNE can maintain at least two causal hypotheses that agree on the initial observations, select a reversible intervention because its predicted outcomes discriminate those hypotheses, receive a previously unavailable canonical outcome, revise its beliefs persistently, acquire the correct causal class within a shared epistemic budget, and improve later decisions.

Transfer of the investigative method is part of the broader EA1 claim but is not executed in EA1-C-v1. It is blocked until a valid `SourceAcquisitionReceipt` exists. EA1-C-v1 establishes source acquisition and the records needed for a later, separately preregistered transfer test.

The claim does not include general intelligence, self-evolution, code rewriting, global architectural superiority, learning from Codex or a local 7B, or universal transfer.

EA1-C-v1 also does not claim open-ended invention of causal hypotheses: each substrate receives the two role-neutral rival candidates for its block. It tests maintenance, intervention-conditioned prediction, informative selection, revision and functional use on causal templates excluded from DEV/DRY_RUN. Open-ended hypothesis formulation requires a later preregistration.

## 2. Frozen scientific decisions

The following decisions cannot change after this document is frozen:

1. Confirmatory capabilities are hidden causal preconditions, observationally confounded rival mechanisms, and deferred consequences.
2. The primary endpoint is valid source acquisition within budget.
3. The inferential baseline is random matched-cost, not passive observation or greedy reward.
4. The two active architectures are MCI+VOI and A11/A12 Scientific Deliberation. Neither is declared a general winner.
5. Codex, local 7B, EML, N4, AutoEvolution and hybrid orchestration are excluded from confirmatory authority.
6. Each instance starts with at least two live rivals plus `unknown/abstain`.
7. Numeric weights and derived ordinal governance states are both recorded; ordinal states cannot invent probabilities.
8. Held-out separation includes mechanism parameters and representation, not merely seed.
9. Only reversible, bounded, observable interventions may consume epistemic budget.
10. Transfer cannot begin until source acquisition has been demonstrated without censoring.

## 3. Arms

| Code | Policy | May update beliefs? | May choose an informative intervention? |
|---|---|---:|---:|
| `C0_PASSIVE` | Observes the natural trajectory | yes | no |
| `C1_GREEDY_REWARD` | Maximizes immediate expected task utility | yes | yes, but never by information value |
| `C2_RANDOM_MATCHED_COST` | Uniform random choice from the architecture-matched proposal set | yes | yes |
| `C3_MCI_VOI` | Maximizes frozen VOI/decision-value score subject to budget | yes | yes |
| `C4_A11_A12_SCIENTIFIC` | A11 predicts per hypothesis; A12 applies defeaters and selects or abstains | yes | yes |
| `C5_ORACLE_CEILING` | Chooses the maximally discriminating admissible test using ground truth | yes | yes |

`C5` is a ceiling and never contributes to the autonomy claim. All non-oracle arms receive identical public state, initial observations, action sets, budgets and outcome interfaces.

Controls are policy codes parameterized by substrate. For the MCI primary contrast, `C2[MCI]` uses exactly C3's hypothesis initialization, predictions, Bayesian updater and proposal set; only the selector is replaced by uniform random. For the A11 primary contrast, `C2[A11]` analogously uses C4's substrate. `C0` and `C1` are instantiated under both substrates for diagnostics. These are matched control instantiations, not additional architectures. A result may only be compared with the control carrying the same substrate tag.

## 4. Scenario allocation

| Family | Role | Primary architecture | Confirmatory? |
|---|---|---|---:|
| `S1_REGIME_CHANGE` | Developmental positive control | MCI | no |
| `S2_HIDDEN_PRECONDITION` | Rival precondition classes | MCI+VOI | yes |
| `S3_DEFERRED_CONSEQUENCE` | Immediate benefit versus delayed harm | A11/A12 | yes |
| `S5_OBSERVATIONAL_CONFOUNDING` | Observational equivalence broken by intervention | MCI+VOI | yes |
| `S4_PIECEWISE_SYMBOLIC` | EML versus EML+N4 shadow pilot | neither confirmatory arm | no |

All six policy codes run on the confirmatory instances; C0/C1/C2 produce the two declared substrate-tagged control instantiations. Secondary head-to-head comparisons remain paired. Primary conclusions remain family-specific.

## 5. Epistemic budget

The common budget is frozen as:

- at most four informative intervention slots per instance;
- one epistemic token per admitted intervention, hence `B_tokens = 4`;
- cumulative normalized intervention cost `<= 4.0`;
- every confirmatory intervention has normalized declared cost `1.0` and invariant-risk allocation `0.25`, hence cumulative maxima `4.0` and `1.0`;
- the same maximum horizon and the same outcome visibility schedule for every arm.

The value four is based only on developmental structure: one theoretically decisive test, one replication opportunity and two recovery/ambiguity slots. It also matches the bounded candidate budget used in prior non-confirmatory MCI transfer development. No confirmatory outcome was used.

Every selection slot exposes exactly six canonical-hash-ordered admissible interventions: exactly two are class-discriminating under the private oracle and four are non-discriminating. Their labels and serialized order are role-neutral, and all six have the same declared cost/risk. `C2[substrate]` samples uniformly from the identical six proposals produced by that substrate. A selection, including a deliberately repeated test, consumes one token. Every arm receives the same one scheduled passive observation per epoch; selection adds one experimental outcome, while abstention adds none. There are exactly four epochs, so abstention cannot create extra exposure. Task reward sacrificed is measured separately and cannot alter the token budget.

An instance that cannot provide its preregistered matched set is replaceable only if detected before assignment, arm initialization and commitment publication. Any later failure remains in intention-to-treat as specified below.

## 6. Theory and selection requirements

Before the first selectable outcome, every non-oracle substrate instance, including controls, must possess:

- at least two `HypothesisCandidate` records with non-zero normalized weights;
- an explicit `unknown/abstain` mass or state;
- a `DivergentPredictionSet` covering every admissible experiment or marking a prediction unavailable;
- a proposal set with cost, risk and reversibility;
- no field derived from hidden mechanism identity.

The `C3` selection score is frozen as:

`score(e) = (EIG(e) + lambda_D * EDV(e)) / (1 + cost(e) + lambda_R * risk(e))`

where EIG is expected reduction in Shannon entropy over active hypotheses and EDV is expected improvement under the public decision-design distribution. `lambda_D = 0.5` and `lambda_R = 2.0`. Unavailable predictions give no EIG contribution; an experiment with incomplete safety fields is inadmissible. Ties are resolved by canonical proposal hash order. Task reward is not a proxy for EIG.

For `C4`, A11 produces one trajectory distribution per `(hypothesis, experiment)`. A12 rejects proposals with safety, model-availability or internal-consistency defeaters, ranks remaining proposals by the same normalized EIG and EDV definitions, and may abstain. Its historical action-decision object is not treated as a belief revision.

EDV is calculated against the public `DECISION_DESIGN_DISTRIBUTION_V1`: the declared distribution over state roles and utility functions, integrated analytically or by a fixed public quadrature grid. The four factual downstream decision probes are generated from a separate sealed RNG stream and are never visible to proposal generation or EDV. Their manifest hash is committed before arm initialization and opened only during final evaluation.

`C1[substrate]` chooses maximum predicted one-step task utility from that substrate's proposals; ties use canonical proposal hash order. `C2[substrate]` uses a recorded counter-based RNG stream derived from the public arm seed, not the hidden mechanism seed.

## 7. Primary endpoint: valid source acquisition

For paired instance `i` and arm `a`, the binary endpoint `A[i,a]` is one only if a `SourceAcquisitionReceipt` satisfies every gate below within four tokens:

1. **Committed acquisition state:** before ground-truth opening, one structural class has posterior weight `>= 0.80`, posterior odds `>= 4:1` over the next class, `unknown_weight <= 0.10`, and the first threshold-crossing class/TheoryState is sealed immutably within budget. Later crossings cannot replace it.
2. **Correct class:** after unsealing, that committed class is structurally equivalent to the hidden causal class. Matching uses causal topology and intervention semantics, never names or IDs.
3. **Held-out prediction:** on eight prespecified `EVALUATION_ONLY` probes spanning the two frozen unseen parameter tuples and two frozen representation transforms, mean log loss improves by at least `0.05` nats/observation over the instance's frozen initial rival mixture. These private evaluator samples are never lived outcomes or belief-update evidence.
4. **Persistence:** the first-crossing class remains top-ranked and non-refuted through the remaining experimental epochs and two fixed post-budget ordinary decision epochs. Those epochs may add canonical evidence but cannot select an informative experiment. If either epoch is absent, the receipt is invalid rather than censored-success.
5. **Functional use:** the common `DOWNSTREAM_EXPLOIT_V1` policy's oracle-optimal action accuracy across four sealed probes improves by at least `0.25` when supplied the committed TheoryState rather than the initial TheoryState, with no additional invariant breach. This exploitation policy is identical within each active/random substrate pair and is not C2's random experiment selector.
6. **Canonical evidence:** every factual evidence reference resolves to the F1A canonical anchor and witness chain.
7. **No prohibited information:** access-log, provenance and schema audits contain no hidden mechanism, seed, target ID, oracle output or future outcome.
8. **No censoring:** the required experiment, held-out probes and persistence checks were actually executed.

Failure of any gate sets `A[i,a] = 0`. A zero-experiment, crashed, prematurely ended or unevaluated run cannot be a success.

## 8. Numeric update and governance policy

All arms, including substrate-matched controls, use the same evidence semantics. Confirmatory S2, S3 and S5 factual targets are Bernoulli. For observed binary outcome `y` after experiment `e`, update each live hypothesis by Bayes' rule:

`w'_h proportional_to w_h * max(P(y | h, do(e)), 1e-12)`.

`P(y|h,do(e))` is the Bernoulli mass `p^y(1-p)^(1-y)` in dimensionless outcome units. For experimental and persistence outcomes, the `unknown` component uses Bernoulli `p=0.5` with initial mass `0.02`; the two rivals start at `0.49` each. Scheduled passive observations use the family-common passive likelihood under both rivals and unknown, so their Bayes factor is exactly one and they cannot move weights. Normalize hypotheses plus unknown to one. A hypothesis with an unavailable likelihood receives the unknown reference likelihood and is marked `revisable`; it is not assigned a fabricated point likelihood. No posterior is rounded before selection or gate evaluation.

Held-out acquired prediction is always the first-crossing posterior predictive mixture `sum_h w_h P(Y|h,e) + unknown_weight * 0.5`; it is not the pure winning hypothesis. The baseline uses the initial `0.49/0.49/0.02` mixture. Both are scored on the identical eight private `EVALUATION_ONLY` samples after arm finalization. Those samples cannot create canonical anchors, ExperienceRecords or BeliefRevisions.

Governance labels are deterministically derived:

- `refuted`: posterior `<= 0.05` and at least one canonical observation has likelihood ratio `P(y|h,e) / max_h* P(y|h*,e) <= 0.10`;
- `revisable`: not refuted and either its latest likelihood was unavailable or it has an unresolved canonical contradiction;
- `active`: non-refuted, evaluable and not revisable;
- system `abstain`: after first checking the committed-acquisition gate, fewer than two non-refuted rivals remain, `unknown_weight >= 0.25`, or no safe proposal has EIG `>= 0.05` nats.

At the first threshold crossing, the ledger seals class ID, TheoryState hash, posterior components, token count and logical time as the candidate portion of `SourceAcquisitionReceipt`. Persistence and held-out gates continue against that immutable candidate; the hidden correctness gate remains unavailable until final opening. These thresholds cannot be tuned in DEV after this version is frozen.

## 9. Confirmatory hypotheses and falsifiers

### H1-S2: active hidden-precondition acquisition

In S2, `C3_MCI_VOI` exceeds `C2[MCI]` in paired valid-acquisition rate.

### H1-S5: active confounding acquisition

In S5, `C3_MCI_VOI` exceeds `C2[MCI]` under the same criteria.

Neither MCI claim is supported unless its own Holm-adjusted exact paired test is significant, its point improvement is at least the `0.20` smallest effect of interest and leakage/matching audits pass. One family cannot rescue the other.

### H2: active deferred acquisition

In S3, `C4_A11_A12_SCIENTIFIC` exceeds `C2[A11]` by the same criteria.

H2 is not supported if its adjusted test fails, point improvement is below `0.20`, delayed outcomes were visible before selection, or the preregistered substrate/dependency audits fail. Immediate reward opportunities are matched by the S3 generator rather than by a post-hoc subgroup.

### Secondary hypotheses

- Active arms require fewer experiments to acquisition than random among acquired pairs.
- Acquisition improves held-out log loss and subsequent decision utility.
- Correct abstention is measured only in the separate non-confirmatory no-positive-information challenge set.
- MCI and A11/A12 have different scenario-specific strengths; this does not establish global superiority.

Secondary outcomes cannot rescue a failed primary claim.

## 10. Ground-truth sealing and outcome ordering

The scenario generator runs behind a sealing interface. It creates canonical hidden-mechanism JSON plus a 256-bit random nonce and publishes only:

`ground_truth_commitment = SHA256(canonical_json || nonce)`

The JSON and nonce enter an oracle-only vault. Low-entropy hashes without a nonce are forbidden. Non-oracle processes receive an allowlisted public projection. Access to the vault is deny-by-default and audited.

For each informative step, ordering is mandatory:

1. create proposals from public state;
2. seal `ExperimentSelectionReceipt` with hash and logical time;
3. verify budget and admissibility;
4. execute the selected intervention;
5. create the factual outcome through `CanonicalOutcomeAuthority`;
6. resolve its anchor and witness;
7. construct `CanonicalOutcomeReference` and `BeliefRevision`;
8. append `ExperimentMemoryRecord` outside `ExperienceStore`.

The receipt must precede the canonical outcome event in the append-only event order. It must not contain the outcome hash, event ID or any field created after intervention execution.

The oracle executes in a separate process with a separate output store. Its selected experiment and predictions remain inaccessible until all non-oracle receipts for that paired block are sealed. The vault is opened only after every arm is finalized. Recomputing the public commitment must reproduce the published hash.

## 11. F1A invariants

EA1-C does not modify or duplicate:

`Observed factual outcome -> CanonicalOutcomeAuthority -> anchor -> witness -> ExperienceRecord -> SituationWisdom`

Proposals, simulations and counterfactuals are never factual outcomes. `BeliefRevision` references the canonical witness. `ExperimentMemoryRecord` is a separate research ledger and cannot write `SituationWisdom`. No proposer creates anchors or writes `ExperienceStore`.

## 12. Missingness, failures and exclusions

- Acquisition failures, budget exhaustion and scientific abstentions are endpoint zero unless all acquisition gates already passed.
- Construction failures may be replaced only before block assignment, arm initialization and commitment publication.
- Any infrastructure failure after assignment, whether before or after an outcome, sets the affected arm acquisition to zero and remains in intention-to-treat analysis. A sensitivity analysis may exclude it but cannot replace the primary result.
- If more than 5% of blocks have infrastructure failures, the campaign is invalidated and no confirmatory claim is made.
- No run is excluded for surprising reward, regret, theory weight or outcome.
- Any hidden-information access, oracle cross-talk or outcome-before-receipt event invalidates the campaign, not merely the affected arm.

## 13. Developmental pilot and transfer block

S4 compares `EML_ONLY` with `EML_PLUS_N4_SHADOW`. N4 starts from historical incremental status `REFUTED`. It advances only if it changes selected experiments and improves acquisition or downstream decisions on held-out mechanisms. Brier, ECE, nDCG or reordered rankings alone are insufficient.

No `MethodTransferReceipt` is executed in EA1-C-v1. A later transfer preregistration may begin only after source acquisition succeeds under the primary definition. It must use structural renaming and representation changes and must not copy actions, thresholds, IDs, `situation_key` values or theories.

## 14. Compute and authority

EA1-C targets 16 GB RAM and 8 GB VRAM. Confirmatory arms use CPU MCI and A11/A12 adapters. No local 7B, H-Net or N4 is required. The S4 N4 shadow pilot uses CPU inference. External models are absent.

## 15. Stop conditions

Implementation must stop before confirmatory execution if ground truth cannot be sealed, outcomes cannot be delayed until after receipt sealing, matched-cost sets cannot be constructed, two live rivals cannot be maintained, intervention-conditioned predictions cannot be produced through reasonable adapters, source acquisition cannot be separated from censoring, or F1A would need modification.

## 16. Frozen artifacts and amendment rule

Before implementation begins, the five EA1 documents are hashed together into a preregistration manifest. Scenario-generator code, contract schemas and analysis code developed later must be reviewed against these documents before any confirmatory mechanism is generated.

No scientific threshold, endpoint, hypothesis order, sample size, exclusion rule or budget may be amended after the first confirmatory ground-truth commitment. Earlier amendments require a new preregistration version, written rationale and fresh confirmatory instance universe. Results from superseded development versions remain non-confirmatory.
