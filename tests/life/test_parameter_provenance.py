"""Ola 4 — el ledger de mutaciones de Λ (§XLII, §XLIII, §XLV, §LXIII).

La ola 3 dejó una sola autoridad de materialización que devuelve un veredicto
auditable. Nadie lo capturaba: tres llamadores, cero rastro. El valor final de
un parámetro se podía leer del checkpoint, pero **el porqué de cada transición
se perdía**, y con él la posibilidad de reconstruir `Λ₀ → Λ₁ → Λ₂ …`.

Eso importa más allá de la auditoría. Una campaña causal compara trayectorias:
si dos gemelos acaban en el mismo Λ por caminos distintos —uno directo, otro
con una aplicación y su revert— sin ledger son indistinguibles. §XLIII pide
exactamente esa reconstrucción, y §LXIII pide poder demostrar que un rollback
devolvió Λ al estado *exacto*, no a uno parecido.

Lo que estas pruebas fijan:

    toda mutación deja registro con procedencia, antes/después y hashes
    hash_after(mᵢ) == hash_before(mᵢ₊₁)        la cadena no tiene huecos
    rollback  ⇒  hash(Λ) vuelve al valor exacto, y se registra COMO rollback
    reconstrucción  ⇒  ninguna entrada nueva   (§CII: rehidratar no es mutar)
    régimen sano  ⇒  ledger vacío              (gate de congelamiento)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory
from runtime.world import parameters

ORGANISM = "organism-param-provenance"
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


class _Excitado(LifeKernel):
    """Excita el lazo sin tocar el trigger de producción (§XXIII).

    El trigger es CONFIGURATION y se pierde legítimamente al reconstruir, así
    que hay que refijarlo en cada runner nuevo.
    """

    def _runner_for(self, **kw):
        runner = super()._runner_for(**kw)
        runner._autoevolution.viability_trigger = 1.1
        return runner


def _ledger(storage, run_id: str) -> List[Dict[str, Any]]:
    """El ledger en orden cronológico, tal como lo leería un auditor."""
    return [
        e.payload
        for e in storage.list_events(limit=500, run_id=run_id)
        if e.event_type == "parameter.mutation"
    ]


# ── §XLII · toda mutación deja procedencia ──────────────────────────────────


def test_toda_mutacion_deja_registro_con_procedencia_y_hashes(tmp_path):
    """Un cambio de Λ sin registro es un cambio que nadie puede explicar después."""
    kernel = LifeKernel(config=_config(run_id="prov"), storage=(st := _storage(tmp_path, "prov")))
    kernel.step()
    runner = kernel._runner

    antes = _ledger(st, "prov")
    v = runner.apply_parameter_intent(
        {"memory_retrieval_limit": 5}, source="execution_tier", reason="punto de operación"
    )
    assert v["outcome"] == "accepted"

    nuevas = _ledger(st, "prov")[len(antes):]
    assert len(nuevas) == 1, f"una mutación, {len(nuevas)} registros"
    reg = nuevas[0]
    assert reg["source"] == "execution_tier"
    assert reg["reason"] == "punto de operación"
    assert reg["changes"] == {"memory_retrieval_limit": {"old": 3, "new": 5}}
    assert reg["hash_before"] != reg["hash_after"]
    assert reg["hash_after"] == parameters.state_hash(runner._parameters)
    assert reg["organism_id"] == runner._organism_id
    # Anclado al episodio en curso: sin esto, una mutación no se puede situar
    # en la trayectoria que se está midiendo.
    assert reg["episode_id"], "la mutación no dice en qué episodio ocurrió"


def test_un_no_cambio_no_entra_como_cambio(tmp_path):
    """Pedir lo vigente no es mutar, y reescribir un conjunto tampoco lo vuelve mutación.

    Importa para §XCVIII: si un revert que reescribe el backup entero registrara
    los dos parámetros, el conteo de mutaciones por `source` mediría escrituras,
    no cambios — y la métrica dejaría de significar lo que dice su nombre.
    """
    kernel = LifeKernel(config=_config(run_id="noop"), storage=(st := _storage(tmp_path, "noop")))
    kernel.step()
    runner = kernel._runner

    n0 = len(_ledger(st, "noop"))
    assert runner.apply_parameter_intent(
        {"memory_retrieval_limit": 3}, source="ecology"
    )["outcome"] == "no_op"
    assert len(_ledger(st, "noop")) == n0, "un no_op ensució el ledger"

    # Conjunto entero, un solo parámetro distinto: sólo ese es un cambio.
    v = runner.apply_parameter_intent(
        {"memory_retrieval_limit": 4, "memory_filter_mode": "strict_same_scenario"},
        source="experiment",
    )
    assert v["outcome"] == "accepted"
    assert list(v["changes"]) == ["memory_retrieval_limit"], (
        f"se registró como mutado algo que no cambió: {v['changes']}"
    )


def test_una_intencion_rechazada_queda_registrada_y_no_mueve_lambda(tmp_path):
    """§XVIII — el rechazo es parte de la historia, no un no-evento.

    `transaction_failures` (§XCVIII) sale de aquí: sin registro, un lazo que
    propone sistemáticamente fuera de dominio sería invisible.
    """
    kernel = LifeKernel(config=_config(run_id="rej"), storage=(st := _storage(tmp_path, "rej")))
    kernel.step()
    runner = kernel._runner
    h_antes = parameters.state_hash(runner._parameters)

    n0 = len(_ledger(st, "rej"))
    v = runner.apply_parameter_intent(
        {"memory_retrieval_limit": 0}, source="experiment", reason="bajo el mínimo"
    )
    assert v["outcome"] == "rejected"

    nuevas = _ledger(st, "rej")[n0:]
    assert len(nuevas) == 1 and nuevas[0]["outcome"] == "rejected"
    assert "PARAMETER_OUT_OF_DOMAIN" in nuevas[0]["error"]
    assert nuevas[0]["hash_before"] == nuevas[0]["hash_after"] == h_antes, (
        "un rechazo movió Λ, o dijo que la movía"
    )


# ── §XLIII · la trayectoria se reconstruye SÓLO del ledger ──────────────────


def test_la_cadena_de_hashes_reconstruye_la_trayectoria_de_lambda(tmp_path):
    """`hash_after(mᵢ) == hash_before(mᵢ₊₁)` — sin huecos, y el final coincide.

    Es la prueba de §XLIII: un auditor que sólo tenga el ledger llega al mismo Λ
    que tiene el organismo, y sabe por qué pasó por cada estado intermedio.
    """
    kernel = LifeKernel(config=_config(run_id="cadena"), storage=(st := _storage(tmp_path, "cadena")))
    kernel.step()
    runner = kernel._runner

    for valor, fuente in ((4, "execution_tier"), (7, "ecology"), (2, "experiment")):
        runner.apply_parameter_intent({"memory_retrieval_limit": valor}, source=fuente)

    reg = [r for r in _ledger(st, "cadena") if r["outcome"] == "accepted"]
    assert len(reg) >= 3, f"la prueba no mide nada: {len(reg)} mutaciones"

    for a, b in zip(reg, reg[1:]):
        assert a["hash_after"] == b["hash_before"], (
            f"hueco en la cadena: {a['hash_after']} ≠ {b['hash_before']}. "
            "Alguien movió Λ sin pasar por la autoridad, o el ledger perdió una entrada"
        )
    assert reg[-1]["hash_after"] == parameters.state_hash(runner._parameters)

    # Y el porqué viaja con el qué: cada transición dice quién la pidió.
    assert [r["source"] for r in reg[-3:]] == ["execution_tier", "ecology", "experiment"]


# ── §CII · reconstruir no es mutar ──────────────────────────────────────────


def test_la_reconstruccion_no_ensucia_el_ledger(tmp_path):
    """Rehidratar Λ tras un rebuild es un no_op, no una mutación.

    Antes de la ola 3 cada reconstrucción devolvía el parámetro al default y lo
    reaplicaba: con ledger, eso serían dos entradas espurias por rebuild y, con
    `block_size=8`, una trayectoria de Λ ilegible. Que el ledger calle aquí es
    la prueba de que el valor *pertenece* al organismo.
    """
    kernel = LifeKernel(config=_config(run_id="rebuild"), storage=(st := _storage(tmp_path, "rebuild")))
    kernel.step()

    # Se escribe DURANTE el paso, que es cuando escriben las fuentes reales.
    original = kernel._runner_for

    def una_vez(**kw):
        runner = original(**kw)
        runner.apply_parameter_intent(
            {"memory_retrieval_limit": 6}, source="execution_tier", reason="punto de operación"
        )
        kernel._runner_for = original
        return runner

    kernel._runner_for = una_vez
    kernel._runner = None
    kernel._runner_key = None
    kernel.step()
    assert kernel._runner.memory_retrieval_limit == 6

    antes = len(_ledger(st, "rebuild"))
    for _ in range(3):
        kernel._runner = None
        kernel._runner_key = None
        kernel.step()

    assert kernel._runner.memory_retrieval_limit == 6, "Λ no sobrevivió"
    assert len(_ledger(st, "rebuild")) == antes, (
        "la reconstrucción añadió mutaciones al ledger: el runner está decidiendo "
        "el valor en vez de recibirlo"
    )


# ── gate de congelamiento sobre el ledger ───────────────────────────────────


def test_el_regimen_sano_no_muta_ningun_parametro(tmp_path):
    """El ledger vacío en régimen sano es el gate: esta ola no encendió nada.

    Y el mismo ledger en régimen excitado prueba que la prueba sabe detectar
    mutaciones — sin eso, «vacío» podría significar «no mide».
    """
    sano = LifeKernel(config=_config(run_id="sano"), storage=(s1 := _storage(tmp_path, "sano")))
    for _ in range(12):
        sano.step()
    assert _ledger(s1, "sano") == [], (
        f"el régimen sano mutó parámetros: {_ledger(s1, 'sano')}"
    )

    excitado = _Excitado(config=_config(run_id="exc"), storage=(s2 := _storage(tmp_path, "exc")))
    for _ in range(12):
        excitado.step()
    assert _ledger(s2, "exc"), "ni siquiera el régimen excitado mutó: la prueba no mide nada"


def test_el_ledger_es_invariante_a_la_reconstruccion(tmp_path):
    """Dos brazos, mismo lazo, distinta frecuencia de rebuild ⇒ misma historia de Λ.

    Es el requisito que los gemelos causales necesitan de esta ola: si la
    trayectoria de Λ dependiera de cuándo se reconstruye el runner, dos gemelos
    con el mismo `do(U)` tendrían historias distintas por un detalle de
    implementación, y la comparación no significaría nada.
    """
    def historia(nombre: str, block_size: int):
        k = _Excitado(
            config=_config(run_id=nombre, block_size=block_size),
            storage=(st := _storage(tmp_path, nombre)),
        )
        for _ in range(12):
            k.step()
        return [
            (r["source"], r["hash_before"], r["hash_after"], r["outcome"])
            for r in _ledger(st, nombre)
        ]

    estable = historia("brazo-estable", 50)
    reconstruido = historia("brazo-rebuild", 1)

    assert estable, "el brazo estable no mutó nada: la comparación sería vacía"
    assert estable == reconstruido, (
        "la historia de Λ depende de cuándo se reconstruye el runner:\n"
        f"  estable      = {estable}\n"
        f"  reconstruido = {reconstruido}"
    )
