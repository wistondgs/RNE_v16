# W0-R2/R3 invariant extraction for Genesis M5

## INVARIANT_EXTRACTED

- Capture and seal one root before deriving arms; use deterministic hashes.
- Forks must not share mutable state, must expose forbidden writes, and arm order
  must not change the scientific summary.
- Declare treatment deltas and seal the decision before opening an oracle.
- Preserve execution order as operational evidence, separate from the summary.

## GENESIS_IMPLEMENTATION

`SyntheticForkableStateAdapter`, CFI receipts, declared intervention specs,
budget receipts, `DecisionSeal`, `OracleGate`, content-addressed evidence and a
ledger seal provide those neutral contracts.

## N3_SPECIFIC_REJECTED

No micro/meso/macro scales, thermal/resource/deferred scenarios, N3 or Mamba
backends, reference/trained branches, membership or sequence treatment semantics
are imported by Genesis.
