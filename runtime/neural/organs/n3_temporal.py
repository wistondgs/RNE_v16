"""N3: puerto temporal version-neutral y backend SSM de referencia."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..contracts import AdmissionDecision, BackendOutput, NeuralInferenceRequest, NeuralModelManifest
from ._math import matrix, matvec, sigmoid, tanh_vector, vector


TEMPORAL_OUTPUTS = ("retrieval_priority", "importance", "risk", "continuity", "confidence")


class ReferenceTemporalSSMBackend:
    """SSM real y pequeno para validar el puerto; no se presenta como Mamba2."""

    def __init__(self) -> None:
        self._weights: dict[str, Any] | None = None
        self._states: dict[tuple[str, str], list[float]] = {}

    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        if device != "cpu" or manifest.organ != "N3":
            raise ValueError("reference_temporal_ssm_requires_cpu_n3_manifest")
        with open(artifact_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        state_size = int(raw["state_size"])
        input_size = int(raw["input_size"])
        a = matrix(raw["a"], columns=state_size, name="a")
        b = matrix(raw["b"], columns=input_size, name="b")
        c = matrix(raw["c"], columns=state_size, name="c")
        if len(a) != state_size or len(b) != state_size or len(c) != len(TEMPORAL_OUTPUTS):
            raise ValueError("n3_ssm_shape_mismatch")
        self._weights = {"state_size": state_size, "input_size": input_size, "a": a, "b": b, "c": c}

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        if self._weights is None:
            raise RuntimeError("backend_not_loaded")
        organism_id = str(request.payload.get("organism_id", ""))
        scenario_id = str(request.payload.get("scenario_id", ""))
        if not organism_id or not scenario_id:
            raise ValueError("n3_organism_and_scenario_are_required")
        values = vector(request.payload.get("input_vector", ()), size=self._weights["input_size"])
        key = (organism_id, scenario_id)
        state = self._states.get(key, [0.0] * self._weights["state_size"])
        state = tanh_vector(
            [left + right for left, right in zip(matvec(self._weights["a"], state), matvec(self._weights["b"], values))]
        )
        self._states[key] = state
        raw_outputs = matvec(self._weights["c"], state)
        outputs = {name: sigmoid(value) for name, value in zip(TEMPORAL_OUTPUTS, raw_outputs)}
        return BackendOutput(
            candidate_output={**outputs, "state_key": [organism_id, scenario_id]},
            confidence=outputs["confidence"],
            uncertainty=1.0 - outputs["confidence"],
            cost={"state_size": len(state)},
        )

    def unload(self) -> None:
        self._weights = None
        self._states.clear()


class TemporalMemoryAdmission:
    """Admite prioridades acotadas; nunca escrituras directas en MFM."""

    def __call__(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision:
        if not isinstance(candidate, Mapping):
            return AdmissionDecision(False, reason="n3_candidate_not_mapping")
        if any(name not in candidate for name in TEMPORAL_OUTPUTS):
            return AdmissionDecision(False, reason="n3_output_schema_incomplete")
        bounded = {name: min(max(float(candidate[name]), 0.0), 1.0) for name in TEMPORAL_OUTPUTS}
        bounded["state_key"] = candidate.get("state_key")
        bounded["memory_authority"] = "MFM"
        return AdmissionDecision(True, output=bounded, reason="n3_bounded_memory_proposal")


class Mamba2BackendUnavailable(RuntimeError):
    """Stop condition explicita mientras el vendor no tenga revision certificada."""


class Mamba2Backend:
    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        raise Mamba2BackendUnavailable(
            "mamba2_activation_blocked_until_vendor_commit_license_and_dependencies_are_certified"
        )

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        raise Mamba2BackendUnavailable("mamba2_backend_not_loaded")

    def unload(self) -> None:
        return None
