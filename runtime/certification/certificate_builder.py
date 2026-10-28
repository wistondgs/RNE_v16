"""Builder de certificado ampliado por episodio."""

from __future__ import annotations

from typing import Any, Dict

from runtime.storage import StorageFacade


class CertificateBuilder:
    def __init__(self, *, storage: StorageFacade):
        self.storage = storage

    def build_and_persist(
        self,
        *,
        run_id: str,
        episode_result: Dict[str, Any],
        continuity_score: float,
        ioc_proxy: float,
        continuity_alert: bool,
        closure_passed: bool,
        trace_integrity: bool,
        collapse_detected: bool,
        transfer_assessment: Dict[str, Any] | None = None,
        risk_plus: Dict[str, Any] | None = None,
        omega: Dict[str, Any] | None = None,
    ):
        episode = episode_result.get("episode", {})
        episode_id = episode.get("episode_id", "")

        # Extract scenario_metadata for certificate traceability
        scenario_metadata = episode.get("scenario_metadata")
        if scenario_metadata is None:
            scenario_name = episode.get("scenario", "unknown")
            scenario_metadata = {"scenario_name": scenario_name}

        trace = episode.get("trace", []) or []
        trace_id = trace[0].get("detail", {}).get("trace_id") if trace else None
        if not trace_id:
            trace_id = f"trace-{episode_id}"

        uncertainty = float(episode.get("context", {}).get("uncertainty", 0.2))
        risk_score = max(
            0.0,
            min(
                1.0,
                0.55 * (1.0 - continuity_score)
                + 0.30 * (1.0 - ioc_proxy)
                + 0.10 * (1.0 - (1.0 if trace_integrity else 0.0))
                + 0.05 * uncertainty
                + (0.08 if collapse_detected else 0.0),
            ),
        )
        verdict = "certified" if closure_passed and trace_integrity and not collapse_detected else "rejected"
        rollback_ready = True
        promotion_candidate = (
            verdict == "certified"
            and not continuity_alert
            and continuity_score >= 0.60
            and ioc_proxy >= 0.72
            and risk_score <= 0.45
        )

        smg_snapshot = episode_result.get("smg_snapshot", {})
        world = episode.get("result", {}).get("updated_world", {})
        main_var = scenario_metadata.get("main_variable", "temperature")
        lotf_formula = episode.get("context", {}).get("formula")
        certificate = self.storage.write_episode_certificate(
            episode_id=episode_id,
            run_id=run_id,
            trace_id=str(trace_id),
            smg_artifacts={
                "observations": len(smg_snapshot.get("observations", [])),
                "signs": len(smg_snapshot.get("signs", [])),
                "relations": len(smg_snapshot.get("relations", [])),
            },
            lotf_artifacts={
                "formula": lotf_formula,
                "reasoning_sequence": episode.get("result", {}).get("reasoning_sequence", []),
            },
            world_artifacts={
                "updated_world": world,
                "counterfactual": episode.get("context", {}).get("counterfactual", {}),
                "relation_kind": episode.get("result", {}).get("relation_kind"),
            },
            continuity_score=continuity_score,
            ioc_proxy=ioc_proxy,
            risk_score=risk_score,
            verdict=verdict,
            rollback_ready=rollback_ready,
            promotion_candidate=promotion_candidate,
            metadata={
                "closure_passed": closure_passed,
                "trace_integrity": trace_integrity,
                "collapse_detected": collapse_detected,
                "continuity_alert": continuity_alert,
                "reasoning_sequence": episode.get("result", {}).get("reasoning_sequence", []),
                "world_temperature": world.get("temperature"),  # back-compat
                "world_main_variable": main_var,
                "world_main_variable_value": world.get(main_var),
                "scenario_metadata": scenario_metadata,
                "closure_profile": episode.get("closure_profile", "baseline_fixed"),
                "transfer_assessment": transfer_assessment or {},
                "risk_plus": risk_plus or {},
                "omega": omega or {},
                "belief_state": episode_result.get("belief_state"),
                # Evidencia aditiva: nunca participa en el cálculo de verdict,
                # risk_score ni promotion_candidate.
                "neural_symbiosis": episode_result.get("neural_symbiosis") or {},
            },
        )
        return certificate
