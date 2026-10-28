"""Gate formal de propuesta -> certificación -> promoción/rechazo."""

from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from runtime.memory.mfm_lite import EpisodeMemoryStore, MFMCondenser, MacroPromotion
from runtime.organism.court_runtime import ConstitutionalCourtRuntime
from runtime.organism.t5_mode import get_t5_mode
from runtime.reality.collapse import CollapseDetector
from runtime.reality.evaluator import evaluate_episode_closure
from runtime.storage import StorageFacade

# P9.6 paso 4 — ventana de historia para el detector de colapso. `CollapseDetector` exige
# una RACHA (streak=3) de continuidad bajo umbral: un bache aislado no es un colapso.
_COLLAPSE_HISTORY = 3

from .certificate_builder import CertificateBuilder
from .coherence_obstruction import CoherenceObstructionTracker
from .continuity_guard import ContinuityGuard
from .ioc_proxy import IoCProxy
from .risk_engine import EpisodeRiskTracker, sample_b_safe_telemetry


class PromotionGate:
    def __init__(self, *, storage: StorageFacade):
        self.storage = storage
        self.builder = CertificateBuilder(storage=storage)
        self.continuity_guard = ContinuityGuard()
        # P9.6 paso 4: el detector de colapso del propio repo (`runtime/reality/collapse.py`),
        # que hasta ahora solo usaba el BENCH. El camino vivo no lo llamaba nunca.
        self.collapse_detector = CollapseDetector()
        self.ioc_proxy = IoCProxy()
        self.risk_tracker = EpisodeRiskTracker(storage=storage)
        self.omega_tracker = CoherenceObstructionTracker(storage=storage)
        self.memory_store = EpisodeMemoryStore(storage=storage)
        self.condenser = MFMCondenser()
        self.macro_promotion = MacroPromotion(storage=storage)
        self.court_runtime = ConstitutionalCourtRuntime(storage=storage)

    def process_episode(
        self,
        *,
        run_id: str,
        episode_result: Dict[str, Any],
        reality_assessment=None,
        compatibility=None,
        transition_vector=None,
        belief_shift=None,
        retrieval_metrics: Dict[str, Any] | None = None,
        organism_state=None,
    ) -> Dict[str, Any]:
        """Certifica un episodio.

        P9.6 (paso 1 — CABLEAR): ``belief_shift`` y ``retrieval_metrics`` se suman a los
        insumos que el gate ya aceptaba pero que NADIE le pasaba en el camino vivo
        (``compatibility``/``transition_vector``/``reality_assessment``). Con los insumos
        ausentes, ``assess_transfer`` los rellenaba con valores FAVORABLES —
        ``memory_purity=1.0``, ``stability=1.0``, ``kl=0.0`` — y ningún detector podía
        contradecirlos: el organismo se auto-certificaba sano por falta de datos.

        Todos siguen siendo opcionales: un dato ausente es AUSENCIA (se registra), no un
        número inventado. Ver ``TransferAssessment.unmeasured_fields``.
        """
        episode = episode_result.get("episode", {})

        # Extract scenario_metadata with fallback
        scenario_metadata = episode.get("scenario_metadata")
        if scenario_metadata is None:
            scenario_name = episode.get("scenario", "unknown")
            scenario_metadata = {"scenario_name": scenario_name}

        # Extract closure_profile from episode contract
        closure_profile = (
            episode.get("closure_profile")
            or episode.get("context", {}).get("closure_profile", "baseline_fixed")
        )

        closure = evaluate_episode_closure(
            storage=self.storage, run_id=run_id, result=episode_result,
            closure_profile=closure_profile,
        )
        # P9.6 paso 4: se traen los últimos N (no 1) — el detector de colapso necesita RACHA.
        previous = self.storage.list_episode_certificates(
            run_id=run_id, limit=_COLLAPSE_HISTORY
        )
        previous_certificate = previous[0] if previous else None
        fallback_continuity = (
            float(reality_assessment.continuity_score) if reality_assessment is not None else None
        )
        continuity = self.continuity_guard.score(
            previous_certificate=previous_certificate,
            current_episode=episode,
            fallback_continuity=fallback_continuity,
        )
        continuity_alert = self.continuity_guard.has_alert(continuity)

        # ── P9.6 paso 4 — EL ORGANISMO PUEDE DETECTAR SU PROPIO COLAPSO ──────────
        # Antes:
        #     collapse_detected = bool(getattr(reality_assessment, "collapse_detected", False))
        # y en producción `reality_assessment` es SIEMPRE None (nadie lo construye en el
        # camino vivo: solo lo arma el bench, `runtime/reality/service.py`). O sea:
        # `collapse_detected` era SIEMPRE False. Y es el ÚNICO que gatea el veredicto
        # (`certificate_builder.py:55`). El organismo era estructuralmente incapaz de
        # detectar su propio colapso: la única compuerta que tenía estaba ciega.
        #
        # Ahora se ejecuta el detector REAL del repo con los datos que este gate YA TIENE
        # medidos (no hay ningún dato nuevo que inventar):
        #   - closure_passed / trace_integrity: de `evaluate_episode_closure` (arriba).
        #   - continuity: del `ContinuityGuard` (arriba).
        #   - historia: los últimos certificados de la corrida. `CollapseDetector` solo lee
        #     `.continuity_score`, que `EpisodeCertificateRecord` expone. En el camino vivo
        #     NADIE escribe `RealityAssessmentRecord`s, así que los certificados son la
        #     única historia de continuidad que existe — y es real.
        #
        # POR QUÉ ESTO NO RECHAZA EPISODIOS SANOS (la pregunta que exige el paquete):
        # `CollapseDetector.detect` da True en dos casos:
        #   (a) `not closure_passed or not trace_integrity` → esos episodios YA eran
        #       `rejected` por el propio veredicto (`certified if closure and trace and not
        #       collapse`). No agrega NINGÚN rechazo nuevo; solo hace visible el motivo.
        #   (b) continuidad < 0.35 sostenida en RACHA (3 episodios) → único rechazo NUEVO.
        #       Un episodio sano tiene continuidad ≈ 0.98: no se le acerca. Y un bache
        #       aislado tampoco alcanza: hace falta que el organismo esté realmente roto,
        #       tres episodios seguidos.
        #
        # El `reality_assessment` explícito (camino del bench) se respeta y se une con OR:
        # si el bench ya dictaminó colapso, no lo contradecimos.
        declared_collapse = bool(getattr(reality_assessment, "collapse_detected", False))
        measured_collapse = self.collapse_detector.detect(
            closure_passed=closure["closure_passed"],
            trace_integrity=closure["trace_integrity"],
            continuity_score=continuity,
            recent_assessments=previous,
        )
        collapse_detected = declared_collapse or measured_collapse
        uncertainty = float(episode.get("context", {}).get("uncertainty", 0.2))
        ioc_value = self.ioc_proxy.compute(
            continuity_score=continuity,
            closure_passed=closure["closure_passed"],
            trace_integrity=closure["trace_integrity"],
            collapse_detected=collapse_detected,
            uncertainty=uncertainty,
        )

        # Ωₜ: obstrucción de coherencia multi-contexto + IoC* (modo sombra)
        omega = self.omega_tracker.assess(
            run_id=run_id,
            episode_result=episode_result,
            ioc_value=ioc_value,
        )

        # Riesgo de cola 𝔠ₜ⁺ (modo sombra: no altera el veredicto existente)
        risk_plus = self.risk_tracker.assess(
            run_id=run_id,
            ioc_value=ioc_value,
            hard_violation_count=int(
                (episode_result.get("constitutional_validation") or {}).get(
                    "hard_violation_count", 0
                )
                or 0
            ),
            b_safe=sample_b_safe_telemetry(),
        )

        # Transfer assessment
        from .transfer_assessment import assess_transfer

        transfer = assess_transfer(
            episode_result=episode_result,
            compatibility=compatibility,
            transition_vector=transition_vector,
            belief_shift=belief_shift,
            retrieval_metrics=retrieval_metrics,
        )
        t5_mode = get_t5_mode()
        # D-047: se reenvía el estado autoritativo para que el tribunal OBSERVE
        # en vez de acuñar una segunda transición fisiológica. Explícito y no por
        # una clave más en `episode_result`: así queda auditable quién le dio la
        # fisiología al tribunal.
        t5_result = self.court_runtime.ingest_episode(
            run_id=run_id,
            episode_result=episode_result,
            organism_state=organism_state,
        )
        transfer_metadata = {
            "compatibility_class": transfer.compatibility_class,
            "transfer_verdict": transfer.transfer_verdict,
            "memory_purity_score": transfer.memory_purity_score,
            "transition_stability_score": transfer.transition_stability_score,
            "cross_scenario_evidence_used": transfer.cross_scenario_evidence_used,
            "analogical_source_present": transfer.analogical_source_present,
            "transfer_posterior": transfer.transfer_posterior,
            "lower_confidence_bound": transfer.lower_confidence_bound,
            "certificate_scope": transfer.certificate_scope,
            "failure_mode_count": transfer.failure_mode_count,
            # P9.6 — las patologías entran al certificado con NOMBRE y severidad, no como un
            # contador mudo. Siguen siendo METADATA: no gatean veredicto ni candidatura
            # (decisión conservadora explícita del paquete). Lo que cambia es que ahora son
            # alcanzables y se evalúan también en episodios locales.
            "failure_modes": [
                {
                    "mode": m.mode,
                    "severity": m.severity,
                    "evidence_score": m.evidence_score,
                    "description": m.description,
                }
                for m in transfer.failure_modes
            ],
            "failure_mode_scope": transfer.failure_mode_scope,
            "detector_checks_applied": list(transfer.detector_checks_applied),
            # P9.6 paso 5 — la ausencia viaja CON el certificado. `memory_purity_score: null`
            # ya no puede leerse como 1.0 por quien lo consuma (ver `vitals.py`), y
            # `memory_purity_basis` dice si el 1.0 se ganó midiendo o si no hubo siquiera
            # oportunidad de contaminarse.
            "unmeasured_fields": list(transfer.unmeasured_fields),
            # B85 — el TERCER estado viaja con el certificado. `not_applicable_fields` no es
            # un agujero (eso es `unmeasured_fields`): es un eje SIN SUJETO — con cero hits no
            # hay memoria que pueda estar contaminada. Sin esta clave, el consumidor
            # (`runtime/life/vitals.py`) solo puede leer el 1.0 vacuo como si fuera una
            # medición, y la compuerta del refugio lo cuenta como eje VERIFICADO. Lo era: una
            # verificación que nunca ocurrió.
            "not_applicable_fields": list(transfer.not_applicable_fields),
            "memory_purity_basis": transfer.memory_purity_basis,
        }
        causal_attestation = (episode.get("context") or {}).get("causal_attestation")
        if isinstance(causal_attestation, dict):
            transfer_metadata["causal_attestation"] = causal_attestation
        if t5_result is not None:
            scope_to_transfer_verdict = {
                "local_safe": "certified_local",
                "transfer_safe": "certified_transfer_safe",
                "modification_safe": "certified_transfer_safe",
                "inheritance_safe": "certified_transfer_safe",
                "quarantine_only": "certified_analogical_only",
                "blocked": "rejected_for_transfer",
            }
            t5_payload = {
                "mode": t5_mode,
                "scope": t5_result.canonical_scope,
                "legacy_scope": t5_result.legacy_scope,
                "transfer_advice": t5_result.transfer_advice,
                "flow_validity": t5_result.flow_validity,
                "erosion": t5_result.erosion,
                "phase_drift": t5_result.phase_drift,
                "rollback_obligation": t5_result.rollback_obligation,
                "viability_score": t5_result.viability_score,
                "organism_risk": t5_result.organism_risk,
                "edge_risk": t5_result.edge_risk,
                "modification_risk": t5_result.modification_risk,
                "inheritance_risk": t5_result.inheritance_risk,
                "failure_mode_count": t5_result.failure_mode_count,
                "renormalization_residual": t5_result.renormalization_residual,
                "renormalization_uncertainty": t5_result.renormalization_uncertainty,
                "expected_recovery_cost": t5_result.expected_recovery_cost,
                "trajectory_id": t5_result.trajectory_id,
            }
            transfer_metadata["t5"] = t5_payload
            transfer_metadata["t4"] = t5_payload  # alias de compatibilidad
            if t5_mode == "on":
                transfer_metadata["legacy_certificate_scope"] = transfer_metadata.get("certificate_scope", "local_only")
                transfer_metadata["certificate_scope"] = t5_result.canonical_scope
                transfer_metadata["transfer_scope_legacy"] = t5_result.legacy_scope
                transfer_metadata["transfer_verdict"] = scope_to_transfer_verdict.get(
                    t5_result.canonical_scope,
                    transfer.transfer_verdict,
                )
                transfer_metadata["failure_mode_count"] = max(
                    int(transfer_metadata["failure_mode_count"]),
                    t5_result.failure_mode_count,
                )
                if t5_result.transfer_advice:
                    transfer_metadata["transfer_advice"] = t5_result.transfer_advice

        proposal = {
            "proposal_id": f"proposal-{uuid4()}",
            "origin": "promotion_gate",
            "change": {"episode_id": episode.get("episode_id"), "run_id": run_id},
            "risk": "low" if ioc_value >= 0.72 else "medium",
            "metadata": {
                "ioc_proxy": ioc_value,
                "continuity_score": continuity,
                "scenario_metadata": scenario_metadata,
                "closure_profile": closure_profile,
                "transfer_assessment": transfer_metadata,
            },
        }
        self.storage.append_event(
            event_type="proposal.evaluated",
            run_id=run_id,
            source="promotion_gate",
            payload=proposal,
        )

        certificate = self.builder.build_and_persist(
            run_id=run_id,
            episode_result=episode_result,
            continuity_score=continuity,
            ioc_proxy=ioc_value,
            continuity_alert=continuity_alert,
            closure_passed=closure["closure_passed"],
            trace_integrity=closure["trace_integrity"],
            collapse_detected=collapse_detected,
            transfer_assessment=transfer_metadata,
            risk_plus=risk_plus,
            omega=omega,
        )
        if t5_result is not None and t5_mode == "on":
            max_t4_risk = max(
                t5_result.organism_risk,
                t5_result.edge_risk,
                t5_result.modification_risk,
                t5_result.inheritance_risk,
            )
            t4_blocks = (
                t5_result.canonical_scope in {"blocked", "quarantine_only"}
                or t5_result.rollback_obligation
                or max_t4_risk >= 0.85
            )
            adjusted_verdict = "rejected" if t4_blocks else certificate.verdict
            adjusted_promotion_candidate = bool(
                certificate.promotion_candidate
                and not t4_blocks
                and max_t4_risk < 0.60
            )
            adjusted_risk = max(certificate.risk_score, max_t4_risk)
            if (
                adjusted_verdict != certificate.verdict
                or adjusted_promotion_candidate != certificate.promotion_candidate
                or adjusted_risk != certificate.risk_score
            ):
                certificate = self.storage.write_episode_certificate(
                    certificate_id=certificate.certificate_id,
                    episode_id=certificate.episode_id,
                    run_id=certificate.run_id,
                    trace_id=certificate.trace_id,
                    smg_artifacts=certificate.smg_artifacts,
                    lotf_artifacts=certificate.lotf_artifacts,
                    world_artifacts=certificate.world_artifacts,
                    continuity_score=certificate.continuity_score,
                    ioc_proxy=certificate.ioc_proxy,
                    risk_score=adjusted_risk,
                    verdict=adjusted_verdict,
                    rollback_ready=certificate.rollback_ready or t5_result.rollback_obligation,
                    promotion_candidate=adjusted_promotion_candidate,
                    metadata={
                        **certificate.metadata,
                        "t5": transfer_metadata.get("t5", {}),
                        "t4": transfer_metadata.get("t4", {}),
                    },
                )
        decision_verdict = "promote" if certificate.promotion_candidate else "reject"
        decision_reason = (
            "certificate_gate_passed"
            if certificate.promotion_candidate
            else "certificate_gate_failed"
        )
        decision = self.storage.write_promotion_decision(
            episode_id=certificate.episode_id,
            run_id=run_id,
            certificate_id=certificate.certificate_id,
            verdict=decision_verdict,
            reason=decision_reason,
            rollback_ready=certificate.rollback_ready,
            metadata={
                "ioc_proxy": certificate.ioc_proxy,
                "risk_score": certificate.risk_score,
                "scenario_metadata": scenario_metadata,
                "closure_profile": closure_profile,
            },
        )

        memory_updates: Dict[str, Any] = {"micro": None, "meso": None, "macro": None}
        memory_extra_metadata = {
            "scenario_metadata": scenario_metadata,
            "closure_profile": closure_profile,
        }
        if certificate.verdict == "certified":
            micro = self.memory_store.write_micro(
                run_id=run_id,
                episode_id=certificate.episode_id,
                certificate_id=certificate.certificate_id,
                ioc_proxy=certificate.ioc_proxy,
                structure=self.condenser.micro(
                    episode_result=episode_result,
                    certificate=certificate,
                ),
                extra_metadata=memory_extra_metadata,
            )
            meso_structure = self.condenser.meso(
                episode_result=episode_result,
                certificate=certificate,
            )
            meso = self.memory_store.write_meso(
                run_id=run_id,
                episode_id=certificate.episode_id,
                certificate_id=certificate.certificate_id,
                ioc_proxy=certificate.ioc_proxy,
                structure=meso_structure,
                extra_metadata=memory_extra_metadata,
            )
            memory_updates["micro"] = micro
            memory_updates["meso"] = meso
            macro_eval = self.macro_promotion.should_promote(
                run_id=run_id,
                pattern_key=meso_structure["pattern_key"],
                continuity_alert=continuity_alert,
            )
            if decision_verdict == "promote" and macro_eval.get("promote"):
                macro = self.memory_store.write_macro(
                    run_id=run_id,
                    episode_id=certificate.episode_id,
                    certificate_id=certificate.certificate_id,
                    ioc_proxy=certificate.ioc_proxy,
                    support_count=int(macro_eval["support"]),
                    structure={
                        "pattern_key": meso_structure["pattern_key"],
                        "support_count": macro_eval["support"],
                        "mean_ioc": macro_eval["mean_ioc"],
                        "std_ioc": macro_eval["std_ioc"],
                    },
                    extra_metadata=memory_extra_metadata,
                )
                memory_updates["macro"] = macro

        self.storage.append_event(
            event_type="promotion.decision",
            run_id=run_id,
            source="promotion_gate",
            payload={
                "episode_id": certificate.episode_id,
                "certificate_id": certificate.certificate_id,
                "decision_id": decision.decision_id,
                "verdict": decision.verdict,
                "rollback_ready": decision.rollback_ready,
            },
        )
        return {
            "proposal": proposal,
            "certificate": certificate,
            "decision": decision,
            "memory_updates": memory_updates,
        }
