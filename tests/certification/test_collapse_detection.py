"""P9.6 paso 4 — el organismo puede detectar su propio colapso.

Antes (`promotion_gate.py:72-73`)::

    collapse_detected = bool(getattr(reality_assessment, "collapse_detected", False))

y en el camino vivo `reality_assessment` es SIEMPRE None (nadie lo construye: solo lo arma
el bench, `runtime/reality/service.py`). O sea: `collapse_detected` era SIEMPRE False. Y es
el ÚNICO que gatea el veredicto (`certificate_builder.py:55`): la única compuerta que el
organismo tenía estaba ciega.

Estos tests fijan las DOS mitades del contrato, que hay que sostener juntas:

1. El detector DISPARA ante un colapso real (continuidad hundida y SOSTENIDA en racha).
2. El detector NO rechaza episodios sanos — la mitad que puede matar al organismo si el
   detector resulta ruidoso.
"""

from pathlib import Path

from runtime.storage import StorageConfig, StorageFactory
from runtime.world.registry import get_scenario
from runtime.world.scenario_runner import ScenarioEpisodeRunner


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "collapse.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _runner(storage, run_id: str) -> ScenarioEpisodeRunner:
    return ScenarioEpisodeRunner(
        storage=storage,
        run_id=run_id,
        scenario=get_scenario("thermal_homeostasis"),
    )


def _certificate_of(storage, episode_result):
    """El certificado REAL que quedó persistido para ese episodio."""
    return storage.get_episode_certificate(
        certificate_id=episode_result["certification"]["certificate_id"]
    )


def _poison_continuity_history(storage, *, run_id: str, count: int = 3) -> None:
    """Escribe certificados con continuidad HUNDIDA — un organismo realmente roto.

    No es un episodio feo aislado: es la continuidad por el piso, sostenida. La secuencia de
    razonamiento queda deliberadamente incomparable con la del escenario real y la variable
    principal, lejísimos, para que el `ContinuityGuard` mida de verdad una ruptura.
    """
    for i in range(count):
        storage.write_episode_certificate(
            episode_id=f"broken-{i}",
            run_id=run_id,
            trace_id=f"trace-broken-{i}",
            smg_artifacts={},
            lotf_artifacts={},
            world_artifacts={},
            continuity_score=0.0,
            ioc_proxy=0.1,
            risk_score=0.9,
            verdict="rejected",
            rollback_ready=True,
            promotion_candidate=False,
            metadata={
                "reasoning_sequence": ["ZZZ", "YYY", "XXX"],
                "world_main_variable": "temperature",
                "world_main_variable_value": 99.0,
            },
        )


def test_healthy_episode_is_not_rejected_by_collapse_wiring(tmp_path: Path):
    """LA MITAD QUE PUEDE MATAR AL ORGANISMO: cablear el colapso NO rechaza lo sano.

    Si al cablear `collapse_detected` empezaran a rechazarse episodios normales, el detector
    sería ruidoso y el organismo quedaría sin poder certificar nada. Un episodio sano tiene
    continuidad ≈ 1.0: no se acerca ni de lejos al umbral de colapso (0.35).
    """
    storage = _storage(tmp_path)
    runner = _runner(storage, "life-collapse-healthy")

    for _ in range(3):
        result = runner.run_episode(external_input=0.04)
        certificate = _certificate_of(storage, result)
        assert certificate.metadata["collapse_detected"] is False
        assert certificate.verdict == "certified"


def test_sustained_continuity_collapse_is_detected_and_rejects(tmp_path: Path):
    """El organismo detecta su propio colapso: racha de continuidad hundida ⇒ `rejected`.

    Antes esto era IMPOSIBLE: `collapse_detected` era la constante False.
    """
    storage = _storage(tmp_path)
    run_id = "life-collapse-broken"
    runner = _runner(storage, run_id)

    # Control: el primer episodio, sin historia rota, certifica.
    healthy = runner.run_episode(external_input=0.04)
    assert _certificate_of(storage, healthy).verdict == "certified"

    # El organismo se rompe: continuidad por el piso, sostenida (racha de 3).
    _poison_continuity_history(storage, run_id=run_id, count=3)

    broken = runner.run_episode(external_input=0.04)
    certificate = _certificate_of(storage, broken)

    assert certificate.continuity_score < 0.35, "el guardia de continuidad debe ver la ruptura"
    assert certificate.metadata["collapse_detected"] is True, (
        "el organismo tiene que poder detectar su propio colapso"
    )
    assert certificate.verdict == "rejected"
    assert certificate.promotion_candidate is False


