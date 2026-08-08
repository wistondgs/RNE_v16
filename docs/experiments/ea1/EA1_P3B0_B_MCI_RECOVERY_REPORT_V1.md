# EA1 P3B0-B — MCI Core Compatibility Base Recovery Report V1

## A. Base and provenance

- Exact P3A base: `b2e01ae792f4e690587f4add5aabeaca020ae49f`.
- MCI extraction source: `2b32e5dd9dacc4358697b8570ce4cab0f15c9cfb`.
- MCI lineage origin: `a7ea25efb8c72cbf2ae95abed285016b18e111bc`.
- Recovery strategy: `EXTRACT_MIXED_CLOSURE`.
- Recovery branch: `codex/ea1-mci-core-recovery-v1`.

The recovery began from the exact P3A commit in a separate, clean worktree. Production files were extracted directly from the audited source commit before compatibility tests or documentation were added.

## B. Recovery manifest

`EA1_MCI_CORE_RECOVERY_MANIFEST_V1.json` records the P3A base, source and lineage commits, recovery strategy, exclusions, and per-file Git blob ID and SHA-256 provenance. All 15 production entries have status `EXACT`; each recovered SHA-256 equals its source SHA-256 and each compatibility-modification field is null.

## C. Exact file closure

The recovered production closure is exactly:

1. `runtime/symbolic/schemas.py`
2. `runtime/symbolic/mci/__init__.py`
3. `runtime/symbolic/mci/conditions.py`
4. `runtime/symbolic/mci/contracts.py`
5. `runtime/symbolic/mci/compiler.py`
6. `runtime/symbolic/mci/specs.py`
7. `runtime/symbolic/mci/causal_learning.py`
8. `runtime/symbolic/mci/hypothesis_ledger.py`
9. `runtime/symbolic/mci/hypothesis_mapping.py`
10. `runtime/symbolic/mci/provider_protocol.py`
11. `runtime/symbolic/mci/jtms.py`
12. `runtime/symbolic/mci/planner.py`
13. `runtime/symbolic/mci/regime_detector.py`
14. `runtime/symbolic/mci/self_model.py`
15. `runtime/symbolic/mci/runtime.py`

No boundary detector, rollout engine, safety contract, overlay translator, scale/morphism, transfer package/ledger, historical world, ScenarioRunner wiring, neural runtime, training code, or campaign was recovered.

The recovered historical test surfaces are structural learning, regime change, and multistep planning. A core-only subset of the historical integrated tests was reconstructed without the historical ScenarioRunner integration. Recovery-only tests cover provenance, architecture, dependency isolation, stable evidence identity, and snapshot/reload.

## D. Compatibility changes

### TYPE A — Mechanical compatibility

Zero. The exact historical production closure imports and passes its behavioral tests on P3A without import, typing, export, or fixture-path patches.

### TYPE B — Semantic compatibility

Zero. No evidence, hypothesis, planner, overlay, JTMS, or regime semantics were changed.

## E. Historical behavioral gates G1–G10

| Gate | Evidence | Result |
|---|---|---|
| G1 | TransitionSpec construction, canonical hashing, immutability, and validation tests | PASS |
| G2 | 10,000 deterministic Python/SMT comparisons for each of three scenario specifications (30,000 total) | PASS |
| G3 | Replayed identical TransitionEvidence has the same content identity; changed evidence has a different identity | PASS |
| G4 | Repeated discrepant observations learn and promote a parameter overlay | PASS |
| G5 | Persistent conditional discrepancies learn a hidden precondition | PASS |
| G6 | A promoted overlay changes the effective model and later contrary evidence rolls it back | PASS |
| G7 | New-runtime snapshot/reload gate described below | PASS |
| G8 | Persistent anomaly produces regime segmentation/change detection | PASS |
| G9 | JTMS retracts an obsolete belief while preserving supported alternatives/refinements | PASS |
| G10 | Planner consumes the updated model and, after reload, produces the same learned-model plan | PASS |

## F. Snapshot/reload

The new recovery gate creates an MCI runtime, supplies sufficient evidence to promote a non-default parameter overlay, submits hypothesis-ledger state, and creates JTMS state. It snapshots the overlay, hypothesis ledger, and JTMS, discards the original runtime, and creates a fresh runtime from the same base specification.

The fresh runtime restores the overlay and hypothesis ledger through the historical restore APIs. Because the historical JTMS exposes a snapshot but no aggregate restore method, the test reconstructs its beliefs and justifications through its public historical APIs. It then proves equality of the effective-model hash, active overlay, hypothesis ledger, relevant JTMS snapshot, and learned planner result. The restored planner result also differs from the untouched baseline model, demonstrating actual consumption rather than merely serialized state equality.

## G. N4 separation

PASS. A subprocess blocks every `runtime.neural` import, imports MCI, compiles a historical transition model, and executes it successfully. Static inspection also finds no `runtime.neural` dependency in the recovered MCI package. The only recovered non-MCI production dependency is `runtime/symbolic/schemas.py`; SMT behavior uses the already-present `z3-solver` dependency.

## H. F1A separation

PASS. Static architecture checks reject references from MCI to `ExperienceRecord`, `ExperienceStore`, `MemoryRecord`, canonical-outcome authority, canonical-experience writes, teacher scars/proposals, and committed life-transition events. No new MCI path writes experience or outcomes, and no EA1 path calls historical `MCIRuntime.observe_outcome`.

The historical method remains inside the exact MCI blob but is neither connected to EA1 nor granted factual authority.

## I. P3A isolation

PASS. MCI is importable and testable but passive. No default runtime path, feature flag, EA1 adapter, TheoryState, EA1 ledger, EpistemicBudget, ground-truth seal, oracle boundary, source-acquisition evaluator, experiment receipt, or ScenarioRunner was changed or wired to MCI.

## J. Test totals

- Exact historical MCI gates before any authored compatibility artifact: **22 passed**.
- Final selected MCI recovery suite: **28 passed** (22 historical plus 6 recovery/compatibility gates, including snapshot/reload).
- P3A regression targets: **45 passed**.
- F1A experience/canonical-authority/contract targets: **55 passed**.
- Storage regression targets: **42 passed, 8 skipped** (PostgreSQL-dependent cases).
- Full repository suite: **1611 passed, 30 skipped, 32 xfailed, 1 xpassed**, with no failures. The later G3 test addition is recovery-test-only and passed in the final selected suite.

## K. Residual limitations

- Historical MCI state persistence is component-level rather than one atomic runtime snapshot.
- JTMS has a public snapshot but lacks a matching aggregate restore API; recovery must replay public belief/justification operations.
- The compatibility base deliberately contains no EA1 adapter, VOI policy, divergent-prediction mapping, belief-revision mapping, canonical-outcome adapter, or source-acquisition integration.
- It deliberately contains no N4/neural hypothesis producer and no historical ScenarioRunner integration, transfer subsystem, training path, or campaign.
- Exact historical behavioral and numerical limitations remain unchanged; this task establishes compatibility, not scientific superiority.

## L. Final commit

This report is part of the single recovery commit on `codex/ea1-mci-core-recovery-v1`. Its exact SHA is reported in the handoff after commit creation and becomes `EA1_MCI_COMPATIBILITY_BASE`.

## M. Verdict

`EA1_P3B0_B_PASS`
