"""Laboratorio de ablación para transferencia analógica.

Ejecuta ablation studies controlados para responder:
- ¿Cuándo la analogía ayuda genuinamente?
- ¿Bajo qué clase de borde de transición?
- ¿Con qué coste en pureza y posterior?

Compara strict / analogical / adversarial-shadow usando
los protocolos de analogical_protocols.py, con EML como
juez secundario.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List
from uuid import uuid4

from runtime.certification.trace_integrity import assess_trace_integrity
from runtime.storage import get_storage
from runtime.storage.records import utc_now_iso
from runtime.world.registry import get_scenario, list_causal_signatures
from runtime.world.morphism_engine import MorphismEngine
from runtime.world.scenario_runner import ScenarioEpisodeRunner
from runtime.reality.belief_state import build_belief_state
from runtime.reality.analogical_protocols import (
    AnalogicalProtocolResult,
    RegimeMetrics,
    run_analogical_protocol,
)
from runtime.certification.transfer_posterior import compute_transfer_posterior


# ── EML Secondary Judge ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class EMLSecondaryJudgment:
    """Juicio secundario de EML con señales ricas.

    A diferencia del eml_concurrence_score decorativo del v1,
    este juicio produce señales específicas que entran como
    evidencia formal al posterior de transferencia.
    """

    regularity_signature: float     # Fit quality of top EML candidate
    symbolic_stability_score: float  # Stability of EML predictions
    counterfactual_fit_score: float  # How well EML fits counterfactual data
    transfer_consistency_score: float  # Cross-scenario consistency of EML models
    composite_judgment: float        # Weighted composite


def compute_eml_secondary_judgment(
    *,
    eml_shadow_payload: dict | None,
    transfer_verdict: str,
    relation_kind: str,
    morphism_score: float = 0.5,
) -> EMLSecondaryJudgment:
    """Computes rich EML secondary judgment from shadow payload.

    Extracts structured signals from EML output instead of
    just mapping to a threshold-based concordance score.

    Args:
        eml_shadow_payload: Payload from EML shadow run.
        transfer_verdict: Current transfer verdict.
        relation_kind: Factual/counterfactual relation kind.
        morphism_score: Directed morphism score.

    Returns:
        EMLSecondaryJudgment with structured signals.
    """
    if eml_shadow_payload is None or not eml_shadow_payload.get("enabled"):
        return EMLSecondaryJudgment(
            regularity_signature=0.5,
            symbolic_stability_score=0.5,
            counterfactual_fit_score=0.5,
            transfer_consistency_score=0.5,
            composite_judgment=0.5,
        )

    # Extract from EML payload
    top_composite = float(eml_shadow_payload.get("top_composite", 0.0))
    top_candidates = eml_shadow_payload.get("top_candidates", [])

    # Regularity signature: how good is the best EML candidate
    regularity = min(1.0, top_composite)

    # Symbolic stability: variance among top candidates
    if top_candidates and len(top_candidates) > 1:
        scores = [float(c.get("composite_score", 0.0)) for c in top_candidates[:5]]
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        stability = max(0.0, 1.0 - variance * 10)  # Low variance → high stability
    else:
        stability = 0.5

    # Counterfactual fit: based on relation kind
    if relation_kind == "support":
        cf_fit = min(1.0, regularity * 1.1)
    elif relation_kind == "contradiction":
        cf_fit = max(0.0, regularity * 0.5)
    else:
        cf_fit = regularity * 0.7

    # Transfer consistency: modulated by morphism score
    transfer_consistency = regularity * (0.5 + 0.5 * morphism_score)

    # Composite judgment
    composite = (
        0.30 * regularity
        + 0.25 * stability
        + 0.20 * cf_fit
        + 0.25 * transfer_consistency
    )

    return EMLSecondaryJudgment(
        regularity_signature=round(regularity, 4),
        symbolic_stability_score=round(stability, 4),
        counterfactual_fit_score=round(cf_fit, 4),
        transfer_consistency_score=round(transfer_consistency, 4),
        composite_judgment=round(composite, 4),
    )


# ── Ablation Lab ─────────────────────────────────────────────────────────────

def run_ablation_study(
    *,
    run_id: str | None = None,
    scenarios: list[str] | None = None,
    episodes_per_regime: int = 3,
    memory_modes: tuple[str, str, str] = (
        "strict_same_scenario",
        "cross_scenario_analogical",
        "cross_scenario_adversarial",
    ),
    closure_profile: str = "adaptive_min",
) -> Dict[str, Any]:
    """Ejecuta ablation study comparando tres regímenes.

    Para cada par de escenarios y cada régimen de memoria,
    ejecuta episodios y recopila métricas para el protocolo analógico v2.

    Args:
        run_id: ID de corrida.
        scenarios: Lista de escenarios.
        episodes_per_regime: Episodios por régimen.
        memory_modes: Modos de memoria (strict, analogical, adversarial).
        closure_profile: Perfil de cierre.

    Returns:
        Dict con protocol_result, eml_judgments, artifact.
    """
    storage = get_storage()
    if run_id is None:
        run_id = f"run-ablation-{uuid4()}"
    bench_run_id = f"bench-ablation-{uuid4()}"

    signatures = list_causal_signatures()
    if scenarios is None:
        scenarios = list(signatures.keys())

    engine = MorphismEngine()
    sig_list = [signatures[s] for s in scenarios]
    morphism_matrix = engine.compute_morphism_matrix(sig_list)

    # Collect metrics per regime
    regime_data: Dict[str, Dict[str, list]] = {}
    for mode in memory_modes:
        regime_data[mode] = {
            "continuity": [],
            "purity": [],
            "posterior": [],
            "safe": [],
            "eml": [],
            "collapse": [],
        }

    eml_judgments: List[Dict[str, Any]] = []

    for mode in memory_modes:
        for src in scenarios:
            for tgt in scenarios:
                morphism = morphism_matrix[src][tgt]
                cell_run = f"{run_id}-{mode[:4]}-{src[:6]}-{tgt[:6]}"

                for ep_idx in range(episodes_per_regime):
                    runner = ScenarioEpisodeRunner(
                        storage=storage,
                        run_id=cell_run,
                        scenario=tgt,
                        memory_filter_mode=mode if mode != "cross_scenario_adversarial" else "strict_same_scenario",
                        closure_profile=closure_profile,
                    )
                    result = runner.run_episode(external_input=0.04 + ep_idx * 0.01)
                    belief = build_belief_state(episode_result=result)

                    # Transfer posterior
                    post = compute_transfer_posterior(
                        source_scenario=src,
                        target_scenario=tgt,
                        morphism_class=morphism.morphism_class,
                        morphism_score=morphism.overall_score,
                        memory_purity=belief.memory_purity_confidence,
                        transfer_stability=belief.composite_confidence,
                        # B77: era `True` HARDCODEADO — la misma mentira que P9/B1 mató en
                        # `transfer_assessment`, viva en el laboratorio. El posterior la
                        # premia (`trace_val` 1.0 en vez de 0.3), así que un episodio con la
                        # traza rota se certificaba como si la tuviera intacta. Ahora se MIDE.
                        trace_integrity=assess_trace_integrity(result["episode"]).integral,
                        policy_confidence=belief.policy_confidence,
                        causal_support=belief.causal_support_confidence,
                    )

                    # EML secondary judgment
                    eml_payload = result.get("eml_shadow")
                    episode = result.get("episode", {})
                    rk = episode.get("result", {}).get("relation_kind", "unknown")
                    eml_judge = compute_eml_secondary_judgment(
                        eml_shadow_payload=eml_payload,
                        transfer_verdict=post.certificate_scope,
                        relation_kind=rk,
                        morphism_score=morphism.overall_score,
                    )
                    eml_judgments.append({
                        "regime": mode,
                        "source": src,
                        "target": tgt,
                        "judgment": asdict(eml_judge),
                    })

                    # Collect regime data
                    is_safe = post.certificate_scope not in ("blocked",)
                    regime_data[mode]["continuity"].append(belief.composite_confidence)
                    regime_data[mode]["purity"].append(belief.memory_purity_confidence)
                    regime_data[mode]["posterior"].append(post.transfer_posterior)
                    regime_data[mode]["safe"].append(1.0 if is_safe else 0.0)
                    regime_data[mode]["eml"].append(eml_judge.composite_judgment)
                    regime_data[mode]["collapse"].append(0)  # placeholder

    # Build regime metrics
    def _build_metrics(mode: str, regime_name: str) -> RegimeMetrics:
        d = regime_data[mode]
        n = len(d["continuity"]) or 1
        return RegimeMetrics(
            regime=regime_name,
            mean_continuity=round(sum(d["continuity"]) / n, 4),
            mean_purity=round(sum(d["purity"]) / n, 4),
            mean_posterior=round(sum(d["posterior"]) / n, 4),
            transfer_safe_rate=round(sum(d["safe"]) / n, 4),
            eml_concurrence_mean=round(sum(d["eml"]) / n, 4),
            collapse_count=sum(d["collapse"]),
            total_episodes=n,
        )

    strict_metrics = _build_metrics(memory_modes[0], "strict_same_scenario")
    analogical_metrics = _build_metrics(memory_modes[1], "cross_scenario_analogical")
    adversarial_metrics = _build_metrics(memory_modes[2], "cross_scenario_adversarial_shadow")

    # Run protocol
    protocol_result = run_analogical_protocol(
        strict_metrics=strict_metrics,
        analogical_metrics=analogical_metrics,
        adversarial_metrics=adversarial_metrics,
    )

    # Persist
    report = {
        "bench_run_id": bench_run_id,
        "run_id": run_id,
        "protocol_result": asdict(protocol_result),
        "eml_judgments_sample": eml_judgments[:10],
        "regime_data_summary": {
            mode: {k: round(sum(v) / max(len(v), 1), 4) for k, v in data.items()}
            for mode, data in regime_data.items()
        },
    }

    artifact = storage.materialize_artifact(
        run_id=run_id,
        kind="ablation_lab_report",
        filename=f"{bench_run_id}.json",
        content=json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2),
        metadata={
            "bench_run_id": bench_run_id,
            "benchmark_type": "ablation_lab",
        },
    )

    storage.append_event(
        event_type="reality.ablation_lab.completed",
        run_id=run_id,
        source="ablation_lab",
        payload={
            "bench_run_id": bench_run_id,
            "timestamp": utc_now_iso(),
            "overall_verdict": protocol_result.overall_verdict,
        },
    )

    return {
        "bench_run_id": bench_run_id,
        "protocol_result": asdict(protocol_result),
        "eml_judgments": eml_judgments,
        "artifact": asdict(artifact),
    }
