"""B46: en un re-write del mismo assessment_id, `created_at` se preserva.

Semantica elegida: created_at = tiempo de creacion -> se conserva en conflicto
(alineado con el backend Postgres). El resto de los campos se actualiza.
"""

from __future__ import annotations

from pathlib import Path

from runtime.storage import StorageConfig, StorageFactory


def _facade(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "transfer.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=True,
            strict_dual_write=False,
        )
    )


def test_transfer_created_at_preserved_on_rewrite(tmp_path: Path) -> None:
    storage = _facade(tmp_path)
    try:
        original_created = "2020-01-01T00:00:00+00:00"
        storage.write_transfer_assessment(
            assessment_id="assess-1",
            run_id="run-1",
            episode_id="ep-1",
            source_scenario="A",
            target_scenario="B",
            compatibility_class="compatible",
            transfer_verdict="allow",
            memory_purity_score=0.9,
            transition_stability_score=0.8,
            metadata={"v": 1},
            created_at=original_created,
        )

        # Re-write mismo assessment_id, otros campos y OTRO created_at.
        storage.write_transfer_assessment(
            assessment_id="assess-1",
            run_id="run-1",
            episode_id="ep-2",
            source_scenario="A2",
            target_scenario="B2",
            compatibility_class="incompatible",
            transfer_verdict="block",
            memory_purity_score=0.1,
            transition_stability_score=0.2,
            metadata={"v": 2},
            created_at="2099-12-31T23:59:59+00:00",
        )

        rows = storage.list_transfer_assessments(run_id="run-1")
        assert len(rows) == 1
        row = rows[0]
        # created_at preservado (el original), NO pisado por el segundo write.
        assert row.created_at == original_created
        # el resto de los campos se actualizo al segundo write.
        assert row.episode_id == "ep-2"
        assert row.source_scenario == "A2"
        assert row.target_scenario == "B2"
        assert row.compatibility_class == "incompatible"
        assert row.transfer_verdict == "block"
        assert row.memory_purity_score == 0.1
        assert row.transition_stability_score == 0.2
        assert row.metadata == {"v": 2}
    finally:
        storage.close()
