# M7-G3 — Certified compositional transfer

`COMPOSITIONAL_TRANSFER` is not discharged by the legacy local benchmark
receipt. The confirmatory protocol predeclares exactly two wrappers:
`ADD_CONST_1` and `MUL_CONST_NEGATIVE_ONE`. Their implementation identities
are part of a pre-policy protocol commitment; changing, reordering, adding,
or removing a wrapper invalidates the protocol.

For each promoted capability `z`, M7 builds a separate binding for each
`wrapper(z)` execution. A binding commits to the GE-I policy, protocol,
campaign, task benchmark binding, exact promoted skill identity, wrapper
implementation, TRANSFER input commitment, and evaluator policy. The wrapped
candidate and the equally wrapped sealed target are then evaluated by the real
M6 differential pipeline under `COMPOSITIONAL` scope. Hence a compositional
PASS has its own verifier record, evidence bundle, adjudication, and trace
closure rather than being an assertion attached to ordinary OOD transfer.

Every wrapper closure stores the policy, protocol, and binding as historical
artifacts. Fresh-CAS replay first checks M6 and then reconstructs the sealed
benchmark, acquisition chain, protocol, binding, and both wrapper observations
to require an identical M6 adjudication receipt.
