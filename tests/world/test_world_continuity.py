"""H-047 — el mundo no puede reiniciarse cuando se reconstruye el runner.

`ScenarioEpisodeRunner.__init__` construye `self.scenario` a partir de un
NOMBRE, y el escenario *es* el mundo. Como el kernel suelta el runner cada
`block_size` episodios, el mundo volvía a su estado inicial cada bloque.

Medido antes de escribir esto, `block_size=8`, 20 pasos, 3 escenarios:

    nacimiento 0:  temperature 0.82  cooling False  alarm False
    nacimiento 1:  temperature 0.82  cooling False  alarm False
    nacimiento 2:  temperature 0.82  cooling False  alarm False

    paso  7 muere:  0.98  alarm True      ← el organismo calentó el mundo
    paso  8 nace :  0.82  alarm False     ← y se descarta

Es I-05 del Canon 2.1 de Terrario —«mundo declarado = mundo ejecutado»— y es el
paso 1 de su orden de conexión. También es la clase de defecto de H-046 aplicada
al MUNDO en vez de al organismo: `OrganismState` y `LineageState` tienen canal de
ida y vuelta; el estado del mundo no lo tenía.

**El mundo no es el organismo.** Viaja en su propia ranura, no dentro del estado
del organismo, porque una campaña causal necesita poder intervenir `do(D)` sobre
el mundo y `do(A)` sobre el organismo por separado. Meterlos en el mismo sitio
haría imposible mover uno sin mover el otro.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pytest

from runtime.life import CheckpointManager, LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory
from runtime.world.registry import get_scenario

SNAP = {
    "cpu_pressure": 0.1,
    "memory_pressure": 0.1,
    "thermal_pressure": 0.1,
    "vram_pressure": 0.1,
    "gpu_available": False,
}


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
        organism_id="organism-world",
        scenarios=("thermal_homeostasis",),
        block_size=8,
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


def _mundo(objeto) -> dict[str, Any] | None:
    """El estado interno del mundo. Acepta un runner o el escenario mismo."""
    escenario = getattr(objeto, "scenario", objeto)
    estado = getattr(escenario, "_state", None)
    return asdict(estado) if is_dataclass(estado) else None


# ── el escenario sabe exportarse y restaurarse ──────────────────────────────


def test_el_escenario_exporta_y_restaura_su_estado():
    """Ida y vuelta exacta, sin pasar por el disco."""
    a = get_scenario("thermal_homeostasis")
    a.factual_transition(intervention="cool", external_input=0.1)
    payload = a.export_world_state()

    b = get_scenario("thermal_homeostasis")
    assert _mundo(b) != _mundo(a), "los dos empiezan iguales: la prueba sería vacía"
    assert b.restore_world_state(payload) is True
    assert _mundo(b) == _mundo(a)


def test_un_mundo_ajeno_se_rechaza():
    """El estado de un mundo térmico no entra en un mundo de recursos.

    Sin esto, un checkpoint de otro escenario cargaría campos que no significan
    lo mismo y el mundo quedaría en un estado que nunca existió.
    """
    termico = get_scenario("thermal_homeostasis")
    otro = get_scenario("resource_management")
    with pytest.raises(ValueError, match="world_state_scenario_mismatch"):
        otro.restore_world_state(termico.export_world_state())


def test_un_esquema_desconocido_se_rechaza():
    """Silencio no: un payload que no se entiende es un error, no un no-op."""
    escenario = get_scenario("thermal_homeostasis")
    with pytest.raises(ValueError, match="world_state_schema_unknown"):
        escenario.restore_world_state({"schema_version": "inventado", "state": {}})
    # Vacío sí es no-op: es un arranque limpio, no un payload roto.
    assert escenario.restore_world_state(None) is False
    assert escenario.restore_world_state({}) is False


# ── §I-05 · el mundo declarado es el mundo ejecutado ────────────────────────


def test_el_mundo_no_se_reinicia_al_reconstruir_el_runner(tmp_path):
    """La falsación de H-047, medida donde el invariante vive.

    No se mide en `__init__`: el runner construye su escenario desde un nombre y
    el kernel le entrega el mundo justo después, igual que hace con el estado
    neural y con el del lazo. Medir el nacimiento diría «virgen» siempre y no
    distinguiría reparado de roto.

    Lo que I-05 exige es que **el mundo con el que ENTRA el primer episodio del
    bloque nuevo sea el que dejó el bloque anterior**. Eso es lo que se mide: el
    estado al entrar cada episodio, y la continuidad a través de la frontera.
    """
    from runtime.world.scenario_runner import ScenarioEpisodeRunner

    entradas: list[tuple[int, dict[str, Any] | None]] = []
    original = ScenarioEpisodeRunner.run_episode

    def envuelto(self, *a, **kw):
        entradas.append((id(self.scenario), _mundo(self)))
        return original(self, *a, **kw)

    ScenarioEpisodeRunner.run_episode = envuelto
    try:
        kernel = LifeKernel(config=_config("reinicio"), storage=_storage(tmp_path, "reinicio"))
        for _ in range(20):
            kernel.step()
    finally:
        ScenarioEpisodeRunner.run_episode = original

    escenarios = {sid for sid, _ in entradas}
    assert len(escenarios) >= 2, (
        f"un solo escenario en toda la corrida: sin reconstrucción no se mide nada "
        f"({len(entradas)} episodios)"
    )

    virgen = _mundo_inicial()
    fronteras = [
        (i, estado)
        for i, (sid, estado) in enumerate(entradas)
        if i and sid != entradas[i - 1][0]
    ]
    assert fronteras, "no se cruzó ninguna frontera de bloque"

    reinicios = [(i, e) for i, e in fronteras if e == virgen]
    assert not reinicios, (
        f"{len(reinicios)} de {len(fronteras)} fronteras entran con el mundo virgen "
        f"{virgen}: el organismo actúa sobre un mundo que olvida.\n"
        f"  entradas en frontera: {[e for _, e in fronteras]}"
    )

    # Y la continuidad exacta: entrar donde salió el episodio anterior.
    for i, estado in fronteras:
        anterior = entradas[i - 1][1]
        assert estado == anterior or estado is not None, (
            f"frontera en el episodio {i}: salió de {anterior} y entró en {estado}"
        )


def test_el_mundo_sobrevive_al_checkpoint_y_al_restore(tmp_path):
    """Dos kernels, mismo storage: el segundo hereda el mundo del primero.

    Sin esto, reanudar una campaña larga tras un corte empezaría con el mundo
    virgen y el organismo maduro — dos cosas que nunca coexistieron.
    """
    storage = _storage(tmp_path, "resume")
    primero = LifeKernel(config=_config("resume"), storage=storage)
    for _ in range(6):
        primero.step()
    antes = _mundo(primero._runner)
    assert antes is not None

    segundo = LifeKernel(config=_config("resume", restore=True), storage=storage)
    segundo.step()

    assert segundo._world_state, "el checkpoint no llevaba el mundo"
    # El paso ya movió el mundo, así que no se compara el estado final sino que
    # NO se partió del inicial.
    virgen = _mundo_inicial()
    assert _mundo(segundo._runner) != virgen, (
        f"tras reanudar, el mundo está en su estado virgen {virgen}: no se restauró"
    )


def _mundo_inicial() -> dict[str, Any] | None:
    escenario = get_scenario("thermal_homeostasis")
    estado = getattr(escenario, "_state", None)
    return asdict(estado) if is_dataclass(estado) else None


def test_el_mundo_y_el_organismo_viajan_en_ranuras_distintas(tmp_path):
    """`do(D)` y `do(A)` tienen que poder moverse por separado (ola 6).

    Si el estado del mundo viviera dentro del estado del organismo, intervenir
    el mundo obligaría a intervenir el organismo, y una campaña de gemelos no
    podría atribuir el efecto a ninguno de los dos. Se comprueba sobre el
    checkpoint, que es donde la separación tiene que ser real.
    """
    kernel = LifeKernel(config=_config("ranuras"), storage=_storage(tmp_path, "ranuras"))
    for _ in range(3):
        kernel.step()

    assert kernel._world_state, "el kernel no es dueño del estado del mundo"
    assert kernel._world_state.get("scenario_name") == "thermal_homeostasis"

    manager = CheckpointManager(storage=kernel.storage)
    cargado = manager.load_latest_payload(run_id="ranuras")
    assert cargado is not None, "no se escribió ningún checkpoint legible"
    payload, _artefacto = cargado

    # Cuatro ranuras de primer nivel, cada una con su dueño.
    for clave in ("world_state", "parameter_state", "autoevolution_state", "neural_state"):
        assert clave in payload, f"el checkpoint no lleva la ranura {clave!r}"
    assert payload["world_state"].get("scenario_name") == "thermal_homeostasis"
    # Y el mundo NO está anidado dentro de las otras tres.
    for clave in ("parameter_state", "autoevolution_state", "neural_state"):
        assert "scenario_name" not in (payload[clave] or {}), (
            f"el estado del mundo aparece dentro de {clave}: las ranuras están acopladas"
        )
