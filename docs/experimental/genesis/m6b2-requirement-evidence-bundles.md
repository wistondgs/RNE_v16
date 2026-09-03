# M6B-2: Requirement evidence bundles

Bundles are structural: `COMPLETE` means every and only preselected binding
has one valid execution record for one plan, requirement, and scientific
subject. It says nothing about claim truth. PASS, FAIL, UNKNOWN, and executed
ERROR records all count as present.

The validator rederives expected bindings from the FederationPlan and checks
the M6B-1 semantic record validator. It rejects omissions, duplicates,
cross-plan/requirement/subject records, unplanned records, and re-sealed false
completeness. Bundling invokes no verifiers and performs no adjudication.
