#!/usr/bin/env python3
"""B22 — entrypoint del benchmark dirigido de bordes de transición.

`runtime.reality.edge_benchmark.run_edge_benchmark` existía desde hacía tiempo y no
lo llamaba NADIE (cero invocadores en runtime/, scripts/ y tests/). Este script le da
entrada: corre el stress A->B->A sobre todos los bordes del grafo de escenarios y
deja el reporte como artifact.

B77 (arreglado en la misma pasada): el benchmark pasaba `trace_integrity=True`
hardcodeado a `compute_transfer_posterior`. Darle invocador sin arreglar eso habría
propagado la mentira al ledger. Ahora la integridad de traza se MIDE con
`assess_trace_integrity` y el reporte declara cuántas trazas pasaron.

Uso:
    python scripts/run_edge_benchmark.py
    python scripts/run_edge_benchmark.py --scenarios thermal_homeostasis resource_management
    python scripts/run_edge_benchmark.py --warmup 2 --probe 2 --return-episodes 1 --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.reality.edge_benchmark import run_edge_benchmark
from runtime.world.registry import SCENARIO_REGISTRY


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark dirigido de bordes de transición entre escenarios.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        choices=sorted(SCENARIO_REGISTRY),
        help="Escenarios a incluir (default: todos los del registry vivo).",
    )
    parser.add_argument("--run-id", default=None, help="ID de corrida.")
    parser.add_argument("--warmup", type=int, default=3, help="Episodios de warmup por borde.")
    parser.add_argument("--probe", type=int, default=3, help="Episodios de probe por borde.")
    parser.add_argument(
        "--return-episodes",
        type=int,
        default=2,
        help="Episodios de retorno (hysteresis) por borde.",
    )
    parser.add_argument(
        "--memory-mode",
        default="strict_same_scenario",
        help="Modo de filtrado de memoria.",
    )
    parser.add_argument("--closure-profile", default="adaptive_min", help="Perfil de cierre.")
    parser.add_argument("--json", action="store_true", help="Emite el reporte crudo en JSON.")
    return parser.parse_args(argv)


def _render(report: Dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["graph_summary"]
    trace = report["trace_integrity"]

    lines.append(f"bench_run_id: {report['bench_run_id']}")
    lines.append(f"bordes evaluados: {summary.get('total_edges', 0)}")
    lines.append("")

    # B77: lo primero que se reporta es si la evidencia es confiable.
    lines.append("── Integridad de traza (MEDIDA, no afirmada) ──")
    lines.append(f"  episodios chequeados : {trace['episodes_checked']}")
    lines.append(f"  trazas íntegras      : {trace['integral_count']}")
    lines.append(f"  tasa de integridad   : {trace['integral_rate']}")
    if trace["failure_reasons"]:
        lines.append(f"  motivos de ruptura   : {', '.join(trace['failure_reasons'])}")
    lines.append("")

    lines.append("── Distribución de clases de borde ──")
    for cls, count in sorted(summary.get("edge_class_distribution", {}).items()):
        lines.append(f"  {cls:<16} {count}")
    lines.append("")

    lines.append("── Globales ──")
    lines.append(f"  estabilidad media : {summary.get('global_mean_stability')}")
    lines.append(f"  hysteresis media  : {summary.get('global_mean_hysteresis')}")
    lines.append(f"  posterior medio   : {summary.get('global_mean_posterior')}")
    lines.append("")

    lines.append("── Bordes ──")
    for edge in report["edge_results"]:
        lines.append(
            f"  {edge['source_scenario']:>20} -> {edge['target_scenario']:<20} "
            f"clase={edge['edge_class']:<14} "
            f"posterior={edge['transfer_posterior_mean']:.4f} "
            f"hysteresis={edge['hysteresis_gap']:.4f}"
        )

    artifact = report.get("artifact") or {}
    if artifact:
        lines.append("")
        lines.append(f"artifact: {artifact.get('path') or artifact.get('artifact_id')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    report = run_edge_benchmark(
        run_id=args.run_id,
        scenarios=args.scenarios,
        warmup_episodes=args.warmup,
        probe_episodes=args.probe,
        return_episodes=args.return_episodes,
        memory_mode=args.memory_mode,
        closure_profile=args.closure_profile,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print(_render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
