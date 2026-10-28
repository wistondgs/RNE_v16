"""Benchmark dirigido de bordes de transición con grafo completo.

Ejecuta stress tests sobre todos los bordes del grafo de escenarios,
produciendo un reporte por edge y un reporte global.

A diferencia del transition_matrix.py plano, este benchmark:
- Usa morfismos dirigidos (asimétricos)
- Mide hysteresis A→B→A
- Computa recovery profiles
- Clasifica bordes en clases
- Produce transfer posteriors por borde
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List
from uuid import uuid4

from runtime.storage import get_storage
from runtime.storage.records import utc_now_iso
from runtime.world.registry import get_scenario, list_causal_signatures
from runtime.world.morphism_engine import MorphismEngine
from runtime.world.scenario_runner import ScenarioEpisodeRunner
from runtime.reality.belief_state import build_belief_state, BeliefState
from runtime.reality.transition_stress import (
    EdgeStressResult,
    classify_edge,
    run_edge_stress_test,
)
from runtime.certification.trace_integrity import assess_trace_integrity
from runtime.certification.transfer_posterior import compute_transfer_posterior


def run_edge_benchmark(
    *,
    run_id: str | None = None,
    scenarios: list[str] | None = None,
    warmup_episodes: int = 3,
    probe_episodes: int = 3,
    return_episodes: int = 2,
    memory_mode: str = "strict_same_scenario",
    closure_profile: str = "adaptive_min",
) -> Dict[str, Any]:
    """Ejecuta benchmark dirigido sobre todos los bordes del grafo.

    Para cada par (A → B):
    1. Warmup en A
    2. Probe en B (shock + stabilization)
    3. Retorno a A (hysteresis)
    4. Análisis de stress por borde

    Args:
        run_id: ID de corrida.
        scenarios: Lista de escenarios a incluir.
        warmup_episodes: Episodios de warmup por borde.
        probe_episodes: Episodios de probe por borde.
        return_episodes: Episodios de retorno para hysteresis.
        memory_mode: Modo de filtrado de memoria.
        closure_profile: Perfil de cierre.

    Returns:
        Dict con edge_results, graph_summary, artifact.
    """
    storage = get_storage()
    if run_id is None:
        run_id = f"run-edge-{uuid4()}"
    bench_run_id = f"bench-edge-{uuid4()}"

    # Resolve scenarios
    signatures = list_causal_signatures()
    if scenarios is None:
        scenarios = list(signatures.keys())

    # Compute morphism matrix
    engine = MorphismEngine()
    sig_list = [signatures[s] for s in scenarios]
    morphism_matrix = engine.compute_morphism_matrix(sig_list)

    # Run stress test per edge
    edge_results: List[EdgeStressResult] = []
    # B77: evidencia de integridad de traza REALMENTE medida, episodio por episodio.
    trace_integrity_checks: List[Dict[str, Any]] = []

    for src_name in scenarios:
        for tgt_name in scenarios:
            morphism = morphism_matrix[src_name][tgt_name]
            cell_run_id = f"{run_id}-{src_name[:6]}-{tgt_name[:6]}"

            # Phase 1: Warmup in source
            warmup_beliefs: List[BeliefState] = []
            for i in range(warmup_episodes):
                runner = ScenarioEpisodeRunner(
                    storage=storage,
                    run_id=cell_run_id,
                    scenario=src_name,
                    memory_filter_mode=memory_mode,
                    closure_profile=closure_profile,
                )
                result = runner.run_episode(external_input=0.04 + i * 0.01)
                belief = build_belief_state(episode_result=result)
                warmup_beliefs.append(belief)

            # Phase 2: Probe in target (shock + stabilization)
            probe_beliefs: List[BeliefState] = []
            posteriors: List[float] = []
            fm_lists: List[Dict[str, int]] = []
            for j in range(probe_episodes):
                runner = ScenarioEpisodeRunner(
                    storage=storage,
                    run_id=cell_run_id,
                    scenario=tgt_name,
                    memory_filter_mode=memory_mode,
                    closure_profile=closure_profile,
                )
                result = runner.run_episode(external_input=0.04 + j * 0.01)
                belief = build_belief_state(episode_result=result)
                probe_beliefs.append(belief)

                # B77 — la integridad de traza se MIDE, no se afirma.
                # Antes: `trace_integrity=True` hardcodeado. Eso no era un default:
                # era una MENTIRA con forma de medición, y el posterior la premia
                # (transfer_posterior.py:128 -> `trace_val = 1.0 if trace_integrity
                # else 0.3`). Darle invocador a este benchmark sin arreglar esto
                # habría propagado la mentira al ledger.
                integrity = assess_trace_integrity(result.get("episode"))
                trace_integrity_checks.append(
                    {
                        "edge": f"{src_name}->{tgt_name}",
                        "integral": integrity.integral,
                        "reason": integrity.reason,
                        "step_count": integrity.step_count,
                        "checks_applied": list(integrity.checks_applied),
                    }
                )

                # Compute transfer posterior for this probe episode
                post_result = compute_transfer_posterior(
                    source_scenario=src_name,
                    target_scenario=tgt_name,
                    morphism_class=morphism.morphism_class,
                    morphism_score=morphism.overall_score,
                    memory_purity=belief.memory_purity_confidence,
                    transfer_stability=belief.composite_confidence,
                    trace_integrity=integrity.integral,
                    policy_confidence=belief.policy_confidence,
                    causal_support=belief.causal_support_confidence,
                )
                posteriors.append(post_result.transfer_posterior)
                fm_dict = {}
                for fm in post_result.failure_modes.detected_modes:
                    fm_dict[fm.mode] = fm_dict.get(fm.mode, 0) + 1
                fm_lists.append(fm_dict)

            # Phase 3: Return to source (hysteresis)
            return_beliefs: List[BeliefState] = []
            for k in range(return_episodes):
                runner = ScenarioEpisodeRunner(
                    storage=storage,
                    run_id=cell_run_id,
                    scenario=src_name,
                    memory_filter_mode=memory_mode,
                    closure_profile=closure_profile,
                )
                result = runner.run_episode(external_input=0.04 + k * 0.01)
                belief = build_belief_state(episode_result=result)
                return_beliefs.append(belief)

            # Phase 4: Stress analysis
            stress = run_edge_stress_test(
                source_scenario=src_name,
                target_scenario=tgt_name,
                morphism_class=morphism.morphism_class,
                morphism_score=morphism.overall_score,
                warmup_beliefs=warmup_beliefs,
                probe_beliefs=probe_beliefs,
                return_beliefs=return_beliefs,
                transfer_posteriors=posteriors,
                failure_mode_lists=fm_lists,
            )
            edge_results.append(stress)

    # Build graph summary
    graph_summary = _build_graph_summary(edge_results)

    # B77 — la integridad de traza que el benchmark MIDIÓ, declarada en el reporte.
    # Si `integral_rate < 1.0`, el posterior de esos episodios YA está penalizado
    # (no se lo maquilla): el reporte dice cuántas trazas pasaron y cuántas no.
    integral_count = sum(1 for c in trace_integrity_checks if c["integral"])
    trace_integrity_summary = {
        "episodes_checked": len(trace_integrity_checks),
        "integral_count": integral_count,
        "integral_rate": (
            round(integral_count / len(trace_integrity_checks), 4)
            if trace_integrity_checks
            else None
        ),
        "measured": True,  # B77: medida, no afirmada
        "failure_reasons": sorted(
            {c["reason"] for c in trace_integrity_checks if not c["integral"]}
        ),
    }

    # Persist
    report_content = {
        "bench_run_id": bench_run_id,
        "run_id": run_id,
        "scenarios": scenarios,
        "edge_results": [asdict(e) for e in edge_results],
        "graph_summary": graph_summary,
        "trace_integrity": trace_integrity_summary,
        "trace_integrity_checks": trace_integrity_checks,
    }

    artifact = storage.materialize_artifact(
        run_id=run_id,
        kind="edge_benchmark_report",
        filename=f"{bench_run_id}.json",
        content=json.dumps(report_content, ensure_ascii=True, sort_keys=True, indent=2),
        metadata={
            "bench_run_id": bench_run_id,
            "benchmark_type": "edge_benchmark",
        },
    )

    storage.append_event(
        event_type="reality.edge_benchmark.completed",
        run_id=run_id,
        source="edge_benchmark",
        payload={
            "bench_run_id": bench_run_id,
            "timestamp": utc_now_iso(),
            "graph_summary": graph_summary,
            "trace_integrity": trace_integrity_summary,
        },
    )

    return {
        "bench_run_id": bench_run_id,
        "edge_results": [asdict(e) for e in edge_results],
        "graph_summary": graph_summary,
        "trace_integrity": trace_integrity_summary,
        "trace_integrity_checks": trace_integrity_checks,
        "artifact": asdict(artifact),
    }


def _build_graph_summary(edges: List[EdgeStressResult]) -> Dict[str, Any]:
    """Construye resumen global del grafo de transiciones."""
    if not edges:
        return {"total_edges": 0}

    by_class = {}
    for e in edges:
        cls = e.edge_class
        if cls not in by_class:
            by_class[cls] = []
        by_class[cls].append(e)

    class_summaries = {}
    for cls, cls_edges in by_class.items():
        class_summaries[cls] = {
            "count": len(cls_edges),
            "mean_stability": round(
                sum(e.transfer_stability_mean for e in cls_edges) / len(cls_edges), 4
            ),
            "mean_hysteresis": round(
                sum(e.hysteresis_gap for e in cls_edges) / len(cls_edges), 4
            ),
            "mean_recovery_steps": round(
                sum(e.recovery_steps for e in cls_edges) / len(cls_edges), 2
            ),
            "mean_posterior": round(
                sum(e.transfer_posterior_mean for e in cls_edges) / len(cls_edges), 4
            ),
            "full_recovery_rate": round(
                sum(1 for e in cls_edges if e.full_recovery) / len(cls_edges), 4
            ),
        }

    return {
        "total_edges": len(edges),
        "edge_class_distribution": {cls: len(es) for cls, es in by_class.items()},
        "class_summaries": class_summaries,
        "global_mean_stability": round(
            sum(e.transfer_stability_mean for e in edges) / len(edges), 4
        ),
        "global_mean_hysteresis": round(
            sum(e.hysteresis_gap for e in edges) / len(edges), 4
        ),
        "global_mean_posterior": round(
            sum(e.transfer_posterior_mean for e in edges) / len(edges), 4
        ),
    }
