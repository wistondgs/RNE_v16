# M7-H2B0: V2 execution and replay integrity gate

## Status

`CLOSED` — focused regression: `40 passed`; full Genesis regression:
`320 passed, 1 pre-existing CUDA-environment warning` in 32m27s.

H2B0 adds the integration substrate required before H2B1 may execute the six
predeclared confirmatory campaigns.  It does not execute, materialize, audit,
promote, replay, or consume any of those campaigns.  Its public execution
entrypoint accepts only the non-canonical `H2B0_TOY_ONLY` scope and rejects all
`m7h2-confirmatory-*` campaign IDs.

H2A remains frozen at commit `df70556`.  This unit does not modify its target
frontier, resource caps, task order, task IDs, benchmark, DSL, acceptance
policy, ranking rule, causal protocol, composition protocol, or M6 policy.

## Version-strict execution boundary

`V2ExecutionBinding` requires all of the following before it can enumerate:

| Binding | Requirement |
| --- | --- |
| campaign and task | campaign ID/hash and task-binding hash |
| V2 policy lineage | acceptance-policy, battery, and complete-search-policy hashes |
| search identity | `RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2`, the fixed H1 V2 implementation ID/hash, and the ranked engine policy hash |
| DSL/frontier | DSL hash; MDL/nodes, depth, raw-AST, behavior, wall-time, and peak-RAM limits |

The production adapter directly runs the V2 rank-canonical algorithm.  It does
not import or instantiate `DeterministicProgramSynthesizer`, and is
structurally distinct from the V1 `AutonomousAcquisitionCampaign` pipeline.  A
test-only child-process tripwire instruments the V1 synthesizer to raise if it
is reached while a V2 toy run and replay still pass.  The reverse test
monkeypatches V2 and proves the historical V1 replay remains V1.

## Receipt and transcript model

`V2SynthesisReceipt` is not a `SynthesisReceipt` and cannot be cross-dispatched
as one.  It commits the execution binding, both search-policy identities, DSL
identity, frontier limits, completed/current level state, raw/behavior/dedup
counters, selected AST/hash/MDL, termination, transcript root, and resource
receipt hash.  The selected AST is frozen and its canonical hash is rederived
in the receipt constructor.

One `V2LevelTranscript` is emitted for every completed level and for an
interrupted current level.  It carries cumulative and delta raw-AST,
behavior-class, and dedup counters; the count of exact candidates; level
completion/event state; and three streaming/canonical digests:

1. enumeration digest: a rolling canonical hash over the canonical AST hashes
   emitted in that MDL level;
2. representative-set digest: a canonical commitment to the V2-minimal
   representative of every observed TRAIN behavior class through that level;
3. exact-candidate-set digest: a canonical commitment to every exact AST hash
   encountered in that level.

The transcript root is a canonical hash of ordered transcript hashes.  No
per-AST audit log is stored.  Replay regenerates the same enumeration, counter
state, representative choice, exact set, digests, and selected candidate.  It
therefore rejects re-sealed counter or transcript alterations instead of
treating their hashes as authority.

An incomplete level has no selected candidate.  A complete selected level must
be the final completed level and its selected hash is the minimum exact hash in
that MDL level.  This carries H1's complete-level requirement into materialized
V2 execution.

## External resource envelope

The execution worker runs in its own process group.  Its parent supervisor
starts the committed wall clock immediately before enumeration (after worker
reconstruction), samples process-group RSS, and signals the child on time or
memory breach.  The child converts that signal into an incomplete-level V2
receipt; if it cannot respond within a grace interval the parent records a
non-promoting termination instead.

The worker independently enforces the two H2A units without conflating them:

- `max_raw_ast_evaluations` is checked before the next AST;
- `max_distinct_behaviors` is checked before admitting a new behavior class.

The resource receipt records configured caps, PID/process-group identity,
search-only elapsed time, peak observed RSS, counters, enforcement labels, and
cause.  It explicitly identifies memory enforcement as
`EXTERNAL_PROCESS_GROUP_RSS_WATCHDOG_NOT_KERNEL_HARD-v1`.

The actual Ubuntu environment exposes cgroup v2, but the current delegated
scope has an empty `cgroup.subtree_control`; creating a memory-governed child
scope would change the shared scope configuration.  H2A freezes an operational
12 GiB *harness* limit, not a kernel-hard-cgroup requirement, so the external
watchdog is the applicable enforcement method and is not overstated.

Wall/RSS readings are observational and intentionally need not match replay.
For an externally interrupted execution, semantic replay stops after the
committed raw-AST count and rederives the incomplete-level transcript.  This is
not resume support: no candidate is promoted and no continuation state is
created.

## H2B0 toy evidence

The non-canonical fixture has a small DSL and a square target at MDL 2.  It
exercises V2 execution, two complete transcripts, candidate selection, and a
fresh replay.  Separate fixtures prove an exact candidate encountered in a
raw-cap-truncated level is not promoted, a parent wall-clock signal produces a
partial level, and a parent RSS breach produces
`NOT_PROVEN_RESOURCE_EXHAUSTION`.

The H2B0 test suite also rejects altered raw/behavior/dedup counters,
enumeration/representative/exact-set digests, MDL level, level-complete state,
campaign hash, implementation hash, V1/V2 cross-dispatch, and every canonical
H2 campaign ID.

## Claim boundary

This closes only the integration/replay gate after its Genesis regression is
green.  It is not H2B1, does not establish GE-I, and does not consume any
AUDIT, HIDDEN, TRANSFER, causal, composition, M6, or persistence evidence from
the six V2 campaign slots.
