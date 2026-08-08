# EA1_P3A_H2_SELECTION_OUTCOME_BINDING_REPORT_V1

## A. Exact base, branch and SHA

- Repository: `Necktral/RNE_v16`
- Mandatory base and starting HEAD: `5c0682e7a9e6e3b4204677b8e2b1c4acae4c86ca`
- Base parent: `b2e01ae792f4e690587f4add5aabeaca020ae49f`
- Base verdict: `EA1_P3A_H1_PASS`
- Branch: `codex/ea1-p3a-selection-outcome-binding-v1`
- Starting worktree: clean, with no pre-existing changes.
- Preflight: H1 and P3A suites, `51 passed` (`6 + 45`).
- Final implementation SHA: reported in the handoff because this report is part of that same single commit.

## B. Three original counterexamples

Before changing the implementation, all three reviewer counterexamples were dynamically reproduced against the H1 base:

| Counterexample | Pre-fix result |
|---|---|
| CE1: canonical F1A outcome committed before selection | `ACCEPTED` |
| CE2: authentic outcome from another episode with matching run/action | `ACCEPTED` |
| CE3: arbitrary `reference_id` over an authentic witness | `ACCEPTED` |

This established the vulnerable semantics before H2 rather than inferring them only from source inspection.

## C. Root cause

The neutral resolver proved that an event was canonical through F1A, but treated the caller's `organism_id` and `episode_id` as lookup hints rather than properties sealed by the selection. It did not revalidate the selection against its persisted ledger entry, did not recompute `reference_id`, and had no selection-issued execution authorization embedded in the factual transition. Therefore canonical authenticity and partial field consistency could be mistaken for causal origin.

The ledger also selected the first alphabetically canonicalized `*_id` as an artifact identity. Once authorization fields were added, that rule could index a selection under `authorization_id` rather than `receipt_id`. The neutral ledger now uses an explicit precedence list for normative artifact identities.

## D. Identity surfaces discovered

The original `ExperimentSelectionReceipt` already carried run, arm, block, scenario family, epoch, proposal, selected action, logical time, receipt ID/hash and proposal-set/budget metadata. It did not carry organism, episode, execution or execution-authorization identity.

The F1A `ObservedOutcomeWitness` carries source run, organism, episode, committed intervention, source record/transition identity, witness identity and outcome hash. Its underlying signed/hashed `LifeTransition` carries `state_before`, `state_after`, their logical times, the committed intervention and the authoritative decision.

H2 adds only neutral integrity fields: `execution_id`, `authorization_id`, `organism_id` and `episode_id` to the receipt; and the corresponding binding fields plus canonical event logical time to the reference. It does not add an outcome, event or witness identity to the selection.

## E. Minimal causal binding key

The sealed selection/execution identity is derived from:

`run_id + arm + epoch + proposal_id + action_id + block_id + scenario_family + organism_id + episode_id`

That immutable payload deterministically derives both `receipt_id` and `execution_id`. A fresh 256-bit post-selection token, combined with `execution_id`, derives `authorization_id`. The admissibility key checked at resolution is therefore:

`persisted receipt_id + execution_id + authorization_id + run_id + organism_id + episode_id + exact action_id`

The token itself is returned only in `ExecutionAuthorization` after the selection has been persisted. It is not policy-visible selection input.

## F. Temporal ordering primitive

Wall-clock is not used. H2 combines two persisted causal primitives:

1. EA1 selection `logical_time` versus F1A `LifeTransition.state_before.logical_time` and `state_after.logical_time`; the factual transition must start no earlier than the sealed selection and commit strictly afterward.
2. The unpredictable selection-minted authorization token must be embedded in the F1A-hashed `LifeTransition.authoritative_decision` and must derive the receipt's persisted `authorization_id`.

The second check prevents a pre-existing event from passing merely by claiming a cosmetically future logical time: an event created before selection cannot contain that selection's fresh token. Stable rejection is `outcome_precedes_selection` for an actually earlier logical transition and `execution_authorization_mismatch` for a pre-existing transition with forged future ordering.

## G. Receipt revalidation

`CanonicalOutcomeResolver` now requires the neutral `ExperimentLedger`. Before resolving or validating evidence it:

- recomputes `receipt_id` and `execution_id` from the immutable selection identity;
- finds exactly one persisted `selection` entry indexed by `receipt_id`;
- compares arm, logical time and the complete canonical receipt payload against that entry.

An unpersisted, altered or merely self-consistent Python receipt fails closed before evidence can be attached.

## H. Witness revalidation

F1A remains the sole factual authority. The resolver reloads the persisted `organism.life_transition.committed` event by authoritative source identity and recreates the witness with `outcome_witness_from_event`. It checks unique resolution, witness ID, outcome hash, run, organism, episode and exact committed intervention. Existing F1A integrity failures remain authoritative; no F1A production file or witness semantic was modified.

## I. Reference-ID derivation and recomputation

The normative reference identity is:

