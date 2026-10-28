"""Censo ejecutable de callers, consumidores y perfiles simbióticos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ComponentClass(str, Enum):
    LIVE = "LIVE"
    SHADOW_CONSUMED = "SHADOW_CONSUMED"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    STUB = "STUB"
    DEAD = "DEAD"


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    organ: str
    classification: ComponentClass
    callers: tuple[str, ...]
    consumers: tuple[str, ...]
    active_profiles: tuple[str, ...] = ()
    reference_only: bool = False
    stub_detected: bool = False
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "organ": self.organ,
            "classification": self.classification.value,
            "caller_count": len(self.callers),
            "consumer_count": len(self.consumers),
            "active_profile_count": len(self.active_profiles),
            "reference_only": self.reference_only,
            "live": self.classification is ComponentClass.LIVE,
            "shadow_consumed": self.classification is ComponentClass.SHADOW_CONSUMED,
            "stub_detected": self.stub_detected,
            "callers": list(self.callers),
            "consumers": list(self.consumers),
            "evidence": self.evidence,
        }


COMPONENT_SPECS: tuple[ComponentSpec, ...] = (
    ComponentSpec("N0", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("N1-N6",), ("symbiotic",), evidence="NeuralRuntime.infer_reference"),
    ComponentSpec("N1", ComponentClass.SHADOW_CONSUMED, ("SymbioticNeuralCoordinator",), ("scheduler comparison", "experience evidence"), ("symbiotic",), evidence="proposal compared with validated_sequence"),
    ComponentSpec("N2", ComponentClass.SHADOW_CONSUMED, ("SymbioticNeuralCoordinator",), ("DED", "LOT-F", "NESY", "certification"), ("symbiotic",), evidence="semantic candidate verification"),
    ComponentSpec("N3", ComponentClass.LIVE, ("SymbioticNeuralCoordinator",), ("next episode reasoning", "MFM candidate", "continuity audit"), ("symbiotic",), evidence="state keyed by organism+scenario+lineage"),
    ComponentSpec("N4", ComponentClass.SHADOW_CONSUMED, ("SymbioticNeuralCoordinator",), ("CAU/CTF/C-GWM comparison", "certification", "experience evidence"), ("symbiotic",), evidence="typed proposal never selects action"),
    ComponentSpec("N5", ComponentClass.LIVE, ("SymbioticNeuralCoordinator",), ("SMG", "MFM", "reasoning context"), ("symbiotic",), evidence="deterministic chunks with offsets"),
    ComponentSpec("N6", ComponentClass.SHADOW_CONSUMED, ("SymbioticNeuralCoordinator",), ("sandbox evaluator", "certification", "autoevolution evidence"), ("symbiotic",), evidence="versioned proposal; no apply_fn"),
    ComponentSpec("NESY", ComponentClass.SHADOW_CONSUMED, ("N2 verification", "MetaScheduler deep profile"), ("N2 trace", "PROB"), ("symbiotic-verifier",), evidence="deterministic symbol-number coherence"),
    ComponentSpec("EVO_SEARCH", ComponentClass.REFERENCE_ONLY, ("MetaScheduler deep profile",), ("PROB",), reference_only=True, evidence="deterministic GA; inactive in baseline profile"),
    ComponentSpec("IMAGINATION/A11", ComponentClass.REFERENCE_ONLY, ("MetaScheduler deep profile",), ("A12", "PROB"), reference_only=True, evidence="deterministic advisory world model; inactive baseline"),
    ComponentSpec("A12", ComponentClass.REFERENCE_ONLY, ("MetaScheduler deep profile", "ScenarioEpisodeRunner gated recomputation"), ("intervention override guard",), reference_only=True, evidence="inactive without explicit deep/actuation gates"),
    ComponentSpec("CAU", ComponentClass.LIVE, ("MetaScheduler",), ("CTF", "PROB", "N4 comparator"), ("baseline", "symbiotic"), evidence="core causal inference family"),
    ComponentSpec("CTF", ComponentClass.LIVE, ("MetaScheduler",), ("PROB", "N4 comparator"), ("baseline", "symbiotic"), evidence="counterfactual family"),
    ComponentSpec("C-GWM", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("world transition", "N4 comparator"), ("baseline", "symbiotic"), evidence="scenario simulation and factual transition"),
    ComponentSpec("DED", ComponentClass.LIVE, ("MetaScheduler",), ("PROB", "N2 verifier"), ("baseline", "symbiotic"), evidence="LOT-F boolean solver"),
    ComponentSpec("LOT-F", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("DED", "N2 verifier", "certification"), ("baseline", "symbiotic"), evidence="parsed and type-checked formula"),
    ComponentSpec("MFM", ComponentClass.LIVE, ("ScenarioEpisodeRunner", "PromotionGate"), ("reasoning", "next episode", "N1", "N3"), ("baseline", "symbiotic"), evidence="retrieval and gated condensation"),
    ComponentSpec("SMG", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("artifact", "certification", "MFM"), ("baseline", "symbiotic"), evidence="observations, signs and relations"),
    ComponentSpec("scheduler", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("world override guard", "certification", "N1 comparator"), ("baseline", "symbiotic"), evidence="authoritative family sequence"),
    ComponentSpec("certification", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("memory promotion", "experience", "autoevolution"), ("baseline", "symbiotic"), evidence="PromotionGate"),
    ComponentSpec("experience", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("future intervention bias",), ("experience-enabled",), evidence="ExperienceStore recall and wisdom"),
    ComponentSpec("autoevolution", ComponentClass.LIVE, ("ScenarioEpisodeRunner",), ("lineage", "future knobs"), ("baseline",), evidence="AutoEvolutionController"),
)


def integration_census() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in COMPONENT_SPECS]


def validate_active_census() -> list[str]:
    failures = []
    for row in integration_census():
        if row["active_profile_count"] > 0 and (
            row["caller_count"] == 0
            or row["consumer_count"] == 0
            or row["stub_detected"]
        ):
            failures.append(str(row["organ"]))
    return failures
