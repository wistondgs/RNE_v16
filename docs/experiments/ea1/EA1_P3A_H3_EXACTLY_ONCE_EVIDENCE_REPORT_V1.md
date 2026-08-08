# EA1_P3A_H3_EXACTLY_ONCE_EVIDENCE_REPORT_V1

## A. Exact base, branch and commit

- Repository: `Necktral/RNE_v16`
- Mandatory base and starting HEAD: `771107d477e442fc7cd2549e7ba0729f903badaf`
- Expected parent: `5c0682e7a9e6e3b4204677b8e2b1c4acae4c86ca`
- Base verdict: `EA1_P3A_H2_PASS`
- Branch: `codex/ea1-p3a-exactly-once-evidence-v1`
- Starting worktree: isolated and clean.
- Preflight: H2 `17 passed`; H1 + P3A `51 passed`.
- Final implementation SHA: reported in the handoff because this report is part of that same single commit.

## B. Original replay reproduced

Before changing H3 source, a dynamic P3A/H2-equivalent restart replay was executed. One persisted selection consumed one token, one bound F1A outcome was attached, a first revision produced TheoryState v2, the ledger/adapter was reconstructed, and the same outcome was applied to v2 to produce a distinct revision and v3.

Observed before the fix:

```text
selection_count = 1
factual_outcome_count = 1
budget_tokens = 1
revision_count = 2
evidence_occurrences = 2
REPLAY_BEFORE_FIX = VULNERABLE
```

This reproduced the historical mechanism without restoring the abandoned C3 implementation.

## C. Root cause

The neutral harness persisted `BeliefRevision` directly and had no persistent evidence-application identity. Historical C3 deduplicated through process-local dictionaries, so reconstruction erased the replay guard. The selection also did not explicitly seal its predecessor `TheoryState`, allowing an old selection/outcome to be presented with a newer state.

At the persistence boundary, PostgreSQL already enforced unique event IDs, but SQLite's generic event log discarded the deterministic `event_id` supplied by `ExperimentLedger`. Therefore ledger idempotency on SQLite depended on a read-before-write check and was not an atomic exclusion primitive.

## D. Storage and atomicity primitives inspected

The following primitives were audited:

- `ExperimentLedger`: deterministic event identity, canonical payload hash, append-only chain, idempotent replay check;
- PostgreSQL `ledger_events.event_id TEXT PRIMARY KEY` with `ON CONFLICT DO NOTHING`;
- SQLite `events`, WAL mode, connection-level lock and transaction-per-insert;
- `StorageFacade`, SQLite/PostgreSQL/Hybrid event adapters;
- the in-memory ledger and budget deduplication dictionaries.

H3 preserves PostgreSQL's existing unique-key path and adds a nullable `event_id` column plus a partial unique index to SQLite. Existing EA1 identities are backfilled from JSON where possible. SQLite insertion now uses atomic `ON CONFLICT DO NOTHING`, and `StorageLedgerBackend` reloads the winning row and verifies its exact EA1 payload. Same ID with different content fails `atomic_event_identity_conflict`.

The in-memory backend is explicitly refused as H3 authority. No `if key not in dict` mechanism is used for official exactly-once behavior.

## E. Application identity definition

The persistent idempotency key is:

```text
stable_id(
  "ea1-evidence-application",
  {
    selection_receipt_id,
    execution_id,
    outcome_reference_id,
    prior_theory_state_id
  }
)
```

`ExperimentSelectionReceipt` now persists `theory_state_id`, derived from the already-registered pre-selection theory. This field strengthens integrity but does not change the H2 receipt/execution identity tuple. H3 checks that the supplied predecessor exactly matches both this sealed ID and the persisted `theory` ledger payload.

The application record also seals run, arm, epoch, H2 authorization, witness, revision ID, successor ID and revision-payload hash. Application IDs are never accepted from a caller.

## F. State machine and transaction design

The existing storage has atomic unique insertion for one event but no backend-neutral multi-event transaction. H3 therefore uses the smallest resumable append-only state machine:

```text
H2 validation
→ persisted predecessor/reference validation
→ evidence_application_reserved
→ deterministic BeliefRevision (embedding deterministic successor)
→ evidence_application_committed
```

Each stage has a deterministic ledger event ID protected by the storage unique key. The reservation contains the expected revision/successor IDs and revision hash. `COMMITTED` is written only after the exact revision can be reloaded and verified. The stable API returns `EvidenceApplicationResult` containing all lineage IDs, status and one of `applied`, `recovered_reservation`, `recovered_revision`, or `already_committed`.

`NeutralExperimentHarness.revise` now requires `EvidenceApplicationService`; the official neutral route cannot append a revision directly through the old harness method.

## G. Crash-window analysis

| Window | Persisted state at crash | Retry behavior |
|---|---|---|
| Before reservation | no application stage | normal application, once |
| After reservation | `RESERVED`, no revision | verifies reservation and persists deterministic revision |
| After revision | reservation + exact revision | reloads the same revision and writes commit marker |
| Immediately before commit | reservation + exact revision | same deterministic recovery |
| After commit/before response | complete chain | returns canonical persisted result without mutation |

Fault injection occurs at the actual append boundaries, not around a top-level mock. All four injected windows recover to one reservation, one revision, one commit and one successor lineage.

## H. Persistent replay behavior

An exact committed retry returns the already persisted application, revision and successor. It does not construct v3, append another event or consume budget. The same behavior was verified in-process, after new service/resolver/ledger construction, and in the reviewer-side process-equivalent replay.

Reviewer-side post-fix counts:

