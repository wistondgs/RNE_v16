# ADR: Genesis v2 experimental foundation

- Status: experimental
- Base SHA: `32f4e41c594b1cecb807bd171e33365516487652`

## Decision

Genesis v2 begins in `lab/genesis/` as a falsifiable instrument for demonstrating acquisition, representation, and improvement of a learning mechanism, without modifying the live RNFE runtime.

- `PromotionGate` and S-I-E remain sovereign.
- Genesis produces evidence and receipts; it does not replace RNFE certification.
- Original evidence is immutable; UNKNOWN never means PASS.
- Experimental components cannot write the live runtime.
- No causal assertion is valid without CFI.
- Strong GE-M distinguishes `LEARNING_RULE` from `RUN_SIDE`.
- Future retention uses a provenance-bearing `RetentionAuditPackage`.

## Consequences

No `runtime/*` module may import `lab.genesis`. Runtime adapters, if later justified, consume Genesis public artifacts rather than allowing experimental code to mutate the organism.
