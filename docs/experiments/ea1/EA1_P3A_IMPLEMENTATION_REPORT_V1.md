# EA1 P3A — Neutral Experimental Substrate Report

## A. Scope

- Repository: `Necktral/RNE_v16`
- Scientific base / initial HEAD: `ae1d7f3ba558004bddcbdcb150b388c423f604c7`
- Protected F1A parent: `dc1e4393621301310f5252e9f8154d66ccaa1975`
- Branch: `codex/ea1-neutral-substrate-v1`
- Worktree: `/home/wis/Desarrollo/RNE_v16_worktrees/ea1-neutral-substrate-v1`
- Preflight: exact HEAD and parent, clean tree, all five frozen documents present, no pre-existing runtime changes.

This phase implements neutral infrastructure only. It executes no confirmatory instance, campaign, architecture policy, learning, training, MCI+VOI, A11/A12 adapter, Codex, 7B, N3, N4, H-Net, EML, AutoEvolution or MethodTransfer.

## B. Files changed

All production changes are new and isolated. No existing F1A, MCI, A11, A12, storage, scenario-runner, Teacher or model file changed.

- `runtime/experiments/__init__.py`: neutral experiment namespace.
- `runtime/experiments/ea1/canonical.py`: finite canonical serialization, hashes and stable identities.
- `runtime/experiments/ea1/contracts.py`: typed EA1 artifacts and frozen constants/enums.
- `runtime/experiments/ea1/ledger.py`: append-only, hash-chained, idempotent event ledger over `StorageFacade`.
- `runtime/experiments/ea1/budget.py`: single four-token/four-epoch cost/risk implementation.
- `runtime/experiments/ea1/sealing.py`: SHA-256 ground-truth commitment with 256-bit nonce and isolated evaluator/oracle capabilities.
- `runtime/experiments/ea1/controls.py`: C0/C1/C2/C5 control shells only.
- `runtime/experiments/ea1/scenarios.py`: deterministic DEV/DRY smoke fixtures for S1/S2/S3/S5.
- `runtime/experiments/ea1/evaluator.py`: immutable first crossing and conjunctive source-acquisition gates.
- `runtime/experiments/ea1/harness.py`: temporal state machine and read-only F1A witness resolver.
- `tests/experiments/ea1/test_substrate.py`: T1–T6 and T9–T15 substrate tests.
- `tests/experiments/ea1/test_f1a_boundary.py`: T7/T8/T13/T15 real SQLite/F1A boundary tests.
- This report: required implementation evidence.

## C. Contracts implemented

The package represents `HypothesisCandidate`, immutable/versioned `TheoryState`, `DivergentPredictionSet`, non-authoritative `ExperimentProposal`, pre-outcome `ExperimentSelectionReceipt`, read-only `CanonicalOutcomeReference`, version-chained `BeliefRevision`, separate `ExperimentMemoryRecord`, and candidate/final `SourceAcquisitionReceipt`.

Selection receipts contain the public candidate set, selected proposal/action, policy, public scores, logical time, seed/draw when applicable, before/after budget, remaining tokens and stable receipt hash. Their schema has no outcome, future-state, canonical posterior event, oracle, hidden-mechanism or nonce field.

The acquisition evaluator freezes posterior `>=0.80`, odds `>=4:1`, unknown `<=0.10`, exact structural signature plus interventional MAE `<=0.10`, eight held-out probes with delta `>=0.05` nats, two persistence opportunities, four functional probes with gain `>=0.25` and zero invariant breaches, canonical F1A evidence, no prohibited information, no censoring and nonzero evaluation.

## D. Temporal integrity

`NeutralExperimentHarness` enforces:

`TheoryState -> proposal set -> sealed selection -> external execution -> existing F1A outcome resolution -> BeliefRevision -> experimental memory -> acquisition candidate/final`.

An outcome cannot be attached before selection. A reference must match both the sealed receipt and the F1A witness's committed intervention. The integration test reconstructs this exact order from the persistent ledger.

