# EA1 P3B — MCI+VOI Epistemic Policy Adapter Implementation Report V1

## A. Exact base, branch and SHA

- Authorized base: `892f0f8ae57f90faa2bdd078df46335116508a80` (`EA1_MCI_COMPATIBILITY_BASE`).
- Base parent: `b2e01ae792f4e690587f4add5aabeaca020ae49f`.
- Implementation branch: `codex/ea1-mci-voi-v1`.
- Worktree: `/home/wis/Desarrollo/RNE_v16_worktrees/ea1-mci-voi-v1`.
- The exact implementation commit SHA is assigned by the commit containing this report and recorded in the final handoff. A Git commit cannot contain its own SHA without changing that SHA.

No confirmatory instance, campaign, training job, external model, or `CONFIRM` path was executed.

## B. Files changed

New adapter modules:

- `runtime/experiments/ea1/mci_adapter.py`: lossless TheoryState/rival mapping, per-rival historical MCI TransitionSpec construction, H×action prediction, MCI snapshots and reload.
- `runtime/experiments/ea1/mci_voi_policy.py`: frozen EIG, EDV, cost/risk normalization, abstention, canonical-hash tie-break and proposal construction.
- `runtime/experiments/ea1/mci_revision_adapter.py`: read-only F1A evidence revalidation, historical MCI evidence ingestion and official EA1 Bayesian BeliefRevision.
- `runtime/experiments/ea1/mci_arm.py`: common MCI substrate preparation plus C3 and matched C2 selector wiring.

Minimal neutral-substrate extensions:

- `contracts.py`: C3/MCI identities and auditable optional model, prediction, VOI, receipt and overlay-provenance fields.
- `scenarios.py`: the two supplied public Bernoulli rival models for DEV fixtures; no true-class label is exposed.
- `harness.py`: prediction-set persistence, complete VOI receipt fields and sealed zero-budget abstention.
- `controls.py`: C2 samples the same proposals in canonical artifact-hash order.
- `ledger.py`: artifact identity now prioritizes the artifact's canonical ID. This fixes collisions between distinct repeated selections of the same action without changing scientific semantics.

Tests added:

- `tests/experiments/ea1/test_mci_architecture.py`
- `tests/experiments/ea1/test_mci_voi_adapter.py`
- `tests/experiments/ea1/test_mci_revision_adapter.py`

## C. Proof that MCI core remains unchanged

The recovery manifest was re-evaluated after implementation. All 15 frozen production paths have the same SHA-256 recorded at recovery and source commit `2b32e5dd9dacc4358697b8570ce4cab0f15c9cfb`: **15/15 unchanged**.

No file below `runtime/symbolic/mci/` and no `runtime/symbolic/schemas.py` file differs from base `892f0f8...`. The new CI gate reads `EA1_MCI_CORE_RECOVERY_MANIFEST_V1.json` and verifies this on every P3B test run.

## D. TheoryState mapping

`TheoryState` remains the only official epistemic state. `MCITheoryAdapter` requires exactly the two supplied rival IDs, preserves each candidate's structural class, scope, assumptions, provenance and public Bernoulli model, and maps official weights without renormalizing or inventing probabilities.

Each rival becomes a separate historical MCI `TransitionSpec` and `MCIRuntime` working representation. The candidate is also registered under the same ID in the historical MCI hypothesis ledger. A working set stores the canonical TheoryState hash and fails closed if IDs, version, weights, unknown mass or state hash disagree. It cannot add a third confirmatory hypothesis.

## E. Prediction semantics

For every supplied hypothesis and public intervention, `MCIPredictionAdapter` executes the historical `TransitionCompiler` over the corresponding public-model `TransitionSpec`. Each cell records:

- hypothesis and intervention IDs;
- Bernoulli success probability;
- spec version and SHA-256;
- overlay ID when present;
- predictor ID;
- TheoryState version and logical time;
- provenance `SIMULATED/MODEL_BASED`.

The complete matrix is persisted before proposals and referenced by ID from proposals and the common `ExperimentSelectionReceipt`. Missing public-model cells are recorded as unavailable, made inadmissible and receive zero EIG/EDV; no point likelihood is fabricated.

## F. Exact VOI implementation reference

The implementation follows `EA1_PREREGISTRATION_V1.md` sections 6 and 8 and `EA1_SCENARIO_SPEC_V1.md` section 3:

`score(e) = (EIG(e) + 0.5 * EDV(e)) / (1 + cost(e) + 2.0 * risk(e))`.

- EIG is expected reduction of natural-log Shannon entropy after both Bernoulli outcomes using current H1/H2/unknown weights and unknown likelihood `0.5`.
- EDV is expected improvement over `DECISION_DESIGN_DISTRIBUTION_V1`: two equiprobable class-dependent roles and two equiprobable recovery/control roles, with utilities `1.0/0.0/0.60/0.50` exactly as frozen.
- Cost and risk remain distinct terms; immediate task reward is stored separately and is never an EIG proxy.
- Ties use canonical proposal artifact hash, independent of input-array order.
- Abstention occurs at the frozen conditions: fewer than two non-refuted rivals, unknown mass `>= 0.25`, or no admissible proposal with EIG `>= 0.05` nats. It consumes no token and creates no factual authorization.

Golden and boundary tests verify EIG, EDV, denominator and final score numerically, including zero-information and unavailable cases.

## G. Public substrate parity C2/C3

`MCIArmAdapter.prepare` creates one immutable public substrate hash, MCI working set, prediction set and six-proposal batch. C3 and `C2[MCI]` consume that exact same batch. C3 applies MCI VOI; C2 replaces only selection with its recorded counter-based random stream over canonical proposal hashes.

