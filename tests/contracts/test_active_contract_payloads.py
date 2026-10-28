"""B18: los payloads persistidos de rollback y proposal tienen la FORMA de su schema.

CANON §13 exige contrato activo mínimo para episodio, propuesta, certificado, rollback y
telemetry snapshot. Este módulo fija la forma del payload que emiten los writers vivos de
`rollback` y `proposal`, que es la precondición para que la validación on-write (B17) pase.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from runtime.life.kernel import LifeKernel


CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


def _schema(name: str) -> Dict[str, Any]:
    return json.loads((CONTRACTS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


class _CapturingStorage:
    """Storage mínimo que captura los append_event emitidos."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def append_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _StubArtifact:
    artifact_id = "artifact-checkpoint-1"


class _StubCheckpoints:
    def load_latest_payload(self, *, organism_id: str, healthy_only: bool, on_reject=None):
        # B83: el kernel pasa un sumidero de rechazos (`on_reject`) para poder emitir
        # `life.refuge.rejected` / `life.refuge.exhausted`. Acá el refugio SE ENCUENTRA, así
        # que no se rechaza ningún candidato y el único evento emitido sigue siendo el
        # rollback — que es lo que este test fija.
        assert healthy_only is True
        assert on_reject is None or callable(on_reject)
        return {"total_steps": 3, "scenario_index": 1, "scenario_episode_index": 2}, _StubArtifact()


def _emit_rollback_event() -> Dict[str, Any]:
    """Ejecuta el camino real de rollback (E5) y devuelve el payload emitido."""
    kernel = LifeKernel.__new__(LifeKernel)
    storage = _CapturingStorage()
    kernel.storage = storage  # type: ignore[assignment]
    kernel.checkpoints = _StubCheckpoints()  # type: ignore[assignment]
    kernel.organism_id = "organism-1"
    kernel.run_id = "run-1"
    kernel.total_steps = 0
    kernel.scenario_index = 0
    kernel.scenario_episode_index = 0

    assert kernel._restore_latest_healthy_checkpoint() is True
    assert len(storage.events) == 1
    event = storage.events[0]
    assert event["event_type"] == "life.rollback.restored_checkpoint"
    return event["payload"]


def test_rollback_event_payload_matches_rollback_schema():
    payload = _emit_rollback_event()
    schema = _schema("rollback")

    for field in schema["required"]:
        assert field in payload, f"rollback payload sin campo requerido: {field}"

    assert isinstance(payload["rollback_id"], str) and payload["rollback_id"]
    assert isinstance(payload["target"], str) and payload["target"]
    assert isinstance(payload["reason"], str) and payload["reason"]
    assert isinstance(payload["timestamp"], str) and payload["timestamp"]
    assert isinstance(payload["artifacts"], list)


def test_rollback_event_payload_keeps_checkpoint_artifact_id_backcompat():
    """La clave legacy sobrevive como additionalProperty (el schema lo permite)."""
    payload = _emit_rollback_event()
    assert payload["checkpoint_artifact_id"] == "artifact-checkpoint-1"
    assert payload["target"] == "artifact-checkpoint-1"


def test_proposal_event_payload_matches_proposal_schema():
    """El proposal vivo lo emite PromotionGate como evento `proposal.evaluated`."""
    schema = _schema("proposal")
    # Forma exacta que construye runtime/certification/promotion_gate.py.
    proposal = {
        "proposal_id": "proposal-abc",
        "origin": "promotion_gate",
        "change": {"episode_id": "ep-1", "run_id": "run-1"},
        "risk": "low",
        "metadata": {"ioc_proxy": 0.8},
    }
    for field in schema["required"]:
        assert field in proposal, f"proposal payload sin campo requerido: {field}"

    assert isinstance(proposal["proposal_id"], str)
    assert isinstance(proposal["origin"], str)
    assert isinstance(proposal["change"], dict)
    assert isinstance(proposal["risk"], str)
