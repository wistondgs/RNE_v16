# M7-H1 — Versioned search correctness repair

Status: **IMPLEMENTED; `NOT_READY` pending the repository-wide validation gate.**

M7-H1 repairs the search semantics found by H0.  It does not alter M7-G4 v1
artifacts, policies, campaigns, benchmark data, DSL semantics, or GE-I
acceptance criteria.  It creates neither a v2 battery nor a confirmatory
campaign.

## Version boundary

| Semantics | Identifier | Implementation binding |
| --- | --- | --- |
| Historical v1 | `FIRST_SEEN_BEHAVIOR_REPRESENTATIVE-v1` | `genesis-m7-deterministic-enumerative-synthesizer-v1` |
| H1 ranked v2 | `RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2` | `genesis-m7-rank-canonical-enumerative-synthesizer-v2` |

The v1 implementation remains exactly the historical first-seen behavior
representative.  `replay_v1_synthesis` accepts only a v1 `SynthesisReceipt`
and v1 implementation binding.  `replay_ranked_synthesis` accepts only the
new `RankedSearchReceipt` and H1 implementation binding.  Each rejects the
other version, preventing semantic laundering across the repair boundary.

## Ranked search rule

For an ordered TRAIN view, a candidate has a behavior key containing every
ordered output or deterministic evaluation failure.  No AUDIT, HIDDEN, or
TRANSFER data enters this key or the search engine.

Within a behavior class, H1 retains:

```text
representative(behavior) = argmin (MDL, canonical_program_hash)
```

Candidate acceptance follows the unchanged declared ranking:

```text
(training_error, MDL, canonical_program_hash)
```

The engine completes a full MDL/node level before it considers an exact
candidate.  It then selects the minimum-hash exact candidate in that completed
level.  A raw-AST, distinct-behavior, wall-time, or future memory cap reached
mid-level yields `RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL`; it never promotes a
candidate observed in that incomplete level.

The immutable receipt records completed/current level state, raw and canonical
AST counts, behavior-class and deduplication counts, candidate identity, an
explicit termination reason, and the versioned policy/implementation hashes.

## Executable correctness evidence

`test_m7h1_ranked_synthesis.py` establishes all of the following against the
versioned engine:

- the H0 counterexample remains historical: `CONST(2) * 3` appears before
  `CONST(3) * 2`, although the latter has the lower same-MDL hash;
- H1 chooses the lower hash only after completing that level, even under
  reversed AST insertion, operator ordering, and constant ordering;
- a lower-MDL representative beats a higher-MDL equivalent even when the
  latter hash is lower;
- incomplete levels and a distinct-behavior safety cap block promotion;
- an exhaustive no-dedup reference oracle agrees with H1 on 12 deterministic
  bounded spaces (selected hash, MDL, behavior key, and terminal result);
- a TRAIN-equivalent candidate that would differ on a held-out audit remains
  ranking-determined without searching on audit information; and
- v1/v2 replay is version-separated.

The fixed DSL contract requires its full frozen operator set, so the bounded
matrix varies every supported search dimension without changing DSL semantics:
constants, maximum depth/nodes, ordered TRAIN examples, and target behaviors.

## TRAIN-only performance characterization

Benchmark authority ran `abs_affine-1` under H1 with no candidate commitment,
audit access, promotion, hidden/OOD measurement, GE-I assessment, or battery
artifact.  These are feasibility observations only.

| Complete frontier | Raw/canonical ASTs | Behavior classes | Deduplicated | Wall time | Result |
| ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 5,964 | 219 | 5,745 | 3.755 s | no exact candidate |
| 5 | 64,729 | 837 | 63,892 | 48.596 s | no exact candidate |
| 6 | 506,569 | 2,987 | 503,582 | 452.677 s | exact TRAIN candidate |

The level-6 dry result is:

```text
DIAGNOSTIC_ONLY
complete_level = 6
candidate_hash = 11ec25d9fe5d29ae7de9b67e93d6b0f312529a4ef82f757e69e9d8ec707c9f96
```

It must not be interpreted as an acquired capability or GE-I evidence.  The
authority target AST remains seven nodes; the observed six-node TRAIN-exact
candidate may be observationally insufficient outside TRAIN, and H1
deliberately did not inspect any held-out split to learn that fact.

## Consequence for M7-H2

H1 establishes the correctness prerequisite for a future common, predeclared
complete-search frontier.  It does not choose that frontier and does not
permit task-specific runtime limits.  H2 may design a v2 confirmatory battery
only after the required repository-wide validation gate is intentionally run.
