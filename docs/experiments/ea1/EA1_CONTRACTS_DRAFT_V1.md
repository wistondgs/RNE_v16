# EA1 Conceptual Contracts Draft V1

Status: `NON_EXECUTABLE_DESIGN_CONTRACTS`

These records specify semantics and validation obligations. They are not runtime schemas and do not authorize implementation changes. Every record has a canonical serialization, schema version, content hash, logical time and provenance envelope.

## 1. Shared provenance rules

Every producer is one of `MCI`, `A11`, `A12`, `EML`, `N4_SHADOW`, `CONTROL_POLICY`, `SCENARIO_PUBLIC_INTERFACE` or `ORACLE_ISOLATED`. Confirmatory records cannot use Codex or local 7B producers.

Provenance distinguishes:

- `MODEL_BASED_PREDICTION`;
- `SIMULATED_PREDICTION`;
- `SYMBOLIC_PREDICTION`;
- `OBSERVED_CANONICAL_REFERENCE`;
- `CONTROL_POLICY_OUTPUT`;
- `EVALUATION_ONLY`;
- `ORACLE_PRIVATE`.

Only `OBSERVED_CANONICAL_REFERENCE` may support factual belief revision. `EVALUATION_ONLY` samples may score frozen predictions after finalization but cannot create anchors, revisions or lived experience. Predictions and counterfactuals never become lived experience.

## 2. HypothesisCandidate

```text
HypothesisCandidate
  hypothesis_id: opaque content-derived identity
  version: positive integer
  producer: allowed producer identity
  proposition: explicit falsifiable statement
  mechanism:
    nodes: role-neutral variables
    directed_relations: signed/typed relations
    functional_family: optional
    lag_structure: optional
    preconditions: explicit or unknown
  scope:
    admissible_states
    scenario_family
    representation_invariants
  assumptions: ordered statements
  prior_weight: [0, 1]
  support_refs: evidence identities
  predicted_effect_templates: intervention-conditioned templates
  refutation_conditions: observable conditions
  provenance: producer, parent IDs, model/config hash, logical time
  content_hash
```

Invariants:

- proposition, mechanism, scope and a refutation condition are mandatory;
- `hypothesis_id` cannot contain a scenario target ID or hidden class name;
- support references cannot point to simulated outcomes;
- prior weights are normalized only at `TheoryState` level;
- two records that differ only by aliases belong to the same structural equivalence class.

## 3. TheoryState

```text
TheoryState
  theory_state_id
  predecessor_id: nullable
  version
  logical_time
  active_hypothesis_ids: at least two initially
  numeric_weights: map[hypothesis_id -> probability]
  unknown_weight: [0, 1]
  ordinal_states: map[hypothesis_id -> active|revisable|refuted|abstain]
  contradictions: typed contradiction records
  factual_evidence_refs: CanonicalOutcomeReference IDs
  nonfactual_support_refs: prediction/model IDs
  normalization_method
  derivation_policy_hash
  content_hash
```

Invariants:

- hypothesis weights plus `unknown_weight` sum to one within `1e-9`;
- ordinal state is deterministically derived by the frozen governance policy;
- a `refuted` hypothesis cannot regain weight without a new version and explicit new canonical evidence;
- predecessor chains are immutable and acyclic;
- missing probability mass remains `unknown`, not redistributed silently.

## 4. DivergentPredictionSet

```text
DivergentPredictionSet
  prediction_set_id
  theory_state_id
  public_state_hash
  experiment_ids
  predictions:
    (hypothesis_id, experiment_id):
      outcome_model
      likelihood_family
      parameters_and_units
      observable_names
      horizon
      method: model_based|simulated|symbolic|unavailable
      uncertainty
      assumptions
      producer_ref
  divergence_scores
  unavailable_cells
  content_hash
```

It represents `(H_i, e_j) -> P(Y | H_i, do(e_j))`. For confirmatory S2/S3/S5, `likelihood_family` must be `BERNOULLI`, the sole parameter is dimensionless `p in [0,1]`, and observations are canonical binary `0/1`. Intervals and untyped point predictions are invalid in confirmatory arms. S1/S4 developmental records may use other explicitly typed likelihood families but cannot enter the EA1-C source-acquisition endpoint. Missing predictions remain unavailable and cannot be imputed from the oracle or ground truth.