## E. Leakage matrix

| Data | C0/C1/C2/future C3/C4 | C5 oracle route | Final evaluator route |
|---|---:|---:|---:|
| Public scenario/actions/commitment | visible | visible | visible |
| Costs, risk, proposal scores, budget | visible | visible | visible |
| Hidden mechanism/action roles/true class | hidden | private read | private read |
| Nonce/opening | hidden | hidden | isolated final opening |
| Oracle choice internals | hidden | local only | not needed |
| Future/delayed outcome before horizon | hidden | hidden | unavailable until horizon |

Public action serialization contains no discriminator label or hidden causal class. Ground truth is kept in a private bundle; arms receive `PublicScenario` only.

## F. Budget parity

`EpistemicBudget` is the only implementation used by neutral selection: four epochs, four tokens, aggregate cost four and aggregate risk one. All admissible actions cost one, risk `0.25`, and are reversible. Exact replay returns the prior consumption and cannot spend twice. C2[MCI] and C2[A11] use identical ordered public proposals, action set and RNG seed; the substrate tag does not alter selection.

## G. F1A separation

Production EA1 code neither imports nor obtains `_issue_canonical_outcome_authority` or `CanonicalOutcomeAuthority`. `CanonicalOutcomeResolver` only scans an existing canonical event and derives/revalidates its `ObservedOutcomeWitness`. The private issuer appears only in the integration test to emulate the existing factual owner.

EA1 artifacts persist as `ea1.experimental.event`, never as scale `experience`. `ExperienceStore.record` rejects their concrete types; generic storage rejects attempts to publish them as reserved canonical outcomes; `SituationWisdom.n` remains zero after experimental ledger writes.

## H. Persistence and idempotency

The event namespace uses stable event/artifact IDs, canonical content hashes, sequence, logical time, previous hash and entry hash. A reconstructed SQLite-backed ledger verifies the whole chain. Exact replay appends nothing. Same identity with different content quarantines the run in-process and fails closed.

## I. Scenario fixtures

- S2: rivals share passive evidence; a hidden precondition changes two intervention predictions; four actions remain nondiscriminating.
- S3: distinguishing outcome is unavailable before horizon two; immediate reward is separately represented and cannot enter selection receipt as future state.
- S5: passive Bayes factor is exactly one while two `do(e)` predictions diverge.

Every fixture has exactly six equal-envelope public actions, two privately discriminating and four private distractors. Only DEV and DRY splits are constructible; CONFIRM generation is rejected.

## J. Source acquisition evaluator

The candidate is sealable only after all arms finalize and fixes the first crossing's class, state hash, posterior, odds, unknown mass, token count and logical time. Later regression is recorded without replacing the candidate. A completed run with no crossing is invalid. Missing probes/opening/evidence is incomplete; every censor reason and zero evaluations are non-success.

Boundary tests cover exact threshold acceptance and immediately failing values for held-out delta, structural match/MAE, persistence, functional gain/breaches, canonical evidence, prohibited information and censoring.

## K. Tests

- EA1 P3A: `45 passed`.
- F1A plus active contract targets: `55 passed`.
- Storage suite: `42 passed, 8 skipped` (PostgreSQL unavailable/not used; SQLite is isolated and exercised).
- Full repository, before the final evaluator-field hardening: `1580 passed, 30 skipped, 32 xfailed, 1 xpassed`, 12 pre-existing warnings, in 627.43 s.
- EA1 P3A rerun after final hardening: `45 passed`.

No project database or confirmatory data was used.

## L. Residual limitations

P3A makes no EA1 capability or architecture claim. Fixtures are deterministic smoke substrates, not the preregistered n=216 sample. Oracle security targets accidental harness leakage, not a hostile host administrator. C3 MCI+VOI and C4 A11/A12 remain unimplemented and must be built in separate branches against these public contracts.

## M. Verdict

`EA1_P3A_PASS`

The neutral substrate satisfies P3A's acceptance gates without changing the frozen science or protected F1A runtime.
