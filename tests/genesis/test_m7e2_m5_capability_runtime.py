"""M7-E2 uses M5's real lifecycle for all capability intervention arms."""

from __future__ import annotations

from lab.genesis.acquisition.benchmark import DatasetSplit, canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
    ProgramSkillArtifact,
    derive_successor_manifest,
)
from lab.genesis.acquisition.dsl import DSLSpecification, expression_metrics
from lab.genesis.acquisition.m5_capability_runtime import (
    CapabilityArmRuntime,
    CapabilityMeasurementOracle,
    CapabilityOperation,
    CapabilityStateAction,
    capability_intervention_type,
    capability_root_state,
)
from lab.genesis.causal.fork import SyntheticForkableStateAdapter
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.intervention.kernel import GenericInterventionKernel
from lab.genesis.intervention.replay import CausalExperimentReplay
from lab.genesis.intervention.specs import (
    ArmRole,
    ArmSpec,
    CausalExperimentManifest,
    ComputeBudgetSpec,
    InterventionSpec,
    RNGPolicy,
)


def h(value: object) -> str:
    return canonical_sha256({"m7e2-runtime": value})


def _prepared():
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000
    )
    benchmark = canonical_benchmark(specification, seed=17)
    baseline = CapabilityManifest("m7e2-g0", "m7", ())
    descriptor = next(item for item in benchmark.manifest.tasks if item.task_id == "affine-0")
    campaign = AcquisitionCampaignManifest(
        "m7e2-campaign",
        "m7",
        h("snapshot"),
        baseline.manifest_hash,
        specification.dsl_hash,
        h("synthesizer"),
        descriptor.split_commitments,
        benchmark.manifest.generator_implementation_hash,
        {split: h(("seed", split)) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        {"max_candidates": 256},
        specification.max_ast_depth,
        specification.max_ast_nodes,
        specification.allowed_constants,
        tuple(item.value for item in specification.operators),
        CANDIDATE_RANKING_RULE,
        PROMOTION_RULE,
        h("cfi-policy"),
        h("resource-budget"),
        30,
        HUMAN_INTERVENTION_POLICY,
        (h("obligation"),),
    )
    result = AutonomousAcquisitionCampaign().run(
        campaign=campaign,
        specification=specification,
        benchmark=benchmark,
        g0_manifest=baseline,
        task_id="affine-0",
        g1_manifest_id="m7e2-g1",
    )
    target = result.synthesis.selected_skill
    assert target is not None and result.g1_manifest is not None
    placebo_ast = {"op": "X", "args": ()}
    placebo = ProgramSkillArtifact(
        "genesis-m7-program-skill-v1",
        "FINITE_INTEGER_FUNCTION",
        specification.dsl_version,
        {"kind": "integer"},
        {"kind": "integer"},
        placebo_ast,
        expression_metrics(placebo_ast, specification),
        ("X",),
        campaign.campaign_hash,
        (h("predeclared-placebo"),),
    )
    placebo_manifest = derive_successor_manifest(
        baseline, placebo, manifest_id="m7e2-g0-plus-placebo", schema_version="m7"
    )
    ablated_manifest = CapabilityManifest("m7e2-g1-minus-z", "m7", ())
    inputs = tuple(
        example.input_value
        for split in (DatasetSplit.HIDDEN, DatasetSplit.TRANSFER)
        for example in benchmark._tasks["affine-0"].datasets[split]
    )
    return specification, benchmark, baseline, result.g1_manifest, ablated_manifest, target, placebo, placebo_manifest, inputs


def _run(*, experiment_id, root_state, schema, specification, benchmark, actions, skills, roles):
    adapter = SyntheticForkableStateAdapter()
    root = adapter.capture_root(root_state)
    budget = ComputeBudgetSpec(10, 1, 1, 0)
    oracle = CapabilityMeasurementOracle(benchmark=benchmark, task_id="affine-0", inputs=root_state["inputs"])
    interventions = tuple(
        InterventionSpec(
            arm_id,
            "genesis-m7e2-capability-intervention-v1",
            capability_intervention_type(action.operation),
            ("capabilities.manifest_hash", "capabilities.installed_skill_hashes", "capabilities.execution_skill_hash")
            if action.operation is not CapabilityOperation.NONE
            else (),
            action.action_hash,
            action.operation.value,
        )
        for arm_id, action in actions.items()
    )
    specs_by_id = {item.intervention_id: item for item in interventions}
    arm_specs = tuple(
        ArmSpec(
            arm_id,
            role,
            specs_by_id[arm_id].spec_hash,
            specs_by_id[arm_id].target_paths,
            (),
            budget.budget_hash,
            RNGPolicy.ARM_DERIVED,
            h((experiment_id, arm_id)),
        )
        for arm_id, role in roles.items()
    )
    manifest = CausalExperimentManifest(
        experiment_id,
        schema,
        h((experiment_id, "claim")),
        root.root_hash,
        h((experiment_id, "cfi")),
        arm_specs,
        budget.budget_hash,
        RNGPolicy.ARM_DERIVED,
        17,
        oracle.oracle_spec_hash,
        oracle.evaluator_version,
        (),
    )
    runtime = CapabilityArmRuntime(
        specification=specification,
        actions_by_spec_hash={specs_by_id[arm_id].spec_hash: action for arm_id, action in actions.items()},
        skills_by_hash={skill.skill_hash: skill for skill in skills},
    )
    result = GenericInterventionKernel().run(
        manifest, root, interventions, budget, adapter, oracle, runtime=runtime
    )
    assert result.cfi.status.value == "PASS"
    assert result.summary.attribution_eligible
    assert CausalExperimentReplay.verify(result).status == "PASS"
    return result


def test_c1_c2_c3_capability_arms_are_real_m5_experiments() -> None:
    spec, benchmark, g0, g1, g1_minus_z, z, placebo, g0_plus_placebo, inputs = _prepared()

    # C1: G0 / G0+z / G0+pz.  All execution follows one M5 root/fork/seal/CFI lifecycle.
    c1_actions = {
        "control": CapabilityStateAction("c1-control", "m7e2", CapabilityOperation.NONE, g0, g0),
        "treatment": CapabilityStateAction("c1-z", "m7e2", CapabilityOperation.INSTALL, g0, g1, z.skill_hash),
        "placebo": CapabilityStateAction("c1-placebo", "m7e2", CapabilityOperation.INSTALL, g0, g0_plus_placebo, placebo.skill_hash),
    }
    c1 = _run(
        experiment_id="m7e2-c1",
        root_state=capability_root_state(
            manifest=g0, execution_skill_hash=None, inputs=inputs, root_instance_id="c1-g0-capture"
        ),
        schema="genesis-m7e2-c1-v1",
        specification=spec,
        benchmark=benchmark,
        actions=c1_actions,
        skills=(z, placebo),
        roles={"control": ArmRole.CONTROL, "treatment": ArmRole.TREATMENT, "placebo": ArmRole.PLACEBO},
    )
    c1_scores = {receipt.arm_id: receipt.score for receipt in c1.receipts}
    assert c1_scores == {"control": 0.0, "treatment": 1.0, "placebo": 0.0}

    # C2: G1 / G1-z proves that ablation changes executable state, not only a label.
    c2_actions = {
        "intact": CapabilityStateAction("c2-intact", "m7e2", CapabilityOperation.NONE, g1, g1),
        "ablation": CapabilityStateAction("c2-z-minus", "m7e2", CapabilityOperation.REMOVE, g1, g1_minus_z, z.skill_hash),
    }
    c2 = _run(
        experiment_id="m7e2-c2",
        root_state=capability_root_state(
            manifest=g1, execution_skill_hash=z.skill_hash, inputs=inputs, root_instance_id="c2-g1-capture"
        ),
        schema="genesis-m7e2-c2-v1",
        specification=spec,
        benchmark=benchmark,
        actions=c2_actions,
        skills=(z,),
        roles={"intact": ArmRole.CUSTOM, "ablation": ArmRole.ABLATION},
    )
    c2_scores = {receipt.arm_id: receipt.score for receipt in c2.receipts}
    assert c2_scores == {"intact": 1.0, "ablation": 0.0}

    # C3 is a separately captured fresh G0 root; prior z is not present in its state history.
    c3_actions = {
        "fresh_control": CapabilityStateAction("c3-control", "m7e2", CapabilityOperation.NONE, g0, g0),
        "transplant": CapabilityStateAction("c3-z", "m7e2", CapabilityOperation.INSTALL, g0, g1, z.skill_hash),
    }
    c3 = _run(
        experiment_id="m7e2-c3",
        root_state=capability_root_state(
            manifest=g0,
            execution_skill_hash=None,
            inputs=inputs,
            root_instance_id="c3-fresh-g0-capture",
            historical_skill_hashes=(),
        ),
        schema="genesis-m7e2-c3-fresh-root-v1",
        specification=spec,
        benchmark=benchmark,
        actions=c3_actions,
        skills=(z,),
        roles={"fresh_control": ArmRole.CONTROL, "transplant": ArmRole.CUSTOM},
    )
    c3_scores = {receipt.arm_id: receipt.score for receipt in c3.receipts}
    assert c3_scores == {"fresh_control": 0.0, "transplant": 1.0}
    assert c1.root.root_hash != c3.root.root_hash
