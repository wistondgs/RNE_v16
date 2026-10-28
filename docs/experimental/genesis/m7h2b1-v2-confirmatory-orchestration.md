# M7-H2B1: V2 confirmatory orchestration

## Scope

H2A remains the frozen scientific authority: it fixes the target audit,
complete frontier, six task IDs, resource limits and acceptance rule.  This
module adds only the execution connection H2B1 needed to consume those slots.
It does not change H2A, H1 ranking, M5 causal semantics, M6 verifier
sovereignty, or a target/split.

There are three deliberately disjoint execution scopes:

| Scope | Entry point | Campaign IDs |
| --- | --- | --- |
| H2B0 toy | `run_v2_toy_execution` | never canonical |
| H2B1 fixture | `run_v2_fixture_execution` | `fixture-v2-*` only |
| H2B1 confirmatory | `run_v2_confirmatory_execution` | exact frozen `m7h2-confirmatory-*` IDs |

The V2 campaign contract has a distinct schema and preserves the native V2
receipt/transcripts.  A `SynthesisReceipt`, `SynthesisOutcome`, or V1
synthesizer is never constructed from the V2 result.  Shared use of the
one-shot audit registry, immutable skill artifact, M5 arms, M6 trace storage,
and content-addressed serialization is intentional: these components do not
define V1 search semantics.

## Identity

`V2ExecutionLaunch` binds the actual code/environment commitments to the
already-sealed H2A policy, battery and frontier.  It also commits the exact
H2B1 orchestrator, atomic durable-AUDIT implementation and V2 replay
implementation.  This separates the immutable scientific policy from an
execution implementation upgrade without silently adopting `latest`.

The launch builder rederives H2A against its benchmark, predecessor V1 policy
and predecessor V1 battery.  Failure is
`IMPLEMENTATION_BINDING_MISMATCH`; it is not repaired by changing an H2A hash.

## Execution and persistence

`execute_v2_confirmatory_battery` uses `battery.execution_order`, executes one
slot at a time, and calls the atomic journal writer before starting the next.
The journal includes the launch, native V2 receipt, resource receipt,
per-level transcripts, candidate commitment, durable audit, promotion and
terminal gate vector.  It is create-only: a conflicting or pre-existing
journal is not overwritten as a retry.

A complete frontier with no exact candidate raises
`SEARCH_OR_BENCHMARK_INTEGRITY_FAILURE`.  A resource-interrupted level is kept
as a terminal non-promotion result.  Scientific FAIL/NOT_PROVEN outcomes are
not retried or substituted.

## Fixture evidence

`test_m7h2b1_v2_e2e_fixture.py` creates a noncanonical fixture root and proves
the following chain under a child-process V1 tripwire:

```text
native V2 synthesis/transcripts
  -> V2 CandidateCommitment
  -> durable AUDIT
  -> promotion G0 union {z}
  -> HIDDEN / TRANSFER / composition through M6
  -> C1/C2/C3 through M5 and M6
  -> M6 persistence, M5 causal replay, native V2 replay
```

The causal replay receives a version-aware arm replayer: M5 replays its roots
and M6 replays each closure, while the V2 search receipt is replayed natively.
It never asks the V1 historical-source reader to parse V2 artifacts.

## Status at the adapter boundary

This document records only preparation.  It records no canonical campaign
result and consumes no confirmatory AUDIT slot.  H2B1 execution begins only
after this code is reviewed, tested, committed, and a clean launch identity is
recorded.
