# M7-H0 — v1 search-failure audit

Status: **BLOCKED — SEARCH_ENUMERATION_DEFECT**

This is a read-only characterization of the immutable M7-G4 v1 experiment.
It does not amend the v1 policy, manifest, campaigns, receipts, closure, or
their interpretation.

## Historical input and direct result

- Start commit: `7926c009c6af549c84aeb5344fcc942653b7c0ee`.
- Historical battery: `2b2f8d766d976ecc2fb6bb4286a283882a488bd0ce182a226e6318bba2237812`.
- v1 aggregate: `GE_I_BATTERY_NOT_PROVEN`; M7 remained `NOT_READY`.
- `abs_affine-1` ran the historical resource policy of 256 unique TRAIN
  behaviors and terminated `BUDGET_EXHAUSTED`, with no selected candidate.

Replaying the v1 traversal against its TRAIN view yields this exact resource
receipt detail:

| Node level | distinct TRAIN behaviors admitted |
| --- | ---: |
| 1 | 7 |
| 2 | 12 |
| 3 | 41 |
| 4 | 159 |
| 5 (partial) | 37 |

The last fully completed structural level was 4.  The 256th behavior was
admitted in level 5.  The direct terminal reason is therefore genuinely a
resource exhaustion, not an audit, hidden, transfer, compositional, causal,
or replay failure.

## Benchmark-authority representability inspection

The evaluator-private targets were inspected only at the benchmark authority
boundary.  No target AST or metric was supplied to `LearnerTrainingView` or
to the synthesizer.

| Task | DSL valid | Nodes | Depth | Operators | Constants |
| --- | --- | ---: | ---: | --- | --- |
| `abs_affine-0` | yes | 7 | 5 | `X, CONST, MUL_CONST, ADD, ABS` | `-2, 0, 1` |
| `abs_affine-1` | yes | 7 | 5 | `X, CONST, MUL_CONST, ADD, ABS` | `-1, 1, 2` |
| `affine-0` | yes | 4 | 3 | `X, CONST, MUL_CONST, ADD` | `0, 2` |
| `affine-1` | yes | 4 | 3 | `X, CONST, MUL_CONST, ADD` | `-1, 1` |
| `quadratic_simple-0` | yes | 5 | 4 | `X, CONST, MUL_CONST, SQUARE, ADD` | `0, 2` |
| `quadratic_simple-1` | yes | 5 | 4 | `X, CONST, MUL_CONST, SQUARE, ADD` | `1, 3` |

Thus `TARGET_REPRESENTABLE = YES` for all six targets.  In particular,
`abs_affine-1` has a seven-node target AST while the v1 resource stop occurs
midway through level 5.  That explains the historical miss under the v1
budget, but it is not sufficient to authorize a v2 frontier expansion.

## Enumeration-completeness finding

`DeterministicProgramSynthesizer` uses this v1 rule:

```python
if outputs in seen_behaviors:
    continue
seen_behaviors.add(outputs)
```

It retains the first AST with a TRAIN output vector.  The declared selection
rule is instead `training_error_then_mdl_then_canonical_program_hash-v1`.
Those are not equivalent orderings.  A bounded counterexample needs no
benchmark target:

| Traversal position | AST | Node count | canonical hash order |
| ---: | --- | ---: | --- |
| 43 | `MUL_CONST(CONST(2), 3)` | 2 | higher |
| 48 | `MUL_CONST(CONST(3), 2)` | 2 | lower |

Both yield the identical constant function 6, including on all TRAIN inputs.
Position 48 is the lower-ranked candidate under the declared tie break, yet
the v1 `seen_behaviors` set discards it because position 43 was seen first.

Therefore:

```text
ENUMERATION_COMPLETE_BY_LEVEL = NO
V1_FAILURE_CLASSIFICATION   = SEARCH_ENUMERATION_DEFECT
```

The historical `abs_affine-1` terminal receipt remains
`BUDGET_EXHAUSTED`; it must not be rewritten as a causal or representability
failure.  The H0 classification is broader: the present enumerator cannot
certify a complete bounded frontier or its own stated selection semantics.

## Disposition

M7-H v2 is **not opened**.  Per the predeclared decision rule, increasing the
budget or adding a new search frontier would be scientifically invalid until
a separate, versioned search-correctness repair proves that it:

1. retains the candidate selected by the unchanged declared ranking for every
   TRAIN-behavior class;
2. records a reproducible exhaustive-frontier receipt; and
3. passes bounded-domain equivalence tests against a complete reference
   enumerator.

That repair must have a new implementation identity and must not mutate v1.
