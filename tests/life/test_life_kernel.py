from pathlib import Path

from runtime.life import (
    AutonomyDecision,
    AutonomySupervisor,
    CheckpointManager,
    LIFE_CHECKPOINT_KIND,
    LifeKernel,
    LifeKernelConfig,
    OrganismPersistence,
    VitalSignsSnapshot,
)
from runtime.storage import StorageConfig, StorageFactory
from runtime.organism.experience import ExperienceStore


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "life.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _vitals(**overrides):
    payload = {
        "run_id": "life-test",
        "episode_count": 3,
        "mode": "normal",
        "viability_margin": 0.80,
        "continuity_score": 0.90,
        "ioc_proxy": 0.80,
        "risk_score": 0.20,
        "memory_purity": 0.95,
        "cognitive_quality": 0.78,
        "resource_pressure": 0.10,
        "recovery_debt": 0.0,
        "accumulated_drift": 0.0,
        "reversible": True,
        "identity_continuity": 0.90,
        "certified": True,
    }
    payload.update(overrides)
    return VitalSignsSnapshot(**payload)


def test_life_kernel_step_persists_checkpoint_and_identity(tmp_path: Path):
    storage = _storage(tmp_path)
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-unit",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )

    result = kernel.step(external_input=0.05)

    assert result.run_id == "life-unit"
    assert result.step_index == 1
    assert result.episode_result is not None
    assert result.decision.action == "act"
    assert result.vital_signs.episode_count == 1
    assert result.checkpoint_artifact_id

    artifacts = storage.list_artifacts(run_id="life-unit", kind=LIFE_CHECKPOINT_KIND)
    assert artifacts

    restored = OrganismPersistence(storage=storage).load_latest_identity(run_id="life-unit")
    assert restored is not None
    assert restored.organism_state.episode_count == 1
    assert restored.goals


def test_nonacting_life_outcome_witness_reenters_wisdom(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")
    storage = _storage(tmp_path)
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-nonacting-witness",
            organism_id="organism-nonacting-witness",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    monkeypatch.setattr(
        kernel.supervisor,
        "decide",
        lambda **_: AutonomyDecision(
            action="sleep",
            mode="conservative",
            reason="test_nonacting_witness",
            scenario="thermal_homeostasis",
        ),
    )

    result = kernel.step(external_input=0.05)

    store = ExperienceStore(storage=storage)
    records = store.recall(organism_id=kernel.organism_id)
    assert result.decision.action == "sleep"
    assert len(records) == 1
    wisdom = store.wisdom(
        organism_id=kernel.organism_id,
        situation=records[0]["situation_key"],
    )
    assert wisdom.n == 1
    assert wisdom.witness_verified_n == 1
    assert records[0]["outcome_witness"]["source_event_type"] == "life.sleep"


def test_life_kernel_resurrects_latest_identity(tmp_path: Path):
    storage = _storage(tmp_path)
    config = LifeKernelConfig(
        run_id="life-resurrect",
        scenarios=("thermal_homeostasis",),
        restore=False,
        enable_msrc=False,
    )
    first = LifeKernel(config=config, storage=storage)
    first.step(external_input=0.05)
    first.step(external_input=0.04)

    second = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-resurrect",
            scenarios=("thermal_homeostasis",),
            restore=True,
            enable_msrc=False,
        ),
        storage=storage,
    )

    assert second.total_steps == first.total_steps
    assert second.organism_state is not None
    assert first.organism_state is not None
    assert second.organism_state.episode_count == first.organism_state.episode_count

    result = second.step(external_input=0.04)
    assert result.step_index == first.total_steps + 1
    assert second.organism_state.episode_count == first.organism_state.episode_count + 1


def test_supervisor_selects_life_modes():
    supervisor = AutonomySupervisor()

    genesis = supervisor.decide(
        vitals=_vitals(episode_count=0, certified=False),
        goals=[],
        step_index=0,
        scenario="thermal_homeostasis",
    )
    assert genesis.action == "act"

    rollback = supervisor.decide(
        vitals=_vitals(mode="rollback", viability_margin=0.01, reversible=False),
        goals=[],
        step_index=4,
        scenario="thermal_homeostasis",
    )
    assert rollback.action == "rollback"

    mutation = supervisor.decide(
        vitals=_vitals(memory_purity=0.20),
        goals=[],
        step_index=5,
        scenario="thermal_homeostasis",
    )
    assert mutation.action == "self_modify"
    assert mutation.directives["requires_checkpoint"] is True


def test_life_kernel_runs_msrc_inside_cycle(tmp_path: Path):
    storage = _storage(tmp_path)
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-msrc",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=True,
        ),
        storage=storage,
    )

    result = kernel.step(external_input=0.05)

    assert result.msrc["selected_scale_id"] in {"1x1", "5x5"}
    assert result.msrc["action"]["action_type"]
    events = storage.list_events(run_id="life-msrc", event_types=["msrc.decision"], limit=5)
    assert events


def test_checkpoint_manager_can_load_healthy_checkpoint(tmp_path: Path):
    storage = _storage(tmp_path)
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-healthy",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    kernel.step(external_input=0.05)

    loaded = CheckpointManager(storage=storage).load_latest_payload(
        run_id="life-healthy",
        healthy_only=True,
    )

    assert loaded is not None
    payload, artifact = loaded
    assert payload["run_id"] == "life-healthy"
    assert artifact.metadata["healthy"] is True
