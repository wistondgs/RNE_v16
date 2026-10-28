import json
from dataclasses import fields
from pathlib import Path

from runtime.storage import contract_validation as cv
from runtime.storage.records import EpisodeCertificateRecord, TelemetrySnapshotRecord


CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


CONTRACT_FILES = [
    "episode.schema.json",
    "proposal.schema.json",
    "certificate.schema.json",
    "rollback.schema.json",
    "telemetry_snapshot.schema.json",
    "event.schema.json",
    "tool_request.schema.json",
    "tool_result.schema.json",
    "session_bridge.schema.json",
    "reasoning_trace.schema.json",
    "artifact_index.schema.json",
    "reality_assessment.schema.json",
    "memory_record.schema.json",
    "eml_candidate.schema.json",
    "eml_run.schema.json",
    # B19: los dos msrc_* existian en contracts/ pero no estaban cubiertos por el test.
    "msrc_scale_decision.schema.json",
    "msrc_transition_event.schema.json",
]

#: B19: dialecto unico para todos los contratos. Los msrc_* venian en draft-07 mientras
#: el resto usaba 2020-12; se unificaron a 2020-12.
CONTRACT_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: B19: red de seguridad de B17. Los contratos activos respaldados por una dataclass de
#: records.py: cada campo `required` del schema TIENE que existir en el record, si no el
#: enforcement estricto rechazaria a un writer legitimo.
#:
#: Los otros tres contratos activos (episode, proposal, rollback) no tienen dataclass: se
#: persisten como payload de evento. Su correspondencia la cubre EVENT_CONTRACTS + los
#: tests de forma en tests/contracts/test_active_contract_payloads.py.
RECORD_BACKED_ACTIVE_CONTRACTS = {
    "certificate": EpisodeCertificateRecord,
    "telemetry_snapshot": TelemetrySnapshotRecord,
}


def _load(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))


def test_contract_schemas_exist_and_parse():
    for name in CONTRACT_FILES:
        path = CONTRACTS_DIR / name
        assert path.exists(), f"Missing contract schema: {name}"
        payload = _load(name)
        assert payload["type"] == "object"
        assert "required" in payload and payload["required"], f"{name} must define required fields"


def test_contract_files_cover_every_schema_on_disk():
    """Que no vuelva a haber un schema en contracts/ sin cobertura (era el caso de msrc_*)."""
    on_disk = {path.name for path in CONTRACTS_DIR.glob("*.schema.json")}
    assert on_disk == set(CONTRACT_FILES)


def test_all_contracts_share_the_same_dialect():
    for name in CONTRACT_FILES:
        assert _load(name).get("$schema") == CONTRACT_DIALECT, (
            f"{name} usa un dialecto distinto al del resto de los contratos"
        )


def test_active_contracts_match_canon_13():
    """CANON 13 exige contrato activo para exactamente estos cinco."""
    assert cv.ACTIVE_CONTRACTS == {
        "episode",
        "proposal",
        "certificate",
        "rollback",
        "telemetry_snapshot",
    }
    for contract in cv.ACTIVE_CONTRACTS:
        assert f"{contract}.schema.json" in CONTRACT_FILES


def test_every_active_contract_has_a_wired_write_path():
    """B17: 'activo' = enganchado a un camino de escritura, no solo un archivo JSON."""
    wired = set(cv.EVENT_CONTRACTS.values()) | set(RECORD_BACKED_ACTIVE_CONTRACTS)
    assert wired == set(cv.ACTIVE_CONTRACTS)


def test_required_fields_of_record_backed_contracts_exist_in_the_dataclass():
    """Red de seguridad de B17: el schema no puede pedir un campo que el record no tiene."""
    for contract, record_cls in RECORD_BACKED_ACTIVE_CONTRACTS.items():
        schema = _load(f"{contract}.schema.json")
        record_fields = {f.name for f in fields(record_cls)}
        missing = [f for f in schema["required"] if f not in record_fields]
        assert not missing, (
            f"{contract}.schema.json exige campos que {record_cls.__name__} no tiene: "
            f"{missing}. El enforcement estricto de B17 rechazaria a un writer legitimo."
        )


#: B20: schemas sin productor ni consumidor en el runtime actual. NO son huerfanos a
#: borrar: son la superficie de contrato de la capa adaptadora que exige
#: governance/adr/ADR_OPENCLAW_ACOPLAMIENTO.md (seccion 6), igual que session_bridge (B23).
#: Retirar un schema de contrato es decision de producto/canon, no de refactor.
RESERVED_CONTRACTS_WITHOUT_PRODUCER = ("tool_request", "tool_result")


def test_reserved_contracts_are_not_active_contracts():
    """B20: reservados != activos. No se validan on-write (no estan entre los 5 de CANON 13)."""
    for contract in RESERVED_CONTRACTS_WITHOUT_PRODUCER:
        assert contract not in cv.ACTIVE_CONTRACTS
        assert contract not in cv.EVENT_CONTRACTS.values()


def test_reserved_contracts_survive_and_declare_their_status():
    """B20: no borrar. El schema se queda y dice por que no tiene productor."""
    for contract in RESERVED_CONTRACTS_WITHOUT_PRODUCER:
        schema = _load(f"{contract}.schema.json")
        assert "RESERVADA" in schema.get("description", ""), (
            f"{contract}.schema.json debe declarar su status de capacidad reservada (B20)"
        )
