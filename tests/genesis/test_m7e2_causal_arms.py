"""M7-E2: three scientifically distinct causal experiments, no five-arm fork."""

from __future__ import annotations

from dataclasses import replace
import runpy

import pytest

from lab.genesis.acquisition.causal_experiments import (
    CausalAttributionStatus,
    PlaceboCommitment,
    materialize_causal_capability_attribution,
)
from lab.genesis.causal.cfi import CFIStatus
from lab.genesis.acquisition.contracts import ProgramSkillArtifact
from lab.genesis.acquisition.dsl import expression_metrics
from lab.genesis.acquisition.causal_replay import (
    persist_causal_capability_attribution,
    replay_causal_capability_attribution,
)
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence import ContentAddressedArtifactStore
from lab.genesis.verifiers.federation import FederationVerdict


support = runpy.run_path("tests/genesis/test_m7f_federated_evidence.py")


def h(value: object) -> str:
    return canonical_sha256({"m7e2-causal-arms": value})


def prepared():
    campaign, baseline, benchmark, result = support["prepared"]()
    ast = {"op": "X", "args": ()}
    placebo = ProgramSkillArtifact(
        "genesis-m7-program-skill-v1",
        "FINITE_INTEGER_FUNCTION",
        benchmark.specification.dsl_version,
        {"kind": "integer"},
        {"kind": "integer"},
        ast,
        expression_metrics(ast, benchmark.specification),
        ("X",),
        campaign.campaign_hash,
        (h("precommitted-before-causal-outcomes"),),
    )
    commitment = PlaceboCommitment(
        "genesis-m7-causal-placebo-commitment-v1",
        campaign.campaign_hash,
        result.task_benchmark_binding.binding_hash,
        placebo.skill_hash,
        "fixed_identity_program_predeclared_before_m5_execution-v1",
    )
    return campaign, baseline, benchmark, result, placebo, commitment


@pytest.fixture(scope="module")
def causal_material():
    campaign, baseline, benchmark, result, placebo, commitment = prepared()
    attribution = materialize_causal_capability_attribution(
        campaign=campaign,
        baseline=baseline,
        benchmark=benchmark,
        task_id="affine-0",
        acquisition=result,
        placebo=placebo,
        placebo_commitment=commitment,
    )
    return attribution, benchmark


def test_c1_c2_c3_use_real_m5_and_close_all_seven_observed_states(causal_material) -> None:
    attribution, _benchmark = causal_material

    assert attribution.verdict is CausalAttributionStatus.PASS
    assert attribution.validate()
    assert attribution.treatment_effect
    assert attribution.placebo_control
    assert attribution.necessity
    assert attribution.sufficiency
    assert attribution.exact_skill_identity
    assert all(experiment.result.cfi.status.value == "PASS" for experiment in (attribution.c1, attribution.c2, attribution.c3))
    assert {arm.arm_id for experiment in (attribution.c1, attribution.c2, attribution.c3) for arm in experiment.arms} == {
        "control", "treatment", "placebo", "intact", "ablation", "fresh_control", "transplant"
    }
    assert attribution.c1.root.root_hash != attribution.c2.root.root_hash != attribution.c3.root.root_hash
    assert attribution.c3.root.state["capabilities"]["historical_skill_hashes"] == ()
    assert all("target" not in arm.root.state for experiment in (attribution.c1, attribution.c2, attribution.c3) for arm in experiment.arms)

    expected_pass = {"treatment", "intact", "transplant"}
    for experiment in (attribution.c1, attribution.c2, attribution.c3):
        for arm in experiment.arms:
            verdicts = {arm.hidden.adjudication.verdict, arm.transfer.adjudication.verdict}
            assert verdicts == ({FederationVerdict.PASS} if arm.arm_id in expected_pass else {FederationVerdict.FAIL})


def test_fresh_cas_replay_rederives_three_m5_experiments_and_all_arm_closures(causal_material, tmp_path) -> None:
    attribution, benchmark = causal_material
    persisted = persist_causal_capability_attribution(
        ContentAddressedArtifactStore(tmp_path), attribution, benchmark=benchmark
    )
    assert replay_causal_capability_attribution(
        ContentAddressedArtifactStore(tmp_path), persisted.manifest_hash
    ).admitted