def test_isolated_dip_is_not_a_collapse(tmp_path: Path):
    """Un bache AISLADO no es un colapso: el detector exige racha, no histeria.

    Complemento del test anterior: sin `streak`, cualquier episodio feo suelto tumbaría la
    certificación. El detector mide colapso SOSTENIDO.
    """
    storage = _storage(tmp_path)
    run_id = "life-collapse-dip"
    runner = _runner(storage, run_id)
    runner.run_episode(external_input=0.04)

    # Un solo certificado roto: hunde la continuidad del episodio siguiente, pero NO hay racha.
    _poison_continuity_history(storage, run_id=run_id, count=1)

    dip = runner.run_episode(external_input=0.04)
    certificate = _certificate_of(storage, dip)

    assert certificate.continuity_score < 0.35, "la continuidad cae..."
    assert certificate.metadata["collapse_detected"] is False, "...pero un bache aislado NO es colapso"
    assert certificate.verdict == "certified"


# ─────────────────────────────────────────────────────────────────────────────
# EFECTO LATERAL NO BUSCADO: darle ojos al colapso ESTRECHÓ EL REFUGIO.
# ─────────────────────────────────────────────────────────────────────────────


def _ioc_and_risk(*, continuity: float, collapse: bool) -> tuple[float, float]:
    """Reproduce la cadena real: IoCProxy.compute -> risk_score de certificate_builder.

    closure y traza CAÍDOS (el régimen degradado), incertidumbre en su default 0.2.
    """
    from runtime.certification.ioc_proxy import IoCProxy

    ioc = IoCProxy().compute(
        continuity_score=continuity,
        closure_passed=False,
        trace_integrity=False,
        collapse_detected=collapse,
        uncertainty=0.2,
    )
    # `certificate_builder.py:44-54`, misma fórmula.
    risk = max(0.0, min(1.0,
        0.55 * (1.0 - continuity)
        + 0.30 * (1.0 - ioc)
        + 0.10 * 1.0          # trace caída
        + 0.05 * 0.2
        + (0.08 if collapse else 0.0)
    ))
    return ioc, risk


def test_collapse_wiring_narrowed_the_refuge_band():
    """DEUDA CONOCIDA Y DELIBERADA: el refugio se estrechó donde MÁS se necesita.

    `collapse_detected` era constante False en el camino vivo. Al cablearlo (paso 4), se
    encendieron por PRIMERA VEZ dos penalizaciones **preexistentes** que ese flag ya
    alimentaba: `ioc_proxy.py` (-0.14 al IoC) y `certificate_builder.py` (+0.08 al riesgo).
    Y `risk_score < 0.50` es un eje del refugio (`contracts.py`, `is_restorable`).

    Consecuencia NO buscada: con closure y traza caídos, la continuidad mínima para
    conservar refugio se corrió de **0.75** (el umbral del propio eje) a **~0.855**. La
    banda [0.75, 0.855) PERDIÓ el refugio.

    Y ese es, textualmente, el régimen que `contracts.py` describe como el habitual en vida
    real ("las certificaciones suelen quedar rejected por closure/trace") — el mismo que
    dejó a aeon-01 atascado en cuarentena.

    Este test NO bendice el cambio: lo hace VISIBLE. Si el humano decide que un organismo
    con closure y traza caídos NO debe refugiarse en ese estado, esto es correcto y el test
    lo documenta. Si decide lo contrario (que perder el refugio ahí es peor que refugiarse
    en un estado degradado), hay que compensar la penalización — y este test se cae, que es
    justo lo que debe pasar.
    """
    # Continuidad 0.80: DENTRO de la banda perdida.
    ioc_antes, risk_antes = _ioc_and_risk(continuity=0.80, collapse=False)
    ioc_ahora, risk_ahora = _ioc_and_risk(continuity=0.80, collapse=True)

    # Antes de cablear el colapso: había refugio.
    assert round(ioc_antes, 4) == 0.348
    assert round(risk_antes, 4) == 0.4156
    assert risk_antes < 0.50  # eje del refugio: PASA

    # Después de cablearlo: el mismo organismo pierde el refugio.
    assert round(ioc_ahora, 4) == 0.208
    assert round(risk_ahora, 4) == 0.5376
    assert risk_ahora >= 0.50  # eje del refugio: FALLA

    # El punto de equilibrio se corrió: con continuidad alta el refugio sobrevive.
    _, risk_sano = _ioc_and_risk(continuity=0.98, collapse=True)
    assert risk_sano < 0.50  # por eso la corrida viva da 12/12 healthy y no se ve el problema
