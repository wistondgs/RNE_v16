# M7-C — Deterministic program synthesis

`DeterministicProgramSynthesizer.synthesize` accepts only three inputs:
the sealed campaign, matching DSL specification, and `LearnerTrainingView`.
It has no benchmark, audit, hidden, transfer, reference, seed, or target-AST
parameter.

Search traverses the finite grammar in a fixed deterministic order, stops at
the predeclared `max_candidates` budget, and uses only observed TRAIN outputs
for semantic deduplication. Candidate selection is the minimum observed tuple
`(training_error, node_count, canonical_program_hash)`, not the first program
that happens to fit.

Budget exhaustion and an exact candidate are different, explicit receipt
states. The search never expands its budget following failure. The optimized
traversal does not construct higher-order AST batches once the campaign budget
has been reached, while preserving the same bounded search semantics.
