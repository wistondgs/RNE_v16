"""N1: enrutador compacto de familias como propuesta no autoritativa."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..contracts import AdmissionDecision, BackendOutput, NeuralInferenceRequest, NeuralModelManifest
from ._math import matrix, matvec, sigmoid, silu, softmax, vector


FAMILY_CATALOG_V1 = (
    "HEUR",
    "DIA_ADV",
    "FAL_GUARD",
    "IND",
    "EML_SR",
    "PLAN",
    "OPT",
)

FAMILY_CATALOG_V2 = FAMILY_CATALOG_V1 + (
    "NESY",
    "EVO_SEARCH",
    "IMAGINATION",
    "A12",
)

FAMILY_CATALOGS = {
    "n1-family-catalog-v1": FAMILY_CATALOG_V1,
    "n1-family-catalog-v2": FAMILY_CATALOG_V2,
}


class CompactMLPRouterBackend:
    """Inferencia MLP desde pesos JSON; no aprende ni descarga en runtime."""

    def __init__(self) -> None:
        self._weights: dict[str, Any] | None = None

    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        if device != "cpu":
            raise RuntimeError("compact_mlp_reference_backend_is_cpu_only")
        if manifest.organ != "N1":
            raise ValueError("n1_manifest_required")
        with open(artifact_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        features = tuple(str(item) for item in raw["feature_names"])
        catalog = tuple(str(item).upper() for item in raw["family_catalog"])
        catalog_version = str(raw.get("catalog_version") or _infer_catalog_version(catalog))
        expected_catalog = FAMILY_CATALOGS.get(catalog_version)
        if expected_catalog is None or catalog != expected_catalog:
            raise ValueError("family_catalog_version_mismatch")
        calibration_ece = float(raw.get("calibration_ece", 1.0))
        if not 0.0 <= calibration_ece <= 1.0:
            raise ValueError("n1_calibration_ece_out_of_range")
        raw_policy = dict(raw.get("activation_policy", {}))
        activation_policy = {
            "min_expected_utility": float(raw_policy.get("min_expected_utility", 0.0)),
            "min_probability_positive": float(raw_policy.get("min_probability_positive", 0.5)),
            "max_uncertainty": float(raw_policy.get("max_uncertainty", 0.5)),
            "max_calibration_ece": float(raw_policy.get("max_calibration_ece", 0.10)),
        }
        if not 0.0 <= activation_policy["min_probability_positive"] <= 1.0:
            raise ValueError("n1_probability_threshold_out_of_range")
        if not 0.0 <= activation_policy["max_uncertainty"] <= 1.0:
            raise ValueError("n1_uncertainty_threshold_out_of_range")
        if not 0.0 <= activation_policy["max_calibration_ece"] <= 1.0:
            raise ValueError("n1_calibration_threshold_out_of_range")
        w1 = matrix(raw["w1"], columns=len(features), name="w1")
        b1 = vector(raw["b1"], size=len(w1), name="b1")
        w2 = matrix(raw["w2"], columns=len(w1), name="w2")
        b2 = vector(raw["b2"], size=len(w2), name="b2")
        utility = matrix(raw["utility_head"], columns=len(w2), name="utility_head")
        probability = matrix(raw["probability_head"], columns=len(w2), name="probability_head")
        if len(utility) != len(catalog) or len(probability) != len(catalog):
            raise ValueError("n1_head_catalog_size_mismatch")
        self._weights = {
            "feature_names": features,
            "catalog": catalog,
            "catalog_version": catalog_version,
            "w1": w1,
            "b1": b1,
            "w2": w2,
            "b2": b2,
            "utility": utility,
            "probability": probability,
            "temperature": float(raw.get("temperature", 1.0)),
            "calibration_ece": calibration_ece,
            "activation_policy": activation_policy,
        }

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        if self._weights is None:
            raise RuntimeError("backend_not_loaded")
        raw_features = request.payload.get("features", {})
        if not isinstance(raw_features, Mapping):
            raise ValueError("n1_features_must_be_mapping")
        features = [float(raw_features.get(name, 0.0)) for name in self._weights["feature_names"]]
        hidden1 = [silu(value) for value in matvec(self._weights["w1"], features, self._weights["b1"])]
        hidden2 = [silu(value) for value in matvec(self._weights["w2"], hidden1, self._weights["b2"])]
        utilities = matvec(self._weights["utility"], hidden2)
        logits = matvec(self._weights["probability"], hidden2)
        probabilities = [sigmoid(value / max(self._weights["temperature"], 1e-6)) for value in logits]
        combined = [utility * probability for utility, probability in zip(utilities, probabilities)]
        normalized = softmax(combined)
        allowed = {str(item).upper() for item in request.payload.get("allowed_families", ())}
        policy = _effective_activation_policy(self._weights["activation_policy"], request.payload)
        calibration_ok = self._weights["calibration_ece"] <= policy["max_calibration_ece"]
        entries = []
        for family, score, utility, probability in zip(
            self._weights["catalog"], normalized, utilities, probabilities
        ):
            is_allowed = family in allowed
            family_uncertainty = 1.0 - probability
            rejection_reasons = []
            if not is_allowed:
                rejection_reasons.append("hard_mask")
            if utility <= policy["min_expected_utility"]:
                rejection_reasons.append("non_positive_utility")
            if probability < policy["min_probability_positive"]:
                rejection_reasons.append("probability_below_threshold")
            if family_uncertainty > policy["max_uncertainty"]:
                rejection_reasons.append("uncertainty_above_threshold")
            if not calibration_ok:
                rejection_reasons.append("calibration_out_of_range")
            entries.append(
                {
                    "family": family,
                    "rank_score": score,
                    "expected_utility": utility,
                    "probability_positive": probability,
                    "uncertainty": family_uncertainty,
                    "allowed": is_allowed,
                    "eligible": not rejection_reasons,
                    "rejection_reasons": rejection_reasons,
                }
            )
        entries.sort(key=lambda item: (-item["rank_score"], item["family"]))
        budget = max(0, int(request.payload.get("max_optional_families", 2)))
        eligible = [item["family"] for item in entries if item["eligible"]]
        activated = eligible[:budget]
        decision = "ACTIVATE" if activated else "ABSTAIN"
        abstain_reason = None if activated else _abstain_reason(entries, allowed, calibration_ok, budget)
        confidence = max(
            (item["probability_positive"] for item in entries if item["eligible"]),
            default=0.0,
        )
        return BackendOutput(
            candidate_output={
                "catalog_version": self._weights["catalog_version"],
                "ranked": entries,
                "activation": {
                    "decision": decision,
                    "families": activated,
                    "budget": budget,
                    "abstain_reason": abstain_reason,
                },
                "optional_families": activated,
                "calibration_ece": self._weights["calibration_ece"],
                "activation_policy": policy,
            },
            confidence=confidence,
            uncertainty=1.0 - confidence,
            cost={"parameter_count_runtime": _parameter_count(self._weights)},
        )

    def unload(self) -> None:
        self._weights = None


class FamilyRouterAdmission:
    """Valida la propuesta N1 sin ejecutar ni reordenar el backbone."""

    def __init__(
        self,
        *,
        min_expected_utility: float = 0.0,
        min_probability_positive: float = 0.5,
        max_uncertainty: float = 0.5,
        max_calibration_ece: float = 0.10,
    ) -> None:
        self._gate_policy = {
            "min_expected_utility": float(min_expected_utility),
            "min_probability_positive": float(min_probability_positive),
            "max_uncertainty": float(max_uncertainty),
            "max_calibration_ece": float(max_calibration_ece),
        }

    def __call__(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision:
        if not isinstance(candidate, Mapping):
            return AdmissionDecision(False, reason="n1_candidate_not_mapping")
        catalog_version = str(candidate.get("catalog_version", ""))
        catalog = FAMILY_CATALOGS.get(catalog_version)
        if catalog is None:
            return AdmissionDecision(False, reason="n1_catalog_version_mismatch")
        activation = candidate.get("activation")
        if not isinstance(activation, Mapping):
            return AdmissionDecision(False, reason="n1_activation_contract_missing")
        if str(activation.get("decision", "")).upper() == "ABSTAIN":
            return AdmissionDecision(
                False,
                output={"optional_families": [], "catalog_version": catalog_version},
                reason=f"n1_abstained:{activation.get('abstain_reason') or 'thresholds'}",
            )
        if str(activation.get("decision", "")).upper() != "ACTIVATE":
            return AdmissionDecision(False, reason="n1_activation_decision_invalid")
        allowed = {str(item).upper() for item in request.payload.get("allowed_families", ())}
        proposed = [str(item).upper() for item in activation.get("families", ())]
        if proposed != [str(item).upper() for item in candidate.get("optional_families", ())]:
            return AdmissionDecision(False, reason="n1_activation_projection_mismatch")
        if any(item not in allowed or item not in catalog for item in proposed):
            return AdmissionDecision(False, reason="n1_hard_mask_violation")
        limit = max(0, int(request.payload.get("max_optional_families", 2)))
        if len(proposed) > limit or int(activation.get("budget", -1)) != limit:
            return AdmissionDecision(False, reason="n1_activation_budget_violation")
        ranked = candidate.get("ranked", ())
        entries = {
            str(item.get("family", "")).upper(): item
            for item in ranked
            if isinstance(item, Mapping)
        }
        policy = _effective_activation_policy(self._gate_policy, request.payload)
        calibration_ece = float(candidate.get("calibration_ece", 1.0))
        if calibration_ece > float(policy.get("max_calibration_ece", 0.10)):
            return AdmissionDecision(False, reason="n1_calibration_out_of_range")
        for family in proposed:
            item = entries.get(family)
            if (
                item is None
                or not bool(item.get("eligible"))
                or float(item.get("expected_utility", 0.0))
                <= float(policy.get("min_expected_utility", 0.0))
                or float(item.get("probability_positive", 0.0))
                < float(policy.get("min_probability_positive", 0.5))
                or float(item.get("uncertainty", 1.0))
                > float(policy.get("max_uncertainty", 0.5))
            ):
                return AdmissionDecision(False, reason="n1_activation_threshold_violation")
        return AdmissionDecision(
            True,
            output={
                "optional_families": proposed,
                "catalog_version": catalog_version,
                "decision": "ACTIVATE",
            },
            reason="n1_bounded_routing_proposal",
        )


def _infer_catalog_version(catalog: tuple[str, ...]) -> str:
    for version, expected in FAMILY_CATALOGS.items():
        if catalog == expected:
            return version
    return "unknown"


def _effective_activation_policy(
    model_policy: Mapping[str, float], request_payload: Mapping[str, Any]
) -> dict[str, float]:
    requested = dict(request_payload.get("activation_policy", {}))
    return {
        "min_expected_utility": max(
            float(model_policy["min_expected_utility"]),
            float(requested.get("min_expected_utility", model_policy["min_expected_utility"])),
        ),
        "min_probability_positive": max(
            float(model_policy["min_probability_positive"]),
            float(
                requested.get(
                    "min_probability_positive", model_policy["min_probability_positive"]
                )
            ),
        ),
        "max_uncertainty": min(
            float(model_policy["max_uncertainty"]),
            float(requested.get("max_uncertainty", model_policy["max_uncertainty"])),
        ),
        "max_calibration_ece": min(
            float(model_policy["max_calibration_ece"]),
            float(
                requested.get("max_calibration_ece", model_policy["max_calibration_ece"])
            ),
        ),
    }


def _abstain_reason(
    entries: list[Mapping[str, Any]],
    allowed: set[str],
    calibration_ok: bool,
    budget: int,
) -> str:
    if budget == 0:
        return "activation_budget_zero"
    if not allowed:
        return "no_family_admitted_by_hard_mask"
    if not calibration_ok:
        return "calibration_out_of_range"
    allowed_entries = [item for item in entries if item["allowed"]]
    if allowed_entries and all(float(item["expected_utility"]) <= 0.0 for item in allowed_entries):
        return "no_positive_expected_utility"
    return "no_candidate_passed_activation_thresholds"


def _parameter_count(weights: Mapping[str, Any]) -> int:
    matrices = ("w1", "w2", "utility", "probability")
    biases = ("b1", "b2")
    return sum(len(row) for name in matrices for row in weights[name]) + sum(
        len(weights[name]) for name in biases
    )
