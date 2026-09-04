# M7-D — Autonomous acquisition and promotion

The M7-D pipeline is fixed:

`G0 → TRAIN view → deterministic synthesis → CandidateCommitment → AUDIT once → PromotionReceipt → G1`.

For this first-capability experiment G0 is the empty immutable
`CapabilityManifest`. `PriorInsufficiencyReceipt` records its actual
no-program behavior rather than treating a missing hash alone as success.

An exact TRAIN candidate is not admitted by itself. `PromotionReceipt` is
created only after the candidate commitment validates and the one-shot AUDIT
evaluation is exact; its promoted G1 must re-derive as exactly `G0 ∪ {z}`.
Budget exhaustion returns an explicit rejected receipt and creates neither a
candidate commitment, audit evaluation, nor successor manifest.
