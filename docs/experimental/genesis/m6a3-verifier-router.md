# M6A-3: Verifier Router and Federation Plan

`VerifierRouter` is an admission and planning boundary. It does not execute
verifiers, inspect their scientific outputs, vote, or adjudicate a claim.

For every federated requirement it derives one of the planning states in
`RoutingStatus`. `PLANNABLE` means that the selected bindings meet the
declared authority, sovereignty, integrity, characterized-reliability,
reference, CFI, and independence prerequisites. It is not a PASS verdict.

Selection is exhaustive and deterministic: compatible candidates are sorted
by descriptor hash, implementation identity, and qualified reference binding;
the router enumerates smallest subsets first and selects the first lexical
subset satisfying both qualifying-count and independently-qualified-count
requirements. UNKNOWN independence never contributes. Equal qualified
reference identities create a dependency even if their implementations differ.

The resulting `FederationPlan` freezes the requirement results, exact verifier
bindings, selected reliability/integrity/reference evidence, graph, CFI reports,
and selection-policy identity. `validate_federation_plan` re-runs routing from
the supplied evidence, so a plan whose fields and SHA-256 are re-sealed after a
semantic falsification is still rejected.
