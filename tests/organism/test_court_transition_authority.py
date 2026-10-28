"""D-047 — autoridad única de transición del organismo.

Gates de aceptación de [[H-045]]. El tribunal constitucional necesita una
trayectoria de snapshots para `window`, `digest` y el motor de flujo, y la
construía DERIVANDO su propio `OrganismState` a partir del episodio. En el
life-loop eso era una SEGUNDA transición fisiológica por paso lógico: medido,
`N_advance_state = 2` en 40/40 pasos y 40 estados huérfanos que nadie adoptaba.

El contrato es:

    ∀ (organism_id, logical_step):  N_transiciones_autoritativas = 1

El tribunal puede evaluar, certificar y conservar estado propio. No puede acuñar
otro `OrganismState` real cuando ya existe una autoridad.
"""

from __future__ import annotations

import collections
from pathlib import Path

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.organism.state import OrganismState
from runtime.organism.trajectory import OrganismTrajectory
from runtime.organism.trajectory_state_machine import TrajectoryStateMachine
from runtime.storage import StorageConfig, StorageFactory

STEPS = 12


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "court.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _corre(tmp_path: Path, monkeypatch):
    """Corre el life-loop contando transiciones y devolviendo lo adoptado."""
    paso = {"i": -1}
    transiciones: list[tuple[int, str]] = []
    original = TrajectoryStateMachine.advance_state

    def espia(self, *, current, episode_result, regime, new_state_id, timestamp):
        salida = original(
            self, current=current, episode_result=episode_result, regime=regime,
            new_state_id=new_state_id, timestamp=timestamp,
        )
        transiciones.append((paso["i"], salida.state_id))
        return salida

    monkeypatch.setattr(TrajectoryStateMachine, "advance_state", espia)

    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id="court-authority",
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=_storage(tmp_path),
    )
    adoptados = []
    for i in range(STEPS):
        paso["i"] = i
        kernel.step()
        adoptados.append(kernel.organism_state.state_id)
    return transiciones, adoptados


def test_a1_una_sola_transicion_por_paso_logico(tmp_path: Path, monkeypatch):
    """A1 — con el tribunal habilitado, exactamente una transición por paso."""
    transiciones, _ = _corre(tmp_path, monkeypatch)
    por_paso = collections.Counter(p for p, _ in transiciones)
    assert por_paso, "no se observó ninguna transición: el espía no se enganchó"
    assert set(por_paso.values()) == {1}, (
        f"N_advance_state por paso = {dict(collections.Counter(por_paso.values()))}; "
        "el contrato D-047 exige exactamente 1"
    )


def test_a2_ninguna_transicion_queda_huerfana(tmp_path: Path, monkeypatch):
    """A2 — todo `OrganismState` producido es adoptado por el organismo."""
    transiciones, adoptados = _corre(tmp_path, monkeypatch)
    producidos = [sid for _, sid in transiciones]
    huerfanos = [s for s in producidos if s not in set(adoptados)]
    assert huerfanos == [], (
        f"{len(huerfanos)} estados producidos y nunca adoptados, p.ej. {huerfanos[:3]}"
    )


def test_a3_el_estado_de_salida_es_el_de_entrada_siguiente(tmp_path: Path, monkeypatch):
    """A3 — continuidad de identidad: la cadena de episodios no salta."""
    _, adoptados = _corre(tmp_path, monkeypatch)
    assert len(set(adoptados)) == len(adoptados), "un state_id se repitió: la cadena no avanza"


def test_observe_asienta_la_autoridad_sin_derivar_nada():
    """`observe` no deriva: el snapshot ES el estado que se le entrega."""
    trayectoria = OrganismTrajectory(trajectory_id="traj-unit")
    maquina = TrajectoryStateMachine()
    autoridad = OrganismState(state_id="state-42-organismo", episode_count=42)

    snapshot = maquina.observe(
        trajectory=trayectoria,
        regime="thermal_homeostasis",
        episode_result={"episode": {"context": {}}},
        authoritative_state=autoridad,
    )

    assert snapshot.snapshot_id == "state-42-organismo"  # hereda la identidad
    assert snapshot.episode_count == 42                  # NO se le sumó 1
    assert len(trayectoria.points) == 1                  # y sí quedó asentado
    assert trayectoria.points[-1].snapshot.snapshot_id == "state-42-organismo"


def test_advance_sigue_derivando_para_quien_es_la_autoridad():
    """El camino del episodio mínimo no tiene `OrganismState`: allí sí se deriva."""
    trayectoria = OrganismTrajectory(trajectory_id="traj-unit-2")
    maquina = TrajectoryStateMachine()

    snapshot = maquina.advance(
        trajectory=trayectoria,
        regime="thermal_homeostasis",
        episode_result={"episode": {"context": {}}, "certification": {"verdict": "certified"}},
        new_snapshot_id="snap-derivado",
        timestamp="2026-09-17T00:00:00Z",
    )

    assert snapshot.snapshot_id == "snap-derivado"
    assert snapshot.episode_count == 1  # derivó: partió de OrganismState() y sumó 1
    assert len(trayectoria.points) == 1
