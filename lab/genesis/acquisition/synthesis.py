"""Deterministic, TRAIN-only enumerative synthesis for M7-v1."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from lab.genesis.acquisition.benchmark import LearnerTrainingView
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest, ProgramSkillArtifact, SynthesisReceipt, SynthesisTermination
from lab.genesis.acquisition.dsl import DSLSpecification, ProgramOperator, _evaluate_canonical_expression, canonical_expression, expression_metrics
from lab.genesis.contracts.serialization import canonical_sha256


# This identifier documents the historical semantics rather than claiming the
# first-seen representative rule was ranking-correct.  It must remain stable:
# existing M7 evidence is replayed under precisely these semantics.
SEARCH_SEMANTICS_V1_ID = "FIRST_SEEN_BEHAVIOR_REPRESENTATIVE-v1"
V1_SYNTHESIZER_IMPLEMENTATION_HASH = canonical_sha256(
    {"synthesizer": "genesis-m7-deterministic-enumerative-synthesizer-v1"}
)


def _node(op: ProgramOperator, *args: Mapping[str, Any], value: int | None = None) -> Mapping[str, Any]:
    result: dict[str, Any] = {"op": op.value, "args": tuple(args)}
    if value is not None: result["value"] = value
    return result


def _primitives(ast: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({str(ast["op"]), *(item for child in ast["args"] for item in _primitives(child))}))


def _expressions(spec: DSLSpecification, maximum_nodes: int) -> Iterable[Mapping[str, Any]]:
    """Yield a deterministic grammar traversal; ranking remains MDL/hash based.

    The predeclared search budget truncates this traversal.  It intentionally
    does not materialize an exponentially larger next node-size merely to sort
    programs the campaign is not permitted to examine.
    """
    by_nodes: dict[int, dict[str, Mapping[str, Any]]] = {}
    for count in range(1, maximum_nodes + 1):
        batch: dict[str, Mapping[str, Any]] = {}
        def raw_candidates() -> Iterable[Mapping[str, Any]]:
            if count == 1:
                yield _node(ProgramOperator.X)
                for value in spec.allowed_constants: yield _node(ProgramOperator.CONST, value=value)
                return
            for operator in (ProgramOperator.MUL_CONST, ProgramOperator.ABS, ProgramOperator.SQUARE):
                for child in by_nodes.get(count - 1, {}).values():
                    if operator is ProgramOperator.MUL_CONST:
                        for value in spec.allowed_constants: yield _node(operator, child, value=value)
                    else: yield _node(operator, child)
            for left_size in range(1, count - 1):
                right_size = count - 1 - left_size
                for left in by_nodes.get(left_size, {}).values():
                    for right in by_nodes.get(right_size, {}).values():
                        left_hash, right_hash = canonical_sha256(left), canonical_sha256(right)
                        if left_hash <= right_hash: yield _node(ProgramOperator.ADD, left, right)
                        yield _node(ProgramOperator.SUB, left, right)
        for candidate in raw_candidates():
            try: canonical = canonical_expression(candidate, spec)
            except ValueError: continue
            artifact_hash = canonical_sha256(canonical)
            if artifact_hash in batch: continue
            batch[artifact_hash] = canonical
            yield canonical
        by_nodes[count] = batch


@dataclass(frozen=True, slots=True)
class SynthesisOutcome:
    receipt: SynthesisReceipt
    selected_skill: ProgramSkillArtifact | None
    training_error: int | None


class DeterministicProgramSynthesizer:
    """Enumerate a bounded closed grammar; no evaluator other than TRAIN enters."""
    implementation_id = "genesis-m7-deterministic-enumerative-synthesizer-v1"

    def synthesize(self, *, campaign: AcquisitionCampaignManifest, specification: DSLSpecification, training: LearnerTrainingView) -> SynthesisOutcome:
        if not campaign.validate() or not specification.validate() or campaign.dsl_hash != specification.dsl_hash:
            raise ValueError("genesis_synthesis_campaign_dsl_mismatch")
        if campaign.max_ast_depth != specification.max_ast_depth or campaign.max_ast_nodes != specification.max_ast_nodes or campaign.allowed_constants != specification.allowed_constants or tuple(campaign.allowed_operators) != tuple(item.value for item in specification.operators):
            raise ValueError("genesis_synthesis_campaign_language_mismatch")
        if not training.training_examples:
            raise ValueError("genesis_synthesis_training_empty")
        budget = campaign.search_budget["max_candidates"]
        examined = 0; best: tuple[int, int, str, Mapping[str, Any]] | None = None; seen_behaviors: set[tuple[int, ...]] = set()
        for expression in _expressions(specification, campaign.max_ast_nodes):
            if examined >= budget: break
            try: outputs = tuple(_evaluate_canonical_expression(expression, item.input_value, specification) for item in training.training_examples)
            except ValueError: continue
            if outputs in seen_behaviors: continue
            seen_behaviors.add(outputs); examined += 1
            error = sum(output != item.output_value for output, item in zip(outputs, training.training_examples))
            metrics = expression_metrics(expression, specification); program_hash = canonical_sha256(expression)
            ranked = (error, int(metrics["node_count"]), program_hash, expression)
            if best is None or ranked[:3] < best[:3]: best = ranked
        search_space_hash = canonical_sha256({"dsl_hash": specification.dsl_hash, "max_nodes": campaign.max_ast_nodes})
        if best is None or best[0] != 0:
            receipt = SynthesisReceipt("genesis-m7-synthesis-receipt-v1", campaign.campaign_hash, search_space_hash, canonical_sha256(campaign.search_budget), examined, SynthesisTermination.BUDGET_EXHAUSTED if examined >= budget else SynthesisTermination.NO_EXACT_CANDIDATE, None, None, None)
            return SynthesisOutcome(receipt, None, None if best is None else best[0])
        error, _nodes, program_hash, expression = best
        training_evidence_hash = canonical_sha256({"training_commitment_hash": training.training_commitment_hash, "candidate_program_hash": program_hash, "training_error": error, "examples": tuple(item.canonical_payload() for item in training.training_examples)})
        ranking_evidence_hash = canonical_sha256({"rule": campaign.candidate_ranking_rule, "rank": (error, _nodes, program_hash), "examined": examined})
        skill = ProgramSkillArtifact("genesis-m7-program-skill-v1", "FINITE_INTEGER_FUNCTION", specification.dsl_version, {"kind":"integer"}, {"kind":"integer"}, expression, expression_metrics(expression, specification), _primitives(expression), campaign.campaign_hash, (training.training_commitment_hash, training_evidence_hash))
        receipt = SynthesisReceipt("genesis-m7-synthesis-receipt-v1", campaign.campaign_hash, search_space_hash, canonical_sha256(campaign.search_budget), examined, SynthesisTermination.SELECTED, skill.skill_hash, training_evidence_hash, ranking_evidence_hash)
        return SynthesisOutcome(receipt, skill, error)


def replay_v1_synthesis(
    *,
    campaign: AcquisitionCampaignManifest,
    specification: DSLSpecification,
    training: LearnerTrainingView,
    receipt: SynthesisReceipt,
) -> SynthesisOutcome:
    """Replay a historical v1 receipt using only v1 search semantics.

    This deliberately rejects a receipt from any later search engine.  The
    helper is a narrow replay boundary for H1; normal M7 federation replay
    continues to invoke :class:`DeterministicProgramSynthesizer` directly.
    """

    if (
        not isinstance(receipt, SynthesisReceipt)
        or receipt.schema_version != "genesis-m7-synthesis-receipt-v1"
        or campaign.synthesizer_implementation_hash
        != V1_SYNTHESIZER_IMPLEMENTATION_HASH
    ):
        raise ValueError("genesis_v1_synthesis_replay_version_mismatch")
    outcome = DeterministicProgramSynthesizer().synthesize(
        campaign=campaign, specification=specification, training=training,
    )
    if outcome.receipt.synthesis_hash != receipt.synthesis_hash:
        raise ValueError("genesis_v1_synthesis_replay_mismatch")
    return outcome