`stable_id("outref", {selection_receipt_id, execution_id, witness_id})`

Validation reconstructs that exact payload and recomputes the ID. It then independently reloads both the selection and factual event, so two mutually consistent caller-created objects cannot manufacture authority. Arbitrary IDs, IDs for another selection, IDs for another witness and correctly shaped references with altered components all fail closed.

## J. Valid path

The accepted path is:

`persist theory/proposals → persist sealed selection and execution identity → return post-selection authorization → execute exact intervention → commit F1A LifeTransition containing authorization → reconstruct F1A witness → derive and validate canonical reference → attach outcome reference → permit later revision`

A correct post-selection canonical outcome passed both direct resolution and `NeutralExperimentHarness.attach_outcome`. The harness now requires the hardened resolver at attachment, preventing a future bridge from bypassing validation with a constructed reference.

## K. Invalid-path matrix

| Test path | Result |
|---|---|
| T1 persisted authentic receipt | accepted on valid path |
| T2 tampered or unpersisted receipt | rejected |
| T3 valid post-selection F1A outcome | accepted |
| T4 pre-selection outcome, genuinely early | rejected: `outcome_precedes_selection` |
| T4 pre-selection outcome with cosmetically future time | rejected: `execution_authorization_mismatch` |
| T5 same-run/action, other episode | rejected: `outcome_episode_mismatch` |
| T6 wrong action | rejected: `outcome_action_mismatch` |
| T7 other organism | rejected: `outcome_organism_mismatch` |
| T8 forged reference ID | rejected: `canonical_reference_id_mismatch` |
| T9 reference ID/identity for another selection | rejected |
| T10 reference ID for another witness | rejected |
| T11 missing execution binding | rejected: `execution_binding_missing` |
| T14 raw mapping | rejected |
| T15 simulated/predicted output | rejected |
| T16 altered F1A outcome hash | rejected by canonical witness comparison |
| T17 EXPERIMENTAL, C1, C2 and C5 | identical binding contract, accepted when valid |

C0 is passive and does not factually select/execute an intervention in the neutral fixture, so selection-to-outcome binding is not applicable there. Future C3/C4 consume the same resolver; there is no arm-specific branch.

Independent dynamic reviewer-equivalent probes after the fix produced:

- Attack A, pre-selection event: `REJECTED:outcome_precedes_selection`
- Attack B, cross-episode event: `REJECTED:outcome_episode_mismatch`
- Attack C, forged reference ID: `REJECTED:canonical_reference_id_mismatch`

## L. Persistence and reload

The complete receipt is persisted in the hash-chained EA1 ledger. The execution authorization is persisted inside the hashed F1A transition, and the reference is derived from persisted identities. Reconstructing both `ExperimentLedger` and `CanonicalOutcomeResolver` from SQLite preserves receipt authenticity, causal ordering and valid binding. T12/T13 passed after one and multiple reconstructions.

Retry semantics were not redesigned. A failed execution cannot substitute an old outcome because the old transition lacks the newly minted authorization token. H2 adds no process-local binding dictionary.

## M. H1 regression

The H1 action-leak firewall remains green. H1 plus the original P3A tests produced `51 passed`. No scenario generator, hidden role, public action ordering or policy-visible action contract changed.

## N. P3A and F1A regression

- H2 targeted suite: `17 passed`.
- H1 + existing P3A suites: `51 passed`.
- Targeted F1A/boundary suites: `45 passed`.
- Full repository: `1607 passed, 30 skipped, 32 xfailed, 1 xpassed`, 12 existing warnings, zero failures, in `666.16s`.

No campaign or training was run. No F1A production file changed.

## O. Residual H3 replay vulnerability

The explicit replay probe validated the same correctly bound reference after reconstructing the resolver and ledger. Result:

`REPLAY_AFTER_RESTART = VULNERABLE`

This is intentional H2 scope. There is no persistent consumed-evidence ledger, and H2 answers only whether the outcome belongs to the selection—not whether that evidence has already been applied. Persistent exactly-once application remains the target of H3.

## P. No scientific changes

The patch strengthens integrity only. It changes no hypothesis, prior, score, threshold, cost, risk, budget, scenario semantics, acquisition rule, evaluator, correction procedure, claim or preregistration decision. The authorization is minted after arm selection and is applied identically across applicable arms. Policies receive no future witness ID, event ID, outcome hash/value or hidden producer information.

No second factual event, outcome, witness or authority was introduced. F1A still answers whether the outcome occurred; EA1 H2 only proves that it belongs to the exact previously authorized experimental execution.

## Q. No CONFIRM

No CONFIRM fixture, seed, manifest, outcome or campaign was generated, opened or executed.

## R. Verdict

`EA1_P3A_H2_PASS`

H2 now supports the statement that each official revision can be grounded only in a canonical F1A outcome bound to the exact intervention and execution selected beforehand. It deliberately does not support the distinct exactly-once statement reserved for H3.
