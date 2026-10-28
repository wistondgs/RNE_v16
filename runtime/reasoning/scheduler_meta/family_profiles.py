"""Perfiles de familias de razonamiento para ejecución comparativa y adaptativa."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Set


CORE_SEQUENCE: List[str] = ["abd", "ana", "cau", "ctf", "ded", "prob"]
BACKBONE_FAMILIES: List[str] = list(CORE_SEQUENCE)
AUGMENTER_FAMILIES: List[str] = ["heur", "dia_adv", "fal_guard"]
CONDITIONAL_SHADOW_FAMILIES: List[str] = ["ind", "eml_sr"]
# Deliberativas (R3b): planificación/optimización sobre el modelo de efectos
# declarado de la firma causal. Solo entran vía perfiles que las incluyan.
DELIBERATIVE_FAMILIES: List[str] = ["plan", "opt"]
EXTERNAL_EXPERIMENTAL_FAMILIES: List[str] = ["ext_open_thinker"]
OPTIONAL_FAMILIES: List[str] = list(AUGMENTER_FAMILIES) + list(CONDITIONAL_SHADOW_FAMILIES)
TRACKED_OPTIONAL_FAMILIES: List[str] = list(OPTIONAL_FAMILIES) + list(EXTERNAL_EXPERIMENTAL_FAMILIES)


@dataclass(frozen=True)
class FamilyProfile:
    name: str
    core_sequence: List[str]
    optional_families: List[str]
    adaptive: bool
    description: str
    lab_only: bool = False

    @property
    def allowed_families(self) -> List[str]:
        ordered: List[str] = []
        for family in list(self.core_sequence) + list(self.optional_families):
            if family not in ordered:
                ordered.append(family)
        return ordered


@dataclass(frozen=True)
class FamilyAdmissionRecord:
    family: str
    stratum: str
    nominal_status: str
    allowed_in_nominal_runtime: bool
    validated_regimes: List[str]
    forbidden_default_regimes: List[str]
    activation_policy: str
    guard_required: bool
    schema_required: bool
    fallback_required: bool
    latency_budget_s: float
    current_latency_mean_s: float
    current_latency_p95_s: float
    evidence_status: str
    admitted_lab_profiles: List[str]
    evidence_artifacts: Mapping[str, str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "family": self.family,
            "stratum": self.stratum,
            "nominal_status": self.nominal_status,
            "allowed_in_nominal_runtime": self.allowed_in_nominal_runtime,
            "validated_regimes": list(self.validated_regimes),
            "forbidden_default_regimes": list(self.forbidden_default_regimes),
            "activation_policy": self.activation_policy,
            "guard_required": self.guard_required,
            "schema_required": self.schema_required,
            "fallback_required": self.fallback_required,
            "latency_budget_s": self.latency_budget_s,
            "current_latency_mean_s": self.current_latency_mean_s,
            "current_latency_p95_s": self.current_latency_p95_s,
            "evidence_status": self.evidence_status,
            "admitted_lab_profiles": list(self.admitted_lab_profiles),
            "evidence_artifacts": dict(self.evidence_artifacts),
        }


@dataclass(frozen=True)
class ExternalReasonerUseValidation:
    allowed: bool
    reason: str
    family: str = "ext_open_thinker"


EXT_OPEN_THINKER_ADMISSION = FamilyAdmissionRecord(
    family="ext_open_thinker",
    stratum="external_experimental",
    nominal_status="conditional_lab",
    allowed_in_nominal_runtime=False,
    validated_regimes=["causal_counterfactual_conflict"],
    forbidden_default_regimes=[
        "viability_edge",
        "heterogeneous_warning",
        "homogeneous_safe",
    ],
    activation_policy="ExternalReasonerGate v1",
    guard_required=True,
    schema_required=True,
    fallback_required=True,
    latency_budget_s=100.0,
    current_latency_mean_s=96.115,
    current_latency_p95_s=98.953,
    evidence_status="conflict_resolver_repetible",
    admitted_lab_profiles=["core_plus_external_reasoner_gated_v1"],
    evidence_artifacts={
        "summary": (
            "data/benchmarks/external_reasoner_gain/"
            "conflict-repeatability-gated-v1-4x4/summary.json"
        ),
        "report": (
            "data/benchmarks/external_reasoner_gain/"
            "conflict-repeatability-gated-v1-4x4/"
            "external_reasoner_conflict_repeatability_report.md"
        ),
        "verdict": (
            "data/benchmarks/external_reasoner_gain/"
            "conflict-repeatability-gated-v1-4x4/"
            "external_reasoner_conflict_repeatability_verdict.json"
        ),
    },
)
FAMILY_ADMISSION_RECORDS: Dict[str, FamilyAdmissionRecord] = {
    EXT_OPEN_THINKER_ADMISSION.family: EXT_OPEN_THINKER_ADMISSION,
}


PROFILES: Dict[str, FamilyProfile] = {
    "core_only": FamilyProfile(
        name="core_only",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=[],
        adaptive=False,
        description="Solo secuencia core canónica.",
    ),
    "core_plus_heur": FamilyProfile(
        name="core_plus_heur",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur"],
        adaptive=False,
        description="Core + heurística contextual.",
    ),
    "core_plus_dialectic": FamilyProfile(
        name="core_plus_dialectic",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["dia_adv"],
        adaptive=False,
        description="Core + crítica dialéctica adversarial.",
    ),
    "core_plus_guard": FamilyProfile(
        name="core_plus_guard",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["fal_guard"],
        adaptive=False,
        description="Core + guardia de falacias/fragilidad.",
    ),
    "core_plus_heur_guard": FamilyProfile(
        name="core_plus_heur_guard",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "fal_guard"],
        adaptive=False,
        description="Core + heurística + guardia de fragilidad.",
    ),
    "core_plus_heur_dialectic": FamilyProfile(
        name="core_plus_heur_dialectic",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "dia_adv"],
        adaptive=False,
        description="Core + heurística + dialéctica adversarial.",
    ),
    "core_plus_guard_dialectic": FamilyProfile(
        name="core_plus_guard_dialectic",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["fal_guard", "dia_adv"],
        adaptive=False,
        description="Core + guardia + dialéctica adversarial.",
    ),
    "core_plus_triple_optional": FamilyProfile(
        name="core_plus_triple_optional",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "dia_adv", "fal_guard"],
        adaptive=False,
        description="Core + triple overlay opcional fijo.",
    ),
    "core_plus_external_reasoner": FamilyProfile(
        name="core_plus_external_reasoner",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["ext_open_thinker"],
        adaptive=False,
        description="Lab legacy: core + razonador externo experimental sin gate.",
        lab_only=True,
    ),
    "core_plus_external_reasoner_guarded": FamilyProfile(
        name="core_plus_external_reasoner_guarded",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["ext_open_thinker", "fal_guard"],
        adaptive=False,
        description="Lab legacy: core + razonador externo experimental + guardia.",
        lab_only=True,
    ),
    "core_plus_external_reasoner_gated_v1": FamilyProfile(
        name="core_plus_external_reasoner_gated_v1",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["ext_open_thinker", "fal_guard"],
        adaptive=False,
        description=(
            "Perfil ADMITIDO (conditional_lab): core + razonador externo gated + "
            "guardia. Solo se agenda ext_open_thinker bajo RNFE_EXTERNAL_REASONER_RUNTIME, "
            "régimen validado (causal_counterfactual_conflict) y admisión (gate/guard/"
            "schema/fallback). Ver EXT_OPEN_THINKER_ADMISSION."
        ),
        lab_only=True,
    ),
    "adaptive_family_ecology": FamilyProfile(
        name="adaptive_family_ecology",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "dia_adv", "fal_guard", "eml_sr"],
        adaptive=True,
        description="Core + opcionales según régimen y necesidad.",
    ),
    "adaptive_family_ecology_v2": FamilyProfile(
        name="adaptive_family_ecology_v2",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=list(OPTIONAL_FAMILIES),
        adaptive=True,
        description="Ecología adaptativa v2 con backbone protegido, overlays y validación.",
    ),
    "full_family_exploration": FamilyProfile(
        name="full_family_exploration",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "dia_adv", "fal_guard", "ind", "eml_sr", "plan", "opt"],
        adaptive=True,
        description="Exploración amplia con guardas y trazabilidad.",
    ),
    "core_plus_deliberative": FamilyProfile(
        name="core_plus_deliberative",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=list(DELIBERATIVE_FAMILIES),
        adaptive=False,
        description="Core + planificación y optimización deliberativas (R3b).",
    ),
    "core_plus_ind": FamilyProfile(
        name="core_plus_ind",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["ind"],
        adaptive=False,
        description="Core + inducción empírica (aislamiento por familia).",
    ),
    "core_plus_plan": FamilyProfile(
        name="core_plus_plan",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["plan"],
        adaptive=False,
        description="Core + planificación deliberativa (aislamiento por familia).",
    ),
    "core_plus_opt": FamilyProfile(
        name="core_plus_opt",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["opt"],
        adaptive=False,
        description="Core + optimización deliberativa (aislamiento por familia).",
    ),
    "full_family_deep_v1": FamilyProfile(
        name="full_family_deep_v1",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["heur", "dia_adv", "fal_guard", "ind", "plan", "opt", "eml_sr", "nesy", "evo_search"],
        adaptive=False,
        description=(
            "Lab: core + TODAS las overlays, incl. nesy y evo_search (antes stubs idle, "
            "ahora reales). Perfil fijo: ejecuta la secuencia completa en orden. La "
            "variante profunda de cada familia se activa con RNFE_REASONING_DEEP (o el "
            "flag por familia RNFE_<FAMILIA>_DEEP)."
        ),
        lab_only=True,
    ),
    "core_plus_imagination": FamilyProfile(
        name="core_plus_imagination",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["imagination"],
        adaptive=False,
        description=(
            "Lab: core + imaginación A11 (previsión de consecuencia diferida). Advisory: "
            "activa la variante deep con RNFE_IMAGINATION_DEEP; nunca decide por sí sola."
        ),
        lab_only=True,
    ),
    "core_plus_a12": FamilyProfile(
        name="core_plus_a12",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["a12"],
        adaptive=False,
        description=(
            "Lab: core + decisor A12 (no-monotonía + Bayes-factor + ACT). Advisory: "
            "activa la variante deep con RNFE_A12_DEEP; nunca decide por sí sola."
        ),
        lab_only=True,
    ),
    "core_plus_imagination_a12": FamilyProfile(
        name="core_plus_imagination_a12",
        core_sequence=list(CORE_SEQUENCE),
        optional_families=["imagination", "a12"],  # A11 antes que A12: el decisor lee la previsión
        adaptive=False,
        description=(
            "Lab: core + A11 imaginación + A12 decisor. Composición: A11 imagina, A12 "
            "decide con lógica sobre esa previsión. Advisory (RNFE_IMAGINATION_DEEP + RNFE_A12_DEEP)."
        ),
        lab_only=True,
    ),
}


def normalize_profile_name(profile_name: str | None) -> str:
    if not profile_name:
        return ""
    return profile_name.strip().lower()


def default_profile_for_mode(mode: str) -> str:
    normalized = (mode or "fixed").strip().lower()
    if normalized == "adaptive":
        return "adaptive_family_ecology_v2"
    return "core_only"


def resolve_family_profile(
    profile_name: str | None,
    *,
    mode: str = "fixed",
) -> FamilyProfile:
    normalized = normalize_profile_name(profile_name)
    if normalized and normalized in PROFILES:
        return PROFILES[normalized]
    return PROFILES[default_profile_for_mode(mode)]


def family_admission_record(family: str) -> FamilyAdmissionRecord | None:
    normalized = str(family or "").strip().lower()
    return FAMILY_ADMISSION_RECORDS.get(normalized)


def nominal_profiles() -> Dict[str, FamilyProfile]:
    return {name: profile for name, profile in PROFILES.items() if not profile.lab_only}


def lab_only_profiles() -> Dict[str, FamilyProfile]:
    return {name: profile for name, profile in PROFILES.items() if profile.lab_only}


def profile_uses_external_reasoner(profile_name: str | None, *, mode: str = "fixed") -> bool:
    profile = resolve_family_profile(profile_name, mode=mode)
    return "ext_open_thinker" in profile.optional_families


def validate_external_reasoner_admission(
    *,
    profile_name: str,
    regime: str,
    gate_present: bool,
    guard_present: bool,
    schema_present: bool,
    fallback_present: bool,
) -> ExternalReasonerUseValidation:
    record = EXT_OPEN_THINKER_ADMISSION
    normalized_profile = str(profile_name or "").strip().lower()
    normalized_regime = str(regime or "").strip().lower()
    if normalized_profile not in set(record.admitted_lab_profiles):
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_profile_not_admitted",
        )
    if normalized_regime not in set(record.validated_regimes):
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_regime_not_validated",
        )
    if record.schema_required and not schema_present:
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_schema_required",
        )
    if record.guard_required and not guard_present:
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_guard_required",
        )
    if not gate_present:
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_gate_required",
        )
    if record.fallback_required and not fallback_present:
        return ExternalReasonerUseValidation(
            allowed=False,
            reason="external_reasoner_fallback_required",
        )
    return ExternalReasonerUseValidation(
        allowed=True,
        reason="external_reasoner_admitted_conditional_lab",
    )


def core_families_upper() -> Set[str]:
    return {family.upper() for family in CORE_SEQUENCE}


def optional_families_upper() -> Set[str]:
    return {family.upper() for family in TRACKED_OPTIONAL_FAMILIES}


def backbone_families_upper() -> Set[str]:
    return {family.upper() for family in BACKBONE_FAMILIES}


def augmenter_families_upper() -> Set[str]:
    return {family.upper() for family in AUGMENTER_FAMILIES}


def conditional_shadow_families_upper() -> Set[str]:
    return {family.upper() for family in CONDITIONAL_SHADOW_FAMILIES}


def profile_optional_families_upper(profile_name: str | None, *, mode: str = "fixed") -> Set[str]:
    profile = resolve_family_profile(profile_name, mode=mode)
    return {family.upper() for family in profile.optional_families}
