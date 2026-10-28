from pathlib import Path

from runtime.life import (
    AutonomySupervisor,
    CheckpointManager,
    LIFE_CHECKPOINT_KIND,
    LifeKernel,
    LifeKernelConfig,
    OrganismPersistence,
    VitalSignsSnapshot,
)
from runtime.storage import StorageConfig, StorageFactory


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


def test_non_acting_step_stores_the_vitals_it_computed(tmp_path: Path):
    """El pestillo de rollback: curarse y no enterarse.

    `step()` decide con `self.last_vitals`. La rama no-actuante RESTAURA el
    último checkpoint sano y recomputa vitales frescos, pero durante un tiempo
    no los guardaba: el paso siguiente releía los vitales enfermos y volvía a
    decidir rollback, sin salida. Medido en vivo: muerte en el paso 32 y 117 de
    150 pasos congelados repitiendo el mismo checkpoint, sin ejecutar un solo
    episodio — y por tanto sin que el lazo de regulación adaptativa corriera.

    Esta prueba fija el invariante mínimo: los vitales con los que la rama
    no-actuante responde son los que quedan para decidir el siguiente paso.
    """
    storage = _storage(tmp_path)
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="life-latch",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    # Un primer paso real deja al organismo con historia y un checkpoint sano.
    kernel.step()

    # Se le fuerza el estado por el que el supervisor exige rollback.
    kernel.last_vitals = _vitals(mode="rollback", reversible=False, viability_margin=0.02)
    result = kernel.step()

    assert result.decision.action == "rollback"
    assert result.episode_result is None  # la rama no-actuante, en efecto
    assert kernel.last_vitals is not None
    assert kernel.last_vitals.mode == result.vital_signs.mode
    assert kernel.last_vitals.viability_margin == result.vital_signs.viability_margin
    assert kernel.last_vitals.reversible == result.vital_signs.reversible
