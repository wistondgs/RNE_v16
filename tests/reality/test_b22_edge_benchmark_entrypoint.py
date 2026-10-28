"""B22 — `run_edge_benchmark` tiene invocador, y no propaga una integridad fabricada.

B22: la función existía y NO la llamaba nadie (cero invocadores en runtime/, scripts/
y tests/). Ahora tiene entrypoint (scripts/run_edge_benchmark.py) y este test.

B77: el benchmark pasaba `trace_integrity=True` HARDCODEADO a
`compute_transfer_posterior`, que lo premia (`trace_val = 1.0 if trace_integrity else
0.3`). Darle invocador sin arreglar eso habría propagado la mentira al ledger.
"""

from __future__ import annotations

import inspect

import pytest

from runtime.reality import edge_benchmark
from runtime.reality.edge_benchmark import run_edge_benchmark


@pytest.fixture()
def storage_env(tmp_path, monkeypatch):
    from runtime.storage import get_storage

    monkeypatch.setenv("RNFE_STORAGE_MODE", "sqlite")
    monkeypatch.setenv("AEON_EVENT_DB", str(tmp_path / "edge.db"))
    monkeypatch.setenv("RNFE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    storage = get_storage(refresh=True)
    yield storage
    storage.close()
    get_storage(refresh=True).close()


# ── B77 — la integridad de traza se MIDE ────────────────────────────────────

def test_el_benchmark_no_hardcodea_trace_integrity():
    """Guardia de regresión sobre la mentira exacta de B77.

    Mira el CÓDIGO, no los comentarios (que citan la mentira para documentarla).
    """
    source = inspect.getsource(run_edge_benchmark)
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines()
    )
    assert "trace_integrity=True" not in code, (
        "edge_benchmark vuelve a afirmar `trace_integrity=True` sin medirla. "
        "El posterior premia esa afirmación (transfer_posterior: trace_val=1.0). "
        "Usá assess_trace_integrity(...)."
    )
    assert "assess_trace_integrity" in code


def test_el_benchmark_mide_la_integridad_y_la_declara(storage_env):
    report = run_edge_benchmark(
        scenarios=["thermal_homeostasis", "resource_management"],
        warmup_episodes=1,
        probe_episodes=1,
        return_episodes=1,
    )

    trace = report["trace_integrity"]
    assert trace["measured"] is True
    # 2 escenarios -> 4 bordes -> 1 probe cada uno -> 4 episodios chequeados
    assert trace["episodes_checked"] == 4
    assert trace["integral_rate"] is not None

    # Cada chequeo trae EVIDENCIA (qué chequeos corrieron), no sólo un booleano.
    checks = report["trace_integrity_checks"]
    assert len(checks) == 4
    for check in checks:
        assert isinstance(check["integral"], bool)
        assert check["checks_applied"], "un chequeo sin `checks_applied` no verificó nada"


# ── B22 — el benchmark corre de punta a punta ───────────────────────────────

def test_run_edge_benchmark_produce_grafo_completo(storage_env):
    scenarios = ["thermal_homeostasis", "resource_management"]
    report = run_edge_benchmark(
        scenarios=scenarios,
        warmup_episodes=1,
        probe_episodes=1,
        return_episodes=1,
    )

    assert report["graph_summary"]["total_edges"] == len(scenarios) ** 2
    assert report["artifact"]
    assert len(report["edge_results"]) == len(scenarios) ** 2


def test_el_cruce_de_polaridad_invertida_se_clasifica_adversarial(storage_env):
    """canon SCENARIO_CONTRACTS_v1 §7.5: minimize <-> maximize es el cruce peligroso."""
    report = run_edge_benchmark(
        scenarios=["thermal_homeostasis", "resource_management"],
        warmup_episodes=1,
        probe_episodes=1,
        return_episodes=1,
    )

    by_edge = {
        (e["source_scenario"], e["target_scenario"]): e["edge_class"]
        for e in report["edge_results"]
    }
    assert by_edge[("thermal_homeostasis", "resource_management")] == "adversarial_edge"
    assert by_edge[("resource_management", "thermal_homeostasis")] == "adversarial_edge"
    # y el borde consigo mismo NO es adversarial
    assert by_edge[("thermal_homeostasis", "thermal_homeostasis")] != "adversarial_edge"


# ── El entrypoint existe y es invocable ─────────────────────────────────────

def test_el_script_expone_main_invocable(storage_env):
    import scripts.run_edge_benchmark as cli

    rc = cli.main(
        [
            "--scenarios", "thermal_homeostasis",
            "--warmup", "1",
            "--probe", "1",
            "--return-episodes", "1",
        ]
    )
    assert rc == 0
