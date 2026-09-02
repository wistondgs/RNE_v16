# Genesis Engine v2

Genesis v2 is an experimental evidence kernel, not a replacement for RNFE certification.

Milestone 1 establishes immutable typed claims, sealed verification plans, explicit causal-surface manifests, a finite exact verifier, hash-chained evidence events, and fail-closed replay. It intentionally declares unknown causal surfaces rather than fabricating coverage.

Milestone 3 adds write-once content-addressed evidence, sealed append-only ledgers,
replayable provenance lineage, append-only provenance-risk assessments, and a
receipt-only quarantine overlay. `AUDIT_DATASET` is a first-class provenance node:
evidence can therefore be traced from `e_a` to both a derived hypothesis and
`D_i^audit`. Risk is a bounded provenance/evidence burden, not a probability or
automatic refutation. M4's `RetentionAuditPackage` is the future consumer of this
mechanism; M3 does not promote or modify any runtime state.
