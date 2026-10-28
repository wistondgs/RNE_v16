# M7-0 — Integration audit

Status: `COMPLETE` (read-only audit against commit `32c6213`).

M7 can reuse the existing scientific substrate without adding another store,
ledger, provenance graph, or verifier authority.

| Question | Code-backed decision |
| --- | --- |
| G0/G1 state | `CapabilityManifest` is the immutable capability set. A causal `RootSnapshot` later holds the manifest hash for forks; `CausalSnapshot` continues to bind the causal environment. |
| Historical mutation | G0 remains a sealed manifest. `derive_successor_manifest` constructs G1 as `G0 ∪ {z}` and `validate_manifest_successor` re-derives that delta. |
| Program certification | Use `DifferentialVerifier` over the sealed finite benchmark. It calls candidates with an input only, keeping the reference private. `ExactVerifier` stays limited to its declared `x + delta` domain. |
| M6 admission | Build normal `VerificationPlan → FederationPlan → execution → bundle → adjudication` evidence. M7 does not introduce a parallel verifier authority. |
| Persistence | `stage_m6_trace(..., historical_artifacts=...)` already accepts role-indexed artifacts. M7 roles can therefore be included in a M6B4 closure. M7 replay must additionally rehydrate and validate its own roles. |
| Causal arms | Reuse M5 `RootSnapshot`, arm/CFI/budget/isolation/receipt contracts. Its current `GenericInterventionKernel` is intentionally an increment-only synthetic scenario, so M7-E will add a typed M7 executor that emits those existing contracts without changing M5 semantics. |
| Retention | M4 has a generic audited retention protocol, but no prior real M7 capability manifest exists. The first acquisition must report retention as `NOT_APPLICABLE_FIRST_CAPABILITY`; the second acquisition can run a non-vacuous M4 retention audit. |

No hard blocker was found. M7-A introduces the minimum new contracts only:
`ProgramSkillArtifact`, `CapabilityManifest`, `AcquisitionCampaignManifest`,
`SynthesisReceipt`, `CandidateCommitment`, and `PromotionReceipt`.

`PromotionReceipt` is needed because CAS presence is not historical admission:
a stored skill is not a promoted capability unless its committed candidate,
audit evidence, G0, and exactly-derived G1 all validate together.
