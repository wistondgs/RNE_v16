# M7-G4/G5 — Confirmatory battery and closure boundary

The confirmatory battery first commits six task slots, including the exact
task, independent empty G0 manifest, dataset commitments, seeds, search
budget, and campaign identity. The later campaign hash and task-binding hash
then derive from that fixed plan and the frozen battery manifest; this avoids a
hash cycle without allowing any task, seed, DSL limit, or budget to change
after outcomes are known.

Each campaign is assessed from the full gate vector named by
`GEIAcceptancePolicy`. A missing candidate, rejected audit, missing closure,
or failed replay is represented as `NOT_PROVEN` or `FAIL` according to the
predeclared semantics. No campaign can be substituted, and no aggregate
boolean or average can conceal a missing gate.

`GEIBatteryClosure` accepts only the exact six canonical task IDs and distinct
campaign identities. Its status is derived from the six campaign assessments:
all `SUPPORTED` closes M7; any `FAIL` makes M7 `FAIL`; otherwise M7 is
`NOT_READY`. This independent-single-skill protocol deliberately makes
retention `NOT_APPLICABLE_SINGLE_CAPABILITY_RUN`, and makes no GE-R or GE-M
claim.

The executed v1 battery retains the policy-fixed budget. In particular,
`abs_affine-1` exhausted that budget before a committed candidate and is
therefore `GE_I_CAMPAIGN_NOT_PROVEN`; it is not tuned, replaced, or averaged
away. Consequently its aggregate status is `GE_I_BATTERY_NOT_PROVEN` and the
M7 status is `NOT_READY`.
