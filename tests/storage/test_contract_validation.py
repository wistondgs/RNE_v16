"""B17 — validación on-write del contrato activo mínimo (CANON §13).

Cubre tres cosas distintas y hay que mantenerlas separadas:

1. el validador **valida de verdad** (rechaza required faltante, tipo malo, enum malo);
2. el **enforcement** es estricto por default y degradable a warn/off;
3. los **writers vivos** de los 5 contratos activos producen payloads conformes (o sea:
   activar el enforcement no rompe el runtime existente).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from runtime.storage import ContractViolationError, StorageConfig, StorageFactory
from runtime.storage import contract_validation as cv


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Cada test arranca sin override de enforcement (o sea: estricto por default)."""
    monkeypatch.delenv(cv.ENV_VAR, raising=False)


@pytest.fixture
def storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "contract_validation.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    facade = StorageFactory.create_facade(config)
    yield facade
    facade.close()


def _certificate_kwargs(**overrides):
    base = dict(
        episode_id="ep-1",
        run_id="run-1",
        trace_id="trace-1",
        smg_artifacts={"observations": 1},
        lotf_artifacts={"formula": "f"},
        world_artifacts={"updated_world": {}},
        continuity_score=0.9,
        ioc_proxy=0.8,
        risk_score=0.1,
        verdict="certified",
        rollback_ready=True,
        promotion_candidate=True,
    )
    base.update(overrides)
    return base


# ───────────────────────── 1. el validador valida de verdad ─────────────────────────


def test_active_contracts_are_exactly_the_five_of_canon_13():
    assert cv.ACTIVE_CONTRACTS == {
        "episode",
        "proposal",
        "certificate",
        "rollback",
        "telemetry_snapshot",
    }


def test_every_active_contract_schema_loads():
    for contract in cv.ACTIVE_CONTRACTS:
        schema = cv.load_schema(contract)
        assert schema["type"] == "object"
        assert schema["required"]


def test_validator_rejects_missing_required_field():
    violations = cv.validate_payload("rollback", {"rollback_id": "r-1"})
    assert violations
    joined = " ".join(violations)
    for missing in ("target", "reason", "timestamp"):
        assert missing in joined


def test_validator_rejects_wrong_type():
    violations = cv.validate_payload(
        "episode",
        {
            "episode_id": "ep-1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "context": "no-soy-un-objeto",  # debe ser object
            "result": {},
        },
    )
    assert any("context" in v for v in violations)


def test_validator_rejects_non_mapping_payload():
    assert cv.validate_payload("episode", ["no", "soy", "objeto"])


def test_validator_does_not_confuse_bool_with_number():
    """Trampa de Python: bool es subclase de int; JSON Schema los distingue."""
    violations = cv.validate_payload(
        "certificate",
        _certificate_payload(continuity_score=True),
    )
    assert any("continuity_score" in v for v in violations)


def _certificate_payload(**overrides):
    payload = {
        "certificate_id": "cert-1",
        "episode_id": "ep-1",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "smg_artifacts": {},
        "lotf_artifacts": {},
        "world_artifacts": {},
        "continuity_score": 0.9,
        "ioc_proxy": 0.8,
        "risk_score": 0.1,
        "verdict": "certified",
        "rollback_ready": True,
        "promotion_candidate": True,
    }
    payload.update(overrides)
    return payload


def test_validator_accepts_conformant_payload():
    assert cv.validate_payload("certificate", _certificate_payload()) == []


def test_validator_enforces_enum(monkeypatch):
    """Ninguno de los 5 schemas usa `enum` hoy; se valida la capacidad igual."""
    monkeypatch.setattr(
        cv,
        "load_schema",
        lambda contract: {
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string", "enum": ["promote", "reject"]}},
        },
    )
    assert cv.validate_payload("fake", {"verdict": "promote"}) == []
    violations = cv.validate_payload("fake", {"verdict": "maybe"})
    assert any("enum" in v for v in violations)


# ───────────────────────── 2. enforcement: strict / warn / off ─────────────────────────


def test_enforcement_is_strict_by_default():
    assert cv.get_mode() == "strict"


def test_strict_raises_and_does_not_persist(storage):
    with pytest.raises(ContractViolationError) as excinfo:
        storage.append_event(
            event_type="life.rollback.restored_checkpoint",
            run_id="run-1",
            payload={"checkpoint_artifact_id": "a-1"},  # forma pre-B18
        )
    assert excinfo.value.contract == "rollback"
    assert "rollback_id" in str(excinfo.value)

    events = storage.list_events(run_id="run-1", limit=10)
    assert not [e for e in events if e.event_type == "life.rollback.restored_checkpoint"]


def test_warn_mode_logs_and_persists(storage, monkeypatch, caplog):
    monkeypatch.setenv(cv.ENV_VAR, "warn")
    with caplog.at_level(logging.WARNING, logger="rnfe.contracts"):
        storage.append_event(
            event_type="life.rollback.restored_checkpoint",
            run_id="run-warn",
            payload={"checkpoint_artifact_id": "a-1"},
        )
    assert "rollback" in caplog.text
    events = storage.list_events(run_id="run-warn", limit=10)
    assert [e for e in events if e.event_type == "life.rollback.restored_checkpoint"]


def test_off_mode_skips_validation(storage, monkeypatch):
    monkeypatch.setenv(cv.ENV_VAR, "off")
    storage.append_event(
        event_type="life.rollback.restored_checkpoint",
        run_id="run-off",
        payload={"checkpoint_artifact_id": "a-1"},
    )
    events = storage.list_events(run_id="run-off", limit=10)
    assert [e for e in events if e.event_type == "life.rollback.restored_checkpoint"]