Tests prove equal public substrate, proposal-set hash, candidate IDs, action envelope, factual token/cost/risk consumption and model access. Names, array order, scenario ID and public commitment changes do not change the C3 decision when action identities and supplied public models are unchanged.

Compute is recorded separately: H×action simulations begin with zero factual interventions and zero canonical outcomes.

## H. Leakage and dependency matrix

| Possible source | Prediction/policy dependency | Result |
|---|---:|---|
| Supplied public TheoryState/rivals/actions | yes | allowed |
| Public Bernoulli intervention tables | yes | allowed |
| Scenario/action names or serialized order | no | PASS |
| Ground-truth commitment contents | no | PASS |
| True class/discriminating labels | no | PASS |
| Oracle/SealedGroundTruth | no import/call path | PASS |
| SourceAcquisitionEvaluator/held-out evaluator | no import/call path | PASS |
| Future or factual outcome before selection | no field/path | PASS |
| N4/runtime.neural | no dependency | PASS |

EA1 acquisition held-out probes never enter the MCI learning buffer. Only post-selection canonical F1A evidence can reach it.

## I. CanonicalOutcome bridge

`CanonicalEvidenceBridge` owns no canonical authority. It accepts only an existing `CanonicalOutcomeReference` plus its sealed common selection receipt, resolves exactly one persisted `organism.life_transition.committed` event, reconstructs and revalidates its F1A witness, checks receipt/intervention/source-record/witness/outcome-hash equality, and extracts only the allowlisted canonical binary field.

Raw mappings, predictions, simulated values, noncanonical objects, mismatched references and divergent replay fail closed. The bridge imports neither the private authority issuer nor `CanonicalOutcomeAuthority`.

## J. BeliefRevision mapping

After bridge validation, `MCIOutcomeAdapter`:

1. evaluates the observed binary outcome under both persisted H×action predictions;
2. applies the frozen Bayes update with likelihood floor `1e-12` and unknown likelihood `0.5`;
3. derives active/refuted labels using the frozen posterior and likelihood-ratio conditions;
4. feeds one content-addressed `TransitionEvidence` per rival into historical MCI learning;
5. creates a versioned successor `TheoryState` and common `BeliefRevision`;
6. records `(TheoryState, BeliefRevision, overlay)` provenance and the derived MCI-state hash.

JTMS/overlay state is auxiliary. It neither replaces the official posterior nor creates an acquisition flag. Nondiscriminating evidence leaves all numeric weights unchanged and does not promote an overlay. Later contradictory canonical evidence can reduce prior support, revive a previously refuted rival and increase unknown mass rather than lock a conclusion irreversibly.

## K. Persistence and downstream effect

The common experiment ledger persists prediction set, proposals, selection, canonical reference, BeliefRevision and an `ExperimentMemoryRecord` containing the derived MCI snapshot. `MCIStateRestorer` reconstructs the latest official TheoryState from the revision and restores/rebuilds the MCI hypothesis ledgers and overlays against the supplied public rivals.

The DEV downstream gate starts at `0.49/0.49/0.02`, selects a uniquely highest-score intervention, receives canonical evidence favoring H1, persists and reloads, then recomputes scores. The next uniquely highest-score intervention changes because the posterior changes expected information/decision value. The restored working snapshot equals the pre-destruction snapshot.

Exact replay creates no second token, selection, revision, evidence ingestion or overlay update. A replay with divergent content fails closed.

## L. S2/S5 DEV results

- S2 hidden-precondition DEV: exactly two public rivals map losslessly; the historical compiler emits 12 H×action predictions; exactly two of six actions diverge; VOI selects an informative action; canonical evidence produces a persistent revision.
- S5 observational-confounding DEV: passive input leaves `0.49/0.49/0.02` unchanged; only the two intervention-conditioned cells diverge and can produce information value; action names, ordering and commitment do not identify them.
- No `n=216`, confirmatory generator, held-out acquisition evaluator or claim comparison against random was executed.

These are mechanism gates, not evidence that C3 outperforms C2.

## M. F1A separation

No F1A production file changed. MCI prediction sets, proposals, TheoryState, VOI records and MCI snapshots are rejected by `ExperienceStore` and cannot change `SituationWisdom`. The adapter cannot mint anchors, witnesses or canonical outcomes. Factual execution remains exclusively behind the existing neutral harness authorization and F1A owner.

The internal overlay changes only the MCI derived model. Explicit tests prove it cannot modify sealed hidden-world contents, public commitment or evaluator state.

## N. Tests

- New P3B gates T1–T23: **23 passed**.
- Recovered historical MCI suite: **28 passed**.
- P3A regression: **45 passed**.
- F1A targeted regression: **55 passed**.
- Storage regression: **42 passed, 8 skipped** (PostgreSQL-dependent).
- Combined EA1 suite: **68 passed**.
- Full repository suite: **1635 passed, 30 skipped, 32 xfailed, 1 xpassed**, zero failures, 12 pre-existing warnings.

## O. Limitations

- P3B implements and tests DEV policy mechanics only. It does not generate or execute confirmatory instances and cannot support a superiority claim.
- The neutral factual runner must include the allowlisted `ea1_binary_outcome` field in its already-authoritative F1A factual payload; P3B does not create that payload.
- Historical MCI persistence remains component-level. P3B stores a derived snapshot in the separate experiment ledger and rebuilds it against the official TheoryState and supplied rivals.
- Open hypothesis generation, transfer, C4, A11/A12, EML, N3/N4, H-Net, Codex, local 7B, AutoEvolution and training remain absent.
- Source acquisition, held-out functional gain, first-crossing validity and confirmatory superiority remain evaluation responsibilities outside this policy adapter.

## P. Verdict

`EA1_P3B_PASS`

C3 is implemented and ready for independent review. This verdict does not state that C3 beats random matched-cost.
