"""Motor de política para selección multiescala (MSRC)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .contracts import ProbeResult, ScaleAction, ScaleEstimate, ScalePolicyState
from .regime_classifier import RegimeClassification, RegimeClassifier
from .scale_catalog import ScaleCatalog


@dataclass(frozen=True)
class CandidateEval:
    scale_id: str
    cognitive_score: float
    viability_score: float
    meta_cost_penalty: float
    utility: float


@dataclass(frozen=True)
class RegimeProfile:
    name: str
    upgrade_threshold: float
    downgrade_threshold: float
    upgrade_evidence_n: int
    downgrade_evidence_n: int
    probe_activation_threshold: float
    probe_commit_threshold: float
    keep_scale_bias: float
    cooldown_steps: int
    post_commit_lock: int
    heterogeneity_weight: float
    epistemic_insufficiency_weight: float
    risk_weight: float
    vram_opportunity_weight: float
    required_weight: float
    oscillation_penalty_weight: float
    meta_cost_penalty_weight: float
    min_upgrade_cognitive_delta: float
    dominant_upgrade_delta: float


class ScalePolicyEngine:
    """Aplica objetivo lexicográfico: cognición -> viabilidad -> coste meta.

    DECIDE, NO APLICA. ``decide()`` devuelve una ``ScaleAction`` con la escala
    destino en ``target_scale_id`` y NO escribe ``state.current_scale_id``: el
    commit de la escala es de ``MSRCController.step``, y solo ocurre si el
    transition manager no aborta (CANON §3.1.6, atomicidad).

    Este motor sí actualiza el estado de POLÍTICA (evidencia, cooldown, lock,
    regret, historial): eso es hysteresis de la decisión, no la aplicación del
    cambio. El cooldown/lock se mantienen aunque la transición aborte después, lo
    que es conservador a propósito: evita martillar una transición que falla.

    Antes escribía ``state.current_scale_id`` acá mismo. Como el controller le
    pasaba después ese estado ya mutado al transition manager, un abort devolvía
    "la escala actual"... que ya era la NUEVA: la transición fallida quedaba
    aplicada igual, con ``rollback_applied=True`` en el registro.
    """

    def __init__(
        self,
        *,
        upgrade_threshold: float = 0.62,
        downgrade_threshold: float = 0.35,
        upgrade_evidence_n: int = 3,
        downgrade_evidence_n: int = 5,
        cooldown_steps: int = 2,
        post_commit_lock: int = 3,
        cognitive_equivalence_epsilon: float = 0.03,
        probe_activation_threshold: float = 0.55,
        probe_commit_threshold: float = 0.55,
        profile_name: str = "baseline",
        regime_classifier: Optional[RegimeClassifier] = None,
        regime_profiles: Optional[Mapping[str, RegimeProfile]] = None,
    ):
        self.upgrade_threshold = upgrade_threshold
        self.downgrade_threshold = downgrade_threshold
        self.upgrade_evidence_n = upgrade_evidence_n
        self.downgrade_evidence_n = downgrade_evidence_n
        self.cooldown_steps = cooldown_steps
        self.post_commit_lock = post_commit_lock
        self.cognitive_equivalence_epsilon = cognitive_equivalence_epsilon
        self.probe_activation_threshold = probe_activation_threshold
        self.probe_commit_threshold = probe_commit_threshold
        self.profile_name = profile_name
        self.regime_classifier = regime_classifier
        self.regime_profiles = dict(regime_profiles or {})

    @classmethod
    def baseline(cls) -> "ScalePolicyEngine":
        return cls(
            upgrade_threshold=0.62,
            downgrade_threshold=0.35,
            upgrade_evidence_n=3,
            downgrade_evidence_n=5,
            cooldown_steps=2,
            post_commit_lock=3,
            cognitive_equivalence_epsilon=0.03,
            probe_activation_threshold=0.55,
            probe_commit_threshold=0.55,
            profile_name="baseline",
        )

    @classmethod
    def aggressive(cls) -> "ScalePolicyEngine":
        return cls(
            upgrade_threshold=0.46,
            downgrade_threshold=0.28,
            upgrade_evidence_n=2,
            downgrade_evidence_n=6,
            cooldown_steps=1,
            post_commit_lock=2,
            cognitive_equivalence_epsilon=0.02,
            probe_activation_threshold=0.38,
            probe_commit_threshold=0.50,
            profile_name="aggressive",
        )

    @classmethod
    def regime_v3(cls) -> "ScalePolicyEngine":
        return cls(
            upgrade_threshold=0.46,
            downgrade_threshold=0.28,
            upgrade_evidence_n=2,
            downgrade_evidence_n=6,
            cooldown_steps=1,
            post_commit_lock=2,
            cognitive_equivalence_epsilon=0.02,
            probe_activation_threshold=0.38,
            probe_commit_threshold=0.50,
            profile_name="regime_v3",
            regime_classifier=RegimeClassifier(),
            regime_profiles=cls._default_regime_profiles(),
        )

    @staticmethod
    def _default_regime_profiles() -> Dict[str, RegimeProfile]:
        return {
            "homogeneous": RegimeProfile(
                name="homogeneous",
                upgrade_threshold=0.64,
                downgrade_threshold=0.24,
                upgrade_evidence_n=3,
                downgrade_evidence_n=4,
                probe_activation_threshold=0.58,
                probe_commit_threshold=0.60,
                keep_scale_bias=0.18,
                cooldown_steps=2,
                post_commit_lock=3,
                heterogeneity_weight=0.16,
                epistemic_insufficiency_weight=0.34,
                risk_weight=0.20,
                vram_opportunity_weight=0.10,
                required_weight=0.20,
                oscillation_penalty_weight=0.20,
                meta_cost_penalty_weight=0.25,
                min_upgrade_cognitive_delta=0.22,
                dominant_upgrade_delta=0.46,
            ),
            "heterogeneous": RegimeProfile(
                name="heterogeneous",
                upgrade_threshold=0.42,
                downgrade_threshold=0.26,
                upgrade_evidence_n=1,
                downgrade_evidence_n=6,
                probe_activation_threshold=0.30,
                probe_commit_threshold=0.46,
                keep_scale_bias=-0.10,
                cooldown_steps=1,
                post_commit_lock=2,
                heterogeneity_weight=0.42,
                epistemic_insufficiency_weight=0.22,
                risk_weight=0.14,
                vram_opportunity_weight=0.14,
                required_weight=0.22,
                oscillation_penalty_weight=0.14,
                meta_cost_penalty_weight=0.12,
                min_upgrade_cognitive_delta=0.10,
                dominant_upgrade_delta=0.35,
            ),
            "viability_edge": RegimeProfile(
                name="viability_edge",
                upgrade_threshold=0.45,
                downgrade_threshold=0.18,
                upgrade_evidence_n=2,
                downgrade_evidence_n=6,
                probe_activation_threshold=0.32,
                probe_commit_threshold=0.48,
                keep_scale_bias=-0.06,
                cooldown_steps=1,
                post_commit_lock=2,
                heterogeneity_weight=0.20,
                epistemic_insufficiency_weight=0.30,
                risk_weight=0.34,
                vram_opportunity_weight=0.18,
                required_weight=0.22,
                oscillation_penalty_weight=0.16,
                meta_cost_penalty_weight=0.12,
                min_upgrade_cognitive_delta=0.08,
                dominant_upgrade_delta=0.30,
            ),
        }

    @property
    def is_aggressive(self) -> bool:
        return self.profile_name in {"aggressive", "regime_v3"}

    @property
    def is_regime_v3(self) -> bool:
        return self.profile_name == "regime_v3"

    def decide(
        self,
        *,
        catalog: ScaleCatalog,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        probe_result: Optional[ProbeResult] = None,
    ) -> ScaleAction:
        state.step_index += 1
        if state.cooldown_remaining > 0:
            state.cooldown_remaining -= 1
        if state.lock_remaining > 0:
            state.lock_remaining -= 1

        classification: Optional[RegimeClassification] = None
        if self.is_regime_v3:
            classifier = self.regime_classifier or RegimeClassifier()
            classification = classifier.classify(estimate=estimate, state=state)
            state.register_regime(classification.regime_label)

        if state.probe_inflight_target and probe_result is not None:
            if classification is not None:
                profile = self._active_regime_profile(classification)
                action = self._handle_probe_result_regime(
                    state=state,
                    probe_result=probe_result,
                    profile=profile,
                    classification=classification,
                )
            else:
                action = self._handle_probe_result(state=state, probe_result=probe_result)
            state.register_action(action.action_type)
            return action

        if self.is_regime_v3:
            action = self._decide_regime_v3(
                catalog=catalog,
                state=state,
                estimate=estimate,
                classification=classification,
            )
            state.register_action(action.action_type)
            return action

        if state.lock_remaining > 0:
            action = ScaleAction(
                action_type="lock_scale_for_n_steps",
                target_scale_id=state.current_scale_id,
                reason="lock activo para evitar oscilación",
                lock_steps=state.lock_remaining,
            )
            state.register_action(action.action_type)
            return action

        evaluations = self._evaluate_candidates(
            catalog=catalog,
            estimate=estimate,
        )
        if not evaluations:
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="sin candidatos evaluables",
                metadata={
                    "profile": self.profile_name,
                    "current_scale_id": state.current_scale_id,
                },
            )
            state.register_action(action.action_type)
            return action

        selected = self._select_lexicographic(evaluations)
        current_spec = catalog.get(state.current_scale_id)
        selected_spec = catalog.get(selected.scale_id)
        current_eval = next(
            (item for item in evaluations if item.scale_id == state.current_scale_id),
            CandidateEval(
                scale_id=state.current_scale_id,
                cognitive_score=0.0,
                viability_score=0.0,
                meta_cost_penalty=1.0,
                utility=-1.0,
            ),
        )
        context = self._decision_context(
            state=state,
            estimate=estimate,
            selected=selected,
            current_eval=current_eval,
        )

        if state.cooldown_remaining > 0:
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="cooldown activo",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    blocked_by_cooldown=True,
                ),
            )
            state.register_action(action.action_type)
            return action

        if selected_spec.resolution_rank > current_spec.resolution_rank:
            return self._decide_upgrade(
                state=state,
                estimate=estimate,
                selected=selected,
                selected_spec=selected_spec,
                current_eval=current_eval,
                context=context,
            )

        if selected_spec.resolution_rank < current_spec.resolution_rank:
            return self._decide_downgrade(
                state=state,
                estimate=estimate,
                selected=selected,
                selected_spec=selected_spec,
                current_eval=current_eval,
                context=context,
            )

        action = ScaleAction(
            action_type="keep_scale",
            target_scale_id=state.current_scale_id,
            reason="escala actual ya es lexicográficamente óptima",
            expected_gain=current_eval.cognitive_score,
            expected_cost_penalty=current_eval.meta_cost_penalty,
            metadata=self._with_flags(context),
        )
        state.upgrade_evidence = 0
        state.downgrade_evidence = 0
        state.register_action(action.action_type)
        return action

    def _decide_regime_v3(
        self,
        *,
        catalog: ScaleCatalog,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        classification: Optional[RegimeClassification],
    ) -> ScaleAction:
        if classification is None:
            classifier = self.regime_classifier or RegimeClassifier()
            classification = classifier.classify(estimate=estimate, state=state)
            state.register_regime(classification.regime_label)

        profile = self._active_regime_profile(classification)

        evaluations = self._evaluate_candidates(catalog=catalog, estimate=estimate)
        if not evaluations:
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="sin candidatos evaluables",
                metadata={
                    "profile": self.profile_name,
                    **classification.to_dict(),
                },
            )

        selected = self._select_lexicographic(evaluations)
        current_spec = catalog.get(state.current_scale_id)
        selected_spec = catalog.get(selected.scale_id)
        current_eval = next(
            (item for item in evaluations if item.scale_id == state.current_scale_id),
            CandidateEval(
                scale_id=state.current_scale_id,
                cognitive_score=0.0,
                viability_score=0.0,
                meta_cost_penalty=1.0,
                utility=-1.0,
            ),
        )

        context = self._decision_context(
            state=state,
            estimate=estimate,
            selected=selected,
            current_eval=current_eval,
        )
        context.update(
            {
                **classification.to_dict(),
                "regime_profile": {
                    "name": profile.name,
                    "upgrade_threshold": profile.upgrade_threshold,
                    "downgrade_threshold": profile.downgrade_threshold,
                    "upgrade_evidence_n": profile.upgrade_evidence_n,
                    "downgrade_evidence_n": profile.downgrade_evidence_n,
                    "probe_activation_threshold": profile.probe_activation_threshold,
                    "probe_commit_threshold": profile.probe_commit_threshold,
                    "cooldown_steps": profile.cooldown_steps,
                    "post_commit_lock": profile.post_commit_lock,
                    "keep_scale_bias": profile.keep_scale_bias,
                },
            }
        )

        if state.lock_remaining > 0:
            return ScaleAction(
                action_type="lock_scale_for_n_steps",
                target_scale_id=state.current_scale_id,
                reason="lock activo para evitar oscilación",
                lock_steps=state.lock_remaining,
                metadata=self._with_flags(context, blocked_by_lock=True),
            )

        if state.cooldown_remaining > 0:
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="cooldown activo",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(context, blocked_by_cooldown=True),
            )

        if selected_spec.resolution_rank > current_spec.resolution_rank:
            return self._decide_upgrade_regime_v3(
                state=state,
                estimate=estimate,
                selected=selected,
                selected_spec=selected_spec,
                current_eval=current_eval,
                context=context,
                profile=profile,
                classification=classification,
            )

        if selected_spec.resolution_rank < current_spec.resolution_rank:
            return self._decide_downgrade_regime_v3(
                state=state,
                estimate=estimate,
                selected=selected,
                selected_spec=selected_spec,
                current_eval=current_eval,
                context=context,
                profile=profile,
                classification=classification,
            )

        return ScaleAction(
            action_type="keep_scale",
            target_scale_id=state.current_scale_id,
            reason="escala actual adecuada al régimen",
            expected_gain=current_eval.cognitive_score,
            expected_cost_penalty=current_eval.meta_cost_penalty,
            metadata=self._with_flags(context),
        )

    def _decide_upgrade_regime_v3(
        self,
        *,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        selected: CandidateEval,
        selected_spec,
        current_eval: CandidateEval,
        context: Dict[str, Any],
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> ScaleAction:
        cognitive_delta = selected.cognitive_score - current_eval.cognitive_score
        signal_score = self._regime_upgrade_signal_score(
            estimate=estimate,
            cognitive_delta=cognitive_delta,
            profile=profile,
            classification=classification,
        )
        if classification.regime_label == "homogeneous":
            signal = (
                signal_score >= profile.upgrade_threshold
                or estimate.required_resolution_score >= profile.upgrade_threshold
                or (
                    cognitive_delta >= max(profile.min_upgrade_cognitive_delta, 0.28)
                    and estimate.epistemic_insufficiency_score >= 0.20
                    and estimate.risk_score >= 0.22
                    and estimate.vram_opportunity_score >= 0.55
                )
            )
        else:
            signal = (
                signal_score >= profile.upgrade_threshold
                or estimate.required_resolution_score >= profile.upgrade_threshold
                or cognitive_delta >= profile.min_upgrade_cognitive_delta
            )

        if signal:
            state.upgrade_evidence += 1
            state.downgrade_evidence = 0
        else:
            state.upgrade_evidence = 0

        if state.upgrade_evidence < profile.upgrade_evidence_n:
            potential = self._missed_upgrade_potential(
                estimate=estimate,
                cognitive_delta=cognitive_delta,
                profile=profile,
                classification=classification,
            )
            if signal and potential >= (profile.upgrade_threshold + 0.06):
                state.missed_upgrade_regret += 1

            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="evidencia de upgrade insuficiente para el régimen",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=signal,
                    upgrade_signal_score=signal_score,
                    missed_upgrade_potential=potential,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                    missed_upgrade_regret=state.missed_upgrade_regret,
                ),
            )

        probe_signal = self._regime_probe_signal(
            estimate=estimate,
            profile=profile,
            classification=classification,
        )
        dominant_signal = (
            signal_score >= (profile.upgrade_threshold + 0.16)
            or cognitive_delta >= profile.dominant_upgrade_delta
            or estimate.required_resolution_score >= 0.82
        )
        should_probe = (
            probe_signal >= profile.probe_activation_threshold
            and not dominant_signal
            and estimate.vram_opportunity_score >= 0.45
            and estimate.vram_pressure < 0.93
            and estimate.vram_fragmentation_risk < 0.92
        )

        if should_probe:
            state.probe_inflight_target = selected.scale_id
            state.cooldown_remaining = profile.cooldown_steps
            return ScaleAction(
                action_type="fork_probe",
                target_scale_id=selected.scale_id,
                reason="régimen requiere sonda antes de migrar",
                expected_gain=cognitive_delta,
                expected_cost_penalty=selected.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=True,
                    triggered_probe_signal=True,
                    probe_signal=probe_signal,
                    probe_activation_threshold=profile.probe_activation_threshold,
                    upgrade_signal_score=signal_score,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )

        # SSOT: NO se escribe `state.current_scale_id` acá. Este motor DECIDE; el
        # commit de la escala lo hace MSRCController.step con lo que devuelve el
        # transition manager, y solo si la transición no aborta. La escala destino
        # ya viaja en `target_scale_id` de la acción.
        state.cooldown_remaining = profile.cooldown_steps
        state.lock_remaining = profile.post_commit_lock
        state.upgrade_evidence = 0

        return ScaleAction(
            action_type="upgrade_scale",
            target_scale_id=selected_spec.scale_id,
            reason="régimen favorece escalado cognitivo viable",
            expected_gain=cognitive_delta,
            expected_cost_penalty=selected.meta_cost_penalty,
            lock_steps=profile.post_commit_lock,
            metadata=self._with_flags(
                context,
                triggered_upgrade_signal=True,
                triggered_probe_signal=False,
                probe_signal=probe_signal,
                probe_activation_threshold=profile.probe_activation_threshold,
                upgrade_signal_score=signal_score,
                upgrade_evidence=state.upgrade_evidence,
                downgrade_evidence=state.downgrade_evidence,
            ),
        )

    def _decide_downgrade_regime_v3(
        self,
        *,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        selected: CandidateEval,
        selected_spec,
        current_eval: CandidateEval,
        context: Dict[str, Any],
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> ScaleAction:
        if estimate.required_resolution_score > profile.downgrade_threshold:
            state.downgrade_evidence = 0
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="demanda cognitiva del régimen bloquea downgrade",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )

        if classification.regime_label in {"heterogeneous", "viability_edge"} and (
            estimate.heterogeneity_score >= 0.20 or estimate.risk_score >= 0.44
        ):
            state.downgrade_evidence = 0
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="régimen activo requiere resolución actual",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )

        useful_gain = current_eval.cognitive_score - selected.cognitive_score
        if useful_gain > self.cognitive_equivalence_epsilon:
            state.downgrade_evidence = 0
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="resolución actual aún aporta ganancia útil",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    useful_gain=useful_gain,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )

        state.downgrade_evidence += 1
        state.upgrade_evidence = 0
        if state.downgrade_evidence < profile.downgrade_evidence_n:
            return ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="evidencia de downgrade insuficiente",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    useful_gain=useful_gain,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )

        # SSOT: el commit de escala es del controller (ver _decide_upgrade_regime_v3).
        state.cooldown_remaining = profile.cooldown_steps
        state.lock_remaining = max(1, profile.post_commit_lock - 1)
        state.downgrade_evidence = 0

        return ScaleAction(
            action_type="downgrade_scale",
            target_scale_id=selected_spec.scale_id,
            reason="resolución extra redundante para el régimen",
            expected_gain=selected.cognitive_score,
            expected_cost_penalty=selected.meta_cost_penalty,
            lock_steps=state.lock_remaining,
            metadata=self._with_flags(
                context,
                useful_gain=useful_gain,
                downgrade_evidence=state.downgrade_evidence,
            ),
        )

    def _active_regime_profile(self, classification: RegimeClassification) -> RegimeProfile:
        profiles = self.regime_profiles or self._default_regime_profiles()
        return profiles.get(classification.regime_label, profiles["homogeneous"])

    def _regime_upgrade_signal_score(
        self,
        *,
        estimate: ScaleEstimate,
        cognitive_delta: float,
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> float:
        score = (
            profile.required_weight * estimate.required_resolution_score
            + profile.heterogeneity_weight * estimate.heterogeneity_score
            + profile.epistemic_insufficiency_weight * estimate.epistemic_insufficiency_score
            + profile.risk_weight * estimate.risk_score
            + profile.vram_opportunity_weight * estimate.vram_opportunity_score
            + 0.25 * max(cognitive_delta, 0.0)
            - profile.keep_scale_bias
            - profile.oscillation_penalty_weight * min((estimate.signals.get("recent_oscillation", 0.0) or 0.0), 1.0)
            - profile.meta_cost_penalty_weight * estimate.operational_pressure_score
        )
        if "critical_high_signal" in classification.regime_tags:
            score += 0.08
        if "probe_favorable" in classification.regime_tags:
            score += 0.05
        return min(max(score, 0.0), 1.5)

    def _regime_probe_signal(
        self,
        *,
        estimate: ScaleEstimate,
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> float:
        score = (
            0.35 * estimate.epistemic_insufficiency_score
            + 0.25 * estimate.heterogeneity_score
            + 0.20 * estimate.risk_score
            + 0.20 * estimate.vram_opportunity_score
        )
        if "probe_favorable" in classification.regime_tags:
            score += 0.10
        return min(max(score, 0.0), 1.0)

    def _missed_upgrade_potential(
        self,
        *,
        estimate: ScaleEstimate,
        cognitive_delta: float,
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> float:
        potential = (
            0.50 * max(cognitive_delta, 0.0)
            + 0.20 * estimate.required_resolution_score
            + 0.15 * estimate.heterogeneity_score
            + 0.10 * estimate.epistemic_insufficiency_score
            + 0.05 * estimate.risk_score
        )
        if classification.regime_label in {"heterogeneous", "viability_edge"}:
            potential += 0.06
        return min(max(potential, 0.0), 1.2)

    def _handle_probe_result_regime(
        self,
        *,
        state: ScalePolicyState,
        probe_result: ProbeResult,
        profile: RegimeProfile,
        classification: RegimeClassification,
    ) -> ScaleAction:
        target = state.probe_inflight_target or probe_result.target_scale_id
        state.probe_inflight_target = None

        commit = (
            probe_result.outcome == "positive"
            and probe_result.viability_preserved
            and probe_result.evidence_score >= profile.probe_commit_threshold
        )
        if classification.regime_label == "homogeneous":
            commit = commit and probe_result.cognitive_gain_delta >= 0.03
        else:
            commit = commit and probe_result.cognitive_gain_delta >= -0.005

        if commit:
            # SSOT: el commit de escala es del controller (ver _decide_upgrade_regime_v3).
            state.cooldown_remaining = profile.cooldown_steps
            state.lock_remaining = profile.post_commit_lock
            return ScaleAction(
                action_type="commit_probe_result",
                target_scale_id=target,
                reason="probe committed según criterio del régimen",
                expected_gain=probe_result.cognitive_gain_delta,
                expected_cost_penalty=0.0,
                lock_steps=profile.post_commit_lock,
                metadata={
                    **probe_result.to_dict(),
                    **classification.to_dict(),
                    "profile": self.profile_name,
                    "probe_commit_threshold": profile.probe_commit_threshold,
                    "upgrade_evidence": state.upgrade_evidence,
                    "downgrade_evidence": state.downgrade_evidence,
                    "missed_upgrade_regret": state.missed_upgrade_regret,
                },
            )

        if probe_result.outcome == "negative":
            state.upgrade_regret += 1

        return ScaleAction(
            action_type="discard_probe_result",
            target_scale_id=state.current_scale_id,
            reason="probe descartado por criterio del régimen",
            expected_gain=probe_result.cognitive_gain_delta,
            expected_cost_penalty=0.0,
            metadata={
                **probe_result.to_dict(),
                **classification.to_dict(),
                "profile": self.profile_name,
                "probe_commit_threshold": profile.probe_commit_threshold,
                "upgrade_evidence": state.upgrade_evidence,
                "downgrade_evidence": state.downgrade_evidence,
                "missed_upgrade_regret": state.missed_upgrade_regret,
            },
        )

    def _handle_probe_result(self, *, state: ScalePolicyState, probe_result: ProbeResult) -> ScaleAction:
        target = state.probe_inflight_target or probe_result.target_scale_id
        state.probe_inflight_target = None
        if (
            probe_result.outcome == "positive"
            and probe_result.viability_preserved
            and probe_result.evidence_score >= self.probe_commit_threshold
        ):
            # SSOT: el commit de escala es del controller (ver _decide_upgrade_regime_v3).
            state.cooldown_remaining = self.cooldown_steps
            state.lock_remaining = self.post_commit_lock
            action = ScaleAction(
                action_type="commit_probe_result",
                target_scale_id=target,
                reason="probe demostró ganancia cognitiva viable",
                expected_gain=probe_result.cognitive_gain_delta,
                expected_cost_penalty=0.0,
                lock_steps=self.post_commit_lock,
                metadata={
                    **probe_result.to_dict(),
                    "profile": self.profile_name,
                    "probe_commit_threshold": self.probe_commit_threshold,
                    "upgrade_evidence": state.upgrade_evidence,
                    "downgrade_evidence": state.downgrade_evidence,
                    "missed_upgrade_regret": state.missed_upgrade_regret,
                },
            )
        else:
            if probe_result.outcome == "negative":
                state.upgrade_regret += 1
            action = ScaleAction(
                action_type="discard_probe_result",
                target_scale_id=state.current_scale_id,
                reason="probe no alcanzó evidencia/viabilidad requerida",
                expected_gain=probe_result.cognitive_gain_delta,
                expected_cost_penalty=0.0,
                metadata={
                    **probe_result.to_dict(),
                    "profile": self.profile_name,
                    "probe_commit_threshold": self.probe_commit_threshold,
                    "upgrade_evidence": state.upgrade_evidence,
                    "downgrade_evidence": state.downgrade_evidence,
                    "missed_upgrade_regret": state.missed_upgrade_regret,
                },
            )
        return action

    def _decide_upgrade(
        self,
        *,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        selected: CandidateEval,
        selected_spec,
        current_eval: CandidateEval,
        context: Dict[str, Any],
    ) -> ScaleAction:
        cognitive_delta = selected.cognitive_score - current_eval.cognitive_score
        signal, signal_reasons = self._upgrade_signal(
            estimate=estimate,
            cognitive_delta=cognitive_delta,
        )

        if signal:
            state.upgrade_evidence += 1
            state.downgrade_evidence = 0
        else:
            state.upgrade_evidence = 0

        if state.upgrade_evidence < self.upgrade_evidence_n:
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="evidencia de upgrade aún insuficiente",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=signal,
                    upgrade_signal_reasons=signal_reasons,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )
            state.register_action(action.action_type)
            return action

        probe_signal = self._probe_signal(estimate)
        should_probe = self._should_probe(
            estimate=estimate,
            cognitive_delta=cognitive_delta,
            probe_signal=probe_signal,
        )
        if should_probe:
            state.probe_inflight_target = selected.scale_id
            state.cooldown_remaining = self.cooldown_steps
            action = ScaleAction(
                action_type="fork_probe",
                target_scale_id=selected.scale_id,
                reason="señal de upgrade con incertidumbre: ejecutar sonda",
                expected_gain=cognitive_delta,
                expected_cost_penalty=selected.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=True,
                    triggered_probe_signal=True,
                    probe_signal=probe_signal,
                    probe_activation_threshold=self.probe_activation_threshold,
                    upgrade_signal_reasons=signal_reasons,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )
            state.register_action(action.action_type)
            return action

        # SSOT: el commit de escala es del controller (ver _decide_upgrade_regime_v3).
        state.cooldown_remaining = self.cooldown_steps
        state.lock_remaining = self.post_commit_lock
        action = ScaleAction(
            action_type="upgrade_scale",
            target_scale_id=selected_spec.scale_id,
            reason="cumple prioridad cognitiva y viabilidad con evidencia acumulada",
            expected_gain=cognitive_delta,
            expected_cost_penalty=selected.meta_cost_penalty,
            lock_steps=self.post_commit_lock,
            metadata=self._with_flags(
                context,
                triggered_upgrade_signal=True,
                triggered_probe_signal=False,
                probe_signal=probe_signal,
                probe_activation_threshold=self.probe_activation_threshold,
                upgrade_signal_reasons=signal_reasons,
                upgrade_evidence=state.upgrade_evidence,
                downgrade_evidence=state.downgrade_evidence,
            ),
        )
        state.upgrade_evidence = 0
        state.register_action(action.action_type)
        return action

    def _decide_downgrade(
        self,
        *,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        selected: CandidateEval,
        selected_spec,
        current_eval: CandidateEval,
        context: Dict[str, Any],
    ) -> ScaleAction:
        if estimate.required_resolution_score > self.downgrade_threshold:
            state.downgrade_evidence = 0
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="demanda cognitiva no permite downgrade",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=False,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )
            state.register_action(action.action_type)
            return action

        useful_gain = current_eval.cognitive_score - selected.cognitive_score
        if useful_gain > self.cognitive_equivalence_epsilon:
            state.downgrade_evidence = 0
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="resolución actual aún aporta ganancia útil",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=False,
                    useful_gain=useful_gain,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )
            state.register_action(action.action_type)
            return action

        state.downgrade_evidence += 1
        state.upgrade_evidence = 0
        if state.downgrade_evidence < self.downgrade_evidence_n:
            action = ScaleAction(
                action_type="keep_scale",
                target_scale_id=state.current_scale_id,
                reason="evidencia de downgrade insuficiente",
                expected_gain=current_eval.cognitive_score,
                expected_cost_penalty=current_eval.meta_cost_penalty,
                metadata=self._with_flags(
                    context,
                    triggered_upgrade_signal=False,
                    useful_gain=useful_gain,
                    upgrade_evidence=state.upgrade_evidence,
                    downgrade_evidence=state.downgrade_evidence,
                ),
            )
            state.register_action(action.action_type)
            return action

        # SSOT: el commit de escala es del controller (ver _decide_upgrade_regime_v3).
        state.cooldown_remaining = self.cooldown_steps
        state.lock_remaining = max(1, self.post_commit_lock - 1)
        action = ScaleAction(
            action_type="downgrade_scale",
            target_scale_id=selected_spec.scale_id,
            reason="resolución extra dejó de aportar inteligencia útil",
            expected_gain=selected.cognitive_score,
            expected_cost_penalty=selected.meta_cost_penalty,
            lock_steps=state.lock_remaining,
            metadata=self._with_flags(
                context,
                triggered_upgrade_signal=False,
                useful_gain=useful_gain,
                upgrade_evidence=state.upgrade_evidence,
                downgrade_evidence=state.downgrade_evidence,
            ),
        )
        state.downgrade_evidence = 0
        state.register_action(action.action_type)
        return action

    def _upgrade_signal(
        self,
        *,
        estimate: ScaleEstimate,
        cognitive_delta: float,
    ) -> Tuple[bool, List[str]]:
        if not self.is_aggressive:
            signal = estimate.required_resolution_score >= self.upgrade_threshold
            reasons: List[str] = []
            if signal:
                reasons.append("required_resolution")
            if cognitive_delta >= 0.06:
                signal = True
                reasons.append("cognitive_delta")
            return signal, reasons

        conditions = {
            "required_resolution": estimate.required_resolution_score >= self.upgrade_threshold,
            "heterogeneity": estimate.heterogeneity_score >= 0.22,
            "epistemic_insufficiency": estimate.epistemic_insufficiency_score >= 0.20,
            "risk": estimate.risk_score >= 0.40,
            "cognitive_vram_combo": (
                cognitive_delta >= 0.12
                and estimate.vram_opportunity_score >= 0.55
                and (estimate.risk_score >= 0.35 or estimate.epistemic_insufficiency_score >= 0.18)
            ),
        }
        reasons = [name for name, ok in conditions.items() if ok]
        return bool(reasons), reasons

    def _probe_signal(self, estimate: ScaleEstimate) -> float:
        return min(
            max(
                (0.35 * estimate.epistemic_insufficiency_score)
                + (0.25 * estimate.heterogeneity_score)
                + (0.20 * estimate.risk_score)
                + (0.20 * estimate.vram_opportunity_score),
                0.0,
            ),
            1.0,
        )

    def _should_probe(
        self,
        *,
        estimate: ScaleEstimate,
        cognitive_delta: float,
        probe_signal: float,
    ) -> bool:
        if not self.is_aggressive:
            return estimate.epistemic_insufficiency_score >= self.probe_activation_threshold

        dominant_signal = (
            estimate.required_resolution_score >= 0.72
            or cognitive_delta >= 0.45
            or estimate.risk_score >= 0.72
        )
        return (
            probe_signal >= self.probe_activation_threshold
            and not dominant_signal
            and estimate.vram_opportunity_score >= 0.45
            and estimate.vram_pressure < 0.93
            and estimate.vram_fragmentation_risk < 0.92
        )

    def _decision_context(
        self,
        *,
        state: ScalePolicyState,
        estimate: ScaleEstimate,
        selected: CandidateEval,
        current_eval: CandidateEval,
    ) -> Dict[str, Any]:
        return {
            "profile": self.profile_name,
            "current_scale_id": state.current_scale_id,
            "candidate_scale_id": selected.scale_id,
            "cognitive_delta": selected.cognitive_score - current_eval.cognitive_score,
            "viability_score": selected.viability_score,
            "meta_cost_penalty": selected.meta_cost_penalty,
            "required_resolution_score": estimate.required_resolution_score,
            "heterogeneity_score": estimate.heterogeneity_score,
            "epistemic_insufficiency_score": estimate.epistemic_insufficiency_score,
            "risk_score": estimate.risk_score,
            "operational_pressure_score": estimate.operational_pressure_score,
            "vram_headroom": estimate.vram_headroom,
            "vram_pressure": estimate.vram_pressure,
            "vram_fragmentation_risk": estimate.vram_fragmentation_risk,
            "vram_opportunity_score": estimate.vram_opportunity_score,
            "upgrade_threshold": self.upgrade_threshold,
            "downgrade_threshold": self.downgrade_threshold,
            "probe_activation_threshold": self.probe_activation_threshold,
            "probe_commit_threshold": self.probe_commit_threshold,
            "upgrade_evidence": state.upgrade_evidence,
            "downgrade_evidence": state.downgrade_evidence,
            "missed_upgrade_regret": state.missed_upgrade_regret,
            "regime_history": list(state.regime_history[-6:]),
        }

    def _with_flags(
        self,
        context: Dict[str, Any],
        **extra: Any,
    ) -> Dict[str, Any]:
        merged = dict(context)
        merged.update(extra)
        return merged

    def _evaluate_candidates(
        self,
        *,
        catalog: ScaleCatalog,
        estimate: ScaleEstimate,
    ) -> List[CandidateEval]:
        candidates: List[str] = []
        for scale_id in estimate.recommended_scale_candidates:
            if not catalog.has_scale(scale_id):
                continue
            spec = catalog.get(scale_id)
            if not spec.is_executable:
                spec = catalog.nearest_executable(scale_id)
            if spec.scale_id not in candidates:
                candidates.append(spec.scale_id)

        if not candidates:
            candidates = [spec.scale_id for spec in catalog.executable_scales()]

        evaluations: List[CandidateEval] = []
        for scale_id in candidates:
            spec = catalog.get(scale_id)
            cognitive_score = self._estimate_cognitive_gain(spec=spec, estimate=estimate)
            viability_score = self._estimate_viability(spec=spec, estimate=estimate)
            meta_cost_penalty = self._estimate_meta_cost_penalty(spec=spec, estimate=estimate)
            utility = cognitive_score - meta_cost_penalty
            if viability_score <= 0.0:
                utility = -999.0
            evaluations.append(
                CandidateEval(
                    scale_id=scale_id,
                    cognitive_score=cognitive_score,
                    viability_score=viability_score,
                    meta_cost_penalty=meta_cost_penalty,
                    utility=utility,
                )
            )
        return evaluations

    def _select_lexicographic(self, evaluations: List[CandidateEval]) -> CandidateEval:
        viable = [item for item in evaluations if item.viability_score > 0.0]
        if not viable:
            return sorted(evaluations, key=lambda item: item.utility, reverse=True)[0]

        max_cognitive = max(item.cognitive_score for item in viable)
        top_cognitive = [
            item
            for item in viable
            if (max_cognitive - item.cognitive_score) <= self.cognitive_equivalence_epsilon
        ]
        return sorted(top_cognitive, key=lambda item: (item.meta_cost_penalty, -item.utility))[0]

    def _estimate_cognitive_gain(self, *, spec, estimate: ScaleEstimate) -> float:
        structure_bonus = 0.0
        if spec.supports_local_structure:
            structure_bonus += 0.18 * estimate.heterogeneity_score
        if spec.supports_spatial_memory:
            structure_bonus += 0.14 * estimate.epistemic_insufficiency_score
        if spec.supports_local_intervention:
            structure_bonus += 0.10 * estimate.risk_score

        if self.is_aggressive:
            structure_bonus += 0.08 * estimate.heterogeneity_score
            structure_bonus += 0.07 * estimate.epistemic_insufficiency_score
            structure_bonus += 0.06 * estimate.risk_score

        vram_bonus = estimate.vram_opportunity_score * min(spec.resolution_rank / 10.0, 1.0) * 0.22
        required_fit = 1.0 - abs(estimate.required_resolution_score - min(spec.resolution_rank / 30.0, 1.0))

        score = (
            0.55 * spec.expected_information_gain_prior
            + 0.20 * max(required_fit, 0.0)
            + structure_bonus
            + vram_bonus
        )
        return min(max(score, 0.0), 1.5)

    def _estimate_viability(self, *, spec, estimate: ScaleEstimate) -> float:
        if estimate.risk_score >= 0.92 and not spec.supports_local_structure:
            return 0.0
        if estimate.vram_pressure > 0.95 and spec.resolution_rank > 5 and estimate.vram_opportunity_score < 0.25:
            return 0.0
        if estimate.vram_pressure > 0.90 and estimate.vram_fragmentation_risk > 0.90 and spec.resolution_rank > 5:
            return 0.0
        return max(1.0 - (0.55 * estimate.risk_score), 0.05)

    def _estimate_meta_cost_penalty(self, *, spec, estimate: ScaleEstimate) -> float:
        time_pen = min(spec.expected_time_cost / 10.0, 1.0)
        artifact_pen = min(spec.expected_artifact_cost / 15.0, 1.0)
        operational = estimate.operational_pressure_score
        oscillation_pen = min((estimate.signals.get("recent_oscillation", 0.0) or 0.0), 1.0)

        vram_pen = 0.0
        if estimate.vram_pressure > 0.85:
            vram_pen = (estimate.vram_pressure - 0.85) / 0.15
        if estimate.vram_fragmentation_risk > 0.88:
            vram_pen = max(vram_pen, (estimate.vram_fragmentation_risk - 0.88) / 0.12)

        base_penalty = (
            0.30 * time_pen
            + 0.20 * artifact_pen
            + 0.25 * operational
            + 0.10 * oscillation_pen
            + 0.15 * vram_pen
        )
        if self.is_aggressive:
            return 0.85 * base_penalty
        return base_penalty
