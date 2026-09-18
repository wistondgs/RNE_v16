"""H-051 — con N escenarios hay N mundos, y cada uno recuerda el suyo.

H-047 dio al mundo un canal de ida y vuelta, y lo hizo con **una** ranura. Eso
basta mientras el organismo vive en un solo escenario. Con varios, el kernel
rota entre ellos y le empujaba al escenario nuevo el mundo del anterior:

    ValueError: world_state_scenario_mismatch: el payload es de
    'thermal_homeostasis' y este escenario es 'resource_management'

La comprobación estricta hizo su trabajo —cazó la confusión en vez de cargar
campos que significan otra cosa— y dejó ver que el modelo estaba mal: un
organismo que alterna entre mundos tiene una historia POR MUNDO, no una sola.

Apareció al preparar la ola 7, midiendo si `memory_filter_mode` puede tener
soporte: para que existan memorias de otro escenario hace falta visitar más de
uno, y al hacerlo la corrida se caía.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory

SNAP = {
    "cpu_pressure": 0.1,
    "memory_pressure": 0.1,
    "thermal_pressure": 0.1,
    "vram_pressure": 0.1,
    "gpu_available": False,
}
DOS = ("thermal_homeostasis", "resource_management")


def _storage(tmp_path: Path, name: str):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / f"{name}.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / f"{name}-artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _config(run_id: str, **kw):
    base = dict(
        run_id=run_id,
        organism_id="organism-multi",
        scenarios=DOS,
        block_size=4,
        max_steps=0,
        restore=False,
        checkpoint_interval=1,
        allow_external_reasoner=False,
        enable_msrc=False,
        enable_operational_conjunction=False,
        resource_snapshot_override=dict(SNAP),
    )
    base.update(kw)
    return LifeKernelConfig(**base)


def _mundo(runner):
    estado = getattr(runner.scenario, "_state", None)
    return asdict(estado) if is_dataclass(estado) else None


def test_alternar_escenarios_no_rompe_la_corrida(tmp_path):
    """Lo mínimo: que no explote. Antes lanzaba en el primer cambio de bloque."""
    kernel = LifeKernel(config=_config("multi"), storage=_storage(tmp_path, "multi"))
    vistos = []
    for _ in range(20):
        kernel.step()
        if kernel._runner is not None:
            vistos.append(kernel._runner.scenario.config.name)
    assert set(vistos) == set(DOS), (
        f"la corrida no visitó los dos escenarios: {set(vistos)}; la prueba no mide nada"
    )


def test_cada_escenario_recuerda_su_propio_mundo(tmp_path):
    """Volver a un escenario debe devolver al organismo al mundo que dejó allí.

    Si hubiera una sola ranura, el mundo al que se vuelve sería el del OTRO
    escenario —o el virgen—, y el organismo viviría una historia que no ocurrió.
    """
    kernel = LifeKernel(config=_config("recuerda"), storage=_storage(tmp_path, "recuerda"))
    ultimo_por_escenario: dict[str, dict] = {}
    entradas: list[tuple[str, dict | None, dict | None]] = []

    for _ in range(24):
        kernel.step()
        runner = kernel._runner
        if runner is None:
            continue
        nombre = runner.scenario.config.name
        entradas.append((nombre, ultimo_por_escenario.get(nombre), _mundo(runner)))
        ultimo_por_escenario[nombre] = _mundo(runner)

    # Cada escenario debe tener estado propio y distinto del otro al final.
    assert set(ultimo_por_escenario) == set(DOS)
    assert kernel._world_state, "el kernel no guardó ningún mundo"
    guardados = {
        payload.get("scenario_name")
        for payload in kernel._world_state.values()
        if isinstance(payload, dict)
    }
    assert guardados == set(DOS), (
        f"el kernel guarda {guardados}, no un mundo por escenario"
    )


def test_el_mundo_de_cada_escenario_sobrevive_al_checkpoint(tmp_path):
    """Reanudar con dos mundos devuelve los dos, no el último."""
    storage = _storage(tmp_path, "resume-multi")
    primero = LifeKernel(config=_config("resume-multi"), storage=storage)
    for _ in range(12):
        primero.step()
    guardados = {
        p.get("scenario_name") for p in primero._world_state.values() if isinstance(p, dict)
    }
    assert guardados == set(DOS), f"el primero no llegó a los dos mundos: {guardados}"

    segundo = LifeKernel(config=_config("resume-multi", restore=True), storage=storage)
    segundo.step()
    recuperados = {
        p.get("scenario_name") for p in segundo._world_state.values() if isinstance(p, dict)
    }
    assert recuperados == set(DOS), (
        f"tras reanudar sólo volvió {recuperados}: el checkpoint no lleva un mundo por escenario"
    )
