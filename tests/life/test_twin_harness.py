"""Ola 6 — dos gemelos empiezan siendo el mismo organismo, y se demuestra.

`do(U)` sólo significa algo si lo que difiere después difiere **por la
intervención y por nada más**. Eso exige probar antes que `X₀ᴬ = X₀ᴮ`.

Estas pruebas fijan lo que el harness tiene que garantizar:

    dos gemelos construidos igual  ⇒  misma huella de origen
    una diferencia real           ⇒  se NIEGA a continuar, y dice en qué pieza
    calcular la huella            ⇒  no mueve nada
    do(U)                         ⇒  pasa por la autoridad y queda en el ledger

La pieza `world` de la huella no existía hasta cerrar H-047: hasta ayer dos
gemelos podían tener la misma huella y mundos distintos, porque el mundo no
pertenecía al organismo. Esa prueba es, además, la demostración de que la
reparación era prerrequisito de esta ola y no un arreglo suelto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.life.twins import (
    TwinsDiverged,
    assert_same_origin,
    compare_origin,
    component_hashes,
    identity_hash,
    intervene,
)
from runtime.storage import StorageConfig, StorageFactory

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
        organism_id="organism-twin",
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


def _gemelo(tmp_path: Path, nombre: str, pasos: int = 3, **kw):
    """Un gemelo se CONSTRUYE de cero, no se copia.

    `deepcopy` no es una opción sobre un organismo con tensores que son nodos de
    grafo, y construir de nuevo es además más fuerte: la identidad se comprueba
    en vez de heredarse. Es la lección que Terrario ya había pagado.
    """
    kernel = LifeKernel(
        config=_config(nombre, **kw), storage=_storage(tmp_path, nombre)
    )
    for _ in range(pasos):
        kernel.step()
    return kernel


# ── X₀ᴬ = X₀ᴮ ───────────────────────────────────────────────────────────────


def test_dos_gemelos_construidos_igual_comparten_origen(tmp_path):
    """La misma configuración y los mismos pasos ⇒ la misma huella.

    Si esto fallara, no habría campaña causal posible: ninguna diferencia
    posterior sería atribuible a la intervención.
    """
    a = _gemelo(tmp_path, "gem-a")
    b = _gemelo(tmp_path, "gem-b")

    veredicto = assert_same_origin(a, b)
    assert veredicto.identical
    assert veredicto.hash_a == veredicto.hash_b
    assert veredicto.diverging == ()
    # Y la huella es de verdad de algo: no puede ser la de un kernel vacío.
    assert set(veredicto.components_a) == {
        "organism", "lineage", "parameters", "world", "autoevolution", "neural"
    }


def test_el_run_id_no_entra_en_la_huella(tmp_path):
    """Dos gemelos son dos ejecuciones: comparten estado, no identidad de corrida.

    Si el `run_id` contara, `X₀ᴬ = X₀ᴮ` sería imposible por construcción y la
    comprobación diría siempre que no — tan inútil como decir siempre que sí.
    """
    a = _gemelo(tmp_path, "run-uno")
    b = _gemelo(tmp_path, "run-dos")
    assert identity_hash(a) == identity_hash(b)


def test_una_divergencia_real_detiene_el_experimento(tmp_path):
    """Negarse es el punto: intervenir sobre orígenes distintos produce una
    diferencia que nadie puede atribuir, y se ve igual de convincente."""
    a = _gemelo(tmp_path, "div-a", pasos=3)
    b = _gemelo(tmp_path, "div-b", pasos=5)   # una vida más larga: otro organismo

    with pytest.raises(TwinsDiverged) as excinfo:
        assert_same_origin(a, b)
    # Y dice EN QUÉ pieza, no sólo que difieren.
    assert "organism" in str(excinfo.value)

    veredicto = compare_origin(a, b)
    assert not veredicto.identical and veredicto.diverging


def test_el_mundo_forma_parte_de_la_identidad(tmp_path):
    """H-047 era prerrequisito de esta ola, y esto lo demuestra.

    Dos gemelos con todo igual salvo el mundo tienen que salir divergentes.
    Antes de que el mundo perteneciera al organismo esto era inexpresable: el
    mundo no estaba en ninguna parte que una huella pudiera leer.
    """
    a = _gemelo(tmp_path, "mundo-a")
    b = _gemelo(tmp_path, "mundo-b")
    assert compare_origin(a, b).identical, "los gemelos no partían iguales"

    # Se mueve SÓLO el mundo de B.
    b._world_state = dict(b._world_state)
    estado = dict(b._world_state.get("state") or {})
    estado["temperature"] = round(float(estado.get("temperature", 0.0)) + 0.1, 4)
    b._world_state["state"] = estado

    veredicto = compare_origin(a, b)
    assert not veredicto.identical
    assert veredicto.diverging == ("world",), (
        f"mover el mundo tocó otras piezas: {veredicto.diverging}"
    )


# ── observar no debe mutar ─────────────────────────────────────────────────


def test_calcular_la_huella_no_mueve_nada(tmp_path):
    """Terrario lo midió y costó tres resultados: examinar contaminaba lo examinado.

    Percibir una sonda avanzaba el estado recurrente y el contador, así que el
    ORDEN de los exámenes pasaba a formar parte del resultado. Aquí la huella se
    calcula sólo con lecturas de payloads ya exportados.
    """
    kernel = _gemelo(tmp_path, "inerte")
    antes = identity_hash(kernel)
    pasos_antes = kernel.total_steps

    for _ in range(5):
        identity_hash(kernel)
        component_hashes(kernel)
        compare_origin(kernel, kernel)

    assert identity_hash(kernel) == antes, "medir la identidad la cambió"
    assert kernel.total_steps == pasos_antes, "medir avanzó el contador de pasos"


# ── do(U) ───────────────────────────────────────────────────────────────────


def test_la_intervencion_pasa_por_la_autoridad_y_deja_rastro(tmp_path):
    """Una `do(U)` que no deja rastro es indistinguible de una deriva."""
    kernel = _gemelo(tmp_path, "intervenido")

    veredicto = intervene(kernel, {"memory_retrieval_limit": 7}, reason="do(U): k=7")
    assert veredicto["outcome"] == "accepted"
    assert veredicto["source"] == "experiment"
    assert veredicto["changes"]["memory_retrieval_limit"]["new"] == 7
    assert veredicto["hash_before"] != veredicto["hash_after"]

    mutaciones = [
        e.payload
        for e in kernel.storage.list_events(limit=500, run_id="intervenido")
        if e.event_type == "parameter.mutation"
    ]
    assert mutaciones and mutaciones[-1]["reason"] == "do(U): k=7"


def test_la_intervencion_hace_divergir_a_los_gemelos(tmp_path):
    """Antes de `do(U)` son el mismo; después, difieren SÓLO en lo intervenido.

    Ése es el experimento entero en una prueba: si la intervención tocara algo
    más, la diferencia de conducta posterior no sería atribuible a `u`.
    """
    a = _gemelo(tmp_path, "par-a")
    b = _gemelo(tmp_path, "par-b")
    assert_same_origin(a, b)          # se niega si no

    intervene(b, {"memory_retrieval_limit": 9}, reason="do(U): k=9")
    b._parameter_state = b._runner.export_parameter_state()

    veredicto = compare_origin(a, b)
    assert not veredicto.identical
    assert veredicto.diverging == ("parameters",), (
        f"la intervención tocó más que Λ: {veredicto.diverging}"
    )
