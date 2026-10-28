"""H2-A: authority audit and immutable V2 battery predeclaration only.

These tests intentionally do not run a synthesizer or materialize a campaign.
That separation is the H2-A commit boundary: H2-B is the first unit allowed
to create V2 acquisition evidence.
"""

from __future__ import annotations

import pytest

from lab.genesis.acquisition.battery import predeclare_confirmatory_battery
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.complete_frontier import (
    CompleteFrontierSearchPolicyV2,
    GEIConfirmatoryBatteryManifestV2,
    H2_ADAPTATION_LINEAGE_HASH,
    TargetClassFrontierAudit,
    TargetFrontierWitness,
    audit_target_class_frontier,
    complete_frontier_acceptance_policy_v2,
    complete_frontier_search_policy_v2,
    estimate_complete_frontier_resources,
    predeclare_complete_frontier_battery_v2,
)
from lab.genesis.acquisition.composition import (
    compositional_transfer_protocol_commitment,
    confirmatory_compositional_transfer_protocol,
)
from lab.genesis.acquisition.confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    confirmatory_policy,
)
from lab.genesis.acquisition.dsl import DSLSpecification, expression_metrics
from lab.genesis.acquisition.ranked_synthesis import (
    RankCanonicalProgramSynthesizer,
    _ordered_expressions,
    ranked_search_policy,
)
from lab.genesis.acquisition.synthesis import SEARCH_SEMANTICS_V1_ID
from lab.genesis.contracts.serialization import canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7h2": value})


