# M7-H2A: complete-frontier GE-I battery V2

## Status

This document records the H2-A pre-execution boundary only.  It freezes the
target-class frontier and six fresh V2 slots; it records no V2 candidate,
audit, promotion, hidden, transfer, causal, persistence, replay, or battery
outcome.  H2-B is the first unit allowed to execute those campaigns.

V1 remains historical evidence with `GE_I_BATTERY_NOT_PROVEN`.  H0 identified
the first-seen representative defect, and H1 repaired the rank-correct search
semantics under a distinct V2 identity.  None of those artifacts is rewritten,
reclassified, or used as V2 campaign evidence.

## Authority-side target audit

The sealed benchmark authority, not `LearnerTrainingView`, derives a
`TargetFrontierWitness` for every canonical task.  A witness commits only the
target hash and structural metadata.  It does not contain a target AST or a
target output vector.

| Task | target MDL / nodes | depth | member of common frontier |
| --- | ---: | ---: | --- |
| `abs_affine-0` | 7 | 5 | yes |
| `abs_affine-1` | 7 | 5 | yes |
| `affine-0` | 4 | 3 | yes |
| `affine-1` | 4 | 3 | yes |
| `quadratic_simple-0` | 5 | 4 | yes |
| `quadratic_simple-1` | 5 | 4 | yes |

For every witness the authority rederives that the target is canonical and
DSL-valid, and that it exactly generates the committed TRAIN split.  The
derived class boundary is therefore:

```text
C_star = max(target_mdl) = 7
```

The V2 policy applies this same `MAX_MDL = 7` to all six tasks.  There is no
task-specific frontier and no special handling for `abs_affine-1`.

## Finite-frontier sufficiency invariant

Before execution, for every task `i`:

```text
target_i is DSL-valid
target_mdl_i <= C_star
target_i exactly generates TRAIN_i
```

Together with H1's complete-by-level rank-canonical search semantics, this
means that a complete search through `C_star` without an exact TRAIN candidate
is an integrity contradiction, not ordinary acquisition failure.  H2-B must
record it as `SEARCH_OR_BENCHMARK_INTEGRITY_FAILURE` and hard-stop the claim.
A safety-cap interruption before a level completes remains
`GE_I_CAMPAIGN_NOT_PROVEN`; it cannot promote a partial-level candidate.

## Resource estimate and caps

The estimate mirrors the H1 grammar without materializing its ASTs.  Its
per-level counts are exact for the closed grammar and depth bound, and its
behavior-class figure is a conservative upper bound (one class per AST), not
a claim about a later campaign's observed behavior count.

| Measure | Value |
| --- | ---: |
| Raw AST counts, MDL 1..7 | `7, 56, 525, 5,376, 58,765, 441,840, 3,361,813` |
| Maximum raw AST evaluations | `3,868,382` |
| Behavior-class upper bound | `3,868,382` |
| Conservative per-campaign wall estimate | `4,680 s` (78 min) |
| Conservative six-campaign estimate | `28,080 s` (7 h 48 min) |
| Estimated peak memory | `9,216 MiB` |

The operational V2 caps are frozen above those estimates:

| Cap | Value |
| --- | ---: |
| Raw AST evaluations | `4,500,000` |
| Distinct TRAIN behaviors | `4,500,000` |
| Wall time per campaign | `6,000 s` |
| Peak memory harness limit | `12,288 MiB` |

The resource model is explicitly operational, not a source of scientific
authority.  It assumes a conservative one millisecond per raw-AST search step
and includes a 20% margin; actual H2-B observations must be recorded without
changing these caps.

## V2 identity and immutability

`CompleteFrontierSearchPolicyV2` binds:

- `RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2` and the H1 implementation hash;
- the complete frontier audit and resource-estimate hashes;
- DSL version, hash, depth, nodes, constants, and operators;
- `ARGMIN_MDL_CANONICAL_HASH_PER_TRAIN_BEHAVIOR-v2`;
- complete-level selection, canonical enumeration, canonicalization, and
  behavior-dedup policy hashes;
- the four safety limits and every H1 termination value.

Any V1 search identity is rejected for this battery.  The V2 acceptance policy
retains the exact six tasks, `ALL_REQUIRED_CAMPAIGNS`, independent fresh G0
baselines, all V1 mandatory gates, and the existing failure semantics.  It
also commits the predecessor V1 policy/battery and the fixed lineage:

```text
V1_NOT_PROVEN -> H0_SEARCH_ENUMERATION_DEFECT
              -> H1_SEARCH_CORRECTNESS_REPAIRED
              -> V2_PREDECLARED_COMPLETE_FRONTIER_CONFIRMATORY
```

The six frozen campaign IDs, in deterministic execution order, are:

```text
m7h2-confirmatory-abs_affine-0
m7h2-confirmatory-abs_affine-1
m7h2-confirmatory-affine-0
m7h2-confirmatory-affine-1
m7h2-confirmatory-quadratic_simple-0
m7h2-confirmatory-quadratic_simple-1
```

Each owns a distinct empty G0 and binds the same V2 complete-frontier policy.
The manifest has only pre-execution material; it has no result/receipt field.
Both the policy and manifest are rederived from their sealed sources, so a
re-signed false target hash, frontier, cap, task-policy binding, or V1
predecessor substitution cannot become valid evidence merely by changing a
digest.

## Claim boundary

If H2-B and H2-C later pass, the supported result is bounded: repeated,
independent acquisition of these six predeclared capabilities inside this
sealed DSL/search class, followed by the already-required downstream gates.
It does not establish unbounded search, open-ended intelligence, GE-R, GE-M,
AGI, consciousness, or cumulative retention.
