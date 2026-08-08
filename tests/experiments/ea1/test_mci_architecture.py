from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.experiments.ea1.contracts import ScenarioFamily, TheoryState
from runtime.experiments.ea1.mci_arm import MCIArmAdapter, MCIArmInput
from runtime.experiments.ea1.scenarios import make_smoke_fixture
from runtime.organism.experience import ExperienceIntegrityError, ExperienceStore
from runtime.storage import StorageConfig, StorageFactory


ROOT = Path(__file__).parents[3]


def test_t1_frozen_mci_core_is_15_of_15_byte_identical() -> None:
    manifest = json.loads(
        (ROOT / "docs/experiments/ea1/EA1_MCI_CORE_RECOVERY_MANIFEST_V1.json").read_text()
    )
    assert len(manifest["files"]) == 15
    for item in manifest["files"]:
        actual = hashlib.sha256((ROOT / item["destination_path"]).read_bytes()).hexdigest()
        assert actual == item["source_file_sha256"] == item["recovered_file_sha256"]
        assert item["status"] == "EXACT"
        assert item["compatibility_modification"] is None


def test_policy_result_cannot_depend_on_names_order_scenario_id_or_commitment() -> None:
    fixture = make_smoke_fixture(ScenarioFamily.S2)
    theory = TheoryState("theory", 1, 0.49, 0.49, 0.02, "h1", logical_time=1)
    adapter = MCIArmAdapter()
    original = MCIArmInput(
        fixture.public, theory, fixture.public.hypotheses, {"observation": "mid"}
    )
    first = adapter.prepare(original, epoch=1, logical_time=2)
    renamed_actions = tuple(
        replace(action, label=f"opaque-{index}")
        for index, action in enumerate(reversed(fixture.public.actions))
    )
    perturbed_scenario = replace(
        fixture.public,
        scenario_id="opaque-scenario-replacement",
        commitment="0" * 64,
        actions=renamed_actions,
    )
    perturbed = adapter.prepare(
        MCIArmInput(
            perturbed_scenario, theory, fixture.public.hypotheses,
            {"observation": "mid"},
        ),
        epoch=1,
        logical_time=2,
    )
    selected_first = adapter.policy.select(theory, first.proposals).selected
    selected_second = adapter.policy.select(theory, perturbed.proposals).selected
    assert selected_first is not None and selected_second is not None
    assert selected_first.action_id == selected_second.action_id


def test_policy_dependency_graph_excludes_evaluator_oracle_holdout_and_f1a_authority() -> None:
    import runtime.experiments.ea1.mci_adapter as adapter_module
    import runtime.experiments.ea1.mci_arm as arm_module
    import runtime.experiments.ea1.mci_revision_adapter as revision_module
    import runtime.experiments.ea1.mci_voi_policy as policy_module

    policy_source = inspect.getsource(policy_module)
    arm_source = inspect.getsource(arm_module)
    prediction_source = inspect.getsource(adapter_module)
    assert "SourceAcquisitionEvaluator" not in policy_source + arm_source + prediction_source
    assert "SealedGroundTruth" not in policy_source + arm_source + prediction_source
    assert "OracleService" not in policy_source + arm_source + prediction_source
    assert "heldout" not in policy_source + arm_source + prediction_source
    assert "runtime.experiments.ea1.evaluator" not in policy_source + arm_source
    assert "_issue_canonical_outcome_authority" not in inspect.getsource(revision_module)


def test_epistemic_objects_cannot_enter_experience_or_situation_wisdom(tmp_path: Path) -> None:
    db = StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "firewall.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )
    fixture = make_smoke_fixture(ScenarioFamily.S5)
    theory = TheoryState("theory", 1, 0.49, 0.49, 0.02, "h1", logical_time=1)
    batch = MCIArmAdapter().prepare(
        MCIArmInput(fixture.public, theory, fixture.public.hypotheses, {"passive": "mid"}),
        epoch=1,
        logical_time=2,
    )
    store = ExperienceStore(storage=db)
    artifacts = (theory, batch.prediction_set, batch.proposals[0], batch.working.snapshot())
    for artifact in artifacts:
        with pytest.raises(ExperienceIntegrityError):
            store.record(artifact)  # type: ignore[arg-type]
    assert store.wisdom(organism_id="organism", situation="ea1-mci").n == 0
