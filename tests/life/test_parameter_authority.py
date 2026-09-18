"""Ola 3 — una sola autoridad de mutación por parámetro (§XI, §CIX, §LIX, §LXII).

`memory_retrieval_limit` tiene hoy cuatro escritores:

    scenario_runner.py:215   __init__              literal 3, en CADA construcción
    scenario_runner.py:338   _apply_knob_changes   autoevolución + adopted_knobs
    kernel.py:877            directive del tier    tras routing_enforced()
    ecology.py:176           _run_member           driver paralelo, runner propio

El objetivo no es que haya un solo DECISOR —varias capas pueden producir
intenciones legítimas: el tier pide un punto de operación, la autoevolución
propone, la ecología expresa el genoma de un miembro— sino que haya una sola
capa que MATERIALICE la mutación, y que el valor vigente pertenezca al organismo
en vez de a la instancia que lo consume.

Dos invariantes, y estas pruebas los miden en el camino productivo:

    ∀ parámetro de runtime:  escritores efectivos = 1
    reconstrucción de objeto  ⇏  vuelta al default

El segundo es §CII: un default pertenece al bootstrap, no a cada construcción de
un consumidor. Hoy `__init__` lo decide siempre, y lo que salva el valor es que
la ola 1 lo reaplique desde `adopted_knobs` — pero sólo si fue la autoevolución
quien lo escribió. Un valor de cualquier otra procedencia se pierde.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Dict, List

import pytest

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory
from runtime.world.scenario_runner import ScenarioEpisodeRunner

ORGANISM = "organism-param-authority"
SNAP = {
    "cpu_pressure": 0.1,
    "memory_pressure": 0.1,
    "thermal_pressure": 0.1,
    "vram_pressure": 0.1,
    "gpu_available": False,
}
PARAMETRO = "memory_retrieval_limit"


def _storage(tmp_path: Path, name: str = "param"):
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


def _config(*, run_id: str, block_size: int = 50, **kw):
    base = dict(
        run_id=run_id,
        organism_id=ORGANISM,
        scenarios=("thermal_homeostasis",),
        block_size=block_size,
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


class _escrituras:
    """Registra cada escritura del parámetro sobre un runner, con su procedencia.

    Sustituye el atributo por una property de clase. Cualquier `runner.<param> = v`
    queda anotado con el marco del repo que lo hizo, así que «cuántos escritores
    efectivos hay» deja de ser una lectura de código y pasa a ser una medición.
    """

    def __init__(self, parametro: str = PARAMETRO):
        self.parametro = parametro
        self.log: List[Dict[str, Any]] = []
        self._oculto = f"_medido_{parametro}"
        self._previo = ScenarioEpisodeRunner.__dict__.get(parametro)

    def __enter__(self):
        log, oculto = self.log, self._oculto

        def getter(runner):
            return getattr(runner, oculto, None)

        def setter(runner, value):
            marcos = [
                f"{Path(fr.filename).name}:{fr.lineno}:{fr.name}"
                for fr in traceback.extract_stack()[:-1]
                if "RNE_v16-genesis-v2" in fr.filename and "test_" not in fr.filename
            ]
            log.append(
                {
                    "valor": value,
                    "origen": marcos[-1] if marcos else "(fuera del repo)",
                    "pila": marcos[-3:],
                }
            )
            setattr(runner, oculto, value)

        setattr(ScenarioEpisodeRunner, self.parametro, property(getter, setter))
        return self.log

    def __exit__(self, *exc):
        if self._previo is None:
            delattr(ScenarioEpisodeRunner, self.parametro)
        else:
            setattr(ScenarioEpisodeRunner, self.parametro, self._previo)
        return False


def _origenes(log, *, excluir_bootstrap: bool) -> Dict[str, int]:
    """Origen → nº de escrituras. El bootstrap del constructor se puede excluir."""
    out: Dict[str, int] = {}
    for w in log:
        if excluir_bootstrap and ":__init__" in w["origen"]:
            continue
        out[w["origen"]] = out.get(w["origen"], 0) + 1
    return out


def _fijar_durante_el_paso(kernel, valor: int) -> None:
    """Fija el parámetro como lo haría el tier: dentro del paso, antes del episodio."""
    original = kernel._runner_for

    def una_vez(**kw):
        runner = original(**kw)
        runner.memory_retrieval_limit = valor
        kernel._runner_for = original
        return runner

    kernel._runner_for = una_vez
    kernel._runner = None
    kernel._runner_key = None
    kernel.step()


# ── §CIX · ¿cuántos escritores efectivos tiene el knob? ─────────────────────


def test_el_parametro_tiene_una_sola_autoridad_de_mutacion(tmp_path):
    """Objetivo: escritores efectivos = 1. El bootstrap no cuenta como mutación.

    Hoy fallan dos cosas a la vez: el constructor decide el valor en cada
    reconstrucción (no es bootstrap, es un consumidor eligiendo), y la
    autoevolución escribe por su lado. Con una autoridad única, toda escritura
    posterior al arranque pasa por ella.
    """
    with _escrituras() as log:
        kernel = LifeKernel(config=_config(run_id="auth", block_size=1), storage=_storage(tmp_path))
        for _ in range(8):
            kernel.step()

    assert log, "nadie escribió el parámetro: la prueba no mide nada"

    # Una sola autoridad de mutación, excluido el bootstrap.
    efectivos = _origenes(log, excluir_bootstrap=True)
    assert len(efectivos) <= 1, (
        f"{len(efectivos)} autoridades de mutación distintas, deben ser 1: {efectivos}"
    )

    # Y ninguna escritura del constructor puede CONTRADECIR el valor vigente.
    # El constructor escribe una vez por construcción y eso es legítimo; lo que
    # no lo es es que devuelva el parámetro al default (§CII). Se mide sobre el
    # valor, no sobre el número de escrituras: así la prueba no depende de por
    # dónde se implemente el traspaso.
    vigente = None
    for w in log:
        if ":__init__" in w["origen"]:
            assert vigente is None or w["valor"] == vigente, (
                f"una reconstrucción puso el parámetro en {w['valor']!r} habiendo "
                f"{vigente!r} vigente: el consumidor lo decidió en vez de recibirlo "
                f"({w['origen']})"
            )
        vigente = w["valor"]


# ── §LXII · el valor sobrevive a la reconstrucción, lo escribiera quien lo escribiera ──


def test_el_valor_vigente_sobrevive_a_la_reconstruccion(tmp_path):
    """Un runner nuevo debe RECIBIR el parámetro, no decidirlo (§XVI).

    El valor se fija por una vía que no es la autoevolución —aquí, directamente
    sobre el runner vivo, como hacen el tier y la ecología— y después se fuerza
    la reconstrucción. Si el parámetro pertenece al organismo, sobrevive.
    """
    kernel = LifeKernel(config=_config(run_id="persist"), storage=_storage(tmp_path, "persist"))
    kernel.step()

    runner = kernel._runner
    assert runner is not None
    assert runner.memory_retrieval_limit == 3, "el default histórico cambió; revisar la prueba"

    # Se escribe DURANTE un paso, que es cuando escriben las fuentes reales: el
    # tier lo hace en `_runner_for` y la ecología al construir su runner. Λ se
    # sincroniza al cerrar el paso, así que escribir entre pasos —como hacía la
    # primera versión de esta prueba— no reproduce ninguna ruta de producción.
    _fijar_durante_el_paso(kernel, 5)

    kernel._runner = None  # reconstrucción, como el cierre de bloque
    kernel._runner_key = None
    kernel.step()

    assert kernel._runner is not None
    assert kernel._runner.memory_retrieval_limit == 5, (
        f"la reconstrucción devolvió el parámetro a "
        f"{kernel._runner.memory_retrieval_limit}: el constructor lo decidió en vez de recibirlo"
    )


def test_el_default_solo_aplica_sin_estado_previo(tmp_path):
    """§CII — `reconstrucción ⇒ reset al default` no debe ocurrir nunca.

    Arranque limpio: el default es legítimo. Tras haberse fijado un valor, ya no.
    """
    kernel = LifeKernel(config=_config(run_id="boot"), storage=_storage(tmp_path, "boot"))
    kernel.step()
    assert kernel._runner.memory_retrieval_limit == 3  # bootstrap legítimo

    _fijar_durante_el_paso(kernel, 2)
    for _ in range(3):
        kernel._runner = None
        kernel._runner_key = None
        kernel.step()
        assert kernel._runner.memory_retrieval_limit == 2, (
            "el parámetro volvió al default en una reconstrucción posterior al arranque"
        )
