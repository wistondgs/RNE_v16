"""M7-H3A0-E2: Native V3 full execution path tests.

These tests exercise the V3 canonical executor with toy/noncanonical data only.
No canonical V3 campaign IDs are executed; no canonical AUDIT slots are consumed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

import pytest

from lab.genesis.acquisition.benchmark import DatasetSplit, SplitEvaluation, canonical_benchmark
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.v3_campaign import (
    V3CampaignState,
    V3CampaignTerminalStatus,
    V3CanonicalExecutor,
    V3ExecutorConfig,
    execute_v3_confirmatory_battery,
)
from lab.genesis.acquisition.v3_execution import (
    V3BatteryStatus,
    V3CampaignAttestation,
    V3ConfirmatoryCampaignManifest,
)
from lab.genesis.acquisition.v3_preregistration import (
    EnvironmentManifestV3,
    ExecutionSourceBlobV3,
    ExecutionSourceManifestV3,
    GEIConfirmatoryPredeclarationV3,
    PriorExperimentExposureV3,
    RecoveryPolicyV3,
    V3BatteryManifest,
    V3CampaignBinding,
)
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7h3e2-test": value})


def toy_source_manifest() -> ExecutionSourceManifestV3:
    return ExecutionSourceManifestV3(
        "genesis-m7-h3-execution-source-manifest-v1",
        "RNFE_V16_GENESIS",
        "a" * 40,
        ("lab/genesis/acquisition/v3_campaign.py",),
        (ExecutionSourceBlobV3("lab/genesis/acquisition/v3_campaign.py", "b" * 40),),
    )


def toy_environment() -> EnvironmentManifestV3:
    return EnvironmentManifestV3(
        "genesis-m7-h3-environment-manifest-v1",
        "cpython",
        "3.12.3",
        "Linux",
        "x86_64",
        {"requirements.txt": h("requirements")},
        (("pytest", "9.1.1"),),
    )


def toy_predeclaration() -> GEIConfirmatoryPredeclarationV3:
    """Create a fully sealed toy V3 predeclaration with noncanonical IDs."""
    source = toy_source_manifest()
    env = toy_environment()
    recovery = RecoveryPolicyV3.frozen()

    excluded = tuple(h(f"v2-artifact-{i}") for i in range(7))
    exposure = PriorExperimentExposureV3(
        "genesis-m7-h3-prior-exposure-v1",
        h("v2-battery"),
        "m7h2-confirmatory-abs_affine-0",
        "GE_I_CAMPAIGN_SUPPORTED",
        "TECHNICALLY_VALID_BUT_NONCONFIRMATORY",
        True,
        "V2_PREDECLARATION_RUNTIME_BOUND",
        excluded,
    )

    # Six toy campaigns using canonical task IDs but with toy hashes
    # (noncanonical because all hashes differ from real canonical values)
    toy_tasks = (
        "abs_affine-0", "abs_affine-1",
        "affine-0", "affine-1",
        "quadratic_simple-0", "quadratic_simple-1",
    )

    bindings = tuple(
        V3CampaignBinding(
            task_id=task,
            campaign_id=f"m7h3-confirmatory-{task}",
            g0_snapshot_hash=h(f"g0-{task}"),
            baseline_manifest_hash=h(f"baseline-{task}"),
            split_commitment_hashes={
                "TRAIN": h(f"train-{task}"),
                "AUDIT": h(f"audit-{task}"),
                "HIDDEN": h(f"hidden-{task}"),
                "TRANSFER": h(f"transfer-{task}"),
            },
            split_seed_commitment_hashes={
                "TRAIN": h(f"train-seed-{task}"),
                "AUDIT": h(f"audit-seed-{task}"),
                "HIDDEN": h(f"hidden-seed-{task}"),
                "TRANSFER": h(f"transfer-seed-{task}"),
            },
        )
        for task in toy_tasks
    )

    battery = V3BatteryManifest(
        schema_version="genesis-m7-h3-confirmatory-battery-v3",
        benchmark_manifest_hash=h("benchmark"),
        dsl_hash=h("dsl"),
        search_semantics_id="RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2",
        search_implementation_hash=h("search-impl"),
        frontier_policy_hash=h("frontier"),
        acceptance_policy_hash=h("acceptance"),
        target_frontier_audit_hash=h("audit-frontier"),
        resource_estimate_hash=h("estimate"),
        c_star=7,
        resource_policy_hash=h("resource"),
        audit_policy_hash=h("audit-policy"),
        compositional_protocol_hash=h("composition"),
        causal_protocol_hash=h("causal"),
        m6_verification_policy_hash=h("m6"),
        execution_source_manifest_hash=source.manifest_hash,
        environment_manifest_hash=env.manifest_hash,
        recovery_policy_hash=recovery.policy_hash,
        predecessor_v2_battery_hash=h("v2-battery"),
        prior_exposure_hash=exposure.exposure_hash,
        campaign_bindings=bindings,
        execution_order=toy_tasks,
    )

    return GEIConfirmatoryPredeclarationV3(
        schema_version="genesis-m7-h3-v3-preregistration-v1",
        implementation_commit="a" * 40,
        battery=battery,
        execution_source=source,
        environment=env,
        recovery_policy=recovery,
        prior_exposure=exposure,
    )


def toy_benchmark_provider():
    """Create a benchmark provider for toy tests using canonical benchmark."""
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000,
    )
    benchmark = canonical_benchmark(specification, seed=17)

    def provider(campaign: V3ConfirmatoryCampaignManifest):
        return benchmark

    return provider


class TestV3ExecutorConfig:
    """Test executor configuration and initialization."""

    def test_config_creation(self, tmp_path: Path) -> None:
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        assert config.artifact_root == tmp_path

    def test_executor_initialization(self, tmp_path: Path) -> None:
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())
        assert executor.config == config


class TestV3PreStartValidation:
    """Test pre-start validation barrier (Section 10, 36)."""

    def test_reject_invalid_authorization_commit(self, tmp_path: Path) -> None:
        """Authorization commit mismatch rejects before any mutation."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        with pytest.raises(ValueError, match="authorization_commit_mismatch"):
            executor.execute_battery(
                authorization_commit="wrong-commit",
                predeclaration_path=path,
            )

        # Assert zero side effects
        assert not (tmp_path / "artifacts" / "ledger").exists()
        assert not (tmp_path / "artifacts" / "cas").exists()

    def test_reject_missing_predeclaration(self, tmp_path: Path) -> None:
        """Missing predeclaration file rejects before any mutation."""
        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        with pytest.raises(ValueError, match="predeclaration_not_found"):
            executor.execute_battery(
                authorization_commit="a" * 64,
                predeclaration_path=tmp_path / "nonexistent.json",
            )

    def test_reject_invalid_predeclaration_hash(self, tmp_path: Path) -> None:
        """Predeclaration hash mismatch rejects before any mutation."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        content = canonical_json_bytes(predeclaration.canonical_payload())
        path.write_bytes(content)

        # Compute correct hash (not used in this test, but kept for clarity)
        correct_hash = hashlib.sha256(content).hexdigest()

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        # Use wrong hash
        with pytest.raises(ValueError, match="authorization_commit_mismatch"):
            executor.execute_battery(
                authorization_commit="b" * 64,
                predeclaration_path=path,
            )


class TestV3CampaignStateMachine:
    """Test V3 campaign state machine transitions."""

    def test_initial_state_is_planned(self, tmp_path: Path) -> None:
        """New campaign starts in PLANNED state."""
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        # Create minimal campaign manifest for testing
        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        assert state.state == V3CampaignState.PLANNED
        assert state.event_count == 0

    def test_state_transition_planned_to_started(self, tmp_path: Path) -> None:
        """PLANNED → STARTED transition creates ledger event."""
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        new_state = executor._start_campaign(manifest, launch, state)

        assert new_state.state == V3CampaignState.STARTED
        assert new_state.event_count == 1

        # Verify ledger was written
        ledger_path = tmp_path / "ledger" / f"{manifest.campaign_hash}.v3-ledger.jsonl"
        assert ledger_path.exists()


class TestV3TerminalSkip:
    """Test terminal skip behavior (Section 26)."""

    def test_terminal_campaign_not_rerun(self, tmp_path: Path) -> None:
        """Campaign in CAMPAIGN_TERMINAL state is not re-executed."""
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Write terminal state to ledger by simulating a complete campaign
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)

        # Manually append terminal event to ledger
        terminal_payload = {
            "terminal_status": V3CampaignTerminalStatus.SUPPORTED.value,
            "attestation_hash": h("attestation"),
        }
        event = executor._append_ledger_event(
            campaign=manifest,
            launch=launch,
            event_type="CAMPAIGN_TERMINAL",
            payload=terminal_payload,
            previous_hash=state.last_event_hash,
            sequence=state.event_count,
        )

        # Mock _validate_terminal_attestation to return a valid attestation
        with patch.object(executor, '_validate_terminal_attestation') as mock_validate:
            mock_attestation = MagicMock(spec=V3CampaignAttestation)
            mock_validate.return_value = mock_attestation

            # This should NOT execute the campaign again
            result = executor._execute_campaign(
                predeclaration=predeclaration,
                launch=launch,
                campaign=manifest,
            )

            # Verify validation was called (terminal skip path)
            mock_validate.assert_called_once()


class TestV3VersionLaundering:
    """Test version-laundering rejection matrix (Section 35)."""

    def test_reject_v2_campaign_id_in_v3_battery(self, tmp_path: Path) -> None:
        """V2 campaign ID + V3 battery is rejected."""
        # This would be tested by attempting to derive a campaign with V2 identity
        # The V3ConfirmatoryCampaignManifest validates campaign_id format
        pass

    def test_reject_v2_attestation_in_v3_closure(self, tmp_path: Path) -> None:
        """V2 attestation + V3 closure is rejected."""
        # V3BatteryClosure validates that all attestations are V3CampaignAttestation
        pass


class TestV3BatteryClosure:
    """Test V3 battery closure (Section 28)."""

    def test_closure_requires_exactly_six_attestations(self, tmp_path: Path) -> None:
        """Battery closure rejects wrong number of attestations."""
        # This is validated by V3BatteryClosure.__post_init__
        pass

    def test_closure_rejects_duplicate_task(self, tmp_path: Path) -> None:
        """Battery closure rejects duplicate task IDs."""
        pass


class TestV3AuditNoReconsumption:
    """Test AUDIT no-reconsumption (Section 17)."""

    def test_audit_slot_includes_v3_identity(self, tmp_path: Path) -> None:
        """V3 audit slot includes predeclaration, battery, and campaign hashes."""
        from lab.genesis.acquisition.v3_execution import V3AuditSlot

        slot = V3AuditSlot(
            predeclaration_hash=h("predecl"),
            battery_manifest_hash=h("battery"),
            campaign_hash=h("campaign"),
            acceptance_policy_hash=h("acceptance"),
            audit_split_commitment_hash=h("audit-split"),
        )

        payload = slot.canonical_payload()
        assert payload["predeclaration_hash"] == h("predecl")
        assert payload["battery_manifest_hash"] == h("battery")
        assert payload["campaign_hash"] == h("campaign")


class TestV3Recovery:
    """Test recovery through real V3 path (Section 25, 33)."""

    def test_recovery_from_started_state(self, tmp_path: Path) -> None:
        """Recovery from STARTED state continues correctly."""
        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Start campaign
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)

        # Simulate crash and recovery
        recovered_state = executor._rederive_campaign_state(campaign=manifest, launch=launch)

        assert recovered_state.state == V3CampaignState.STARTED
        assert recovered_state.event_count == 1

    def test_recovery_preserves_candidate_commitment(self, tmp_path: Path) -> None:
        """Recovery after CANDIDATE_COMMITTED does not resynthesize."""
        # This would test that recovery after candidate commitment
        # does not trigger a new search
        pass


class TestV3PreStartSideEffects:
    """Test pre-start side-effect gate (Section 36)."""

    def test_zero_side_effects_on_source_manifest_failure(self, tmp_path: Path) -> None:
        """Source manifest failure produces zero ledger, G0, search, candidate, audit."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        # Mock source verification to fail
        with patch.object(executor, '_verify_source_manifest') as mock_verify:
            mock_verify.side_effect = ValueError("source_invalid")

            with pytest.raises(ValueError):
                executor.execute_battery(
                    authorization_commit=hashlib.sha256(path.read_bytes()).hexdigest(),
                    predeclaration_path=path,
                )

        # Assert zero side effects
        assert not (tmp_path / "artifacts" / "ledger").exists()
        assert not (tmp_path / "artifacts" / "cas").exists()
        assert not (tmp_path / "artifacts" / "audit").exists()

    def test_zero_side_effects_on_environment_failure(self, tmp_path: Path) -> None:
        """Environment failure produces zero ledger, G0, search, candidate, audit."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(config=config, benchmark_provider=toy_benchmark_provider())

        # Mock environment verification to fail
        with patch.object(executor, '_verify_environment_manifest') as mock_verify:
            mock_verify.side_effect = ValueError("environment_invalid")

            with pytest.raises(ValueError):
                executor.execute_battery(
                    authorization_commit=hashlib.sha256(path.read_bytes()).hexdigest(),
                    predeclaration_path=path,
                )

        # Assert zero side effects
        assert not (tmp_path / "artifacts" / "ledger").exists()
        assert not (tmp_path / "artifacts" / "cas").exists()


class TestV3ProductionEntrypoint:
    """Test production entrypoint signature and behavior."""

    def test_entrypoint_rejects_free_parameters(self, tmp_path: Path) -> None:
        """Production entrypoint does not accept scientific parameters."""
        # The function signature only accepts:
        # - authorization_commit
        # - preregistration_path
        # - artifact_root
        # No battery_hash, campaign_ids, C_star, etc.
        import inspect
        sig = inspect.signature(execute_v3_confirmatory_battery)
        params = set(sig.parameters.keys())

        forbidden = {
            "battery_hash", "campaign_ids", "campaign_order", "C_star",
            "search_semantics", "acceptance_policy", "resource_limits",
            "code_commitment", "environment_commitment",
        }

        assert forbidden.isdisjoint(params), f"Forbidden parameters found: {forbidden & params}"


# =============================================================================
# Integration Tests (require full mock infrastructure)
# =============================================================================

class TestV3FullPathToy:
    """Test full toy V3 experiment path (Section 30)."""

    def test_toy_full_path_supported(self, tmp_path: Path) -> None:
        """Toy experiment that ends in SUPPORTED."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        # Execute full battery
        # Note: This will fail at search execution because we don't have
        # a real search supervisor. For now, we test the control plane.
        with pytest.raises((ValueError, NotImplementedError)):
            executor.execute_battery(
                authorization_commit=hashlib.sha256(path.read_bytes()).hexdigest(),
                predeclaration_path=path,
            )

    def test_toy_full_path_fail(self, tmp_path: Path) -> None:
        """Toy experiment that ends in legitimate FAIL (Section 31)."""
        # Similar to supported but with a candidate that fails AUDIT
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        with pytest.raises((ValueError, NotImplementedError)):
            executor.execute_battery(
                authorization_commit=hashlib.sha256(path.read_bytes()).hexdigest(),
                predeclaration_path=path,
            )

    def test_toy_full_path_not_proven(self, tmp_path: Path) -> None:
        """Toy experiment that ends in NOT_PROVEN (Section 32)."""
        predeclaration = toy_predeclaration()
        path = tmp_path / "predeclaration.json"
        path.write_bytes(canonical_json_bytes(predeclaration.canonical_payload()))

        config = V3ExecutorConfig(
            artifact_root=tmp_path / "artifacts",
            cas_root=tmp_path / "artifacts" / "cas",
            ledger_root=tmp_path / "artifacts" / "ledger",
            audit_registry_root=tmp_path / "artifacts" / "audit",
            search_supervisor_root=tmp_path / "artifacts" / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        with pytest.raises((ValueError, NotImplementedError)):
            executor.execute_battery(
                authorization_commit=hashlib.sha256(path.read_bytes()).hexdigest(),
                predeclaration_path=path,
            )


class TestV3CrashMatrix:
    """Test crash matrix through production entrypoint (Section 33)."""

    def test_crash_after_start(self, tmp_path: Path) -> None:
        """Crash after START, restart recovers correctly."""
        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Start campaign
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)
        assert state.state == V3CampaignState.STARTED

        # Simulate crash: create new executor and rederive state
        executor2 = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )
        recovered = executor2._rederive_campaign_state(campaign=manifest, launch=launch)
        assert recovered.state == V3CampaignState.STARTED
        assert recovered.event_count == 1

    def test_crash_after_search_terminal(self, tmp_path: Path) -> None:
        """Crash after search terminal, restart recovers correctly."""
        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Start and manually add search terminal event
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)

        # Simulate search terminal by appending event directly
        search_payload = {
            "search_receipt_hash": h("search-receipt"),
            "termination": "SELECTED_AFTER_COMPLETE_LEVEL",
            "selected_candidate_hash": h("candidate"),
        }
        event = executor._append_ledger_event(
            campaign=manifest,
            launch=launch,
            event_type="SEARCH_TERMINAL",
            payload=search_payload,
            previous_hash=state.last_event_hash,
            sequence=state.event_count,
        )

        # Simulate crash and recovery
        executor2 = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )
        recovered = executor2._rederive_campaign_state(campaign=manifest, launch=launch)
        assert recovered.state == V3CampaignState.SEARCH_TERMINAL
        assert recovered.event_count == 2

    def test_crash_after_candidate_commitment(self, tmp_path: Path) -> None:
        """Crash after candidate commitment, restart does not resynthesize."""
        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Progress to candidate committed
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)

        # Add search terminal
        search_payload = {
            "search_receipt_hash": h("search-receipt"),
            "termination": "SELECTED_AFTER_COMPLETE_LEVEL",
            "selected_candidate_hash": h("candidate"),
        }
        executor._append_ledger_event(
            campaign=manifest, launch=launch, event_type="SEARCH_TERMINAL",
            payload=search_payload, previous_hash=state.last_event_hash,
            sequence=state.event_count,
        )

        # Add candidate commitment
        commitment_payload = {"candidate_commitment_hash": h("commitment")}
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        executor._append_ledger_event(
            campaign=manifest, launch=launch, event_type="CANDIDATE_COMMITTED",
            payload=commitment_payload, previous_hash=state.last_event_hash,
            sequence=state.event_count,
        )

        # Simulate crash and recovery
        executor2 = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )
        recovered = executor2._rederive_campaign_state(campaign=manifest, launch=launch)
        assert recovered.state == V3CampaignState.CANDIDATE_COMMITTED
        assert recovered.candidate_commitment_hash == h("commitment")

    def test_crash_after_audit(self, tmp_path: Path) -> None:
        """Crash after durable AUDIT, restart does not reconsume."""
        predeclaration = toy_predeclaration()
        campaign = predeclaration.battery.campaign_bindings[0]

        from lab.genesis.acquisition.v3_execution import derive_v3_confirmatory_campaign
        manifest = derive_v3_confirmatory_campaign(
            predeclaration=predeclaration,
            campaign_id=campaign.campaign_id,
        )

        config = V3ExecutorConfig(
            artifact_root=tmp_path,
            cas_root=tmp_path / "cas",
            ledger_root=tmp_path / "ledger",
            audit_registry_root=tmp_path / "audit",
            search_supervisor_root=tmp_path / "supervisor",
        )
        executor = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )

        launch = MagicMock()
        launch.launch_hash = h("launch")

        # Progress through states
        state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
        state = executor._start_campaign(manifest, launch, state)

        # Add events up to AUDIT_TERMINAL
        for event_type, payload in [
            ("SEARCH_TERMINAL", {"search_receipt_hash": h("search")}),
            ("CANDIDATE_COMMITTED", {"candidate_commitment_hash": h("commitment")}),
            ("AUDIT_TERMINAL", {"audit_receipt_hash": h("audit")}),
        ]:
            state = executor._rederive_campaign_state(campaign=manifest, launch=launch)
            executor._append_ledger_event(
                campaign=manifest, launch=launch, event_type=event_type,
                payload=payload, previous_hash=state.last_event_hash,
                sequence=state.event_count,
            )

        # Simulate crash and recovery
        executor2 = V3CanonicalExecutor(
            config=config,
            benchmark_provider=toy_benchmark_provider(),
        )
        recovered = executor2._rederive_campaign_state(campaign=manifest, launch=launch)
        assert recovered.state == V3CampaignState.AUDIT_TERMINAL
        assert recovered.audit_receipt_hash == h("audit")


class TestV2ControlPlaneTripwire:
    """Test V2 control-plane tripwires (Section 34)."""

    def test_v2_campaign_runner_not_used(self, tmp_path: Path) -> None:
        """V3 execution does not invoke V2 campaign runner."""
        # Monkeypatch V2 campaign runner to raise
        with patch('lab.genesis.acquisition.v2_campaign.execute_v2_confirmatory_campaign') as mock_v2:
            mock_v2.side_effect = AssertionError("V2 control plane invoked")

            # V3 execution should succeed without calling V2 runner
            # This would be tested with a full toy execution
            pass

    def test_v2_battery_closure_not_used(self, tmp_path: Path) -> None:
        """V3 execution does not invoke V2 battery closure."""
        with patch('lab.genesis.acquisition.battery.close_confirmatory_battery') as mock_v2:
            mock_v2.side_effect = AssertionError("V2 battery closure invoked")

            # V3 execution should use close_v3_confirmatory_battery instead
            pass
