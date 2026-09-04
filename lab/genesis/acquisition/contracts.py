"""Sealed, derivable contracts for the first M7 capability acquisition.

M7 deliberately models a capability as an immutable program artifact, not as
an entry in a mutable registry.  These types establish the scientific links
which later M7 units must re-derive: a selected candidate comes only from a
sealed campaign and synthesis receipt, and a promoted G1 is exactly G0 plus
that one concrete skill.

This module owns structural AST identity only.  M7-B will add the safe DSL's
operator and evaluation semantics; no Python code is embedded or executed by
these contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash


DATASET_SPLITS = ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")
CANDIDATE_RANKING_RULE = "training_error_then_mdl_then_canonical_program_hash-v1"
PROMOTION_RULE = "train_exact_audit_once_exact_no_leakage-v1"
HUMAN_INTERVENTION_POLICY = "no_interactive_corrective_selection-v1"


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _canonical_hashes(values: Sequence[str], reason: str) -> tuple[str, ...]:
    result = tuple(sorted(str(value) for value in values))
    if len(set(result)) != len(result) or any(not is_artifact_hash(value) for value in result):
        raise ValueError(reason)
    return result


def _canonical_strings(values: Sequence[str], reason: str) -> tuple[str, ...]:
    result = tuple(sorted(str(value) for value in values))
    if not result or len(set(result)) != len(result) or any(not value for value in result):
        raise ValueError(reason)
    return result


def _require_identifier(value: str, reason: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(reason)


def _inspect_ast(node: Any) -> tuple[int, int, tuple[str, ...]]:
    """Return structural metrics without interpreting any DSL operation.

    Requiring the compact ``op``/``args``/``value`` shape now prevents later
    ambiguity in program identity.  M7-B, rather than this identity layer,
    decides which operations and arities are semantically allowed.
    """

    if not isinstance(node, Mapping):
        raise ValueError("genesis_program_ast_node_invalid")
    keys = set(node)
    if not keys.issubset({"op", "args", "value"}) or "op" not in keys or "args" not in keys:
        raise ValueError("genesis_program_ast_shape_invalid")
    op = node["op"]
    args = node["args"]
    if not isinstance(op, str) or not op or not isinstance(args, tuple):
        raise ValueError("genesis_program_ast_node_invalid")
    if "value" in node and (not isinstance(node["value"], int) or isinstance(node["value"], bool)):
        raise ValueError("genesis_program_ast_value_invalid")
    child_metrics = tuple(_inspect_ast(item) for item in args)
    return (
        1 + sum(item[0] for item in child_metrics),
        1 + max((item[1] for item in child_metrics), default=0),
        tuple(sorted({op, *(primitive for item in child_metrics for primitive in item[2])})),
    )


def _complexity_payload(program_ast: Mapping[str, Any]) -> Mapping[str, int]:
    node_count, depth, _ = _inspect_ast(program_ast)
    return freeze({"node_count": node_count, "ast_depth": depth})


def _ast_constants(node: Any) -> tuple[int, ...]:
    if not isinstance(node, Mapping):
        raise ValueError("genesis_program_ast_node_invalid")
    values: list[int] = []
    if "value" in node:
        value = node["value"]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("genesis_program_ast_value_invalid")
        values.append(value)
    for child in node.get("args", ()):
        values.extend(_ast_constants(child))
    return tuple(values)


@dataclass(frozen=True, slots=True)
class ProgramSkillArtifact:
    """One reusable, inert program capability with a canonical AST identity."""

    schema_version: str
    skill_kind: str
    dsl_version: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    program_ast: Mapping[str, Any]
    complexity: Mapping[str, int]
    required_primitives: tuple[str, ...]
    discovery_campaign_hash: str
    provenance_hashes: tuple[str, ...]
    program_hash: str = field(init=False)
    skill_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.schema_version, "genesis_skill_schema_invalid")
        _require_identifier(self.skill_kind, "genesis_skill_kind_invalid")
        _require_identifier(self.dsl_version, "genesis_skill_dsl_invalid")
        if not isinstance(self.input_contract, Mapping) or not isinstance(self.output_contract, Mapping):
            raise ValueError("genesis_skill_io_contract_invalid")
        object.__setattr__(self, "input_contract", freeze(self.input_contract))
        object.__setattr__(self, "output_contract", freeze(self.output_contract))
        object.__setattr__(self, "program_ast", freeze(self.program_ast))
        expected_complexity = _complexity_payload(self.program_ast)
        object.__setattr__(self, "complexity", freeze(self.complexity))
        if self.complexity != expected_complexity:
            raise ValueError("genesis_skill_complexity_not_derived")
        _, _, primitives = _inspect_ast(self.program_ast)
        object.__setattr__(self, "required_primitives", _canonical_strings(
            self.required_primitives, "genesis_skill_primitives_invalid"
        ))
        if self.required_primitives != primitives:
            raise ValueError("genesis_skill_primitives_not_derived")
        _require_hash(self.discovery_campaign_hash, "genesis_skill_campaign_hash_invalid")
        provenance_hashes = _canonical_hashes(
            self.provenance_hashes, "genesis_skill_provenance_invalid"
        )
        if not provenance_hashes:
            raise ValueError("genesis_skill_provenance_missing")
        object.__setattr__(self, "provenance_hashes", provenance_hashes)
        object.__setattr__(self, "program_hash", canonical_sha256(self.program_ast))
        object.__setattr__(self, "skill_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "skill_kind": self.skill_kind,
            "dsl_version": self.dsl_version,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "program_ast": self.program_ast,
            "program_hash": self.program_hash,
            "complexity": self.complexity,
            "required_primitives": self.required_primitives,
            "discovery_campaign_hash": self.discovery_campaign_hash,
            "provenance_hashes": self.provenance_hashes,
        }

    def validate(self) -> bool:
        try:
            _, _, primitives = _inspect_ast(self.program_ast)
            return (
                self.program_hash == canonical_sha256(self.program_ast)
                and self.complexity == _complexity_payload(self.program_ast)
                and self.required_primitives == primitives
                and self.provenance_hashes == _canonical_hashes(
                    self.provenance_hashes, "genesis_skill_provenance_invalid"
                )
                and is_artifact_hash(self.discovery_campaign_hash)
                and self.skill_hash == canonical_sha256(self.canonical_payload())
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProgramSkillArtifact":
        values = dict(payload)
        supplied_program_hash = values.pop("program_hash")
        skill = cls(**values)
        if supplied_program_hash != skill.program_hash:
            raise ValueError("genesis_skill_program_hash_invalid")
        return skill


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """A state of capabilities, represented as a canonical immutable set."""

    manifest_id: str
    schema_version: str
    skill_hashes: tuple[str, ...]
    predecessor_manifest_hash: str | None = None
    added_skill_hashes: tuple[str, ...] = ()
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.manifest_id, "genesis_capability_manifest_id_invalid")
        _require_identifier(self.schema_version, "genesis_capability_manifest_schema_invalid")
        object.__setattr__(self, "skill_hashes", _canonical_hashes(
            self.skill_hashes, "genesis_capability_manifest_skills_invalid"
        ))
        object.__setattr__(self, "added_skill_hashes", _canonical_hashes(
            self.added_skill_hashes, "genesis_capability_manifest_delta_invalid"
        ))
        if self.predecessor_manifest_hash is None:
            if self.added_skill_hashes:
                raise ValueError("genesis_capability_manifest_root_delta_invalid")
        else:
            _require_hash(self.predecessor_manifest_hash, "genesis_capability_manifest_predecessor_invalid")
            if not self.added_skill_hashes or not set(self.added_skill_hashes).issubset(self.skill_hashes):
                raise ValueError("genesis_capability_manifest_delta_invalid")
        object.__setattr__(self, "manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
            "skill_hashes": self.skill_hashes,
            "predecessor_manifest_hash": self.predecessor_manifest_hash,
            "added_skill_hashes": self.added_skill_hashes,
        }

    def validate(self) -> bool:
        try:
            if self.skill_hashes != _canonical_hashes(
                self.skill_hashes, "genesis_capability_manifest_skills_invalid"
            ) or self.added_skill_hashes != _canonical_hashes(
                self.added_skill_hashes, "genesis_capability_manifest_delta_invalid"
            ):
                return False
            if self.predecessor_manifest_hash is None:
                if self.added_skill_hashes:
                    return False
            elif (
                not is_artifact_hash(self.predecessor_manifest_hash)
                or not self.added_skill_hashes
                or not set(self.added_skill_hashes).issubset(self.skill_hashes)
            ):
                return False
            return self.manifest_hash == canonical_sha256(self.canonical_payload())
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CapabilityManifest":
        return cls(**dict(payload))


def derive_successor_manifest(
    baseline: CapabilityManifest,
    skill: ProgramSkillArtifact,
    *,
    manifest_id: str,
    schema_version: str,
) -> CapabilityManifest:
    """Construct the only M7-v1 successor form: ``G1 = G0 ∪ {z}``."""

    if not baseline.validate() or not skill.validate():
        raise ValueError("genesis_capability_successor_input_invalid")
    if skill.skill_hash in baseline.skill_hashes:
        raise ValueError("genesis_capability_successor_skill_already_present")
    return CapabilityManifest(
        manifest_id=manifest_id,
        schema_version=schema_version,
        skill_hashes=(*baseline.skill_hashes, skill.skill_hash),
        predecessor_manifest_hash=baseline.manifest_hash,
        added_skill_hashes=(skill.skill_hash,),
    )


def validate_manifest_successor(
    successor: CapabilityManifest,
    baseline: CapabilityManifest,
    skill: ProgramSkillArtifact,
) -> bool:
    """Re-derive a one-skill promotion rather than trusting manifest counters."""

    return (
        baseline.validate()
        and successor.validate()
        and skill.validate()
        and successor.predecessor_manifest_hash == baseline.manifest_hash
        and successor.added_skill_hashes == (skill.skill_hash,)
        and successor.skill_hashes == tuple(sorted((*baseline.skill_hashes, skill.skill_hash)))
        and skill.skill_hash not in baseline.skill_hashes
    )


@dataclass(frozen=True, slots=True)
class AcquisitionCampaignManifest:
    """Frozen pre-acquisition policy and non-leaking dataset commitments."""

    campaign_id: str
    schema_version: str
    g0_snapshot_hash: str
    g0_capability_manifest_hash: str
    dsl_hash: str
    synthesizer_implementation_hash: str
    dataset_commitments: Mapping[str, str]
    task_generator_implementation_hash: str
    dataset_seed_commitments: Mapping[str, str]
    search_budget: Mapping[str, int]
    max_ast_depth: int
    max_ast_nodes: int
    allowed_constants: tuple[int, ...]
    allowed_operators: tuple[str, ...]
    candidate_ranking_rule: str
    promotion_rule: str
    cfi_policy_hash: str
    resource_budget_hash: str
    timeout_seconds: int
    human_intervention_policy: str
    verifier_obligation_hashes: tuple[str, ...]
    campaign_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.campaign_id, "genesis_acquisition_campaign_id_invalid")
        _require_identifier(self.schema_version, "genesis_acquisition_campaign_schema_invalid")
        for value, reason in (
            (self.g0_snapshot_hash, "genesis_acquisition_g0_snapshot_invalid"),
            (self.g0_capability_manifest_hash, "genesis_acquisition_g0_manifest_invalid"),
            (self.dsl_hash, "genesis_acquisition_dsl_invalid"),
            (self.synthesizer_implementation_hash, "genesis_acquisition_synthesizer_invalid"),
            (self.task_generator_implementation_hash, "genesis_acquisition_generator_invalid"),
            (self.cfi_policy_hash, "genesis_acquisition_cfi_policy_invalid"),
            (self.resource_budget_hash, "genesis_acquisition_resource_budget_invalid"),
        ):
            _require_hash(value, reason)
        commitments = {str(key): str(value) for key, value in self.dataset_commitments.items()}
        seed_commitments = {str(key): str(value) for key, value in self.dataset_seed_commitments.items()}
        if set(commitments) != set(DATASET_SPLITS) or set(seed_commitments) != set(DATASET_SPLITS):
            raise ValueError("genesis_acquisition_split_commitments_invalid")
        if any(not is_artifact_hash(value) for value in (*commitments.values(), *seed_commitments.values())):
            raise ValueError("genesis_acquisition_split_hash_invalid")
        if len(set(commitments.values())) != len(DATASET_SPLITS) or len(set(seed_commitments.values())) != len(DATASET_SPLITS):
            raise ValueError("genesis_acquisition_split_overlap_invalid")
        object.__setattr__(self, "dataset_commitments", freeze(commitments))
        object.__setattr__(self, "dataset_seed_commitments", freeze(seed_commitments))
        budget = freeze(self.search_budget)
        if set(budget) != {"max_candidates"} or not isinstance(budget["max_candidates"], int) or isinstance(budget["max_candidates"], bool) or budget["max_candidates"] <= 0:
            raise ValueError("genesis_acquisition_search_budget_invalid")
        object.__setattr__(self, "search_budget", budget)
        if (
            not isinstance(self.max_ast_depth, int)
            or isinstance(self.max_ast_depth, bool)
            or self.max_ast_depth <= 0
            or not isinstance(self.max_ast_nodes, int)
            or isinstance(self.max_ast_nodes, bool)
            or self.max_ast_nodes <= 0
            or not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("genesis_acquisition_limits_invalid")
        constants = tuple(sorted(self.allowed_constants))
        if not constants or len(set(constants)) != len(constants) or any(not isinstance(value, int) or isinstance(value, bool) for value in constants):
            raise ValueError("genesis_acquisition_constants_invalid")
        object.__setattr__(self, "allowed_constants", constants)
        object.__setattr__(self, "allowed_operators", _canonical_strings(
            self.allowed_operators, "genesis_acquisition_operators_invalid"
        ))
        if self.candidate_ranking_rule != CANDIDATE_RANKING_RULE:
            raise ValueError("genesis_acquisition_ranking_rule_invalid")
        if self.promotion_rule != PROMOTION_RULE:
            raise ValueError("genesis_acquisition_promotion_rule_invalid")
        if self.human_intervention_policy != HUMAN_INTERVENTION_POLICY:
            raise ValueError("genesis_acquisition_human_policy_invalid")
        obligations = _canonical_hashes(
            self.verifier_obligation_hashes, "genesis_acquisition_verifier_obligations_invalid"
        )
        if not obligations:
            raise ValueError("genesis_acquisition_verifier_obligations_missing")
        object.__setattr__(self, "verifier_obligation_hashes", obligations)
        object.__setattr__(self, "campaign_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "schema_version": self.schema_version,
            "g0_snapshot_hash": self.g0_snapshot_hash,
            "g0_capability_manifest_hash": self.g0_capability_manifest_hash,
            "dsl_hash": self.dsl_hash,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "dataset_commitments": self.dataset_commitments,
            "task_generator_implementation_hash": self.task_generator_implementation_hash,
            "dataset_seed_commitments": self.dataset_seed_commitments,
            "search_budget": self.search_budget,
            "max_ast_depth": self.max_ast_depth,
            "max_ast_nodes": self.max_ast_nodes,
            "allowed_constants": self.allowed_constants,
            "allowed_operators": self.allowed_operators,
            "candidate_ranking_rule": self.candidate_ranking_rule,
            "promotion_rule": self.promotion_rule,
            "cfi_policy_hash": self.cfi_policy_hash,
            "resource_budget_hash": self.resource_budget_hash,
            "timeout_seconds": self.timeout_seconds,
            "human_intervention_policy": self.human_intervention_policy,
            "verifier_obligation_hashes": self.verifier_obligation_hashes,
        }

    def validate(self) -> bool:
        try:
            rebuilt = AcquisitionCampaignManifest(**self.canonical_payload())
            return rebuilt.campaign_hash == self.campaign_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AcquisitionCampaignManifest":
        return cls(**dict(payload))


def validate_campaign_binding(
    campaign: AcquisitionCampaignManifest,
    g0_manifest: CapabilityManifest,
    *,
    g0_snapshot_hash: str,
) -> bool:
    return (
        campaign.validate()
        and g0_manifest.validate()
        and campaign.g0_capability_manifest_hash == g0_manifest.manifest_hash
        and campaign.g0_snapshot_hash == g0_snapshot_hash
        and is_artifact_hash(g0_snapshot_hash)
    )


class SynthesisTermination(str, Enum):
    SELECTED = "SELECTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NO_EXACT_CANDIDATE = "NO_EXACT_CANDIDATE"


@dataclass(frozen=True, slots=True)
class SynthesisReceipt:
    """The bounded, TRAIN-only result from a deterministic search."""

    schema_version: str
    campaign_hash: str
    search_space_hash: str
    search_budget_hash: str
    candidates_examined: int
    termination: SynthesisTermination
    selected_skill_hash: str | None
    training_evidence_hash: str | None
    ranking_evidence_hash: str | None
    synthesis_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.schema_version, "genesis_synthesis_schema_invalid")
        for value, reason in (
            (self.campaign_hash, "genesis_synthesis_campaign_invalid"),
            (self.search_space_hash, "genesis_synthesis_space_invalid"),
            (self.search_budget_hash, "genesis_synthesis_budget_invalid"),
        ):
            _require_hash(value, reason)
        object.__setattr__(self, "termination", SynthesisTermination(self.termination))
        if not isinstance(self.candidates_examined, int) or isinstance(self.candidates_examined, bool) or self.candidates_examined < 0:
            raise ValueError("genesis_synthesis_count_invalid")
        result_hashes = (self.selected_skill_hash, self.training_evidence_hash, self.ranking_evidence_hash)
        if self.termination is SynthesisTermination.SELECTED:
            if any(value is None or not is_artifact_hash(value) for value in result_hashes):
                raise ValueError("genesis_synthesis_selected_material_invalid")
        elif any(value is not None for value in result_hashes):
            raise ValueError("genesis_synthesis_failed_material_invalid")
        object.__setattr__(self, "synthesis_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "search_space_hash": self.search_space_hash,
            "search_budget_hash": self.search_budget_hash,
            "candidates_examined": self.candidates_examined,
            "termination": self.termination.value,
            "selected_skill_hash": self.selected_skill_hash,
            "training_evidence_hash": self.training_evidence_hash,
            "ranking_evidence_hash": self.ranking_evidence_hash,
        }

    def validate(self) -> bool:
        try:
            rebuilt = SynthesisReceipt(**self.canonical_payload())
            return rebuilt.synthesis_hash == self.synthesis_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SynthesisReceipt":
        return cls(**dict(payload))


def validate_synthesis_receipt(
    receipt: SynthesisReceipt,
    campaign: AcquisitionCampaignManifest,
    candidate: ProgramSkillArtifact | None = None,
) -> bool:
    if not receipt.validate() or not campaign.validate():
        return False
    if (
        receipt.campaign_hash != campaign.campaign_hash
        or receipt.search_budget_hash != canonical_sha256(campaign.search_budget)
        or receipt.candidates_examined > campaign.search_budget["max_candidates"]
    ):
        return False
    if receipt.termination is SynthesisTermination.SELECTED:
        if candidate is None or not candidate.validate() or receipt.selected_skill_hash != candidate.skill_hash:
            return False
        try:
            return (
                candidate.discovery_campaign_hash == campaign.campaign_hash
                and candidate.complexity["node_count"] <= campaign.max_ast_nodes
                and candidate.complexity["ast_depth"] <= campaign.max_ast_depth
                and set(candidate.required_primitives).issubset(campaign.allowed_operators)
                and set(_ast_constants(candidate.program_ast)).issubset(campaign.allowed_constants)
            )
        except (KeyError, TypeError, ValueError):
            return False
    return candidate is None


@dataclass(frozen=True, slots=True)
class CandidateCommitment:
    """A pre-audit commitment to the one candidate selected from TRAIN."""

    schema_version: str
    candidate_skill_hash: str
    campaign_hash: str
    training_evidence_hash: str
    synthesis_receipt_hash: str
    ranking_evidence_hash: str
    commitment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.schema_version, "genesis_candidate_commitment_schema_invalid")
        for value, reason in (
            (self.candidate_skill_hash, "genesis_candidate_commitment_skill_invalid"),
            (self.campaign_hash, "genesis_candidate_commitment_campaign_invalid"),
            (self.training_evidence_hash, "genesis_candidate_commitment_training_invalid"),
            (self.synthesis_receipt_hash, "genesis_candidate_commitment_synthesis_invalid"),
            (self.ranking_evidence_hash, "genesis_candidate_commitment_ranking_invalid"),
        ):
            _require_hash(value, reason)
        object.__setattr__(self, "commitment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "candidate_skill_hash": self.candidate_skill_hash,
            "campaign_hash": self.campaign_hash,
            "training_evidence_hash": self.training_evidence_hash,
            "synthesis_receipt_hash": self.synthesis_receipt_hash,
            "ranking_evidence_hash": self.ranking_evidence_hash,
        }

    def validate(self) -> bool:
        return self.commitment_hash == canonical_sha256(self.canonical_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CandidateCommitment":
        return cls(**dict(payload))


def validate_candidate_commitment(
    commitment: CandidateCommitment,
    campaign: AcquisitionCampaignManifest,
    synthesis: SynthesisReceipt,
    candidate: ProgramSkillArtifact,
) -> bool:
    return (
        commitment.validate()
        and candidate.validate()
        and validate_synthesis_receipt(synthesis, campaign, candidate)
        and commitment.campaign_hash == campaign.campaign_hash
        and commitment.candidate_skill_hash == candidate.skill_hash
        and commitment.synthesis_receipt_hash == synthesis.synthesis_hash
        and commitment.training_evidence_hash == synthesis.training_evidence_hash
        and commitment.ranking_evidence_hash == synthesis.ranking_evidence_hash
    )


class PromotionStatus(str, Enum):
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    """Historical admission evidence; CAS presence of a skill is insufficient."""

    schema_version: str
    campaign_hash: str
    candidate_commitment_hash: str
    synthesis_receipt_hash: str
    candidate_skill_hash: str
    audit_evidence_hash: str
    g0_capability_manifest_hash: str
    g1_capability_manifest_hash: str | None
    status: PromotionStatus
    reason_codes: tuple[str, ...]
    promotion_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identifier(self.schema_version, "genesis_promotion_schema_invalid")
        for value, reason in (
            (self.campaign_hash, "genesis_promotion_campaign_invalid"),
            (self.candidate_commitment_hash, "genesis_promotion_commitment_invalid"),
            (self.synthesis_receipt_hash, "genesis_promotion_synthesis_invalid"),
            (self.candidate_skill_hash, "genesis_promotion_skill_invalid"),
            (self.audit_evidence_hash, "genesis_promotion_audit_invalid"),
            (self.g0_capability_manifest_hash, "genesis_promotion_g0_invalid"),
        ):
            _require_hash(value, reason)
        object.__setattr__(self, "status", PromotionStatus(self.status))
        if self.status is PromotionStatus.PROMOTED:
            if self.g1_capability_manifest_hash is None:
                raise ValueError("genesis_promotion_g1_missing")
            _require_hash(self.g1_capability_manifest_hash, "genesis_promotion_g1_invalid")
        elif self.g1_capability_manifest_hash is not None:
            raise ValueError("genesis_promotion_rejected_g1_present")
        object.__setattr__(self, "reason_codes", tuple(sorted(self.reason_codes)))
        object.__setattr__(self, "promotion_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "candidate_commitment_hash": self.candidate_commitment_hash,
            "synthesis_receipt_hash": self.synthesis_receipt_hash,
            "candidate_skill_hash": self.candidate_skill_hash,
            "audit_evidence_hash": self.audit_evidence_hash,
            "g0_capability_manifest_hash": self.g0_capability_manifest_hash,
            "g1_capability_manifest_hash": self.g1_capability_manifest_hash,
            "status": self.status.value,
            "reason_codes": self.reason_codes,
        }

    def validate(self) -> bool:
        try:
            rebuilt = PromotionReceipt(**self.canonical_payload())
            return rebuilt.promotion_hash == self.promotion_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PromotionReceipt":
        return cls(**dict(payload))


def validate_promotion_receipt(
    receipt: PromotionReceipt,
    *,
    campaign: AcquisitionCampaignManifest,
    commitment: CandidateCommitment,
    synthesis: SynthesisReceipt,
    candidate: ProgramSkillArtifact,
    g0_manifest: CapabilityManifest,
    g1_manifest: CapabilityManifest | None,
) -> bool:
    """Validate only structural promotion here; M7-D validates audit content."""

    if not (
        receipt.validate()
        and validate_campaign_binding(
            campaign, g0_manifest, g0_snapshot_hash=campaign.g0_snapshot_hash
        )
        and validate_candidate_commitment(commitment, campaign, synthesis, candidate)
        and receipt.campaign_hash == campaign.campaign_hash
        and receipt.candidate_commitment_hash == commitment.commitment_hash
        and receipt.synthesis_receipt_hash == synthesis.synthesis_hash
        and receipt.candidate_skill_hash == candidate.skill_hash
        and receipt.g0_capability_manifest_hash == g0_manifest.manifest_hash
    ):
        return False
    if receipt.status is PromotionStatus.PROMOTED:
        return (
            g1_manifest is not None
            and receipt.g1_capability_manifest_hash == g1_manifest.manifest_hash
            and validate_manifest_successor(g1_manifest, g0_manifest, candidate)
        )
    return g1_manifest is None and receipt.g1_capability_manifest_hash is None