```text
selection_count = 1
factual_outcome_count = 1
epistemic_token_count = 1
application_count = 1
belief_revision_count = 1
evidence_occurrences = 1
application_id_same = true
revision_id_same = true
successor_state_same = true
retry_result = already_committed
```

## I. Stale-state rejection

The receipt seals `theory_state_id`; H3 then compares the complete supplied predecessor against the corresponding persisted theory entry. Both of these fail closed:

- old receipt + old outcome + canonical successor as the new prior;
- caller object with the correct predecessor ID but altered posterior content.

The already applied outcome can therefore never advance its successor again. A successor's evidence history is normalized to `prior.evidence_ids + application_id`, and contradictory caller-provided ancestry is rejected.

## J. Concurrent duplicate behavior

Two ordinary consumers with separate `StorageFacade`, `ExperimentLedger`, resolver and service objects were run concurrently against the same SQLite file. The database unique event key selected one persisted row at every deterministic stage; the other consumer reloaded the identical winner.

Final result: one reservation, one committed application, one revision, identical successor and no divergent branch. The application test uses two real concurrent connections rather than only a sequential interleaving.

## K. Divergent duplicate behavior

After a persisted reservation, a retry with different posterior/rationale produces a different deterministic revision payload for the same application key. It fails closed with `divergent_evidence_application_replay`; no revision or commit is added.

A forged application record using the same selection/reference/predecessor tuple but arbitrary `application_id` fails `forged_application_id`. A same-ID storage conflict with different payload fails at the atomic storage boundary. Two genuinely distinct selections produce distinct application keys.

## L. Budget and token behavior

H3 never calls `EpistemicBudget.consume`, executes an intervention or creates factual opportunities. Selection remains the sole token/cost/risk consumption point. Same-process, recovery and post-commit retries leave the original snapshot unchanged:

```text
tokens_consumed_by_selection = 1
additional_retry_tokens = 0
additional_retry_cost = 0
additional_retry_risk = 0
```

## M. H2 regression

H2 remains the first gate on every application attempt. `CanonicalOutcomeResolver.validate` still revalidates persisted receipt, execution authorization, timing, run, organism, episode, action, reference ID and F1A witness before H3 performs any deduplication.

- H2 targeted suite: `17 passed`.
- Forged-reference H3 gate: rejected before reservation.
- Existing pre-selection, cross-episode, wrong-action and forged-reference cases remain green in the H2 suite.

No H2 causal key or temporal semantic changed. The new receipt predecessor field is not policy-visible future outcome information.

## N. H1 regression

The H1 positional-leak firewall remains green. H1 plus the original P3A neutral tests produced `51 passed`. No scenario, action ordering, hidden role or policy-visible proposal surface changed.

## O. Persistence and reload

The lineage is reconstructible exclusively from persisted artifacts:

```text
persisted TheoryState
→ persisted SelectionReceipt(theory_state_id)
→ persisted H2 outcome reference
→ RESERVED application record
→ deterministic BeliefRevision(theory_after)
→ COMMITTED application record
```

Reload verifies every record's canonical hash and chain ancestry. The retry result is reconstructed from the stored revision payload rather than returning an old in-memory object. A successor cannot exist officially without its embedding revision, and commit cannot complete unless that exact revision reloads successfully.

SQLite is the P3A/H2 exercised backend and received direct H3 concurrency/fault tests. PostgreSQL's existing primary-key primitive and backend-neutral ledger verification path are preserved, but no PostgreSQL DSN was available for a live H3 run. Hybrid behavior remains based on its existing dual-write policy; H3 makes no claim beyond the configured backend's ordinary consistency/failure model.

## P. Test totals

- Preflight H2: `17 passed`.
- Preflight H1 + P3A: `51 passed`.
- H3 targeted, including four fault boundaries and concurrency: `18 passed`.
- Storage regression: `42 passed, 8 skipped`.
- F1A/boundary targeted: `45 passed`.
- Full repository: `1625 passed, 30 skipped, 32 xfailed, 1 xpassed`, 12 existing warnings, zero failures, in `674.10s`.

No campaign or training was run.

## Q. Residual limitations

The claim is exactly-once epistemic effect under the declared project failure model: ordinary process crashes, retries, duplicate delivery and concurrent consumers sharing the configured persistent backend. It does not claim universal distributed exactly-once under arbitrary partitions, malicious database editing, disk corruption or source mutation.

The pre-existing EA1 ledger read limit remains 10,000 events per run. PostgreSQL/Hybrid were not live-tested in this environment. These limitations do not affect the tested P3A SQLite protocol but should remain explicit for future deployment scaling.

## R. No scientific changes

H3 changes identity, persistence, recovery and audit metadata only. It does not alter priors, likelihoods, posterior arithmetic, thresholds, budget limits, scenario semantics, action count, H1 permutation, H2 factual binding, acquisition evaluator, sample size, Holm correction or preregistered claim.

The caller still supplies the already-computed revision semantics. H3 only assigns deterministic IDs, seals lineage and ensures that the resulting official effect is persisted once. No MCI, C3, VOI, A11/A12 or evaluator file was recovered or modified. F1A remains the unique factual authority and no F1A production file changed.

## S. No CONFIRM

No CONFIRM fixture, seed, manifest, outcome or campaign was generated, opened or executed.

## T. Verdict

`EA1_P3A_H3_PASS`

The neutral substrate now provides persistent exactly-once evidence application: one H2-bound factual outcome can produce one official deterministic revision/successor lineage, and exact retries recover that same lineage after restart or partial failure.
