from __future__ import annotations

from pathlib import Path

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "resume.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _config(*, run_id: str, restore: bool) -> LifeKernelConfig:
    return LifeKernelConfig(
        run_id=run_id,
        organism_id="organism-resume-test",
        scenarios=("thermal_homeostasis",),
        block_size=50,
        max_steps=2,
        restore=restore,
        checkpoint_interval=1,
        allow_external_reasoner=False,
        enable_msrc=True,
        enable_operational_conjunction=False,
        resource_snapshot_override={
            "cpu_pressure": 0.1,
            "memory_pressure": 0.1,
            "thermal_pressure": 0.1,
            "vram_pressure": 0.1,
            "gpu_available": False,
        },
    )


def test_checkpoint_resume_preserves_n3_identity_and_temporal_state(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RNFE_NEURAL_MODE", "shadow")
    monkeypatch.setenv("RNFE_CAUSAL_CONTEXT", "1")
    storage = _storage(tmp_path)

    first_kernel = LifeKernel(config=_config(run_id="run-before", restore=False), storage=storage)
    first_steps = first_kernel.run_until_stopped(max_steps=2)
    first_episodes = [step.episode_result for step in first_steps if step.episode_result]
    assert len(first_episodes) == 2
    prior_n3 = next(
        entry["candidate"]
        for entry in first_episodes[-1]["neural_symbiosis_trace"]["organs"]
        if entry["organ"] == "N3"
    )
    assert prior_n3["episode_count"] == 2

    resumed = LifeKernel(config=_config(run_id="run-after", restore=True), storage=storage)
    assert resumed.run_id == "run-after"
    assert resumed.organism_id == first_kernel.organism_id
    assert resumed.lineage_id == first_kernel.lineage_id
    resumed_steps = resumed.run_until_stopped(max_steps=1)
    resumed_episode = next(step.episode_result for step in resumed_steps if step.episode_result)
    resumed_n3 = next(
        entry["candidate"]
        for entry in resumed_episode["neural_symbiosis_trace"]["organs"]
        if entry["organ"] == "N3"
    )

    assert resumed_n3["episode_count"] == 3
    assert resumed_n3["previous_state"]["episode_count"] == 2
    assert resumed_n3["state_key"] == prior_n3["state_key"]
    assert resumed_episode["neural_symbiosis_trace"]["run_id"] == "run-after"
    assert resumed_steps[0].msrc["trace_group_id"] == resumed_episode[
        "neural_symbiosis_trace"
    ]["trace_group_id"]
    assert resumed_steps[0].msrc["atomic"] is True
    storage.close()