def predeclared_v1():
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000,
    )
    benchmark = canonical_benchmark(specification, seed=17)
    policy = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("v1-audit-policy"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    protocol = confirmatory_compositional_transfer_protocol(
        policy=policy, evaluation_policy_hash=h("v1-composition-policy"),
    )
    battery = predeclare_confirmatory_battery(
        policy=policy,
        protocol=protocol,
        benchmark=benchmark,
        code_snapshot_hash=h("v1-code"),
        environment_commitment_hash=h("v1-environment"),
    )
    return specification, benchmark, policy, battery


def h2_predeclared():
    specification, benchmark, v1_policy, v1_battery = predeclared_v1()
    audit = audit_target_class_frontier(benchmark)
    estimate = estimate_complete_frontier_resources(
        audit=audit, specification=specification, benchmark=benchmark,
    )
    frontier = complete_frontier_search_policy_v2(
        audit=audit, estimate=estimate, specification=specification, benchmark=benchmark,
    )
    acceptance = complete_frontier_acceptance_policy_v2(
        benchmark=benchmark,
        audit=audit,
        frontier_policy=frontier,
        estimate=estimate,
        predecessor_v1_policy=v1_policy,
        predecessor_v1_battery=v1_battery,
    )
    battery = predeclare_complete_frontier_battery_v2(
        acceptance_policy=acceptance,
        frontier_policy=frontier,
        estimate=estimate,
        audit=audit,
        benchmark=benchmark,
        predecessor_v1_policy=v1_policy,
        predecessor_v1_battery=v1_battery,
        code_snapshot_hash=h("v2-code"),
        environment_commitment_hash=h("v2-environment"),
    )
    return specification, benchmark, v1_policy, v1_battery, audit, estimate, frontier, acceptance, battery


def test_authority_audit_derives_the_exact_target_class_without_learner_leakage() -> None:
    _specification, benchmark, _v1_policy, _v1_battery = predeclared_v1()

    audit = audit_target_class_frontier(benchmark)

    assert audit.validate()
    assert audit.validate_against(benchmark)
    assert tuple(item.task_id for item in audit.task_witnesses) == CANONICAL_CONFIRMATORY_TASK_IDS
    assert audit.c_star == 7
    assert {
        item.task_id: (item.target_mdl, item.target_depth, item.target_nodes)
        for item in audit.task_witnesses
    } == {
        "abs_affine-0": (7, 5, 7),
        "abs_affine-1": (7, 5, 7),
        "affine-0": (4, 3, 4),
        "affine-1": (4, 3, 4),
        "quadratic_simple-0": (5, 4, 5),
        "quadratic_simple-1": (5, 4, 5),
    }
    assert all(item.target_dsl_valid for item in audit.task_witnesses)
    # The durable witness commits identity and structural metadata, never a
    # target AST or target output vector for the learner to consume.
    assert all("target_ast" not in item.canonical_payload() for item in audit.task_witnesses)


def test_resealed_target_metadata_cannot_substitute_for_authority_rederivation() -> None:
    _specification, benchmark, _v1_policy, _v1_battery = predeclared_v1()
    audit = audit_target_class_frontier(benchmark)
    original = audit.task_witnesses[0]
    forged = TargetFrontierWitness(
        **{**original.canonical_payload(), "target_ast_hash": h("false-target")},
    )
    false_audit = TargetClassFrontierAudit(
        audit.schema_version,
        audit.benchmark_manifest_hash,
        audit.dsl_hash,
        (forged, *audit.task_witnesses[1:]),
        audit.c_star,
    )

    assert false_audit.validate()
    assert not false_audit.validate_against(benchmark)


def test_resource_estimate_is_an_exact_grammar_count_with_conservative_caps() -> None:
    specification, benchmark, _v1_policy, _v1_battery = predeclared_v1()
    audit = audit_target_class_frontier(benchmark)
    estimate = estimate_complete_frontier_resources(
        audit=audit, specification=specification, benchmark=benchmark,
    )
    policy = complete_frontier_search_policy_v2(
        audit=audit, estimate=estimate, specification=specification, benchmark=benchmark,
    )

    # The first six cumulative counts coincide with the observed H1 frontier:
    # 64,729 through level five and 506,569 through level six.
    assert estimate.raw_ast_count_by_mdl == (7, 56, 525, 5_376, 58_765, 441_840, 3_361_813)
    assert estimate.maximum_raw_ast_count == 3_868_382
    assert estimate.behavior_class_upper_bound == estimate.maximum_raw_ast_count
    assert estimate.expected_wall_time_seconds_per_campaign == 4_680
    assert estimate.expected_wall_time_seconds_battery == 28_080
    assert estimate.estimated_peak_memory_mib == 9_216
    assert estimate.validate_against(audit, specification)
    assert policy.validate_against(audit, estimate, specification)
    assert policy.max_raw_ast_evaluations > estimate.maximum_raw_ast_count
    assert policy.max_distinct_behaviors > estimate.behavior_class_upper_bound
    assert policy.max_wall_time_seconds > estimate.expected_wall_time_seconds_per_campaign
    assert policy.max_peak_memory_mib > estimate.estimated_peak_memory_mib
    assert policy.ranked_engine_policy(specification).validate()


def test_counting_recurrence_matches_the_h1_enumerator_on_a_materialized_prefix() -> None:
    specification, _benchmark, _v1_policy, _v1_battery = predeclared_v1()
    audit = audit_target_class_frontier(_benchmark)
    estimate = estimate_complete_frontier_resources(
        audit=audit, specification=specification, benchmark=_benchmark,
    )
    prefix_policy = ranked_search_policy(
        specification=specification,
        policy_id="m7h2-counting-prefix",
        max_ast_nodes=5,
        max_ast_depth=specification.max_ast_depth,
    )
    observed = [0] * 5
    for expression in _ordered_expressions(
        specification, prefix_policy, enumeration_order="CANONICAL",
    ):
        observed[int(expression_metrics(expression, specification)["node_count"]) - 1] += 1

    assert tuple(observed) == estimate.raw_ast_count_by_mdl[:5]


def test_v2_policy_rejects_v1_identity_and_resealed_frontier_or_cap_weakening() -> None:
    specification, _benchmark, _v1_policy, _v1_battery, audit, estimate, policy, _acceptance, _battery = h2_predeclared()

    with pytest.raises(ValueError, match="identity_invalid"):
        CompleteFrontierSearchPolicyV2(
            **{**policy.canonical_payload(), "search_semantics_id": SEARCH_SEMANTICS_V1_ID},
        )
    false_frontier = CompleteFrontierSearchPolicyV2(
        **{**policy.canonical_payload(), "max_mdl": 6, "max_nodes": 6},
    )
    false_cap = CompleteFrontierSearchPolicyV2(
        **{
            **policy.canonical_payload(),
            "max_raw_ast_evaluations": estimate.maximum_raw_ast_count,
        },
    )

    assert false_frontier.validate()
    assert false_cap.validate()
    assert not false_frontier.validate_against(audit, estimate, specification)
    assert not false_cap.validate_against(audit, estimate, specification)


def test_h2a_predeclares_fresh_slots_but_never_executes_a_campaign(monkeypatch) -> None:
    def synthesis_must_not_run(*_args, **_kwargs):
        raise AssertionError("H2-A must not run synthesis")

    monkeypatch.setattr(RankCanonicalProgramSynthesizer, "synthesize", synthesis_must_not_run)
    _specification, _benchmark, v1_policy, v1_battery, audit, _estimate, frontier, acceptance, battery = h2_predeclared()

    assert battery.validate()
    assert battery.execution_order == CANONICAL_CONFIRMATORY_TASK_IDS
    assert tuple(item.task_id for item in battery.task_plans) == CANONICAL_CONFIRMATORY_TASK_IDS
    assert tuple(item.campaign_id for item in battery.task_plans) == (
        "m7h2-confirmatory-abs_affine-0",
        "m7h2-confirmatory-abs_affine-1",
        "m7h2-confirmatory-affine-0",
        "m7h2-confirmatory-affine-1",
        "m7h2-confirmatory-quadratic_simple-0",
        "m7h2-confirmatory-quadratic_simple-1",
    )
    assert len({item.baseline.manifest_hash for item in battery.task_plans}) == 6
    assert {item.complete_frontier_policy_hash for item in battery.task_plans} == {frontier.policy_hash}
    assert acceptance.predecessor_v1_policy_hash == v1_policy.policy_hash
    assert battery.predecessor_v1_battery_manifest_hash == v1_battery.battery_manifest_hash
    assert battery.adaptation_lineage_hash == H2_ADAPTATION_LINEAGE_HASH
    assert all("result" not in item.canonical_payload() for item in battery.task_plans)
    assert acceptance.validate_against(
        benchmark=_benchmark,
        audit=audit,
        frontier_policy=frontier,
        estimate=_estimate,
        predecessor_v1_policy=v1_policy,
        predecessor_v1_battery=v1_battery,
    )
    assert battery.validate_against(
        acceptance_policy=acceptance,
        frontier_policy=frontier,
        estimate=_estimate,
        audit=audit,
        benchmark=_benchmark,
        predecessor_v1_policy=v1_policy,
        predecessor_v1_battery=v1_battery,
    )


def test_battery_rejects_resealed_cross_frontier_and_predecessor_substitutions() -> None:
    specification, benchmark, v1_policy, v1_battery, audit, estimate, frontier, acceptance, battery = h2_predeclared()
    first = battery.task_plans[0]
    bad_plan = type(first).from_payload({
        **first.canonical_payload(), "complete_frontier_policy_hash": h("task-specific-frontier"),
    })
    with pytest.raises(ValueError, match="battery_plans_invalid"):
        GEIConfirmatoryBatteryManifestV2(
            **{**battery.canonical_payload(), "task_plans": (bad_plan, *battery.task_plans[1:])},
        )

    other_v1_policy = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("substituted-v1-audit"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    with pytest.raises(ValueError, match="predecessor_binding_invalid"):
        complete_frontier_acceptance_policy_v2(
            benchmark=benchmark,
            audit=audit,
            frontier_policy=frontier,
            estimate=estimate,
            predecessor_v1_policy=other_v1_policy,
            predecessor_v1_battery=v1_battery,
        )
    assert v1_policy.validate()
    assert specification.validate()