def test_unknown_mode_falls_back_to_strict(monkeypatch):
    monkeypatch.setenv(cv.ENV_VAR, "banana")
    assert cv.get_mode() == "strict"


def test_strict_rejects_bad_certificate(storage):
    with pytest.raises(ContractViolationError) as excinfo:
        storage.write_episode_certificate(**_certificate_kwargs(verdict=123))
    assert excinfo.value.contract == "certificate"
    assert not storage.list_episode_certificates(run_id="run-1")


def test_strict_rejects_bad_telemetry_snapshot(storage):
    with pytest.raises(ContractViolationError) as excinfo:
        storage.write_telemetry_snapshot(
            snapshot_id=123,  # debe ser string
            run_id="run-1",
            metrics={"latency_ms": 1.0},
        )
    assert excinfo.value.contract == "telemetry_snapshot"
    assert not storage.list_telemetry_snapshots(run_id="run-1")


# ───────────────── 3. los writers vivos de los 5 contratos conforman ─────────────────


def test_live_telemetry_writer_conforms(storage):
    snapshot = storage.write_telemetry_snapshot(run_id="run-1", metrics={"latency_ms": 7.5})
    assert snapshot.snapshot_id


def test_live_certificate_writer_conforms(storage):
    certificate = storage.write_episode_certificate(**_certificate_kwargs())
    assert certificate.certificate_id


def test_live_episode_event_conforms(storage):
    """Forma que emiten scenario_runner.py y min_cognitive_episode.py."""
    storage.append_event(
        event_type="episode.closed",
        run_id="run-1",
        payload={
            "episode_id": "ep-1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "closure_profile": "baseline_fixed",
            "context": {"observation": {}},
            "result": {"updated_world": {}},
            "trace": [],
        },
    )
    assert storage.list_events(run_id="run-1", event_types=["episode.closed"], limit=5)


def test_live_proposal_event_conforms(storage):
    """Forma que emite promotion_gate.py."""
    storage.append_event(
        event_type="proposal.evaluated",
        run_id="run-1",
        payload={
            "proposal_id": "proposal-1",
            "origin": "promotion_gate",
            "change": {"episode_id": "ep-1", "run_id": "run-1"},
            "risk": "low",
            "metadata": {"ioc_proxy": 0.8},
        },
    )
    assert storage.list_events(run_id="run-1", event_types=["proposal.evaluated"], limit=5)


def test_live_rollback_event_conforms(storage):
    """Forma que emite kernel.py DESPUES de B18."""
    storage.append_event(
        event_type="life.rollback.restored_checkpoint",
        run_id="run-1",
        payload={
            "rollback_id": "rollback-1",
            "target": "artifact-1",
            "reason": "restore_latest_healthy_checkpoint",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "artifacts": ["artifact-1"],
            "checkpoint_artifact_id": "artifact-1",
        },
    )
    assert storage.list_events(
        run_id="run-1", event_types=["life.rollback.restored_checkpoint"], limit=5
    )


def test_non_active_event_types_are_not_validated(storage):
    """El ledger es genérico: CANON §13 sólo exige contrato para los 5 activos."""
    storage.append_event(
        event_type="smg.sign_created",
        run_id="run-1",
        payload={"cualquier": "cosa"},
    )
    assert storage.list_events(run_id="run-1", event_types=["smg.sign_created"], limit=5)


# --------------------------------------------------------------------------- #
# TRIPWIRE (B60): el mapa EVENT_CONTRACTS está deliberadamente INCOMPLETO.
# --------------------------------------------------------------------------- #


def test_nonconforming_writers_are_not_mapped_as_active_contracts() -> None:
    """No "completes" EVENT_CONTRACTS: hay writers de rollback/propuesta que NO conforman.

    El contrato de rollback se hace cumplir hoy en 1 de 4 caminos de rollback vivos. Los
    otros 3 (más un segundo writer de propuesta) emiten payloads que NO cumplen su schema.
    Mapearlos en ``EVENT_CONTRACTS`` sin arreglar ANTES su payload los haría levantar
    ``ContractViolationError`` bajo el modo ``strict`` (el default).

    El caso grave es ``life.rollback`` (``runtime/life/kernel.py:677``): su ``append_event``
    **no está envuelto en try/except**, así que mapearlo **mata al organismo justo en la
    decisión de rollback** — el camino de refugio que más se necesita.

    Si este test falla: NO saques la entrada del set para "arreglarlo". Arreglá primero el
    payload del writer para que cumpla su schema (ese trabajo es B60), y recién entonces
    mapealo en ``EVENT_CONTRACTS`` y sacalo de ``NONCONFORMING_EVENT_TYPES``.
    """
    colisiones = cv.NONCONFORMING_EVENT_TYPES & set(cv.EVENT_CONTRACTS)
    assert not colisiones, (
        f"event_type(s) {sorted(colisiones)} fueron mapeados como contrato activo, pero su "
        "writer NO produce un payload conforme: bajo RNFE_CONTRACT_VALIDATION=strict van a "
        "levantar ContractViolationError. Hay que arreglar el payload del writer primero (B60). "
        "Caso crítico: 'life.rollback' (runtime/life/kernel.py:677) no tiene try/except -> "
        "mapearlo mata al organismo en la decisión de rollback."
    )


def test_nonconforming_event_types_are_documented_and_nonempty() -> None:
    # El set es la documentación ejecutable de la deuda B60: si alguien hace conformar a un
    # writer y lo mapea, debe sacarlo de acá (y este test lo obliga a mantenerlo coherente).
    assert cv.NONCONFORMING_EVENT_TYPES, "el set no debe vaciarse sin cerrar B60"
    assert "life.rollback" in cv.NONCONFORMING_EVENT_TYPES
