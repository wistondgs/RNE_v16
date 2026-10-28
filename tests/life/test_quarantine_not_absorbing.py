"""Ola 5 — una cuarentena atascada no puede ser un estado absorbente (H-050).

Medido en el régimen de referencia, 60 pasos, configuración default:

    paso  0: EEEEEEEEEEEEEEEEEEEEEEEEEEEEEE
    paso 30: Eqqqqqqqqqqqqqqqqqqqqqqqqqqqqq       E=episodio  q=cuarentena

31 episodios, y a partir del 31 nada: 29 pasos con el margen clavado en 0.1435,
min = max. El organismo deja de ejecutar y no vuelve.

Existe una salida —`_handle_non_acting_decision`, «refugio sano»: tras 3
cuarentenas seguidas se rueda al último yo sano— y nunca dispara, porque su
contador está detrás de `self._experience is not None`, que depende de
`RNFE_EXPERIENCE`, apagada por default.

Salir de una cuarentena atascada y guardar memoria de golpes son dos
capacidades distintas. Compartían rama, y Wis confirmó que el acoplamiento no
es deliberado.

Lo que estas pruebas fijan:

    el refugio no depende del almacén de experiencia
    ninguna corrida termina en una cola de cuarentena sin fin

El umbral 0.15 que decide la cuarentena NO se toca: está congelado (§X). Lo que
se repara es que la salida exista de verdad, no cuándo se entra.
"""

from __future__ import annotations

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
        organism_id="organism-quarantine",
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


def _patron(kernel, pasos: int) -> str:
    """`E` por paso con episodio, `q` sin él. La secuencia, no el conteo.

    El conteo no distingue un pestillo del que no se sale de una alternancia;
    la secuencia sí, y la diferencia es lo único que importa aquí.
    """
    out = []
    for _ in range(pasos):
        res = kernel.step()
        out.append("E" if res.episode_result is not None else "q")
    return "".join(out)


def _cola_sin_episodio(patron: str) -> int:
    return len(patron) - len(patron.rstrip("q"))


def test_el_refugio_no_depende_del_almacen_de_experiencia(tmp_path, monkeypatch):
    """La salida de la cuarentena debe existir con las gates en su default.

    Es la prueba directa del acoplamiento: se fuerza el default explícito de
    `RNFE_EXPERIENCE` para que la prueba no dependa del entorno de quien la
    corra, y se comprueba que el contador del refugio avanza igualmente.
    """
    monkeypatch.delenv("RNFE_EXPERIENCE", raising=False)
    kernel = LifeKernel(
        config=_config("refugio"), storage=_storage(tmp_path, "refugio")
    )
    patron = _patron(kernel, 60)

    assert "q" in patron, "el organismo nunca entró en cuarentena: la prueba no mide nada"

    quarantines = patron.count("q")
    eventos = [
        e
        for e in kernel.storage.list_events(limit=500, run_id="refugio")
        if e.event_type == "life.refuge"
    ]
    assert eventos, (
        f"{quarantines} pasos en cuarentena y ni un solo `life.refuge`: la salida "
        f"está cableada pero su contador no avanza con las gates en default"
    )


def test_ninguna_corrida_termina_en_cuarentena_sin_fin(tmp_path):
    """§XCI — el organismo no puede quedar absorbido.

    El refugio tiene paciencia 3, así que una cuarentena legítima dura unos
    pocos pasos. Una cola de decenas significa que no hay salida. El límite se
    pone holgado a propósito: la prueba mide «hay salida», no «cuán rápida es».
    """
    kernel = LifeKernel(config=_config("absorb"), storage=_storage(tmp_path, "absorb"))
    patron = _patron(kernel, 60)

    cola = _cola_sin_episodio(patron)
    assert cola <= 8, (
        f"la corrida termina con {cola} pasos seguidos sin ejecutar episodio: "
        f"estado absorbente.\n  patrón: {patron}"
    )


def test_el_organismo_sigue_ejecutando_en_la_segunda_mitad(tmp_path):
    """Que haya salida no basta: tiene que seguir viviendo después de usarla.

    Sin esto, un refugio que dispara una vez y vuelve a atascarse pasaría la
    prueba anterior por un tecnicismo de dónde cae el final de la corrida.
    """
    kernel = LifeKernel(config=_config("mitad"), storage=_storage(tmp_path, "mitad"))
    patron = _patron(kernel, 60)

    # Los últimos 20 pasos, no «la segunda mitad»: con el último episodio en el
    # paso 30, medir desde 30 haría pasar la prueba por UN carácter — guardia en
    # vez de falsación. La ventana final no admite ese tecnicismo.
    final = patron[-20:]
    assert final.count("E") > 0, (
        f"cero episodios en los últimos 20 pasos.\n  patrón: {patron}"
    )
