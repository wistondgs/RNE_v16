"""N2: recurrencia compartida con verificacion simbolica obligatoria."""

from __future__ import annotations

import json
import math
from typing import Any, Callable, Mapping

from ..contracts import AdmissionDecision, BackendOutput, NeuralInferenceRequest, NeuralModelManifest
from ._math import matrix, matvec, sigmoid, tanh_vector, vector


Verifier = Callable[[str, NeuralInferenceRequest], bool]


class SharedRecursiveBackend:
    def __init__(self) -> None:
        self._weights: dict[str, Any] | None = None

    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        if device != "cpu" or manifest.organ != "N2":
            raise ValueError("n2_reference_backend_requires_cpu_n2_manifest")
        with open(artifact_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        hidden_size = int(raw["hidden_size"])
        input_size = int(raw["input_size"])
        self._weights = {
            "hidden_size": hidden_size,
            "input_size": input_size,
            "w_state": matrix(raw["w_state"], columns=hidden_size, name="w_state"),
            "w_input": matrix(raw["w_input"], columns=input_size, name="w_input"),
            "bias": vector(raw["bias"], size=hidden_size, name="bias"),
            "candidate_weight": vector(raw["candidate_weight"], size=hidden_size),
            "halt_weight": vector(raw["halt_weight"], size=hidden_size),
            "max_iterations": min(max(int(raw.get("max_iterations", 8)), 4), 16),
            "halt_threshold": min(max(float(raw.get("halt_threshold", 0.8)), 0.0), 1.0),
        }
        if len(self._weights["w_state"]) != hidden_size or len(self._weights["w_input"]) != hidden_size:
            raise ValueError("n2_recurrent_shape_mismatch")

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        if self._weights is None:
            raise RuntimeError("backend_not_loaded")
        inputs = vector(request.payload.get("state_vector", ()), size=self._weights["input_size"])
        templates = [str(item) for item in request.payload.get("candidate_templates", ())]
        if not templates:
            raise ValueError("n2_candidate_templates_required")
        state = [0.0] * self._weights["hidden_size"]
        trace = []
        candidates = []
        for iteration in range(self._weights["max_iterations"]):
            recurrent = matvec(self._weights["w_state"], state)
            driven = matvec(self._weights["w_input"], inputs)
            state = tanh_vector(
                [a + b + c for a, b, c in zip(recurrent, driven, self._weights["bias"])]
            )
            base_score = sum(a * b for a, b in zip(state, self._weights["candidate_weight"]))
            index = int(abs(base_score * 1_000.0 + request.seed + iteration)) % len(templates)
            confidence = sigmoid(base_score)
            halt = sigmoid(sum(a * b for a, b in zip(state, self._weights["halt_weight"])))
            candidate = {
                "iteration": iteration,
                "proposition": templates[index],
                "confidence": confidence,
                "halt_probability": halt,
            }
            candidates.append(candidate)
            trace.append({"iteration": iteration, "candidate_index": index, "halt_probability": halt})
            if iteration >= 3 and halt >= self._weights["halt_threshold"]:
                break
        confidence = max(item["confidence"] for item in candidates)
        return BackendOutput(
            candidate_output={"candidates": candidates, "shared_weights": True},
            confidence=confidence,
            uncertainty=1.0 - confidence,
            cost={"iterations": len(candidates)},
            trace=tuple(trace),
        )

    def unload(self) -> None:
        self._weights = None


class SymbolicVerificationAdmission:
    def __init__(self, *, ded_verifier: Verifier, lotf_verifier: Verifier):
        self.ded_verifier = ded_verifier
        self.lotf_verifier = lotf_verifier

    def __call__(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision:
        if not isinstance(candidate, Mapping):
            return AdmissionDecision(False, reason="n2_candidate_not_mapping")
        verified = []
        rejected = []
        for item in candidate.get("candidates", ()):
            proposition = str(item.get("proposition", "")) if isinstance(item, Mapping) else ""
            ded_ok = bool(proposition) and self.ded_verifier(proposition, request)
            lotf_ok = bool(proposition) and self.lotf_verifier(proposition, request)
            record = {**dict(item), "ded_verified": ded_ok, "lotf_verified": lotf_ok}
            (verified if ded_ok and lotf_ok else rejected).append(record)
        if not verified:
            return AdmissionDecision(False, output={"verified": [], "rejected": rejected}, reason="n2_no_verified_candidate")
        return AdmissionDecision(
            True,
            output={"verified": verified, "rejected": rejected, "authority": "DED+LOTF"},
            reason="n2_symbolically_verified",
        )
