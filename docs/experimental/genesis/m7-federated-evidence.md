# M7-F1 — Federated evidence for acquired program skills

M7-F1 is the boundary between an acquisition experiment and the sealed M6
evidence system. It does not introduce a parallel ledger, verifier,
adjudicator, or persistence path.

## Certifiable task identity

`AcquisitionCampaignManifest` has one commitment for each dataset split. A
generic campaign result is therefore insufficient to assert which benchmark
task it trained on. `TaskBenchmarkBinding` is required for certification and
rederives all of the following before synthesis is allowed to begin:

\[
(campaign\_hash, benchmark\_manifest\_hash, task\_id,
  C_{TRAIN}, C_{AUDIT}, C_{HIDDEN}, C_{TRANSFER}).
\]

The four campaign commitments must exactly equal the four commitments on the
sealed task descriptor. An unbound historical M7-D run remains useful as an
experiment, but cannot be materialized as M7 certification evidence.

## Measurement boundary

`FederatedMeasurementScope` binds the candidate skill, one `HIDDEN` or
`TRANSFER` split, its commitment, the task binding, the finite verification
domain, and a non-revealing reference-target commitment. `TRAIN` and `AUDIT`
are deliberately rejected as certifiable scopes.

For a sparse split, the M6 differential domain may be the declared contiguous
superset spanning its smallest and largest input. The scope commits both the
split and that exact domain, so the resulting claim is stronger than the split
check but is never silently relabelled as a different measurement.

The trusted evaluator can access the sealed target AST only to construct the
private reference callable. The learner receives neither that callable, the
target AST, its outputs, nor the scope's hidden examples.

## Evidence path

```text
TaskBenchmarkBinding + promoted candidate
  -> deterministic TRAIN replay + committed-candidate AUDIT validation
  -> finite DifferentialVerifier execution
  -> M6 FederationPlan
  -> plan-bound execution record
  -> COMPLETE RequirementEvidenceBundle
  -> RequirementAdjudicationReceipt
  -> M6B4 TraceClosureManifest / CAS replay
```

The audit validation re-evaluates only the already committed candidate on the
trusted evaluator side. It creates no learner-visible audit handle and gives
no opportunity to select a replacement candidate.

`DifferentialVerifier` is explicitly `SUPPORTING`, and the generated M7
requirement has `sovereign_required=False`. This records finite-domain
reference equivalence; it does not expand `ExactVerifier`, fabricate sovereign
authority, or establish a global claim verdict.

## Current scope and next gate

The resulting closure replays M6 semantics from fresh CAS objects and retains
the M7 campaign, binding, target commitment, scope, candidate, promotion, and
manifest artifacts as historical roles.

M7-F2 additionally persists an evaluator-private
`SealedBenchmarkReplayWitness`: target ASTs and split examples, each
revalidated against the benchmark manifest and DSL before use. This is not a
learner artifact or a learner API; the CAS used for replay must remain within
the evaluator/persistence trust boundary. It lets a fresh process replay TRAIN
synthesis, validate the committed candidate's AUDIT result, rebuild the M6
material, and require the same adjudication receipt.

This distinction is deliberate: a trace with a re-sealed false M7 audit or
target witness may still be structurally valid M6 history, but it fails M7
semantic replay. Causal-arm binding, restart persistence across causal arms,
and GE-I's all-gates conjunction remain later M7 work. A passing M7-F1/F2
trace alone is not GE-I certification.