def test_resealed_semantic_tampers_cannot_preserve_a_causal_pass(causal_material) -> None:
    attribution, _benchmark = causal_material

    swapped_control = replace(
        attribution.c1.arm("control"),
        execution_binding=attribution.c1.arm("treatment").execution_binding,
        hidden=attribution.c1.arm("treatment").hidden,
        transfer=attribution.c1.arm("treatment").transfer,
    )
    swapped = replace(
        attribution.c1,
        arms=(swapped_control, attribution.c1.arm("treatment"), attribution.c1.arm("placebo")),
    )
    with pytest.raises(ValueError, match="verdict_not_derived"):
        replace(attribution, c1=swapped)

    with pytest.raises(ValueError, match="verdict_not_derived"):
        replace(attribution, placebo_skill_hash=attribution.promoted_skill_hash)

    with pytest.raises(ValueError, match="experiment_identity_invalid"):
        replace(attribution.c1, root=attribution.c2.root)

    with pytest.raises(ValueError, match="fresh_baseline_invalid"):
        replace(
            attribution.fresh_baseline,
            history_skill_hashes=(attribution.promoted_skill_hash,),
        )

    incomplete_cfi = replace(attribution.c1.result.cfi, status=CFIStatus.INCOMPLETE)
    cfi_tampered = replace(attribution.c1, result=replace(attribution.c1.result, cfi=incomplete_cfi))
    with pytest.raises(ValueError, match="verdict_not_derived"):
        replace(attribution, c1=cfi_tampered)


def test_resealed_outer_tampers_are_rejected_by_fresh_causal_replay(causal_material, tmp_path) -> None:
    attribution, benchmark = causal_material
    store = ContentAddressedArtifactStore(tmp_path)
    persisted = persist_causal_capability_attribution(store, attribution, benchmark=benchmark)

    def reseal(mutator):
        outer = store.get(persisted.manifest_hash)
        mutator(outer)
        return store.put(outer)

    swapped = reseal(
        lambda outer: outer["arm_trace_closures"].update(
            {
                "c1:control:HIDDEN": outer["arm_trace_closures"]["c1:treatment:HIDDEN"],
                "c1:treatment:HIDDEN": outer["arm_trace_closures"]["c1:control:HIDDEN"],
            }
        )
    )
    assert not replay_causal_capability_attribution(store, swapped).admitted

    wrong_skill = reseal(
        lambda outer: (
            outer["certificate_payload"].__setitem__("promoted_skill_hash", attribution.placebo_skill_hash),
            outer.__setitem__("certificate_hash", canonical_sha256(outer["certificate_payload"])),
        )
    )
    assert not replay_causal_capability_attribution(store, wrong_skill).admitted

    placebo_attack = reseal(
        lambda outer: (
            outer["certificate_payload"].__setitem__("placebo_skill_hash", attribution.promoted_skill_hash),
            outer.__setitem__("certificate_hash", canonical_sha256(outer["certificate_payload"])),
        )
    )
    assert not replay_causal_capability_attribution(store, placebo_attack).admitted

    root_attack = reseal(
        lambda outer: outer["plans"][0].__setitem__("root", outer["plans"][1]["root"])
    )
    assert not replay_causal_capability_attribution(store, root_attack).admitted

    history_attack = reseal(
        lambda outer: (
            outer["certificate_payload"]["fresh_baseline"].__setitem__(
                "history_skill_hashes", [attribution.promoted_skill_hash]
            ),
            outer.__setitem__("certificate_hash", canonical_sha256(outer["certificate_payload"])),
        )
    )
    assert not replay_causal_capability_attribution(store, history_attack).admitted

    cfi_attack = reseal(
        lambda outer: outer["plans"][0]["expected_kernel"].__setitem__("cfi_hash", "0" * 64)
    )
    assert not replay_causal_capability_attribution(store, cfi_attack).admitted
