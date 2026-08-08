"""Ledger inmutable lógico para el ciclo de vida de hipótesis externas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.symbolic.schemas import sealed_sha256

from .contracts import NeuralHypothesis, NeuralHypothesisEvaluation


@dataclass(frozen=True)
class HypothesisLedgerEntry:
    hypothesis_id: str
    payload_sha256: str
    provider: str
    model_ref: str
    status: str
    reason: str
    evaluation_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "payload_sha256": self.payload_sha256,
            "provider": self.provider,
            "model_ref": self.model_ref,
            "status": self.status,
            "reason": self.reason,
            "evaluation_ref": self.evaluation_ref,
        }


class HypothesisLedger:
    def __init__(self) -> None:
        self._entries: dict[str, HypothesisLedgerEntry] = {}

    def submit(self, hypothesis: NeuralHypothesis) -> bool:
        digest = sealed_sha256(hypothesis.to_dict())
        previous = self._entries.get(hypothesis.hypothesis_id)
        if previous is not None:
            if previous.payload_sha256 != digest:
                raise ValueError(
                    f"Colisión de hypothesis_id: {hypothesis.hypothesis_id}"
                )
            return previous.status in {"submitted", "pending"}
        self._entries[hypothesis.hypothesis_id] = HypothesisLedgerEntry(
            hypothesis_id=hypothesis.hypothesis_id,
            payload_sha256=digest,
            provider=hypothesis.provider,
            model_ref=hypothesis.model_ref,
            status="submitted",
            reason="accepted_for_validation",
            evaluation_ref=None,
        )
        return True

    def apply(self, evaluation: NeuralHypothesisEvaluation) -> None:
        previous = self._entries.get(evaluation.hypothesis_id)
        if previous is None:
            return
        evaluation_ref = f"sha256:{sealed_sha256(evaluation.to_dict())}"
        self._entries[evaluation.hypothesis_id] = HypothesisLedgerEntry(
            hypothesis_id=previous.hypothesis_id,
            payload_sha256=previous.payload_sha256,
            provider=previous.provider,
            model_ref=previous.model_ref,
            status=evaluation.status,
            reason=evaluation.reason,
            evaluation_ref=evaluation_ref,
        )

    def get(self, hypothesis_id: str) -> HypothesisLedgerEntry | None:
        return self._entries.get(hypothesis_id)

    def snapshot(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            self._entries[key].to_dict() for key in sorted(self._entries)
        )

    def restore(self, payload: tuple[Mapping[str, Any], ...]) -> None:
        restored: dict[str, HypothesisLedgerEntry] = {}
        for item in payload:
            entry = HypothesisLedgerEntry(
                hypothesis_id=str(item["hypothesis_id"]),
                payload_sha256=str(item["payload_sha256"]),
                provider=str(item["provider"]),
                model_ref=str(item["model_ref"]),
                status=str(item["status"]),
                reason=str(item["reason"]),
                evaluation_ref=(
                    str(item["evaluation_ref"])
                    if item.get("evaluation_ref") is not None
                    else None
                ),
            )
            if entry.hypothesis_id in restored:
                raise ValueError("duplicate_hypothesis_ledger_entry")
            restored[entry.hypothesis_id] = entry
        self._entries = restored
