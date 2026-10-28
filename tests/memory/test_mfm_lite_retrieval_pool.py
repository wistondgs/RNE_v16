"""B28: el pool de candidatos se separa del top-k devuelto.

Antes el pool era `max(20, limit*4)` sobre un storage que ordena por created_at DESC,
o sea: los N MAS RECIENTES. Una memoria vieja con mejor overlap nunca entraba al
scoring — la recencia decidia antes que la relevancia.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.memory.mfm_lite.retrieval import (
    _DEFAULT_CANDIDATE_POOL_SIZE,
    _resolve_candidate_pool_size,
    MemoryRetrieval,
)
from runtime.storage import StorageConfig, StorageFactory

QUERY = {"proposition": "TEMP_HIGH", "alarm": True}


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "pool.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def _seed_old_gem_then_recent_noise(storage, run_id: str, *, noise: int = 25) -> None:
    """Primero la memoria VIEJA y buena; despues N recientes e irrelevantes."""
    storage.write_memory_record(
        run_id=run_id,
        episode_id="episode-old",
        scale="micro",
        # Overlap perfecto con la query.
        structure_json={"proposition": "TEMP_HIGH", "alarm": True},
        metadata={"scenario_name": "thermal_homeostasis"},
        memory_id="mem-old-gem",
    )
    for i in range(noise):
        storage.write_memory_record(
            run_id=run_id,
            episode_id=f"episode-noise-{i}",
            scale="micro",
            # Overlap nulo con la query.
            structure_json={"proposition": f"UNRELATED_{i}", "alarm": False},
            metadata={"scenario_name": "thermal_homeostasis"},
            memory_id=f"mem-noise-{i}",
        )


class TestCandidatePoolSizing:
    def test_pool_defaults_and_never_below_limit(self):
        assert _resolve_candidate_pool_size(limit=5, override=None) == (
            _DEFAULT_CANDIDATE_POOL_SIZE
        )
        # El top-k jamas puede exceder el pool.
        assert _resolve_candidate_pool_size(limit=500, override=None) == 500
        assert _resolve_candidate_pool_size(limit=10, override=3) == 10
        assert _resolve_candidate_pool_size(limit=2, override=50) == 50

    def test_pool_size_env_override(self, monkeypatch):
        monkeypatch.setenv("RNFE_MEMORY_CANDIDATE_POOL", "42")
        assert _resolve_candidate_pool_size(limit=5, override=None) == 42

    def test_pool_size_env_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RNFE_MEMORY_CANDIDATE_POOL", "no-soy-un-int")
        assert _resolve_candidate_pool_size(limit=5, override=None) == (
            _DEFAULT_CANDIDATE_POOL_SIZE
        )


class TestOldMemoryWithBetterOverlapCompetes:
    def test_old_better_memory_is_retrieved(self, tmp_path: Path):
        """EL TEST DE B28: la memoria vieja y mejor DEBE ser recuperada."""
        storage = _storage(tmp_path)
        run_id = "run-pool-old-gem"
        # 25 ruidos recientes > el viejo pool de 20: con el bug, mem-old-gem ni siquiera
        # llegaba al scoring.
        _seed_old_gem_then_recent_noise(storage, run_id, noise=25)

        retrieval = MemoryRetrieval(storage=storage)
        hits = retrieval.retrieve(
            run_id=run_id,
            query=QUERY,
            limit=3,
            scenario_name="thermal_homeostasis",
            scenario_filter_mode="strict_same_scenario",
        )

        ids = [hit["memory_id"] for hit in hits]
        assert "mem-old-gem" in ids, (
            "la memoria vieja con mejor overlap no entro al ranking: "
            f"la recencia sigue decidiendo antes que la relevancia ({ids})"
        )
        # Y no solo entra: gana.
        assert ids[0] == "mem-old-gem"
        assert hits[0]["score"] > 0.0
        storage.close()

    def test_topk_is_respected_even_with_wide_pool(self, tmp_path: Path):
        storage = _storage(tmp_path)
        run_id = "run-pool-topk"
        _seed_old_gem_then_recent_noise(storage, run_id, noise=25)

        retrieval = MemoryRetrieval(storage=storage)
        hits = retrieval.retrieve(run_id=run_id, query=QUERY, limit=3)
        # Pool amplio (se puntuan 26), pero se devuelven 3.
        assert len(hits) == 3
        metrics = hits[0]["retrieval_metrics"]
        assert metrics["candidate_pool_scored"] == 26
        assert metrics["candidate_pool_size"] == _DEFAULT_CANDIDATE_POOL_SIZE
        storage.close()

    def test_narrow_pool_reproduces_recency_bias(self, tmp_path: Path):
        """Documenta el trade-off: pool chico => vuelve a mandar la recencia."""
        storage = _storage(tmp_path)
        run_id = "run-pool-narrow"
        _seed_old_gem_then_recent_noise(storage, run_id, noise=25)

        retrieval = MemoryRetrieval(storage=storage)
        hits = retrieval.retrieve(
            run_id=run_id,
            query=QUERY,
            limit=3,
            candidate_pool_size=5,  # solo los 5 mas recientes compiten
        )
        ids = [hit["memory_id"] for hit in hits]
        assert "mem-old-gem" not in ids
        # El pool saturado es observable (pool_scored == pool_size).
        metrics = hits[0]["retrieval_metrics"]
        assert metrics["candidate_pool_scored"] == metrics["candidate_pool_size"] == 5
        storage.close()

    def test_scoring_ranks_all_candidates_not_just_recent(self, tmp_path: Path):
        """Con pool amplio, el orden del resultado es por SCORE, no por created_at."""
        storage = _storage(tmp_path)
        run_id = "run-pool-rank"
        # vieja=perfecta, media=parcial, recientes=nulas
        storage.write_memory_record(
            run_id=run_id,
            episode_id="e-perfect",
            scale="micro",
            structure_json={"proposition": "TEMP_HIGH", "alarm": True},
            metadata={"scenario_name": "thermal_homeostasis"},
            memory_id="mem-perfect",
        )
        storage.write_memory_record(
            run_id=run_id,
            episode_id="e-partial",
            scale="micro",
            structure_json={"proposition": "TEMP_HIGH", "alarm": False},
            metadata={"scenario_name": "thermal_homeostasis"},
            memory_id="mem-partial",
        )
        for i in range(22):
            storage.write_memory_record(
                run_id=run_id,
                episode_id=f"e-none-{i}",
                scale="micro",
                structure_json={"proposition": f"NOPE_{i}", "alarm": False},
                metadata={"scenario_name": "thermal_homeostasis"},
                memory_id=f"mem-none-{i}",
            )

        retrieval = MemoryRetrieval(storage=storage)
        hits = retrieval.retrieve(run_id=run_id, query=QUERY, limit=2)
        assert [hit["memory_id"] for hit in hits] == ["mem-perfect", "mem-partial"]
        assert hits[0]["score"] > hits[1]["score"]
        storage.close()

    def test_ttl_filter_still_applies_before_limit(self, tmp_path: Path):
        """P6: las memorias expiradas no consumen presupuesto de pool. No se deshace.

        La expirada es MAS RECIENTE que la viva, y el pool es de 1: si el TTL se
        aplicara DESPUES del limit, la expirada se comeria el unico slot del pool y el
        resultado seria vacio. Se aplica en el WHERE (antes del LIMIT), asi que la viva
        entra igual.
        """
        now = datetime.now(timezone.utc)
        storage = _storage(tmp_path)
        run_id = "run-pool-ttl"
        # Viva pero vieja (sin ttl): created_at hace 1h.
        storage.write_memory_record(
            run_id=run_id,
            episode_id="e-live",
            scale="micro",
            structure_json={"proposition": "TEMP_HIGH", "alarm": True},
            metadata={"scenario_name": "thermal_homeostasis"},
            memory_id="mem-live",
            ttl_seconds=None,
            created_at=(now - timedelta(hours=1)).isoformat(),
        )
        # Expirada pero MAS RECIENTE: edad 60s > ttl 10s.
        storage.write_memory_record(
            run_id=run_id,
            episode_id="e-expired",
            scale="micro",
            structure_json={"proposition": "TEMP_HIGH", "alarm": True},
            metadata={"scenario_name": "thermal_homeostasis"},
            memory_id="mem-expired",
            ttl_seconds=10,
            created_at=(now - timedelta(seconds=60)).isoformat(),
        )

        retrieval = MemoryRetrieval(storage=storage)
        hits = retrieval.retrieve(
            run_id=run_id, query=QUERY, limit=1, candidate_pool_size=1
        )
        ids = [hit["memory_id"] for hit in hits]
        assert "mem-expired" not in ids
        assert ids == ["mem-live"]
        storage.close()
