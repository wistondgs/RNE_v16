"""Predeclared complete-frontier contracts for M7-H2.

This module is deliberately authority-side preparation, not a learner API and
not a campaign runner.  It audits the sealed benchmark's target class, fixes
one common bounded frontier, and predeclares six fresh campaign slots before
any H2 acquisition result can exist.

The resulting claim remains deliberately narrow: the H2 battery investigates
independent acquisition inside the immutable M7 DSL and its predeclared finite
frontier.  It is not evidence about unbounded or open-ended search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, Mapping, Sequence

from lab.genesis.acquisition.battery import GEIConfirmatoryBatteryManifest
from lab.genesis.acquisition.benchmark import DatasetSplit, SealedCapabilityBenchmark
from lab.genesis.acquisition.confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    AggregateRule,
    CampaignStateMode,
    GEIAcceptancePolicy,
    PilotEvidencePolicy,
    REQUIRED_PER_CAMPAIGN_GATES,
    RetentionPolicy,
)
from lab.genesis.acquisition.contracts import CapabilityManifest
from lab.genesis.acquisition.dsl import (
    DSLSpecification,
    canonical_expression,
    evaluate_expression,
    expression_metrics,
)
from lab.genesis.acquisition.ranked_synthesis import (
    RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
    SEARCH_SEMANTICS_V2_ID,
    RankedSearchPolicy,
    RankedSearchTermination,
    ranked_search_policy,
)
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash


_AUDIT_SCHEMA = "genesis-m7-target-frontier-audit-v2"
_ESTIMATE_SCHEMA = "genesis-m7-complete-frontier-resource-estimate-v2"
_POLICY_SCHEMA = "genesis-m7-complete-frontier-search-policy-v2"
_ACCEPTANCE_SCHEMA = "genesis-m7-gei-acceptance-policy-v2"
_BATTERY_SCHEMA = "genesis-m7-gei-confirmatory-battery-v2"
_TASK_PLAN_SCHEMA = "genesis-m7-gei-confirmatory-task-plan-v2"

_POLICY_ID = "M7_H2_COMPLETE_TARGET_FRONTIER_V2"
_RANKED_ENGINE_POLICY_ID = "m7-h2-complete-frontier-v2"
_MDL_MEASURE = "AST_NODE_COUNT-v1"
_REPRESENTATIVE_RULE = "ARGMIN_MDL_CANONICAL_HASH_PER_TRAIN_BEHAVIOR-v2"
_LEVEL_COMPLETION_RULE = "COMPLETE_EACH_MDL_LEVEL_BEFORE_SELECTION-v2"
_NO_EXACT_FULL_FRONTIER = "SEARCH_OR_BENCHMARK_INTEGRITY_FAILURE"
_RESOURCE_ESTIMATE_METHOD = (
    "exact_m7_grammar_count_with_1ms_per_raw_ast_conservative_model-v1"
)
_BYTES_PER_FRONTIER_RECORD = 2_048
_MEMORY_MARGIN = 1.20
_WALL_MARGIN = 1.20

_FAILURE_SEMANTICS = freeze({
    "all_pass": "GE_I_CAMPAIGN_SUPPORTED",
    "any_fail": "GE_I_CAMPAIGN_FAIL",
    "otherwise": "GE_I_CAMPAIGN_NOT_PROVEN",
    "battery_all_supported": "GE_I_BATTERY_SUPPORTED",
    "battery_any_fail": "GE_I_BATTERY_FAIL",
    "battery_otherwise": "GE_I_BATTERY_NOT_PROVEN",
})
_ADAPTATION_LINEAGE = freeze({
    "v1": "GE_I_BATTERY_NOT_PROVEN",
    "h0": "SEARCH_ENUMERATION_DEFECT",
    "h1": "SEARCH_CORRECTNESS_REPAIRED",
    "v2": "PREDECLARED_COMPLETE_FRONTIER_CONFIRMATORY",
})
H2_ADAPTATION_LINEAGE_HASH = canonical_sha256(_ADAPTATION_LINEAGE)


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _canonical_task_ids(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(sorted(str(item) for item in values))
    if result != CANONICAL_CONFIRMATORY_TASK_IDS:
        raise ValueError("genesis_h2_task_set_invalid")
    return result


def _target_operators(node: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({str(node["op"]), *(
        operator
        for child in node["args"]
        for operator in _target_operators(child)
    )}))


def _target_constants(node: Mapping[str, Any]) -> tuple[int, ...]:
    values = () if "value" not in node else (int(node["value"]),)
    return tuple(sorted({
        *values,
        *(value for child in node["args"] for value in _target_constants(child)),
    }))


@dataclass(frozen=True, slots=True)
class TargetFrontierWitness:
    """A non-leaking, authority-derived membership witness for one target."""

    task_id: str
    target_ast_hash: str
    target_dsl_valid: bool
    target_mdl: int
    target_depth: int
    target_nodes: int
    target_operator_set: tuple[str, ...]
    target_constant_set: tuple[int, ...]
    training_split_commitment_hash: str
    witness_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.task_id or not self.target_dsl_valid:
            raise ValueError("genesis_h2_target_witness_identity_invalid")
        for value in (self.target_ast_hash, self.training_split_commitment_hash):
            _require_hash(value, "genesis_h2_target_witness_hash_invalid")
        if (
            any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in (self.target_mdl, self.target_depth, self.target_nodes)
            )
            or self.target_mdl != self.target_nodes
        ):
            raise ValueError("genesis_h2_target_witness_metrics_invalid")
        operators = tuple(sorted(str(item) for item in self.target_operator_set))
        constants = tuple(sorted(int(item) for item in self.target_constant_set))
        if not operators or len(operators) != len(set(operators)) or len(constants) != len(set(constants)):
            raise ValueError("genesis_h2_target_witness_language_invalid")
        object.__setattr__(self, "target_operator_set", operators)
        object.__setattr__(self, "target_constant_set", constants)
        object.__setattr__(self, "witness_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "target_ast_hash": self.target_ast_hash,
            "target_dsl_valid": self.target_dsl_valid,
            "target_mdl": self.target_mdl,
            "target_depth": self.target_depth,
            "target_nodes": self.target_nodes,
            "target_operator_set": self.target_operator_set,
            "target_constant_set": self.target_constant_set,
            "training_split_commitment_hash": self.training_split_commitment_hash,
        }

    def validate(self) -> bool:
        try:
            return TargetFrontierWitness(**self.canonical_payload()).witness_hash == self.witness_hash
        except (TypeError, ValueError):
            return False


def _authority_target_witness(
    benchmark: SealedCapabilityBenchmark, task_id: str,
) -> TargetFrontierWitness:
    """Derive one witness without placing a target in a learner-facing object."""

    task = benchmark._tasks[task_id]  # Authority boundary; never used by a synthesizer.
    expression = canonical_expression(task.target_ast, benchmark.specification)
    metrics = expression_metrics(expression, benchmark.specification)
    training = benchmark.learner_view(task_id)
    if (
        expression != task.target_ast
        or tuple(
            evaluate_expression(expression, item.input_value, benchmark.specification)
            for item in training.training_examples
        ) != tuple(item.output_value for item in training.training_examples)
    ):
        raise ValueError("genesis_h2_target_train_generation_invalid")
    return TargetFrontierWitness(
        task_id,
        canonical_sha256(expression),
        True,
        int(metrics["node_count"]),
        int(metrics["ast_depth"]),
        int(metrics["node_count"]),
        _target_operators(expression),
        _target_constants(expression),
        training.training_commitment_hash,
    )


@dataclass(frozen=True, slots=True)
class TargetClassFrontierAudit:
    """The target-class audit that derives, rather than accepts, ``C_star``."""

    schema_version: str
    benchmark_manifest_hash: str
    dsl_hash: str
    task_witnesses: tuple[TargetFrontierWitness, ...]
    c_star: int
    audit_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != _AUDIT_SCHEMA:
            raise ValueError("genesis_h2_frontier_audit_schema_invalid")
        for value in (self.benchmark_manifest_hash, self.dsl_hash):
            _require_hash(value, "genesis_h2_frontier_audit_hash_invalid")
        witnesses = tuple(sorted(self.task_witnesses, key=lambda item: item.task_id))
        if (
            _canonical_task_ids(tuple(item.task_id for item in witnesses))
            != tuple(item.task_id for item in witnesses)
            or not all(item.validate() for item in witnesses)
            or self.c_star != max(item.target_mdl for item in witnesses)
        ):
            raise ValueError("genesis_h2_frontier_audit_content_invalid")
        object.__setattr__(self, "task_witnesses", witnesses)
        object.__setattr__(self, "audit_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "dsl_hash": self.dsl_hash,
            "task_witnesses": tuple(item.canonical_payload() for item in self.task_witnesses),
            "c_star": self.c_star,
        }

    def validate(self) -> bool:
        try:
            witnesses = tuple(TargetFrontierWitness(**item.canonical_payload()) for item in self.task_witnesses)
            return TargetClassFrontierAudit(
                self.schema_version, self.benchmark_manifest_hash, self.dsl_hash,
                witnesses, self.c_star,
            ).audit_hash == self.audit_hash
        except (TypeError, ValueError):
            return False

    def validate_against(self, benchmark: SealedCapabilityBenchmark) -> bool:
        """Re-derive every scientific field from the sealed authority source."""

        if not (
            self.validate()
            and benchmark.validate()
            and self.benchmark_manifest_hash == benchmark.manifest.manifest_hash
            and self.dsl_hash == benchmark.specification.dsl_hash
        ):
            return False
        try:
            expected = tuple(
                _authority_target_witness(benchmark, task_id)
                for task_id in CANONICAL_CONFIRMATORY_TASK_IDS
            )
        except (KeyError, ValueError):
            return False
        return (
            tuple(item.canonical_payload() for item in self.task_witnesses)
            == tuple(item.canonical_payload() for item in expected)
            and self.c_star == max(item.target_mdl for item in expected)
        )

    def validate_against_specification(self, specification: DSLSpecification) -> bool:
        """Check the non-leaking structural relation used before benchmark access.

        The full source check remains :meth:`validate_against`; this smaller
        relation is only a construction prerequisite and never substitutes for
        the evaluator-side target re-derivation.
        """

        return (
            self.validate()
            and specification.validate()
            and self.dsl_hash == specification.dsl_hash
            and self.c_star <= specification.max_ast_nodes
            and all(item.target_depth <= specification.max_ast_depth for item in self.task_witnesses)
            and all(set(item.target_constant_set).issubset(specification.allowed_constants) for item in self.task_witnesses)
            and all(
                set(item.target_operator_set).issubset({operator.value for operator in specification.operators})
                for item in self.task_witnesses
            )
        )


def audit_target_class_frontier(
    benchmark: SealedCapabilityBenchmark,
) -> TargetClassFrontierAudit:
    """Audit the canonical target class before any H2 campaign may be created."""

    if not benchmark.validate():
        raise ValueError("genesis_h2_frontier_audit_benchmark_invalid")
    witnesses = tuple(
        _authority_target_witness(benchmark, task_id)
        for task_id in CANONICAL_CONFIRMATORY_TASK_IDS
    )
    return TargetClassFrontierAudit(
        _AUDIT_SCHEMA,
        benchmark.manifest.manifest_hash,
        benchmark.specification.dsl_hash,
        witnesses,
        max(item.target_mdl for item in witnesses),
    )


def _grammar_level_counts(
    specification: DSLSpecification,
    *, maximum_nodes: int,
    maximum_depth: int,
) -> tuple[int, ...]:
    """Count the exact canonical H1 grammar frontier without materializing ASTs.

    ``_expressions`` has one constructor family for leaves, three unary
    families, ordered SUB pairs, and hash-canonicalized unordered ADD pairs.
    The recurrence below counts that same finite grammar by ``(nodes, depth)``.
    It is checked in tests against the H1 enumerator's observed levels 1--6.
    """

    if (
        not specification.validate()
        or maximum_nodes <= 0
        or maximum_nodes > specification.max_ast_nodes
        or maximum_depth <= 0
        or maximum_depth > specification.max_ast_depth
    ):
        raise ValueError("genesis_h2_resource_frontier_invalid")
    counts: dict[tuple[int, int], int] = {(1, 1): 1 + len(specification.allowed_constants)}
    levels = [counts[(1, 1)]]
    unary_multiplier = len(specification.allowed_constants) + 2  # MUL_CONST, ABS, SQUARE
    for nodes in range(2, maximum_nodes + 1):
        current: dict[tuple[int, int], int] = {}

        def add(depth: int, amount: int) -> None:
            if depth <= maximum_depth:
                current[(nodes, depth)] = current.get((nodes, depth), 0) + amount

        for (child_nodes, child_depth), total in tuple(counts.items()):
            if child_nodes == nodes - 1:
                add(child_depth + 1, unary_multiplier * total)

        # SUB retains every ordered left/right pair.
        for left_nodes in range(1, nodes - 1):
            right_nodes = nodes - 1 - left_nodes
            for (n1, d1), left_total in tuple(counts.items()):
                if n1 != left_nodes:
                    continue
                for (n2, d2), right_total in tuple(counts.items()):
                    if n2 == right_nodes:
                        add(max(d1, d2) + 1, left_total * right_total)

        # ADD keeps exactly one orientation of each pair.  For equal child
        # sizes this is combinations-with-replacement, grouped by max depth.
        for left_nodes in range(1, nodes - 1):
            right_nodes = nodes - 1 - left_nodes
            if left_nodes > right_nodes:
                continue
            if left_nodes < right_nodes:
                for (n1, d1), left_total in tuple(counts.items()):
                    if n1 != left_nodes:
                        continue
                    for (n2, d2), right_total in tuple(counts.items()):
                        if n2 == right_nodes:
                            add(max(d1, d2) + 1, left_total * right_total)
                continue
            for depth in range(2, maximum_depth + 1):
                at_most = sum(
                    total for (size, item_depth), total in counts.items()
                    if size == left_nodes and item_depth <= depth - 1
                )
                below = sum(
                    total for (size, item_depth), total in counts.items()
                    if size == left_nodes and item_depth <= depth - 2
                )
                add(depth, at_most * (at_most + 1) // 2 - below * (below + 1) // 2)
        counts.update(current)
        levels.append(sum(current.values()))
    return tuple(levels)


@dataclass(frozen=True, slots=True)
class CompleteFrontierResourceEstimateV2:
    """A predeclared operational estimate, never scientific evidence itself."""

    schema_version: str
    frontier_audit_hash: str
    dsl_hash: str
    search_semantics_id: str
    synthesizer_implementation_hash: str
    estimate_method: str
    raw_ast_count_by_mdl: tuple[int, ...]
    maximum_raw_ast_count: int
    behavior_class_upper_bound: int
    expected_wall_time_seconds_per_campaign: int
    expected_wall_time_seconds_battery: int
    estimated_peak_memory_mib: int
    estimate_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _ESTIMATE_SCHEMA
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.synthesizer_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
            or self.estimate_method != _RESOURCE_ESTIMATE_METHOD
        ):
            raise ValueError("genesis_h2_resource_estimate_identity_invalid")
        for value in (self.frontier_audit_hash, self.dsl_hash):
            _require_hash(value, "genesis_h2_resource_estimate_hash_invalid")
        counts = tuple(self.raw_ast_count_by_mdl)
        if not counts or any(not isinstance(item, int) or item <= 0 for item in counts):
            raise ValueError("genesis_h2_resource_estimate_levels_invalid")
        if self.maximum_raw_ast_count != sum(counts) or self.behavior_class_upper_bound != sum(counts):
            raise ValueError("genesis_h2_resource_estimate_counts_invalid")
        if any(
            not isinstance(value, int) or value <= 0
            for value in (
                self.expected_wall_time_seconds_per_campaign,
                self.expected_wall_time_seconds_battery,
                self.estimated_peak_memory_mib,
            )
        ) or self.expected_wall_time_seconds_battery != 6 * self.expected_wall_time_seconds_per_campaign:
            raise ValueError("genesis_h2_resource_estimate_capacity_invalid")
        object.__setattr__(self, "raw_ast_count_by_mdl", counts)
        object.__setattr__(self, "estimate_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "frontier_audit_hash": self.frontier_audit_hash,
            "dsl_hash": self.dsl_hash,
            "search_semantics_id": self.search_semantics_id,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "estimate_method": self.estimate_method,
            "raw_ast_count_by_mdl": self.raw_ast_count_by_mdl,
            "maximum_raw_ast_count": self.maximum_raw_ast_count,
            "behavior_class_upper_bound": self.behavior_class_upper_bound,
            "expected_wall_time_seconds_per_campaign": self.expected_wall_time_seconds_per_campaign,
            "expected_wall_time_seconds_battery": self.expected_wall_time_seconds_battery,
            "estimated_peak_memory_mib": self.estimated_peak_memory_mib,
        }

    def validate(self) -> bool:
        try:
            return CompleteFrontierResourceEstimateV2(**self.canonical_payload()).estimate_hash == self.estimate_hash
        except (TypeError, ValueError):
            return False

    def validate_against(
        self, audit: TargetClassFrontierAudit, specification: DSLSpecification,
    ) -> bool:
        if not (
            self.validate()
            and audit.validate()
            and specification.validate()
            and self.frontier_audit_hash == audit.audit_hash
            and self.dsl_hash == specification.dsl_hash
        ):
            return False
        try:
            counts = _grammar_level_counts(
                specification,
                maximum_nodes=audit.c_star,
                maximum_depth=specification.max_ast_depth,
            )
        except ValueError:
            return False
        total = sum(counts)
        expected_wall = ceil((total / 1_000) * _WALL_MARGIN / 60) * 60
        expected_memory = ceil(
            (total * _BYTES_PER_FRONTIER_RECORD * _MEMORY_MARGIN) / (1024 * 1024 * 512)
        ) * 512
        return (
            self.raw_ast_count_by_mdl == counts
            and self.maximum_raw_ast_count == total
            and self.behavior_class_upper_bound == total
            and self.expected_wall_time_seconds_per_campaign == expected_wall
            and self.expected_wall_time_seconds_battery == 6 * expected_wall
            and self.estimated_peak_memory_mib == expected_memory
        )


def estimate_complete_frontier_resources(
    *,
    audit: TargetClassFrontierAudit,
    specification: DSLSpecification,
    benchmark: SealedCapabilityBenchmark,
) -> CompleteFrontierResourceEstimateV2:
    if not (
        audit.validate_against(benchmark)
        and specification.validate()
        and benchmark.specification.dsl_hash == specification.dsl_hash
        and audit.dsl_hash == specification.dsl_hash
    ):
        raise ValueError("genesis_h2_resource_estimate_input_invalid")
    counts = _grammar_level_counts(
        specification, maximum_nodes=audit.c_star, maximum_depth=specification.max_ast_depth,
    )
    total = sum(counts)
    per_campaign = ceil((total / 1_000) * _WALL_MARGIN / 60) * 60
    memory = ceil(
        (total * _BYTES_PER_FRONTIER_RECORD * _MEMORY_MARGIN) / (1024 * 1024 * 512)
    ) * 512
    return CompleteFrontierResourceEstimateV2(
        _ESTIMATE_SCHEMA, audit.audit_hash, specification.dsl_hash,
        SEARCH_SEMANTICS_V2_ID, RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
        _RESOURCE_ESTIMATE_METHOD, counts, total, total, per_campaign,
        6 * per_campaign, memory,
    )


def _enumeration_order_hash() -> str:
    return canonical_sha256({
        "search_semantics_id": SEARCH_SEMANTICS_V2_ID,
        "enumeration_order": "CANONICAL_AST_NODE_ASCENDING-v2",
    })


def _canonicalization_policy_hash() -> str:
    return canonical_sha256({"canonicalization": "DSL_CANONICAL_EXPRESSION-v1"})


def _dedup_policy_hash() -> str:
    return canonical_sha256({
        "deduplication": "one_rank_minimal_representative_per_train_behavior-v2",
        "representative_rule": _REPRESENTATIVE_RULE,
    })


@dataclass(frozen=True, slots=True)
class CompleteFrontierSearchPolicyV2:
    """One common, complete scientific frontier plus non-authoritative caps."""

    schema_version: str
    policy_id: str
    frontier_audit_hash: str
    resource_estimate_hash: str
    search_semantics_id: str
    synthesizer_implementation_hash: str
    dsl_version: str
    dsl_hash: str
    mdl_measure: str
    max_mdl: int
    max_depth: int
    max_nodes: int
    allowed_constants: tuple[int, ...]
    allowed_operators: tuple[str, ...]
    representative_rule: str
    level_completion_required: bool
    enumeration_order_hash: str
    canonicalization_policy_hash: str
    dedup_policy_hash: str
    max_raw_ast_evaluations: int
    max_distinct_behaviors: int
    max_wall_time_seconds: int
    max_peak_memory_mib: int
    termination_semantics: tuple[str, ...]
    complete_frontier_no_exact_status: str
    ranked_engine_policy_hash: str
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _POLICY_SCHEMA
            or self.policy_id != _POLICY_ID
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.synthesizer_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
            or self.mdl_measure != _MDL_MEASURE
            or self.representative_rule != _REPRESENTATIVE_RULE
            or self.level_completion_required is not True
            or self.enumeration_order_hash != _enumeration_order_hash()
            or self.canonicalization_policy_hash != _canonicalization_policy_hash()
            or self.dedup_policy_hash != _dedup_policy_hash()
            or self.complete_frontier_no_exact_status != _NO_EXACT_FULL_FRONTIER
        ):
            raise ValueError("genesis_h2_frontier_policy_identity_invalid")
        for value in (
            self.frontier_audit_hash, self.resource_estimate_hash, self.dsl_hash,
            self.enumeration_order_hash, self.canonicalization_policy_hash,
            self.dedup_policy_hash, self.ranked_engine_policy_hash,
        ):
            _require_hash(value, "genesis_h2_frontier_policy_hash_invalid")
        if not self.dsl_version or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (
                self.max_mdl, self.max_depth, self.max_nodes,
                self.max_raw_ast_evaluations, self.max_distinct_behaviors,
                self.max_wall_time_seconds, self.max_peak_memory_mib,
            )
        ):
            raise ValueError("genesis_h2_frontier_policy_limits_invalid")
        constants = tuple(sorted(self.allowed_constants))
        operators = tuple(sorted(str(item) for item in self.allowed_operators))
        if not constants or not operators or len(constants) != len(set(constants)) or len(operators) != len(set(operators)):
            raise ValueError("genesis_h2_frontier_policy_language_invalid")
        terms = tuple(str(item) for item in self.termination_semantics)
        expected_terms = tuple(item.value for item in RankedSearchTermination)
        if terms != expected_terms:
            raise ValueError("genesis_h2_frontier_policy_termination_invalid")
        object.__setattr__(self, "allowed_constants", constants)
        object.__setattr__(self, "allowed_operators", operators)
        object.__setattr__(self, "termination_semantics", terms)
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "frontier_audit_hash": self.frontier_audit_hash,
            "resource_estimate_hash": self.resource_estimate_hash,
            "search_semantics_id": self.search_semantics_id,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "dsl_version": self.dsl_version,
            "dsl_hash": self.dsl_hash,
            "mdl_measure": self.mdl_measure,
            "max_mdl": self.max_mdl,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "allowed_constants": self.allowed_constants,
            "allowed_operators": self.allowed_operators,
            "representative_rule": self.representative_rule,
            "level_completion_required": self.level_completion_required,
            "enumeration_order_hash": self.enumeration_order_hash,
            "canonicalization_policy_hash": self.canonicalization_policy_hash,
            "dedup_policy_hash": self.dedup_policy_hash,
            "max_raw_ast_evaluations": self.max_raw_ast_evaluations,
            "max_distinct_behaviors": self.max_distinct_behaviors,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_peak_memory_mib": self.max_peak_memory_mib,
            "termination_semantics": self.termination_semantics,
            "complete_frontier_no_exact_status": self.complete_frontier_no_exact_status,
            "ranked_engine_policy_hash": self.ranked_engine_policy_hash,
        }

    def validate(self) -> bool:
        try:
            return CompleteFrontierSearchPolicyV2(**self.canonical_payload()).policy_hash == self.policy_hash
        except (TypeError, ValueError):
            return False

    def ranked_engine_policy(self, specification: DSLSpecification) -> RankedSearchPolicy:
        if not specification.validate() or specification.dsl_hash != self.dsl_hash:
            raise ValueError("genesis_h2_frontier_policy_dsl_mismatch")
        policy = ranked_search_policy(
            specification=specification,
            policy_id=_RANKED_ENGINE_POLICY_ID,
            max_ast_nodes=self.max_nodes,
            max_ast_depth=self.max_depth,
            max_raw_ast_evaluations=self.max_raw_ast_evaluations,
            max_distinct_behaviors=self.max_distinct_behaviors,
            wall_time_limit_seconds=self.max_wall_time_seconds,
        )
        if policy.policy_hash != self.ranked_engine_policy_hash:
            raise ValueError("genesis_h2_frontier_policy_engine_binding_invalid")
        return policy

    def validate_against(
        self,
        audit: TargetClassFrontierAudit,
        estimate: CompleteFrontierResourceEstimateV2,
        specification: DSLSpecification,
    ) -> bool:
        if not (
            self.validate()
            and audit.validate_against_specification(specification)
            and estimate.validate_against(audit, specification)
            and self.frontier_audit_hash == audit.audit_hash
            and self.resource_estimate_hash == estimate.estimate_hash
            and self.dsl_hash == specification.dsl_hash
            and self.dsl_version == specification.dsl_version
        ):
            return False
        return (
            self.max_mdl == audit.c_star
            and self.max_nodes == audit.c_star
            and self.max_nodes <= specification.max_ast_nodes
            and self.max_depth == specification.max_ast_depth
            and self.max_depth <= specification.max_ast_depth
            and self.allowed_constants == specification.allowed_constants
            and self.allowed_operators == tuple(item.value for item in specification.operators)
            and self.max_raw_ast_evaluations > estimate.maximum_raw_ast_count
            and self.max_distinct_behaviors > estimate.behavior_class_upper_bound
            and self.max_wall_time_seconds > estimate.expected_wall_time_seconds_per_campaign
            and self.max_peak_memory_mib > estimate.estimated_peak_memory_mib
            and self._engine_policy_valid(specification)
        )

    def _engine_policy_valid(self, specification: DSLSpecification) -> bool:
        try:
            return self.ranked_engine_policy(specification).validate()
        except ValueError:
            return False


def complete_frontier_search_policy_v2(
    *,
    audit: TargetClassFrontierAudit,
    estimate: CompleteFrontierResourceEstimateV2,
    specification: DSLSpecification,
    benchmark: SealedCapabilityBenchmark,
) -> CompleteFrontierSearchPolicyV2:
    if not (
        audit.validate_against(benchmark)
        and benchmark.specification.dsl_hash == specification.dsl_hash
        and estimate.validate_against(audit, specification)
    ):
        raise ValueError("genesis_h2_frontier_policy_input_invalid")
    # These values are frozen before campaign execution.  They exceed the
    # exact finite grammar count / conservative time-memory estimate above.
    raw_cap = 4_500_000
    behavior_cap = 4_500_000
    wall_cap = 6_000
    memory_cap = 12_288
    engine = ranked_search_policy(
        specification=specification,
        policy_id=_RANKED_ENGINE_POLICY_ID,
        max_ast_nodes=audit.c_star,
        max_ast_depth=specification.max_ast_depth,
        max_raw_ast_evaluations=raw_cap,
        max_distinct_behaviors=behavior_cap,
        wall_time_limit_seconds=wall_cap,
    )
    policy = CompleteFrontierSearchPolicyV2(
        _POLICY_SCHEMA, _POLICY_ID, audit.audit_hash, estimate.estimate_hash,
        SEARCH_SEMANTICS_V2_ID, RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
        specification.dsl_version, specification.dsl_hash, _MDL_MEASURE,
        audit.c_star, specification.max_ast_depth, audit.c_star,
        specification.allowed_constants,
        tuple(item.value for item in specification.operators),
        _REPRESENTATIVE_RULE, True, _enumeration_order_hash(),
        _canonicalization_policy_hash(), _dedup_policy_hash(), raw_cap,
        behavior_cap, wall_cap, memory_cap,
        tuple(item.value for item in RankedSearchTermination),
        _NO_EXACT_FULL_FRONTIER, engine.policy_hash,
    )
    if not policy.validate_against(audit, estimate, specification):
        raise ValueError("genesis_h2_frontier_policy_derivation_invalid")
    return policy


@dataclass(frozen=True, slots=True)
class GEIAcceptancePolicyV2:
    """V2 acceptance rule, anchored to rather than rewriting V1 history."""

    schema_version: str
    policy_id: str
    policy_version: str
    canonical_benchmark_manifest_hash: str
    target_frontier_audit_hash: str
    complete_frontier_policy_hash: str
    predecessor_v1_policy_hash: str
    predecessor_v1_battery_manifest_hash: str
    adaptation_lineage_hash: str
    required_task_ids: tuple[str, ...]
    aggregate_rule: AggregateRule
    campaign_state_mode: CampaignStateMode
    pilot_evidence_policy: PilotEvidencePolicy
    audit_policy_hash: str
    compositional_transfer_protocol_hash: str
    required_per_campaign_gates: tuple[str, ...]
    retention_policy: RetentionPolicy
    failure_semantics: Mapping[str, str]
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _ACCEPTANCE_SCHEMA
            or self.policy_id != "GEI_CONFIRMATORY_BATTERY_V2"
            or self.policy_version != "v2"
            or self.adaptation_lineage_hash != H2_ADAPTATION_LINEAGE_HASH
        ):
            raise ValueError("genesis_h2_acceptance_identity_invalid")
        for value in (
            self.canonical_benchmark_manifest_hash, self.target_frontier_audit_hash,
            self.complete_frontier_policy_hash, self.predecessor_v1_policy_hash,
            self.predecessor_v1_battery_manifest_hash, self.adaptation_lineage_hash,
            self.audit_policy_hash, self.compositional_transfer_protocol_hash,
        ):
            _require_hash(value, "genesis_h2_acceptance_hash_invalid")
        object.__setattr__(self, "required_task_ids", _canonical_task_ids(self.required_task_ids))
        object.__setattr__(self, "aggregate_rule", AggregateRule(self.aggregate_rule))
        object.__setattr__(self, "campaign_state_mode", CampaignStateMode(self.campaign_state_mode))
        object.__setattr__(self, "pilot_evidence_policy", PilotEvidencePolicy(self.pilot_evidence_policy))
        object.__setattr__(self, "retention_policy", RetentionPolicy(self.retention_policy))
        gates = tuple(sorted(str(item) for item in self.required_per_campaign_gates))
        if (
            self.aggregate_rule is not AggregateRule.ALL_REQUIRED_CAMPAIGNS
            or self.campaign_state_mode is not CampaignStateMode.INDEPENDENT_FRESH_BASELINE_PER_TASK
            or self.pilot_evidence_policy is not PilotEvidencePolicy.EXCLUDED_FROM_CONFIRMATORY_RESULT
            or self.retention_policy is not RetentionPolicy.NOT_APPLICABLE_SINGLE_CAPABILITY_RUN
            or gates != REQUIRED_PER_CAMPAIGN_GATES
            or freeze({str(key): str(value) for key, value in self.failure_semantics.items()}) != _FAILURE_SEMANTICS
        ):
            raise ValueError("genesis_h2_acceptance_semantics_invalid")
        object.__setattr__(self, "required_per_campaign_gates", gates)
        object.__setattr__(self, "failure_semantics", _FAILURE_SEMANTICS)
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "canonical_benchmark_manifest_hash": self.canonical_benchmark_manifest_hash,
            "target_frontier_audit_hash": self.target_frontier_audit_hash,
            "complete_frontier_policy_hash": self.complete_frontier_policy_hash,
            "predecessor_v1_policy_hash": self.predecessor_v1_policy_hash,
            "predecessor_v1_battery_manifest_hash": self.predecessor_v1_battery_manifest_hash,
            "adaptation_lineage_hash": self.adaptation_lineage_hash,
            "required_task_ids": self.required_task_ids,
            "aggregate_rule": self.aggregate_rule.value,
            "campaign_state_mode": self.campaign_state_mode.value,
            "pilot_evidence_policy": self.pilot_evidence_policy.value,
            "audit_policy_hash": self.audit_policy_hash,
            "compositional_transfer_protocol_hash": self.compositional_transfer_protocol_hash,
            "required_per_campaign_gates": self.required_per_campaign_gates,
            "retention_policy": self.retention_policy.value,
            "failure_semantics": self.failure_semantics,
        }

    def validate(self) -> bool:
        try:
            return GEIAcceptancePolicyV2(**self.canonical_payload()).policy_hash == self.policy_hash
        except (TypeError, ValueError):
            return False

    def validate_against(
        self,
        *,
        benchmark: SealedCapabilityBenchmark,
        audit: TargetClassFrontierAudit,
        frontier_policy: CompleteFrontierSearchPolicyV2,
        estimate: CompleteFrontierResourceEstimateV2,
        predecessor_v1_policy: GEIAcceptancePolicy,
        predecessor_v1_battery: GEIConfirmatoryBatteryManifest,
    ) -> bool:
        """Re-derive every V2/V1 boundary; a self-consistent hash is insufficient."""

        return (
            self.validate()
            and benchmark.validate()
            and audit.validate_against(benchmark)
            and estimate.validate_against(audit, benchmark.specification)
            and frontier_policy.validate_against(audit, estimate, benchmark.specification)
            and predecessor_v1_policy.validate()
            and predecessor_v1_battery.validate()
            and self.canonical_benchmark_manifest_hash == benchmark.manifest.manifest_hash
            and self.target_frontier_audit_hash == audit.audit_hash
            and self.complete_frontier_policy_hash == frontier_policy.policy_hash
            and self.predecessor_v1_policy_hash == predecessor_v1_policy.policy_hash
            and self.predecessor_v1_battery_manifest_hash == predecessor_v1_battery.battery_manifest_hash
            and predecessor_v1_policy.policy_hash == predecessor_v1_battery.acceptance_policy_hash
            and predecessor_v1_policy.canonical_battery_manifest_hash == benchmark.manifest.manifest_hash
            and predecessor_v1_battery.canonical_battery_manifest_hash == benchmark.manifest.manifest_hash
            and self.audit_policy_hash == predecessor_v1_policy.audit_policy_hash
            and self.compositional_transfer_protocol_hash
            == predecessor_v1_policy.compositional_transfer_protocol_hash
        )


def complete_frontier_acceptance_policy_v2(
    *,
    benchmark: SealedCapabilityBenchmark,
    audit: TargetClassFrontierAudit,
    frontier_policy: CompleteFrontierSearchPolicyV2,
    estimate: CompleteFrontierResourceEstimateV2,
    predecessor_v1_policy: GEIAcceptancePolicy,
    predecessor_v1_battery: GEIConfirmatoryBatteryManifest,
) -> GEIAcceptancePolicyV2:
    if not (
        benchmark.validate()
        and audit.validate_against(benchmark)
        and frontier_policy.validate_against(audit, estimate, benchmark.specification)
        and predecessor_v1_policy.validate()
        and predecessor_v1_battery.validate()
        and predecessor_v1_policy.policy_hash == predecessor_v1_battery.acceptance_policy_hash
        and predecessor_v1_policy.canonical_battery_manifest_hash == benchmark.manifest.manifest_hash
        and predecessor_v1_battery.canonical_battery_manifest_hash == benchmark.manifest.manifest_hash
    ):
        raise ValueError("genesis_h2_acceptance_predecessor_binding_invalid")
    policy = GEIAcceptancePolicyV2(
        _ACCEPTANCE_SCHEMA, "GEI_CONFIRMATORY_BATTERY_V2", "v2",
        benchmark.manifest.manifest_hash, audit.audit_hash, frontier_policy.policy_hash,
        predecessor_v1_policy.policy_hash, predecessor_v1_battery.battery_manifest_hash,
        H2_ADAPTATION_LINEAGE_HASH, CANONICAL_CONFIRMATORY_TASK_IDS,
        AggregateRule.ALL_REQUIRED_CAMPAIGNS,
        CampaignStateMode.INDEPENDENT_FRESH_BASELINE_PER_TASK,
        PilotEvidencePolicy.EXCLUDED_FROM_CONFIRMATORY_RESULT,
        predecessor_v1_policy.audit_policy_hash,
        predecessor_v1_policy.compositional_transfer_protocol_hash,
        REQUIRED_PER_CAMPAIGN_GATES,
        RetentionPolicy.NOT_APPLICABLE_SINGLE_CAPABILITY_RUN,
        _FAILURE_SEMANTICS,
    )
    if not policy.validate_against(
        benchmark=benchmark,
        audit=audit,
        frontier_policy=frontier_policy,
        estimate=estimate,
        predecessor_v1_policy=predecessor_v1_policy,
        predecessor_v1_battery=predecessor_v1_battery,
    ):
        raise ValueError("genesis_h2_acceptance_derivation_invalid")
    return policy


@dataclass(frozen=True, slots=True)
class CompleteFrontierTaskPlanV2:
    """A fresh V2 slot.  It intentionally cannot contain a result artifact."""

    task_id: str
    campaign_id: str
    g0_snapshot_hash: str
    baseline: CapabilityManifest
    split_commitment_hashes: Mapping[str, str]
    split_seed_commitment_hashes: Mapping[str, str]
    complete_frontier_policy_hash: str
    plan_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.task_id or not self.campaign_id or not self.baseline.validate():
            raise ValueError("genesis_h2_task_plan_identity_invalid")
        for value in (self.g0_snapshot_hash, self.complete_frontier_policy_hash):
            _require_hash(value, "genesis_h2_task_plan_hash_invalid")
        splits = freeze({str(key): str(value) for key, value in self.split_commitment_hashes.items()})
        seeds = freeze({str(key): str(value) for key, value in self.split_seed_commitment_hashes.items()})
        expected_splits = {item.value for item in DatasetSplit}
        if (
            set(splits) != expected_splits
            or set(seeds) != expected_splits
            or any(not is_artifact_hash(item) for item in (*splits.values(), *seeds.values()))
        ):
            raise ValueError("genesis_h2_task_plan_splits_invalid")
        object.__setattr__(self, "split_commitment_hashes", splits)
        object.__setattr__(self, "split_seed_commitment_hashes", seeds)
        object.__setattr__(self, "plan_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "campaign_id": self.campaign_id,
            "g0_snapshot_hash": self.g0_snapshot_hash,
            "baseline": self.baseline.canonical_payload(),
            "split_commitment_hashes": self.split_commitment_hashes,
            "split_seed_commitment_hashes": self.split_seed_commitment_hashes,
            "complete_frontier_policy_hash": self.complete_frontier_policy_hash,
        }

    def validate(self) -> bool:
        try:
            return CompleteFrontierTaskPlanV2(
                self.task_id, self.campaign_id, self.g0_snapshot_hash,
                self.baseline, self.split_commitment_hashes,
                self.split_seed_commitment_hashes, self.complete_frontier_policy_hash,
            ).plan_hash == self.plan_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CompleteFrontierTaskPlanV2":
        values = dict(payload)
        values["baseline"] = CapabilityManifest.from_payload(values["baseline"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class GEIConfirmatoryBatteryManifestV2:
    """Pre-execution V2 universe; campaign materialization belongs to H2-B."""

    schema_version: str
    acceptance_policy_hash: str
    canonical_benchmark_manifest_hash: str
    target_frontier_audit_hash: str
    complete_frontier_policy_hash: str
    task_plans: tuple[CompleteFrontierTaskPlanV2, ...]
    execution_order: tuple[str, ...]
    dsl_version: str
    dsl_hash: str
    search_semantics_id: str
    synthesizer_implementation_hash: str
    audit_policy_hash: str
    compositional_protocol_hash: str
    causal_protocol_hash: str
    m6_verification_policy_hash: str
    code_snapshot_hash: str
    environment_commitment_hash: str
    tamper_matrix_hash: str
    predecessor_v1_battery_manifest_hash: str
    adaptation_lineage_hash: str
    battery_manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _BATTERY_SCHEMA
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.synthesizer_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
            or self.adaptation_lineage_hash != H2_ADAPTATION_LINEAGE_HASH
            or not self.dsl_version
        ):
            raise ValueError("genesis_h2_battery_identity_invalid")
        for value in (
            self.acceptance_policy_hash, self.canonical_benchmark_manifest_hash,
            self.target_frontier_audit_hash, self.complete_frontier_policy_hash,
            self.dsl_hash, self.audit_policy_hash, self.compositional_protocol_hash,
            self.causal_protocol_hash, self.m6_verification_policy_hash,
            self.code_snapshot_hash, self.environment_commitment_hash,
            self.tamper_matrix_hash, self.predecessor_v1_battery_manifest_hash,
            self.adaptation_lineage_hash,
        ):
            _require_hash(value, "genesis_h2_battery_hash_invalid")
        plans = tuple(sorted(self.task_plans, key=lambda item: item.task_id))
        order = tuple(str(item) for item in self.execution_order)
        if (
            _canonical_task_ids(tuple(item.task_id for item in plans))
            != tuple(item.task_id for item in plans)
            or order != CANONICAL_CONFIRMATORY_TASK_IDS
            or not all(item.validate() for item in plans)
            or any(item.complete_frontier_policy_hash != self.complete_frontier_policy_hash for item in plans)
            or len({item.campaign_id for item in plans}) != len(plans)
            or len({item.baseline.manifest_hash for item in plans}) != len(plans)
        ):
            raise ValueError("genesis_h2_battery_plans_invalid")
        object.__setattr__(self, "task_plans", plans)
        object.__setattr__(self, "execution_order", order)
        object.__setattr__(self, "battery_manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "canonical_benchmark_manifest_hash": self.canonical_benchmark_manifest_hash,
            "target_frontier_audit_hash": self.target_frontier_audit_hash,
            "complete_frontier_policy_hash": self.complete_frontier_policy_hash,
            "task_plans": tuple(item.canonical_payload() for item in self.task_plans),
            "execution_order": self.execution_order,
            "dsl_version": self.dsl_version,
            "dsl_hash": self.dsl_hash,
            "search_semantics_id": self.search_semantics_id,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "audit_policy_hash": self.audit_policy_hash,
            "compositional_protocol_hash": self.compositional_protocol_hash,
            "causal_protocol_hash": self.causal_protocol_hash,
            "m6_verification_policy_hash": self.m6_verification_policy_hash,
            "code_snapshot_hash": self.code_snapshot_hash,
            "environment_commitment_hash": self.environment_commitment_hash,
            "tamper_matrix_hash": self.tamper_matrix_hash,
            "predecessor_v1_battery_manifest_hash": self.predecessor_v1_battery_manifest_hash,
            "adaptation_lineage_hash": self.adaptation_lineage_hash,
        }

    def validate(self) -> bool:
        try:
            return (
                GEIConfirmatoryBatteryManifestV2.from_payload(self.canonical_payload())
                .battery_manifest_hash
                == self.battery_manifest_hash
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GEIConfirmatoryBatteryManifestV2":
        values = dict(payload)
        values["task_plans"] = tuple(
            CompleteFrontierTaskPlanV2.from_payload(item)
            for item in values["task_plans"]
        )
        return cls(**values)

    def plan_for(self, task_id: str) -> CompleteFrontierTaskPlanV2:
        plan = next((item for item in self.task_plans if item.task_id == task_id), None)
        if plan is None:
            raise ValueError("genesis_h2_battery_task_missing")
        return plan

    def validate_against(
        self,
        *,
        acceptance_policy: GEIAcceptancePolicyV2,
        frontier_policy: CompleteFrontierSearchPolicyV2,
        estimate: CompleteFrontierResourceEstimateV2,
        audit: TargetClassFrontierAudit,
        benchmark: SealedCapabilityBenchmark,
        predecessor_v1_policy: GEIAcceptancePolicy,
        predecessor_v1_battery: GEIConfirmatoryBatteryManifest,
    ) -> bool:
        """Reconstruct the whole pre-execution universe from immutable inputs."""

        if not (
            self.validate()
            and acceptance_policy.validate_against(
                benchmark=benchmark,
                audit=audit,
                frontier_policy=frontier_policy,
                estimate=estimate,
                predecessor_v1_policy=predecessor_v1_policy,
                predecessor_v1_battery=predecessor_v1_battery,
            )
            and self.acceptance_policy_hash == acceptance_policy.policy_hash
            and self.complete_frontier_policy_hash == frontier_policy.policy_hash
            and self.target_frontier_audit_hash == audit.audit_hash
            and self.predecessor_v1_battery_manifest_hash == predecessor_v1_battery.battery_manifest_hash
        ):
            return False
        try:
            expected = predeclare_complete_frontier_battery_v2(
                acceptance_policy=acceptance_policy,
                frontier_policy=frontier_policy,
                estimate=estimate,
                audit=audit,
                benchmark=benchmark,
                predecessor_v1_policy=predecessor_v1_policy,
                predecessor_v1_battery=predecessor_v1_battery,
                code_snapshot_hash=self.code_snapshot_hash,
                environment_commitment_hash=self.environment_commitment_hash,
            )
        except ValueError:
            return False
        return self.canonical_payload() == expected.canonical_payload()


def predeclare_complete_frontier_battery_v2(
    *,
    acceptance_policy: GEIAcceptancePolicyV2,
    frontier_policy: CompleteFrontierSearchPolicyV2,
    estimate: CompleteFrontierResourceEstimateV2,
    audit: TargetClassFrontierAudit,
    benchmark: SealedCapabilityBenchmark,
    predecessor_v1_policy: GEIAcceptancePolicy,
    predecessor_v1_battery: GEIConfirmatoryBatteryManifest,
    code_snapshot_hash: str,
    environment_commitment_hash: str,
) -> GEIConfirmatoryBatteryManifestV2:
    """Freeze H2A.  This function intentionally cannot execute a campaign."""

    if not acceptance_policy.validate_against(
        benchmark=benchmark,
        audit=audit,
        frontier_policy=frontier_policy,
        estimate=estimate,
        predecessor_v1_policy=predecessor_v1_policy,
        predecessor_v1_battery=predecessor_v1_battery,
    ):
        raise ValueError("genesis_h2_battery_predeclaration_invalid")
    _require_hash(code_snapshot_hash, "genesis_h2_battery_code_snapshot_invalid")
    _require_hash(environment_commitment_hash, "genesis_h2_battery_environment_invalid")
    descriptors = {item.task_id: item for item in benchmark.manifest.tasks}
    plans: list[CompleteFrontierTaskPlanV2] = []
    for task_id in CANONICAL_CONFIRMATORY_TASK_IDS:
        descriptor = descriptors.get(task_id)
        if descriptor is None:
            raise ValueError("genesis_h2_battery_task_missing")
        baseline = CapabilityManifest(
            f"m7h2-confirmatory-{task_id}-g0", "genesis-m7-confirmatory-g0-v2", (),
        )
        plans.append(CompleteFrontierTaskPlanV2(
            task_id,
            f"m7h2-confirmatory-{task_id}",
            canonical_sha256({"m7_h2_g0": baseline.manifest_hash, "task_id": task_id}),
            baseline,
            descriptor.split_commitments,
            {
                split.value: canonical_sha256({
                    "m7_h2_seed": task_id,
                    "split": split.value,
                    "policy": acceptance_policy.policy_hash,
                    "frontier": frontier_policy.policy_hash,
                })
                for split in DatasetSplit
            },
            frontier_policy.policy_hash,
        ))
    return GEIConfirmatoryBatteryManifestV2(
        _BATTERY_SCHEMA, acceptance_policy.policy_hash,
        benchmark.manifest.manifest_hash, audit.audit_hash, frontier_policy.policy_hash,
        tuple(plans), CANONICAL_CONFIRMATORY_TASK_IDS,
        benchmark.specification.dsl_version, benchmark.specification.dsl_hash,
        SEARCH_SEMANTICS_V2_ID, RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
        predecessor_v1_policy.audit_policy_hash,
        predecessor_v1_battery.compositional_protocol_hash,
        predecessor_v1_battery.causal_protocol_hash,
        predecessor_v1_battery.m6_verification_policy_hash,
        code_snapshot_hash, environment_commitment_hash,
        predecessor_v1_battery.tamper_matrix_hash,
        predecessor_v1_battery.battery_manifest_hash,
        H2_ADAPTATION_LINEAGE_HASH,
    )