## 5. ExperimentProposal

```text
ExperimentProposal
  proposal_id
  prediction_set_id
  intervention:
    public_action_id
    parameters
    required_public_state
  comparator_or_control
  predicted_outcomes_by_hypothesis
  discriminated_hypothesis_pairs
  expected_information_gain
  expected_decision_value
  normalized_cost
  invariant_risk
  reversibility_proof_ref
  admissibility_status_and_reasons
  producer
  content_hash
```

Invariants:

- expected values are computed only from `TheoryState` and `DivergentPredictionSet`;
- proposal identity is fixed before action execution;
- reward, EIG and EDV are separate fields;
- inadmissible proposals cannot be selected by any arm, including oracle;
- proposals have no authority over outcomes, memory or final belief state.

## 6. ExperimentSelectionReceipt

```text
ExperimentSelectionReceipt
  receipt_id
  arm_id
  paired_block_id
  theory_state_id
  proposal_ids_considered: complete ordered set
  chosen_proposal_id: nullable
  policy_id_and_hash
  score_components_by_proposal
  tie_break_result
  budget_before
  budget_reserved
  budget_after_if_executed
  abstention: boolean and reason
  public_rng_counter: controls only
  logical_time
  predecessor_event_hash
  seal_hash
```

Invariants:

- it is append-only and sealed before intervention execution;
- it contains neither canonical outcome ID/hash nor future logical time;
- the considered set is complete, including rejected proposals with reasons;
- policy and coefficients must match preregistration;
- sealing failure forces abstention and produces no experimental outcome.

## 7. CanonicalOutcomeReference

```text
CanonicalOutcomeReference
  reference_id
  selection_receipt_id
  canonical_anchor_id
  witness_id_or_digest
  f1a_evidence_identity
  canonical_event_logical_time
  intervention_identity
  resolution_status
  content_hash
```

This is a reference, not a second outcome system. Validation resolves the existing F1A anchor and witness and confirms that the committed intervention equals the sealed selection. It cannot contain a Teacher, Codex, 7B, N4 or simulation-produced outcome.

## 8. BeliefRevision

```text
BeliefRevision
  revision_id
  prior_theory_state_id
  canonical_outcome_reference_id
  likelihood_or_evidence_evaluation_by_hypothesis
  update_rule_id_and_hash
  posterior_numeric_weights
  posterior_ordinal_states
  retracted_hypothesis_ids
  restricted_hypothesis_ids
  unresolved_hypothesis_ids
  contradiction_changes
  rationale
  resulting_theory_state_id
  provenance
  content_hash
```

Invariants:

- exactly one prior and one resulting `TheoryState`;
- all factual evidence passes through `CanonicalOutcomeReference`;
- zero-likelihood handling and unknown mass follow the frozen update rule;
- revision cannot modify `ExperienceStore` or `SituationWisdom`;
- the producer cannot be Codex, local 7B, N4 shadow or oracle.

## 9. ExperimentMemoryRecord

```text
ExperimentMemoryRecord
  record_id
  paired_block_id
  arm_id
  theory_state_before_id
  divergent_prediction_set_id
  proposal_ids
  selection_receipt_id
  canonical_outcome_reference_id: nullable on abstention
  belief_revision_id: nullable with explicit reason
  observed_discrimination
  token_cost
  physical_cost_and_risk
  audit_flags
  logical_time
  content_hash
```

This ledger is separate from `ExperienceStore`. Retrieval from it must be scoped by public structural features and must never reveal hidden IDs, oracle records or confirmatory outcomes from another arm.

## 10. SourceAcquisitionReceipt

