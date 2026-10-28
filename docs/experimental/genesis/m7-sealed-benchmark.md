# M7-B — Safe DSL and sealed benchmark

The M7-v1 learner receives only `LearnerTrainingView`: a task identifier,
TRAIN examples, and the TRAIN commitment. It receives no target AST, reference
callable, evaluator session, AUDIT labels, HIDDEN data, or TRANSFER data.

The boundary is operational and testable: it is an interface boundary inside
the instrumented process, not a claim that arbitrary Python reflection is a
security sandbox. Later campaign execution must pass the training view—not the
benchmark object—to the synthesizer.

`DSLSpecification` admits exactly `X`, `CONST`, `ADD`, `SUB`, `MUL_CONST`,
`ABS`, and `SQUARE`; its interpreter has no callback, import, filesystem,
network, subprocess, `eval`, or `exec` surface. AST arity, allowed constants,
node/depth bounds, and integer bounds are all checked before or during pure
evaluation.

`canonical_benchmark` deterministically creates six semantically nonduplicate
tasks: two each from `AFFINE`, `ABS_AFFINE`, and `QUADRATIC_SIMPLE`. Their
TRAIN/AUDIT/HIDDEN/TRANSFER input supports are pairwise disjoint. AUDIT is
available only through a one-shot `AuditAccess` issued after a candidate is
committed; hidden and transfer evaluations return aggregate results, never
example labels through the learner view.
