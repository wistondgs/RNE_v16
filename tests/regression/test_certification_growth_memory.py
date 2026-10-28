from pathlib import Path

from runtime.certification.continuity_guard import ContinuityGuard
from runtime.certification.ioc_proxy import IoCProxy
from runtime.certification.promotion_gate import PromotionGate
from runtime.storage import StorageConfig, StorageFactory
from runtime.world.min_cognitive_episode import MinimalCognitiveEpisodeRunner


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "growth.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def test_continuity_guard_and_ioc_proxy_units():
    guard = ContinuityGuard()
    ioc = IoCProxy()

    score = guard.score(
        previous_certificate=None,
        current_episode={"result": {"reasoning_sequence": ["ABD", "ANA"]}},
        fallback_continuity=0.74,
    )
    assert score == 0.74
    assert guard.has_alert(0.2) is True
    assert guard.has_alert(0.7) is False

    ioc_value = ioc.compute(
        continuity_score=0.8,
        closure_passed=True,
        trace_integrity=True,
        collapse_detected=False,
        uncertainty=0.2,
    )
    assert 0.0 <= ioc_value <= 1.0
    assert ioc_value > 0.7


def test_growth_pipeline_persists_certificates_and_memory_levels(tmp_path: Path):
    storage = _storage(tmp_path)
    runner = MinimalCognitiveEpisodeRunner(storage=storage, run_id="run-growth-1")

    first = runner.run_episode(external_heat=0.05)
    second = runner.run_episode(external_heat=0.05)
    third = runner.run_episode(external_heat=0.05)

    assert first["episode"]["context"]["retrieved_memory"] == []
    assert isinstance(second["episode"]["context"]["retrieved_memory"], list)

    certs = storage.list_episode_certificates(run_id="run-growth-1", limit=20)
    assert len(certs) >= 3
    assert all(item.rollback_ready for item in certs[:3])

    decisions = storage.list_promotion_decisions(run_id="run-growth-1", limit=20)
    assert len(decisions) >= 3
    assert all(item.verdict in {"promote", "reject"} for item in decisions[:3])

    memories = storage.retrieve_memory_records(run_id="run-growth-1", limit=100)
    scales = {item.scale for item in memories}
    assert "micro" in scales
    assert "meso" in scales
    assert "macro" in scales
    # B24: acá había `assert all(item.no_interference for item in memories)`, que
    # trataba un campo NO COMPUTADO como si fuera evidencia de no-interferencia.
    # Ese `True` es el default de schema (columna NOT NULL), no una medición: no
    # hay lógica que lo calcule ni consumidor que lo lea. Afirmar sobre él no
    # verifica NADA de la memoria. Ver tests/regression/test_no_interference_declared_uncomputed.py

    # Solo para evitar variables sin uso en asserts y dejar trazabilidad.
    assert isinstance(third["certification"]["certificate_id"], str)
    assert third["certification"]["certificate_id"]
    storage.close()


def test_promotion_gate_rejects_corrupted_episode(tmp_path: Path):
    storage = _storage(tmp_path)
    runner = MinimalCognitiveEpisodeRunner(storage=storage, run_id="run-growth-reject")
    result = runner.run_episode(external_heat=0.05)

    corrupted = {
        **result,
        "episode": {**result["episode"]},
    }
    corrupted["episode"]["episode_id"] = "episode-corrupted"
    corrupted["episode"]["trace"] = []
    corrupted["episode"]["context"]["formula"] = ""

    gate = PromotionGate(storage=storage)
    out = gate.process_episode(run_id="run-growth-reject", episode_result=corrupted)
    assert out["decision"].verdict == "reject"
    assert out["certificate"].promotion_candidate is False
    storage.close()