```text
SourceAcquisitionReceipt
  acquisition_receipt_id
  lifecycle_status: CANDIDATE_SEALED|FINALIZED
  arm_id
  paired_block_id
  candidate_theory_state_id
  selected_structural_class
  token_count
  acquisition_logical_time
  committed_acquisition_gate:
    posterior_weight
    runner_up_odds
    unknown_weight
    first_crossing_proof
    predecessor_event_hash
    candidate_seal_hash
  correct_class_gate
    candidate_canonical_signature
    ground_truth_canonical_signature
    exact_signature_match
    heldout_interventional_mae
  heldout_prediction_gate:
    probe_manifest_hash
    baseline_theory_state_id
    candidate_theory_state_id
    posterior_predictive_rule_hash
    baseline_log_loss
    acquired_log_loss
    delta_nats
  persistence_gate:
    required_opportunities
    observed_opportunities
    stable_class_and_state
  functional_use_gate:
    decision_probe_manifest_hash
    baseline_utility
    acquired_utility
    invariant_breaches
  canonical_evidence_gate
  prohibited_information_audit
  censoring_audit
  valid: conjunction of all gates
  invalid_reasons
  evaluator_version_and_hash
  ground_truth_opening_ref: attached only after campaign finalization
  finalization_hash
  content_hash
```

At the first threshold crossing, the epistemic ledger creates the immutable `CANDIDATE_SEALED` portion before ground-truth opening. It fixes class, TheoryState, time, token and posterior values. Finalization may only append gates and the opening reference; it cannot replace the candidate with a later crossing. Exact validity thresholds are defined in `EA1_PREREGISTRATION_V1.md`. `valid` is a conjunction, not a weighted score. Missing evidence, absent probes, early termination and zero evaluations are invalid, never successful censoring.

## 11. MethodTransferReceipt

This contract is designed but not executed in EA1-C-v1.

```text
MethodTransferReceipt
  transfer_receipt_id
  valid_source_acquisition_receipt_id
  source_method_trace_hash
  target_public_structure_hash
  morphism_spec_and_score
  transferred_steps:
    rival_formation
    divergent_prediction_search
    experiment_selection
    belief_update
    continue_or_abstain
  prohibited_copy_audit:
    no_action_copy
    no_id_copy
    no_threshold_copy
    no_situation_key_copy
    no_theory_copy
    no_name_mapping
  target_selection_receipts
  target_source_acquisition_receipt
  aba_recovery_refs
  valid
  invalid_reasons
  content_hash
```

It requires an already valid source receipt and a separately preregistered target study. A morphism score alone cannot establish method transfer.

## 12. Governance state derivation

The deterministic mapping is frozen in `EA1_PREREGISTRATION_V1.md`: rivals start at `0.49/0.49`, unknown starts at `0.02`, confirmatory Bayesian updates use Bernoulli mass, floor `1e-12` and unknown `Bernoulli(0.5)`; acquisition requires weight `>= 0.80`, odds `>= 4:1` and unknown mass `<= 0.10`. Required ordinal semantics are:

- `active`: evaluable, non-refuted and without unresolved contradiction;
- `revisable`: non-refuted with unavailable latest likelihood or unresolved canonical contradiction;
- `refuted`: posterior `<= 0.05` plus canonical likelihood ratio against `<= 0.10`;
- `abstain`: after checking the committed-acquisition gate, fewer than two non-refuted rivals, unknown mass `>= 0.25`, or no safe experiment with EIG `>= 0.05` nats.

These labels summarize numeric state; they never substitute for it.

## 13. Authority matrix

| Record | May propose | May seal/validate | May write F1A outcome? |
|---|---|---|---:|
| Hypothesis/prediction/proposal | Active arm adapters | Contract validator | no |
| Selection receipt | Arm policy | append-only receipt authority | no |
| Canonical outcome reference | Outcome resolver | F1A resolver | no new outcome |
| Belief revision | Active arm update adapter | epistemic ledger validator | no |
| Source acquisition candidate seal | Active arm threshold detector | append-only epistemic ledger authority | no |
| Source acquisition finalization | Independent evaluator after required probes | acquisition evaluation authority | no |
| Oracle record | isolated oracle | oracle store | no non-oracle write |

No EA1 contract grants behavioral, outcome or ExperienceStore authority to an external proposer.
