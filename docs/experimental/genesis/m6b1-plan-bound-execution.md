# M6B-1: Plan-bound verifier execution

`PlanBoundExecutionKernel` is an execution boundary, not a routing or
adjudication boundary. It first semantically revalidates the supplied M6A-3
`FederationPlan`, then admits one exact `SelectedVerifierBinding`, and invokes
that verifier once. Rejected admission never invokes a verifier.

`ExecutionSubjectBinding` seals claim, candidate identity, domain, and canonical
context. `PlannedExecutionRequest` seals the plan, requirement, selected binding,
and subject before an outcome exists. The resulting `VerifierExecutionRecord`
preserves the verifier's original PASS/FAIL/UNKNOWN/ERROR receipt verdict; it
does not combine, vote, or adjudicate evidence.

Both plan and record have semantic validators. Therefore resealing altered
fields with a coherent SHA-256 does not make a substituted plan, verifier,
reference, subject, or receipt admissible.
