"""B30: penalty_cross_version = 0.8, DISTINTA de la penalizacion cross-scenario.

Fuente normativa: canon/normative/MEMORY_COMPATIBILITY_POLICY_v1.md
  - §5.1 strict: "si scenario_name != query.scenario_name -> descartar"  (solo por NOMBRE)
  - §5.2 analogical: score * penalty_cross_scenario
  - §5   valores: penalty_cross_scenario = 0.5 / penalty_cross_version = 0.8
  - §2.1 strict = mismo scenario_name "y preferiblemente misma scenario_version"
  - §6   contaminacion = memoria "de otro escenario"

Antes, mismo-escenario-otra-version se degradaba al bucket cross-scenario: en modo
estricto se DESCARTABA. Ahora se conserva penalizada 0.8. Otro escenario en modo
estricto se sigue descartando: eso NO cambia.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.memory.mfm_lite.retrieval import (
    _CROSS_SCENARIO_PENALTY,
    _CROSS_VERSION_PENALTY,
    MemoryRetrieval,
)
from runtime.storage import StorageConfig, StorageFactory

QUERY = {"proposition": "TEMP_HIGH", "alarm": True}
STRUCTURE = {"proposition": "TEMP_HIGH", "alarm": True}


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "xversion.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def _seed(storage, run_id: str) -> None:
    """Tres memorias con overlap IDENTICO: solo difieren en identidad de escenario."""
    # (1) mismo escenario, misma version
    storage.write_memory_record(
        run_id=run_id,
        episode_id="ep-same",
        scale="micro",
        structure_json=dict(STRUCTURE),
        metadata={
            "scenario_metadata": {
                "scenario_name": "thermal_homeostasis",
                "scenario_version": "1.0",
            }
        },
        memory_id="mem-same-version",
    )
    # (2) MISMO escenario, OTRA version -> candidato valido penalizado (B30)
    storage.write_memory_record(
        run_id=run_id,
        episode_id="ep-oldver",
        scale="micro",
        structure_json=dict(STRUCTURE),
        metadata={
            "scenario_metadata": {
                "scenario_name": "thermal_homeostasis",
                "scenario_version": "0.9",
            }
        },
        memory_id="mem-other-version",
    )
    # (3) OTRO escenario -> contaminacion: se descarta en estricto
    storage.write_memory_record(
        run_id=run_id,
        episode_id="ep-other",
        scale="micro",
        structure_json=dict(STRUCTURE),
        metadata={
            "scenario_metadata": {
                "scenario_name": "resource_management",
                "scenario_version": "1.0",
            }
        },
        memory_id="mem-other-scenario",
    )


def _by_id(hits):
    return {hit["memory_id"]: hit for hit in hits}


class TestCanonValues:
    def test_penalties_match_canon(self):
        assert _CROSS_VERSION_PENALTY == 0.8
        assert _CROSS_SCENARIO_PENALTY == 0.5
        # Y la de version es ESTRICTAMENTE mas suave que la de escenario.
        assert _CROSS_VERSION_PENALTY > _CROSS_SCENARIO_PENALTY


class TestVersionAbsent:
    def test_memory_without_version_is_kept_and_penalized(self, tmp_path: Path):
        """Versión AUSENTE en la memoria + query CON versión: se conserva penalizada 0.8.

        Caso que P8 cambió sin cubrir con test: en la base, una memoria sin
        `scenario_version` caía al bucket cross-scenario y se **descartaba** en estricto;
        ahora sobrevive penalizada. Es coherente con el canon §5.1 (el descarte estricto es
        SOLO por `scenario_name`), pero "versión desconocida" no es lo mismo que "otra
        versión": el canon §3 declara `scenario_version` metadata **obligatoria**, así que una
        memoria sin ella está malformada (calidad de metadata: B71).

        Este test FIJA la semántica elegida —conservar + penalizar + marcar como
        cross_version— para que cualquier cambio futuro sea deliberado y no accidental.
        """
        storage = _storage(tmp_path)
        run_id = "run-xv-noversion"
        # Mismo overlap que las de _seed, pero SIN scenario_version en la metadata.
        storage.write_memory_record(
            run_id=run_id,
            episode_id="ep-nover",
            scale="micro",
            structure_json=dict(STRUCTURE),
            metadata={"scenario_metadata": {"scenario_name": "thermal_homeostasis"}},
            memory_id="mem-no-version",
        )
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="strict_same_scenario",
        )
        found = _by_id(hits)

        # Mismo scenario_name -> el canon NO manda descartarla.
        assert "mem-no-version" in found
        # Se trata como cross-version, NO como cross-scenario ni como procedencia analógica.
        assert found["mem-no-version"]["cross_version_source"] is True
        assert found["mem-no-version"].get("analogical_source") is not True
        same = found["mem-same-version"]["score"]
        assert found["mem-no-version"]["score"] == pytest.approx(same * _CROSS_VERSION_PENALTY)
        storage.close()


class TestStrictMode:
    def test_same_scenario_other_version_is_kept_and_penalized(self, tmp_path: Path):
        """EL TEST DE B30: no se descarta, no es cross-scenario, score x0.8."""
        storage = _storage(tmp_path)
        run_id = "run-xv-strict"
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="strict_same_scenario",
        )
        found = _by_id(hits)

        # 1) Se CONSERVA (antes: descartada por caer al bucket cross-scenario).
        assert "mem-other-version" in found
        # 2) NO se marca como procedencia analogica (no vino de otro escenario).
        assert found["mem-other-version"].get("analogical_source") is not True
        assert found["mem-other-version"]["cross_version_source"] is True
        # 3) Score exactamente x0.8 respecto de la memoria de misma version
        #    (overlap identico), ni x0.5 (cross-scenario) ni descartada.
        same = found["mem-same-version"]["score"]
        other_ver = found["mem-other-version"]["score"]
        assert other_ver == pytest.approx(same * _CROSS_VERSION_PENALTY)
        assert other_ver != pytest.approx(same * _CROSS_SCENARIO_PENALTY)
        # 4) Y la de misma version sigue ganando el ranking.
        assert hits[0]["memory_id"] == "mem-same-version"
        storage.close()

    def test_other_scenario_still_discarded(self, tmp_path: Path):
        """NO se afloja el estricto: otro escenario se sigue descartando."""
        storage = _storage(tmp_path)
        run_id = "run-xv-strict-discard"
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="strict_same_scenario",
        )
        ids = set(_by_id(hits))
        assert "mem-other-scenario" not in ids
        assert ids == {"mem-same-version", "mem-other-version"}

        metrics = hits[0]["retrieval_metrics"]
        assert metrics["filtered_cross_scenario_count"] == 1
        assert metrics["retrieved_cross_scenario_count"] == 0
        # El eje version se reporta SEPARADO del eje escenario.
        assert metrics["retrieved_cross_version_count"] == 1
        assert metrics["cross_version_penalty_applied"] is True
        assert metrics["cross_scenario_penalty_applied"] is False
        storage.close()

    def test_cross_version_is_not_pollution(self, tmp_path: Path):
        """La atestacion no reporta contaminacion por mezcla de versiones."""
        storage = _storage(tmp_path)
        run_id = "run-xv-attestation"
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="strict_same_scenario",
        )
        att = hits[0]["rag_attestation"]
        # No es strict_policy_violation: canon §5.1 descarta por NOMBRE, no por version.
        assert att["validation_status"] == "pass"
        assert att["degradation_level"] == "cross_version_penalized"
        assert att["returned_cross_scenario_count"] == 0
        assert att["returned_cross_version_count"] == 1
        # Purity 1.0: cross-version NO es contaminacion (canon §6).
        assert att["retrieval_purity"] == 1.0
        storage.close()

    def test_no_version_in_query_means_no_version_penalty(self, tmp_path: Path):
        """Sin scenario_version en la query, el eje version no se evalua (back-compat)."""
        storage = _storage(tmp_path)
        run_id = "run-xv-noversion"
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_filter_mode="strict_same_scenario",
        )
        found = _by_id(hits)
        assert set(found) == {"mem-same-version", "mem-other-version"}
        assert found["mem-same-version"]["score"] == pytest.approx(
            found["mem-other-version"]["score"]
        )
        metrics = hits[0]["retrieval_metrics"]
        assert metrics["cross_version_penalty_applied"] is False
        assert metrics["retrieved_cross_version_count"] == 0
        storage.close()


class TestAnalogicalMode:
    def test_cross_version_softer_than_cross_scenario(self, tmp_path: Path):
        """Las dos penalizaciones coexisten y son distintas: 0.8 vs 0.5."""
        storage = _storage(tmp_path)
        run_id = "run-xv-analog"
        _seed(storage, run_id)

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="analogical",
        )
        found = _by_id(hits)
        assert set(found) == {
            "mem-same-version",
            "mem-other-version",
            "mem-other-scenario",
        }

        base = found["mem-same-version"]["score"]
        assert found["mem-other-version"]["score"] == pytest.approx(
            base * _CROSS_VERSION_PENALTY
        )
        assert found["mem-other-scenario"]["score"] == pytest.approx(
            base * _CROSS_SCENARIO_PENALTY
        )
        # Orden: misma version > otra version > otro escenario.
        assert [hit["memory_id"] for hit in hits] == [
            "mem-same-version",
            "mem-other-version",
            "mem-other-scenario",
        ]
        # Solo la de otro ESCENARIO es procedencia analogica.
        assert found["mem-other-scenario"]["analogical_source"] is True
        assert found["mem-other-version"].get("analogical_source") is not True
        storage.close()

    def test_other_scenario_other_version_is_only_cross_scenario(self, tmp_path: Path):
        """Nombre distinto: la version es irrelevante, penaliza 0.5 (no 0.5*0.8)."""
        storage = _storage(tmp_path)
        run_id = "run-xv-both"
        storage.write_memory_record(
            run_id=run_id,
            episode_id="ep-base",
            scale="micro",
            structure_json=dict(STRUCTURE),
            metadata={
                "scenario_metadata": {
                    "scenario_name": "thermal_homeostasis",
                    "scenario_version": "1.0",
                }
            },
            memory_id="mem-base",
        )
        storage.write_memory_record(
            run_id=run_id,
            episode_id="ep-far",
            scale="micro",
            structure_json=dict(STRUCTURE),
            metadata={
                "scenario_metadata": {
                    "scenario_name": "resource_management",
                    "scenario_version": "0.7",
                }
            },
            memory_id="mem-far",
        )

        hits = MemoryRetrieval(storage=storage).retrieve(
            run_id=run_id,
            query=QUERY,
            limit=10,
            scenario_name="thermal_homeostasis",
            scenario_version="1.0",
            scenario_filter_mode="analogical",
        )
        found = _by_id(hits)
        base = found["mem-base"]["score"]
        assert found["mem-far"]["score"] == pytest.approx(base * _CROSS_SCENARIO_PENALTY)
        assert found["mem-far"].get("cross_version_source") is not True
        storage.close()
