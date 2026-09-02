# Genesis v2 construction blueprint

1. Define claim and verification identities with canonical bytes and SHA-256.
2. Declare every required causal surface, including `UNKNOWN`.
3. Run a deterministic finite verifier without arbitrary code evaluation.
4. Seal receipts and link evidence events by parent hash.
5. Recompute all identities during replay; any mismatch fails closed.

The next unit may add adapters, but it must not give Genesis authority over `PromotionGate` or S-I-E.
