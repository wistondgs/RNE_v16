"""Contratos neutrales para proveedores externos de hipótesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import NeuralHypothesisEvaluation


@dataclass(frozen=True)
class ExternalHypothesis:
    """Propuesta sin autoridad emitida por un proveedor externo."""

    kind: str
    source: str = ""
    target: str = ""
    target_id: str = ""
    expression: str | None = None
    proposed_value: float | None = None
    confidence: float = 0.0
    evidence_refs: tuple[str, ...] = ()
    provider: str = "external"
    model_ref: str = "unavailable"
    hypothesis_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


@runtime_checkable
class HypothesisProvider(Protocol):
    """Interfaz mínima; el proveedor nunca recibe autoridad sobre el mundo."""

    def infer_hypotheses(
        self, context: Mapping[str, Any]
    ) -> Sequence[ExternalHypothesis]:
        ...

    def receive_feedback(
        self, evaluations: Sequence[NeuralHypothesisEvaluation]
    ) -> None:
        ...
