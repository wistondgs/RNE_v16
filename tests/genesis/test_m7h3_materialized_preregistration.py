"""M7-H3A: V3 seals one predeclared battery before any canonical execution.

Every run here is an in-memory or temporary-directory fixture.  No canonical
V3 campaign ID is executed and no durable AUDIT registry is opened.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess

import pytest

from lab.genesis.acquisition.battery import predeclare_confirmatory_battery
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.complete_frontier import (
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
from lab.genesis.acquisition.confirmation import confirmatory_policy
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.v3_preregistration import (
    EnvironmentManifestV3,
    ExecutionSourceBlobV3,
    ExecutionSourceManifestV3,
    GEIConfirmatoryPredeclarationV3,
    PriorExperimentExposureV3,
    RecoveryPolicyV3,
    V3BatteryManifest,
    V3CampaignBinding,
    V3RecoveryAction,
    V3RunLedger,
    V3RunLedgerEvent,
    V3RunState,
    V3ScientificDomain,
    audit_dynamic_local_dependencies,
    discover_execution_source_paths,
    load_sealed_predeclaration,
    materialize_v3_predeclaration,
    prepare_v3_launch,
    recovery_receipt,
    reject_prior_v2_evidence,
    validate_v3_launch_environment,
    validate_runtime_import_witness,
    verify_sealed_predeclaration_provenance,
)
from lab.genesis.acquisition.v3_execution import (
    V3AuditSlot,
    V3CampaignAttestation,
    V3CandidateCommitment,
    V3CampaignTerminalStatus,
    V3BatteryStatus,
    V3DurableAuditRegistry,
    close_v3_confirmatory_battery,
    derive_v3_confirmatory_campaign,
)
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7h3-test": value})


def source_manifest() -> ExecutionSourceManifestV3:
    return ExecutionSourceManifestV3(
        "genesis-m7-h3-execution-source-manifest-v1", "RNFE_V16_GENESIS", "a" * 40,
        ("lab/genesis/acquisition/v3_preregistration.py",),
        (ExecutionSourceBlobV3("lab/genesis/acquisition/v3_preregistration.py", "b" * 40),),
    )


def environment() -> EnvironmentManifestV3:
    return EnvironmentManifestV3(
        "genesis-m7-h3-environment-manifest-v1", "cpython", "3.12.3", "Linux", "x86_64",
        {"requirements.reasoning-core-causal.txt": h("requirements")},
        (("pytest", "9.1.1"), ("z3-solver", "4.16.0")),
    )


def material() -> GEIConfirmatoryPredeclarationV3:
    source = source_manifest()
    env = environment()
    recovery = RecoveryPolicyV3.frozen()
    excluded = tuple(h(f"v2-artifact-{index}") for index in range(7))
    exposure = PriorExperimentExposureV3(
        "genesis-m7-h3-prior-exposure-v1", h("v2-battery"),
        "m7h2-confirmatory-abs_affine-0", "GE_I_CAMPAIGN_SUPPORTED",
        "TECHNICALLY_VALID_BUT_NONCONFIRMATORY", True,
        "V2_PREDECLARATION_RUNTIME_BOUND", excluded,
    )
    bindings = tuple(V3CampaignBinding(
        task, f"m7h3-confirmatory-{task}", h((task, "g0")), h((task, "baseline")),
        {split: h((task, split, "commit")) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        {split: h((task, split, "seed")) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
    ) for task in (
        "abs_affine-0", "abs_affine-1", "affine-0", "affine-1",
        "quadratic_simple-0", "quadratic_simple-1",
    ))
    battery = V3BatteryManifest(
        "genesis-m7-h3-confirmatory-battery-v3", h("benchmark"), h("dsl"),
        "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2", h("search"), h("frontier"), h("acceptance"),
        h("audit"), h("estimate"), 7, h("resource"), h("audit-policy"), h("composition"),
        h("causal"), h("m6"), source.manifest_hash, env.manifest_hash, recovery.policy_hash,
        exposure.prior_battery_hash, exposure.exposure_hash, bindings,
        tuple(item.task_id for item in bindings),
    )
    return GEIConfirmatoryPredeclarationV3(
        "genesis-m7-h3-v3-preregistration-v1", "a" * 40, source, env, recovery, exposure, battery,
    )


def event(pre: GEIConfirmatoryPredeclarationV3, launch_hash: str, task: str, sequence: int,
          state: V3RunState, previous: str | None, *, terminal: str | None = None) -> V3RunLedgerEvent:
    return V3RunLedgerEvent(
        "genesis-m7-h3-run-ledger-event-v1", pre.battery.battery_manifest_hash, task, launch_hash,
        pre.execution_source.manifest_hash, pre.environment.manifest_hash, sequence, state, previous,
        (h((task, sequence, state.value)),), terminal,
    )


def test_v2_runtime_bound_counterexample_is_preserved() -> None:
    """The old builder admits two batteries from identical scientific sources."""

    specification = DSLSpecification("m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000)
    benchmark = canonical_benchmark(specification, seed=17)
    v1 = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("v1-audit"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    protocol = confirmatory_compositional_transfer_protocol(policy=v1, evaluation_policy_hash=h("v1-composition"))
    predecessor = predeclare_confirmatory_battery(
        policy=v1, protocol=protocol, benchmark=benchmark,
        code_snapshot_hash=h("v1-code"), environment_commitment_hash=h("v1-environment"),
    )
    audit = audit_target_class_frontier(benchmark)
    estimate = estimate_complete_frontier_resources(audit=audit, specification=specification, benchmark=benchmark)
    frontier = complete_frontier_search_policy_v2(
        audit=audit, estimate=estimate, specification=specification, benchmark=benchmark,
    )
    policy = complete_frontier_acceptance_policy_v2(
        benchmark=benchmark, audit=audit, frontier_policy=frontier, estimate=estimate,
        predecessor_v1_policy=v1, predecessor_v1_battery=predecessor,
    )
    a = predeclare_complete_frontier_battery_v2(
        acceptance_policy=policy, frontier_policy=frontier, estimate=estimate, audit=audit,
        benchmark=benchmark, predecessor_v1_policy=v1, predecessor_v1_battery=predecessor,
        code_snapshot_hash=h("A-code"), environment_commitment_hash=h("A-environment"),
    )
    b = predeclare_complete_frontier_battery_v2(
        acceptance_policy=policy, frontier_policy=frontier, estimate=estimate, audit=audit,
        benchmark=benchmark, predecessor_v1_policy=v1, predecessor_v1_battery=predecessor,
        code_snapshot_hash=h("B-code"), environment_commitment_hash=h("B-environment"),
    )
    assert a.validate_against(
        acceptance_policy=policy, frontier_policy=frontier, estimate=estimate, audit=audit,
        benchmark=benchmark, predecessor_v1_policy=v1, predecessor_v1_battery=predecessor,
    )
    assert b.validate_against(
        acceptance_policy=policy, frontier_policy=frontier, estimate=estimate, audit=audit,
        benchmark=benchmark, predecessor_v1_policy=v1, predecessor_v1_battery=predecessor,
    )
    assert a.battery_manifest_hash != b.battery_manifest_hash


def test_v3_loader_authorizes_one_exact_predeclaration(tmp_path: Path) -> None:
    pre = material()
    path = tmp_path / "predeclaration.json"
    path.write_bytes(canonical_json_bytes(pre.canonical_payload()))
    loaded = load_sealed_predeclaration(path, expected_hash=pre.predeclaration_hash)
    assert loaded.predeclaration_hash == pre.predeclaration_hash
    assert loaded.battery.battery_manifest_hash != loaded.prior_exposure.prior_battery_hash
    assert "code_snapshot_hash" not in inspect.signature(prepare_v3_launch).parameters
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_sealed_predeclaration(path, expected_hash=h("other-predeclaration"))


def test_v3_launch_receipt_requires_external_seal_provenance() -> None:
    pre = material()
    with pytest.raises(TypeError):
        prepare_v3_launch(predeclaration=pre, artifact_root_identity="fixture-v3-root")
    with pytest.raises(ValueError, match="authorization_commit_invalid"):
        prepare_v3_launch(
            predeclaration=pre, artifact_root_identity="fixture-v3-root",
            authorization_commit="not-a-commit", sealed_predeclaration_path="sealed/predeclaration.json",
            sealed_predeclaration_blob_hash="d" * 40,
        )


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args), text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_seal_provenance_requires_exact_cseal_blob_and_unchanged_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source_path = repo / "lab/genesis/acquisition/v3_preregistration.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("SOURCE = 'v3'\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "M7-H3 fixture")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "implementation")
    c_impl = _git(repo, "rev-parse", "HEAD")
    source = ExecutionSourceManifestV3(
        "genesis-m7-h3-execution-source-manifest-v1", "RNFE_V16_GENESIS", c_impl,
        ("lab/genesis/acquisition/v3_preregistration.py",),
        (ExecutionSourceBlobV3(
            "lab/genesis/acquisition/v3_preregistration.py",
            _git(repo, "rev-parse", f"{c_impl}:lab/genesis/acquisition/v3_preregistration.py"),
        ),),
    )
    old = material()
    battery_payload = dict(old.battery.canonical_payload())
    battery_payload["execution_source_manifest_hash"] = source.manifest_hash
    battery = V3BatteryManifest.from_payload(battery_payload)
    pre = GEIConfirmatoryPredeclarationV3(
        old.schema_version, c_impl, source, old.environment, old.recovery_policy,
        old.prior_exposure, battery,
    )
    sealed = repo / "sealed/predeclaration.json"
    sealed.parent.mkdir()
    sealed.write_bytes(canonical_json_bytes(pre.canonical_payload()))
    _git(repo, "add", "sealed/predeclaration.json")
    _git(repo, "commit", "-qm", "seal")
    c_seal = _git(repo, "rev-parse", "HEAD")
    blob = verify_sealed_predeclaration_provenance(
        predeclaration=pre, repo=repo, authorization_commit=c_seal,
        sealed_predeclaration_path="sealed/predeclaration.json",
    )
    receipt = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root", authorization_commit=c_seal,
        sealed_predeclaration_path="sealed/predeclaration.json", sealed_predeclaration_blob_hash=blob,
    )
    assert receipt.authorization_commit == c_seal
    source_path.write_text("SOURCE = 'tampered'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="execution_source_mismatch"):
        verify_sealed_predeclaration_provenance(
            predeclaration=pre, repo=repo, authorization_commit=c_seal,
            sealed_predeclaration_path="sealed/predeclaration.json",
        )


def test_v3_rejects_alternate_scientific_identity_and_prior_laundering() -> None:
    pre = material()
    alternate_environment = EnvironmentManifestV3(
        "genesis-m7-h3-environment-manifest-v1", "cpython", "3.13.0", "Linux", "x86_64",
        {"requirements.reasoning-core-causal.txt": h("requirements")},
        (("pytest", "9.1.1"),),
    )
    assert not validate_v3_launch_environment(predeclaration=pre, observed=alternate_environment)
    wrong_source = ExecutionSourceManifestV3(
        "genesis-m7-h3-execution-source-manifest-v1", "RNFE_V16_GENESIS", "a" * 40,
        ("lab/genesis/acquisition/v3_preregistration.py",),
        (ExecutionSourceBlobV3("lab/genesis/acquisition/v3_preregistration.py", "c" * 40),),
    )
    with pytest.raises(ValueError, match="binding_invalid"):
        GEIConfirmatoryPredeclarationV3(
            pre.schema_version, pre.implementation_commit, wrong_source, pre.environment,
            pre.recovery_policy, pre.prior_exposure, pre.battery,
        )
    for artifact in pre.prior_exposure.excluded_artifact_hashes:
        with pytest.raises(ValueError, match="evidence_reuse_rejected"):
            reject_prior_v2_evidence(
                predeclaration=pre, campaign_id="m7h3-confirmatory-affine-0", artifact_hashes=(artifact,),
            )
    with pytest.raises(ValueError, match="campaign_reuse_rejected"):
        reject_prior_v2_evidence(predeclaration=pre, campaign_id="m7h2-confirmatory-abs_affine-0", artifact_hashes=())


def test_materializer_derives_new_slots_from_fixed_historical_domain() -> None:
    pre = material()
    plans = tuple({
        "task_id": item.task_id,
        "campaign_id": f"m7h2-confirmatory-{item.task_id}",
        "split_commitment_hashes": item.split_commitment_hashes,
    } for item in pre.battery.campaign_bindings)
    domain = V3ScientificDomain(
        h("benchmark"), h("dsl"), h("search"), h("frontier"), h("acceptance"), h("audit"),
        h("estimate"), h("audit-policy"), h("composition"), h("causal"), h("m6"), plans,
    )
    sealed = materialize_v3_predeclaration(
        implementation_commit=pre.implementation_commit, execution_source=pre.execution_source,
        environment=pre.environment, domain=domain, prior_exposure=pre.prior_exposure,
    )
    assert sealed.validate()
    assert sealed.battery.battery_manifest_hash != pre.prior_exposure.prior_battery_hash
    assert all(item.campaign_id.startswith("m7h3-confirmatory-") for item in sealed.battery.campaign_bindings)
    assert all(item.campaign_id != "m7h2-confirmatory-abs_affine-0" for item in sealed.battery.campaign_bindings)


def test_recovery_ledger_is_ordered_idempotent_and_terminal_slots_skip(tmp_path: Path) -> None:
    pre = material()
    launch = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root",
        authorization_commit="c" * 40, sealed_predeclaration_path="sealed/predeclaration.json",
        sealed_predeclaration_blob_hash="d" * 40,
    )
    task = "m7h3-confirmatory-affine-0"
    ledger = V3RunLedger(tmp_path / "ledger")
    states = (
        V3RunState.PLANNED, V3RunState.STARTED, V3RunState.SEARCH_TERMINAL,
        V3RunState.CANDIDATE_COMMITTED, V3RunState.AUDIT_TERMINAL, V3RunState.PROMOTED,
        V3RunState.POST_PROMOTION_EVIDENCE, V3RunState.CAMPAIGN_TERMINAL,
    )
    events = []
    previous = None
    for sequence, state in enumerate(states):
        item = event(pre, launch.launch_hash, task, sequence, state, previous,
                     terminal="FAIL" if state is V3RunState.CAMPAIGN_TERMINAL else None)
        ledger.append(item)
        events.append(item)
        previous = item.event_hash
    assert ledger.append(events[-1]) == events[-1]
    recovered = recovery_receipt(
        predeclaration=pre, launch=launch, events=ledger.read(task), campaign_id=task, reason="fixture restart",
    )
    assert recovered.allowed_action is V3RecoveryAction.SKIP_TERMINAL_CAMPAIGN
    assert recovered.last_state is V3RunState.CAMPAIGN_TERMINAL
    assert recovered.irreversible_artifact_hashes == events[-1].artifact_hashes
    with pytest.raises(ValueError, match="transition_invalid"):
        ledger.append(event(pre, launch.launch_hash, task, len(events), V3RunState.STARTED, events[-1].event_hash))


def test_audit_state_recovers_without_a_second_audit(tmp_path: Path) -> None:
    pre = material()
    launch = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root",
        authorization_commit="c" * 40, sealed_predeclaration_path="sealed/predeclaration.json",
        sealed_predeclaration_blob_hash="d" * 40,
    )
    task = "m7h3-confirmatory-abs_affine-1"
    ledger = V3RunLedger(tmp_path / "ledger")
    previous = None
    events = []
    for sequence, state in enumerate((
        V3RunState.PLANNED, V3RunState.STARTED, V3RunState.SEARCH_TERMINAL,
        V3RunState.CANDIDATE_COMMITTED, V3RunState.AUDIT_TERMINAL,
    )):
        item = event(pre, launch.launch_hash, task, sequence, state, previous)
        ledger.append(item)
        events.append(item)
        previous = item.event_hash
    receipt = recovery_receipt(
        predeclaration=pre, launch=launch, events=ledger.read(task), campaign_id=task, reason="post-audit death",
    )
    assert receipt.allowed_action is V3RecoveryAction.REUSE_DURABLE_AUDIT
    assert pre.recovery_policy.audit_reconsumption_allowed is False


def test_recovery_rejects_a_resealed_event_from_another_battery() -> None:
    pre = material()
    launch = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root",
        authorization_commit="c" * 40, sealed_predeclaration_path="sealed/predeclaration.json",
        sealed_predeclaration_blob_hash="d" * 40,
    )
    task = "m7h3-confirmatory-affine-1"
    valid = event(pre, launch.launch_hash, task, 0, V3RunState.PLANNED, None)
    payload = dict(valid.canonical_payload())
    payload["battery_manifest_hash"] = h("foreign-v3-battery")
    foreign = V3RunLedgerEvent.from_payload(payload)
    with pytest.raises(ValueError, match="event_binding_invalid"):
        recovery_receipt(
            predeclaration=pre, launch=launch, events=(foreign,), campaign_id=task,
            reason="malicious journal substitution",
        )


@pytest.mark.parametrize(("last_state", "expected"), [
    (V3RunState.PLANNED, V3RecoveryAction.START),
    (V3RunState.STARTED, V3RecoveryAction.RESTART_DETERMINISTIC_SEARCH),
    (V3RunState.SEARCH_TERMINAL, V3RecoveryAction.CONTINUE_WITH_COMMITTED_CANDIDATE),
    (V3RunState.CANDIDATE_COMMITTED, V3RecoveryAction.CONTINUE_WITH_COMMITTED_CANDIDATE),
    (V3RunState.AUDIT_TERMINAL, V3RecoveryAction.REUSE_DURABLE_AUDIT),
    (V3RunState.PROMOTED, V3RecoveryAction.CONTINUE_POST_PROMOTION),
    (V3RunState.POST_PROMOTION_EVIDENCE, V3RecoveryAction.COMPLETE_TERMINAL_EVIDENCE),
])
def test_recovery_matrix_has_one_predeclared_action_per_nonterminal_state(
    tmp_path: Path, last_state: V3RunState, expected: V3RecoveryAction,
) -> None:
    pre = material()
    launch = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root",
        authorization_commit="c" * 40, sealed_predeclaration_path="sealed/predeclaration.json",
        sealed_predeclaration_blob_hash="d" * 40,
    )
    task = "m7h3-confirmatory-quadratic_simple-0"
    states = tuple(V3RunState)[:tuple(V3RunState).index(last_state) + 1]
    ledger = V3RunLedger(tmp_path / last_state.value)
    previous = None
    for sequence, state in enumerate(states):
        item = event(pre, launch.launch_hash, task, sequence, state, previous)
        ledger.append(item)
        previous = item.event_hash
    receipt = recovery_receipt(
        predeclaration=pre, launch=launch, events=ledger.read(task), campaign_id=task, reason="fixture interruption",
    )
    assert receipt.allowed_action is expected
    assert receipt.execution_source_manifest_hash == pre.execution_source.manifest_hash
    assert receipt.environment_manifest_hash == pre.environment.manifest_hash


def test_v3_rejects_wrong_frontier_and_campaign_set_before_launch() -> None:
    pre = material()
    wrong = dict(pre.battery.canonical_payload())
    wrong["c_star"] = 6
    wrong["campaign_bindings"] = tuple(
        V3CampaignBinding.from_payload(item) for item in wrong["campaign_bindings"]
    )
    wrong["execution_order"] = tuple(wrong["execution_order"])
    with pytest.raises(ValueError, match="battery_identity_invalid"):
        V3BatteryManifest(**wrong)
    with pytest.raises(ValueError, match="campaign_identity_invalid"):
        V3CampaignBinding(
            "affine-0", "m7h2-confirmatory-affine-0", h("g0"), h("baseline"),
            {split: h((split, "commit")) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
            {split: h((split, "seed")) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        )
    wrong_predecessor = dict(pre.battery.canonical_payload())
    wrong_predecessor["predecessor_v2_battery_hash"] = h("other-v2-battery")
    wrong_predecessor["campaign_bindings"] = tuple(
        V3CampaignBinding.from_payload(item) for item in wrong_predecessor["campaign_bindings"]
    )
    wrong_predecessor["execution_order"] = tuple(wrong_predecessor["execution_order"])
    with pytest.raises(ValueError, match="predeclaration_binding_invalid"):
        GEIConfirmatoryPredeclarationV3(
            pre.schema_version, pre.implementation_commit, pre.execution_source, pre.environment,
            pre.recovery_policy, pre.prior_exposure, V3BatteryManifest(**wrong_predecessor),
        )


def test_execution_source_discovery_uses_real_imports() -> None:
    repo = Path(__file__).resolve().parents[2]
    paths = discover_execution_source_paths(
        repo, entrypoints=("lab/genesis/acquisition/v3_preregistration.py",),
    )
    assert "lab/genesis/acquisition/v3_preregistration.py" in paths
    assert "lab/genesis/contracts/serialization.py" in paths
    # Python executes package initializers before the requested submodule.
    # The acquisition initializer currently imports the V2 supervisor and
    # orchestrator, so omitting either would understate runtime code surface.
    assert "lab/genesis/acquisition/__init__.py" in paths
    assert "lab/genesis/acquisition/v2_execution.py" in paths
    assert "lab/genesis/acquisition/v2_campaign.py" in paths
    assert audit_dynamic_local_dependencies(repo, source_paths=paths) == ()
    assert all(not Path(path).is_absolute() and ".." not in Path(path).parts for path in paths)


def test_runtime_witness_rejects_a_transitively_executed_helper_omitted_from_manifest() -> None:
    manifest = source_manifest()
    with pytest.raises(ValueError, match="source_closure_incomplete"):
        validate_runtime_import_witness(
            manifest=manifest,
            runtime_local_paths=(
                "lab/genesis/acquisition/v3_preregistration.py",
                "lab/genesis/acquisition/v2_campaign.py",
            ),
        )


def test_v3_native_campaign_and_battery_closure_do_not_accept_v2_authority() -> None:
    pre = material()
    launch = prepare_v3_launch(
        predeclaration=pre, artifact_root_identity="fixture-v3-root",
        authorization_commit="c" * 40, sealed_predeclaration_path="sealed/predeclaration.json",
        sealed_predeclaration_blob_hash="d" * 40,
    )
    attestations = tuple(
        V3CampaignAttestation(
            "genesis-m7-v3-campaign-attestation-h3a0",
            derive_v3_confirmatory_campaign(predeclaration=pre, campaign_id=binding.campaign_id),
            launch.launch_hash, V3CampaignTerminalStatus.NOT_PROVEN,
            h((binding.task_id, "terminal")), (h((binding.task_id, "evidence")),),
        )
        for binding in pre.battery.campaign_bindings
    )
    closure = close_v3_confirmatory_battery(
        predeclaration=pre, launch=launch, attestations=attestations,
    )
    assert closure.status is V3BatteryStatus.GE_I_BATTERY_NOT_PROVEN
    assert all(item.campaign.campaign_id.startswith("m7h3-confirmatory-") for item in attestations)
    with pytest.raises(ValueError, match="campaign_not_authorized"):
        derive_v3_confirmatory_campaign(predeclaration=pre, campaign_id="m7h2-confirmatory-affine-0")


def test_v3_durable_audit_is_campaign_bound_and_never_evaluates_a_second_candidate(tmp_path: Path) -> None:
    pre = material()
    campaign = derive_v3_confirmatory_campaign(
        predeclaration=pre, campaign_id="m7h3-confirmatory-affine-0",
    )
    commitment = V3CandidateCommitment(
        "genesis-m7-v3-candidate-commitment-h3a0", campaign.campaign_hash, h("skill"), h("program"),
        campaign.split_commitment_hashes["TRAIN"], h("search"), h("ranking"), 2,
    )
    slot = V3AuditSlot(
        pre.predeclaration_hash, pre.battery.battery_manifest_hash, campaign.campaign_hash,
        campaign.acceptance_policy_hash, campaign.split_commitment_hashes["AUDIT"],
    )
    calls = 0

    def evaluate() -> object:
        nonlocal calls
        calls += 1
        from lab.genesis.acquisition.benchmark import DatasetSplit, SplitEvaluation
        return SplitEvaluation(campaign.task_id, DatasetSplit.AUDIT, commitment.candidate_skill_hash, True, 1, 1)

    registry = V3DurableAuditRegistry(tmp_path / "audit")
    first = registry.evaluate(slot=slot, commitment=commitment, evaluate_once=evaluate)
    second = registry.evaluate(slot=slot, commitment=commitment, evaluate_once=evaluate)
    assert first == second and calls == 1
    other = V3CandidateCommitment(
        "genesis-m7-v3-candidate-commitment-h3a0", campaign.campaign_hash, h("other-skill"), h("other-program"),
        campaign.split_commitment_hashes["TRAIN"], h("search"), h("ranking"), 2,
    )
    with pytest.raises(ValueError, match="reconsumption_rejected"):
        registry.evaluate(slot=slot, commitment=other, evaluate_once=evaluate)
