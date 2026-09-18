"""R-012 — la historia de certificación no puede depender de que viva un runner.

`trajectory_reward="previous_certificate"` entrega al trayecto el último veredicto
emitido, porque en el paso 12c el certificado de ESTE episodio todavía no existe
(se emite en el 13). El veredicto anterior se cacheaba en
`ScenarioEpisodeRunner._last_certification`, un atributo de una instancia que el
kernel destruye cada `block_size` episodios, tras cada refugio y al cambiar la
clave de `_runner_for`.

Consecuencia medida: en el primer episodio de cada runner nuevo la caché está
vacía, no hay inyección, y el organismo cobra la penalización de «no certificado»
aunque el episodio anterior estuviera certificado. **Una penalización espuria por
reconstrucción.** Con `block_size=1` eso es una por paso.

El defecto no es el cacheo: es que la caché sea la FUENTE DE VERDAD. Los
certificados se persisten (`write_episode_certificate`) y las decisiones de
promoción también, así que `C_{t-1}` es rederivable del ledger. La caché puede
quedarse por eficiencia; lo que no puede es ser lo único que lo sabe.

Estas pruebas miden la penalización espuria directamente: cuentan las
transiciones que toman la rama «no certificado» teniendo un certificado anterior
CERTIFICADO en el ledger. En el sistema correcto son cero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from runtime.life import LifeKernel, LifeKernelConfig
from runtime.organism.trajectory_state_machine import TrajectoryStateMachine
from runtime.storage import StorageConfig, StorageFactory

ORGANISM = "organism-cert-continuity"
SNAP = {
    "cpu_pressure": 0.1,
    "memory_pressure": 0.1,
    "thermal_pressure": 0.1,
    "vram_pressure": 0.1,
    "gpu_available": False,
}


def _storage(tmp_path: Path, name: str = "cert"):
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


def _config(*, run_id: str, block_size: int, restore: bool = False):
    return LifeKernelConfig(
        run_id=run_id,
        organism_id=ORGANISM,
        scenarios=("thermal_homeostasis",),
        block_size=block_size,
        max_steps=0,
        restore=restore,
        checkpoint_interval=1,
        trajectory_reward="previous_certificate",
        allow_external_reasoner=False,
        enable_msrc=False,
        enable_operational_conjunction=False,
        resource_snapshot_override=dict(SNAP),
    )


class _spy:
    """Registra, por transición, qué veredicto vio el trayecto y qué rama tomó.

    Context manager y no fixture: dos brazos en el mismo test anidarían los
    parches y el primer espía recogería también las transiciones del segundo.
    """

    def __init__(self):
        self.seen: List[Dict[str, Any]] = []
        self._original = TrajectoryStateMachine.advance_state

    def __enter__(self):
        original = self._original
        seen = self.seen

        def espia(machine, *, current, episode_result, regime, new_state_id, timestamp):
            cert = dict(episode_result.get("certification") or {})
            antes = float(current.viability.viability_margin)
            salida = original(
                machine, current=current, episode_result=episode_result, regime=regime,
                new_state_id=new_state_id, timestamp=timestamp,
            )
            despues = float(salida.viability.viability_margin)
            seen.append(
                {
                    "verdict_visto": cert.get("verdict"),
                    "certificada": cert.get("verdict") == "certified",
                    "delta": round(despues - antes, 9),
                    "margen_antes": round(antes, 9),
                }
            )
            return salida

        TrajectoryStateMachine.advance_state = espia
        return self.seen

    def __exit__(self, *exc):
        TrajectoryStateMachine.advance_state = self._original
        return False


def _penalizadas(seen) -> List[int]:
    """Transiciones que tomaron la rama «no certificado», por índice.

    La rama se reconoce por el signo: certificado ⇒ +0.01·g, no certificado ⇒
    −0.03·g. Se ignoran las saturadas contra el clamp (delta 0 con margen en 0 ó 1).
    """
    out = []
    for i, r in enumerate(seen):
        if r["delta"] < 0:
            out.append(i)
    return out


def _certificados_en_ledger(storage, run_id: str) -> int:
    return sum(
        1 for c in storage.list_episode_certificates(run_id=run_id, limit=500)
        if c.verdict == "certified"
    )


def _correr(tmp_path, *, run_id: str, block_size: int, steps: int):
    storage = _storage(tmp_path, run_id)
    with _spy() as seen:
        kernel = LifeKernel(config=_config(run_id=run_id, block_size=block_size), storage=storage)
        for _ in range(steps):
            kernel.step()
    return list(seen), storage, kernel


# ── El defecto, medido ───────────────────────────────────────────────────────


def test_rebuild_no_produce_penalizaciones_espurias(tmp_path):
    """Un runner reconstruido en cada paso no debe cobrar de más.

    Con `block_size=1` el kernel destruye el runner tras cada episodio. Si la
    historia de certificación depende del runner, cada primer episodio del runner
    nuevo pierde `C_{t-1}` y cobra la penalización de «no certificado» aunque el
    episodio anterior esté certificado en el ledger.
    """
    seen, storage, _ = _correr(tmp_path, run_id="rb", block_size=1, steps=10)

    certificados = _certificados_en_ledger(storage, "rb")
    assert certificados >= 8, f"la corrida no certificó lo suficiente para medir: {certificados}"

    # Tras el primer episodio (que no tiene anterior), toda transición debería ver
    # el veredicto del episodio previo. Ninguna debería tomar la rama negativa.
    espurias = [i for i in _penalizadas(seen) if i > 0]
    assert espurias == [], (
        f"{len(espurias)} penalizaciones espurias por reconstrucción, en las "
        f"transiciones {espurias[:8]}; veredictos vistos: "
        f"{[seen[i]['verdict_visto'] for i in espurias[:8]]}"
    )


def test_los_dos_brazos_ven_el_mismo_veredicto_anterior(tmp_path):
    """Brazo estable vs brazo reconstruido en cada paso: misma historia epistemológica.

    `C_{t-1}^{rebuild} = C_{t-1}^{stable}` para cada paso lógico equivalente. Esto
    es lo que R-012 posee y cierra: el VEREDICTO, que es lo que decide el signo.
    """
    estable, _, _ = _correr(tmp_path, run_id="est", block_size=50, steps=10)
    rebuild, _, _ = _correr(tmp_path, run_id="reb", block_size=1, steps=10)

    va = [r["verdict_visto"] for r in estable]
    vb = [r["verdict_visto"] for r in rebuild]
    assert va == vb, f"la historia de certificación difiere:\n  estable={va}\n  rebuild={vb}"

    # Y por tanto la RAMA (el signo de Δm) coincide en los dos brazos.
    sa = [(r["delta"] > 0) - (r["delta"] < 0) for r in estable]
    sb = [(r["delta"] > 0) - (r["delta"] < 0) for r in rebuild]
    assert sa == sb, f"el signo de Δm difiere:\n  estable={sa}\n  rebuild={sb}"


def test_la_magnitud_de_delta_m_tambien_coincide(tmp_path):
    """La MAGNITUD requiere algo que R-012 no poseía. Ya lo posee.

    Esta prueba nació como tripwire `xfail(strict)` de H-047 y **disparó**:
    cerrado el ownership del mundo, pasó, y el `strict` la convirtió en fallo
    hasta retirar la marca. Es la confirmación más fuerte de la reparación —
    la escribió quien no podía hacerla pasar.

    Reparado R-012, los dos brazos ya coinciden en veredicto y en signo. Siguen
    difiriendo en `|Δm|`, y la causa está medida: `g = clip(1 − |f−cf| + …)` y el
    `gap = |factual − counterfactual|` vale 0.07 en el brazo estable y 0.0 en el
    reconstruido, con `n_memorias` idéntico en ambos.

    El motivo es que `self.scenario` —el MUNDO SIMULADO— se construye en
    `ScenarioEpisodeRunner.__init__` a partir de un nombre, así que cada
    reconstrucción lo devuelve a su estado inicial. Medido con el `block_size=8`
    por default: la temperatura observada vuelve a 0.82 en los pasos 8 y 16. El
    organismo actúa sobre el mundo y el efecto se descarta cada bloque.

    Es la clase de defecto de H-046 aplicada al mundo en vez de al organismo, y
    es de otra ola. Esta prueba queda como su tripwire: cuando el mundo persista
    entre reconstrucciones, pasará sola y habrá que quitarle la marca.
    """
    estable, _, _ = _correr(tmp_path, run_id="mag-est", block_size=50, steps=10)
    rebuild, _, _ = _correr(tmp_path, run_id="mag-reb", block_size=1, steps=10)
    da = [r["delta"] for r in estable]
    db = [r["delta"] for r in rebuild]
    assert da == db, f"Δm difiere entre brazos:\n  estable={da}\n  rebuild={db}"


def test_el_veredicto_anterior_se_rederiva_del_ledger_sin_cache(tmp_path):
    """Vaciar la caché a mano no debe cambiar nada: el ledger es la fuente de verdad."""
    storage = _storage(tmp_path, "rederiva")
    kernel = LifeKernel(config=_config(run_id="rederiva", block_size=50), storage=storage)
    for _ in range(4):
        kernel.step()

    runner = kernel._runner
    assert runner is not None
    cacheado = runner._last_certification
    assert cacheado is not None, "el runner debería tener la caché caliente"

    runner._last_certification = None  # se borra la caché, no el ledger
    rederivado = runner._previous_certification()

    assert rederivado is not None, "sin caché no se pudo rederivar del ledger"
    assert rederivado["certificate_id"] == cacheado["certificate_id"]
    assert rederivado["verdict"] == cacheado["verdict"]
    assert rederivado["promotion_candidate"] == cacheado["promotion_candidate"]
    assert rederivado["decision_verdict"] == cacheado["decision_verdict"]


def test_sin_certificados_previos_no_se_inventa_nada(tmp_path):
    """Primer episodio de un run limpio: no hay `C_{t-1}` y no se fabrica uno."""
    storage = _storage(tmp_path, "virgen")
    kernel = LifeKernel(config=_config(run_id="virgen", block_size=50), storage=storage)
    runner = kernel._runner_for(
        scenario="thermal_homeostasis",
        closure_profile="baseline_fixed",
        memory_filter_mode="strict_same_scenario",
    )
    assert runner._previous_certification() is None
