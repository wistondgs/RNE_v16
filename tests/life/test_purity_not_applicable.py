"""B85 — la compuerta del refugio deja de contar un eje NO APLICABLE como VERIFICADO.

`memory_purity >= 0.85` existe para impedir que el organismo se refugie en un estado con
memoria CONTAMINADA. Sin hits de retrieval no hay memoria que pueda estar contaminada: el eje
no aplica. Pasar la compuerta es CORRECTO — lo que estaba mal era cómo se decía.

El hallazgo del auditor: `memory_purity_basis` VIAJABA (transfer_assessment → certificado →
vitals → snapshot) y **ninguna compuerta lo leía** (cero consumidores de producción). La
etiqueta existía, y la compuerta seguía consumiendo el 1.0 vacuo como si fuera evidencia
ganada. Estos tests fijan que ahora SÍ se lee, y que se lee sin matar el refugio.

LA RESTRICCIÓN DURA: el refugio NO puede morir. Un episodio sin memoria debe seguir
produciendo checkpoints `healthy` — por NO APLICABILIDAD, no por un 1.0 fingido.
"""

from __future__ import annotations

from pathlib import Path

from runtime.life import LIFE_CHECKPOINT_KIND, LifeKernel, LifeKernelConfig, VitalSignsSnapshot
from runtime.life.contracts import VITALS_BELOW_THRESHOLD, VITALS_OK, VITALS_UNVERIFIED
from runtime.storage import StorageConfig, StorageFactory


BASE = {
    "run_id": "life-b85",
    "episode_count": 3,
    "mode": "normal",
    "viability_margin": 0.80,
    "continuity_score": 0.90,
    "ioc_proxy": 0.80,
    "risk_score": 0.20,
    "memory_purity": 1.0,
    "cognitive_quality": 0.78,
    "resource_pressure": 0.10,
    "recovery_debt": 0.0,
    "accumulated_drift": 0.0,
    "reversible": True,
    "identity_continuity": 0.90,
    "certified": True,
}


def _snapshot(**overrides) -> VitalSignsSnapshot:
    payload = dict(BASE)
    payload.update(overrides)
    return VitalSignsSnapshot(**payload)


def _vacuous() -> VitalSignsSnapshot:
    """El estado del episodio sin memoria: pureza 1.0 VACUA, declarada no aplicable."""
    return _snapshot(
        not_applicable_axes=frozenset({"memory_purity"}),
        metadata={
            "memory_purity_basis": {
                "source": "no_memory_retrieved",
                "status": "not_applicable",
                "hits": 0,
                "contamination_opportunity": False,
            }
        },
    )


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "life.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


# ── LA COMPUERTA PASA, PERO YA NO MIENTE SOBRE POR QUÉ ───────────────────────────

def test_not_applicable_purity_still_opens_the_refuge():
    """CERO CAMBIO DE COMPORTAMIENTO: sin memoria que contaminar, el refugio sigue abierto.

    Si esto se pusiera en False, el organismo perdería el refugio en todo episodio sin
    retrieval — cambiar "acepta basura" por "no acepta nada" es PEOR.
    """
    assert _vacuous().is_restorable is True
    assert _vacuous().is_stable is True


def test_the_gate_no_longer_calls_a_non_applicable_axis_verified():
    """CAMBIO DE SEMÁNTICA: el eje pasa a `not_applicable_axes`, NO a `checks_applied`.

    Antes el informe decía «memory_purity: 1.0 ✓» — una verificación que nunca ocurrió.
    """
    report = _vacuous().restorability_report()

    assert report["restorable"] is True
    assert report["reason"] == VITALS_OK
    assert "memory_purity" not in report["checks_applied"], (
        "un eje SIN SUJETO no puede contarse como eje verificado"
    )
    assert report["not_applicable_axes"] == ["memory_purity"]
    assert "memory_purity" not in report["unverified_axes"]
    # Los otros cuatro ejes SÍ se chequearon: el refugio no se vació.
    assert set(report["checks_applied"]) == {
        "reversible",
        "viability_margin",
        "continuity_score",
        "risk_score",
    }


def test_the_report_says_why_the_axis_does_not_apply():
    """«memory_purity: no aplica (no había memoria que contaminar)», no «1.0 ✓»."""
    reasons = _vacuous().restorability_report()["not_applicable_reasons"]

    assert "no había memoria que contaminar" in reasons["memory_purity"]
    assert "hits=0" in reasons["memory_purity"]


def test_measured_purity_is_still_a_check_that_was_applied():
    """Cuando el eje APLICA (hubo hits), sigue siendo un chequeo hecho y contado."""
    measured = _snapshot(
        memory_purity=0.95,
        metadata={
            "memory_purity_basis": {"status": "measured", "hits": 12,
                                    "contamination_opportunity": True}
        },
    )
    report = measured.restorability_report()

    assert "memory_purity" in report["checks_applied"]
    assert report["not_applicable_axes"] == []


def test_a_contaminated_purity_still_slams_the_gate():
    """LA COMPUERTA SIGUE SIENDO UNA COMPUERTA: si el eje aplica y falla, cierra."""
    dirty = _snapshot(memory_purity=0.33)

    assert dirty.is_restorable is False
    report = dirty.restorability_report()
    assert report["reason"] == VITALS_BELOW_THRESHOLD
    assert "memory_purity" in report["failed_axes"]


# ── LOS CERROJOS: no aplicable NO es una llave maestra ───────────────────────────

def test_not_applicable_cannot_be_claimed_for_an_axis_that_always_has_a_subject():
    """LISTA BLANCA: nadie vacía la compuerta declarando `reversible` "no aplicable".

    La viabilidad, el riesgo, la continuidad y la reversibilidad SIEMPRE tienen sujeto: el
    organismo mismo. Solo `memory_purity` puede quedarse sin sujeto. Sin este cerrojo, un
    payload corrupto (o adversario) podría pasar el refugio por no tener nada que chequear.
    """
    fake = _snapshot(
        reversible=False,
        risk_score=0.99,
        viability_margin=0.0,
        not_applicable_axes=frozenset({"reversible", "risk_score", "viability_margin"}),
    )

    assert fake.is_restorable is False, "la lista blanca no deja vaciar la compuerta"
    report = fake.restorability_report()
    assert report["not_applicable_axes"] == []
    assert set(report["failed_axes"]) >= {"reversible", "risk_score", "viability_margin"}


def test_absence_beats_non_applicability():
    """Un eje AUSENTE del payload no puede reciclarse como "no aplicable".

    Ausencia de dato ⇒ NO VERIFICADO ⇒ la compuerta se cierra (B73). Que el payload declare
    "no aplica" no resucita un dato que no está.
    """
    payload = {k: v for k, v in BASE.items() if k != "memory_purity"}
    payload["not_applicable_axes"] = ["memory_purity"]
    snapshot = VitalSignsSnapshot.from_dict(payload)

    assert "memory_purity" in snapshot.unverified_fields
    assert snapshot.is_restorable is False
    assert snapshot.restorability_report()["reason"] == VITALS_UNVERIFIED
    assert snapshot.restorability_report()["not_applicable_axes"] == []


# ── LA NO APLICABILIDAD VIAJA (y no se lava al re-serializar) ────────────────────

def test_non_applicability_survives_the_round_trip():
    """Si no viajara, el checkpoint se releería como una pureza VERIFICADA de 1.0."""
    payload = _vacuous().to_dict()
    assert payload["not_applicable_axes"] == ["memory_purity"]

    revived = VitalSignsSnapshot.from_dict(payload)
    assert revived.not_applicable_axes == frozenset({"memory_purity"})
    assert revived.is_restorable is True
    assert "memory_purity" not in revived.restorability_report()["checks_applied"]


def test_a_snapshot_with_measured_purity_keeps_the_pre_b85_payload_shape():
    """Cero migración: sin ejes no aplicables, el payload no gana ni una clave."""
    assert "not_applicable_axes" not in _snapshot(memory_purity=0.95).to_dict()


# ── LA PREGUNTA QUE PUEDE MATAR AL ORGANISMO ────────────────────────────────────

def test_the_refuge_survives_the_semantic_change(tmp_path: Path):
    """RESTRICCIÓN DURA: corrida viva ⇒ SIGUE habiendo checkpoints `healthy`.

    El fix es de semántica, no de comportamiento. Si al distinguir "no aplicable" de
    "verificado" el organismo se quedara sin ningún checkpoint sano, habríamos matado el
    refugio — el callejón sin salida (cuarentena muda, sin a dónde volver) que el camino E5
    existe para romper.
    """
    storage = _storage(tmp_path)
    run_id = "life-b85-refuge"
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )

    kernel.run_until_stopped(max_steps=4)

    checkpoints = storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND, limit=50)
    healthy = [c for c in checkpoints if (c.metadata or {}).get("healthy")]

    assert checkpoints, "el organismo tiene que estar guardando checkpoints"
    assert healthy, (
        "REFUGIO MUERTO: ningún checkpoint quedó `healthy` ⇒ el organismo no puede volver "
        "atrás nunca más. El cambio de semántica no puede costarle el refugio."
    )

    vitals = kernel.last_vitals
    assert vitals is not None
    assert vitals.is_restorable is True
    # Y el refugio se sostiene sobre ejes REALES: ni un eje del refugio quedó no verificado.
    assert vitals.unverified_restore_axes == ()


def test_a_live_snapshot_never_claims_more_than_it_checked(tmp_path: Path):
    """El informe del estado vivo es honesto en los dos sentidos, sea cual sea la rama.

    Con memoria ⇒ la pureza está MEDIDA y cuenta como chequeo. Sin memoria ⇒ NO APLICA y no
    cuenta. Lo que NUNCA puede pasar es que un eje esté en `checks_applied` y a la vez
    declarado sin sujeto: eso es el certificado autocontradiciéndose.
    """
    storage = _storage(tmp_path)
    run_id = "life-b85-honest"
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    kernel.run_until_stopped(max_steps=3)

    vitals = kernel.last_vitals
    assert vitals is not None
    report = vitals.restorability_report()

    overlap = set(report["checks_applied"]) & set(report["not_applicable_axes"])
    assert not overlap, f"el informe se autocontradice en {overlap}"

    basis = (vitals.metadata or {}).get("memory_purity_basis") or {}
    if basis.get("contamination_opportunity") is False:
        assert "memory_purity" in report["not_applicable_axes"]
        assert "memory_purity" not in report["checks_applied"]
    else:
        assert "memory_purity" in report["checks_applied"]
        assert "memory_purity" not in report["not_applicable_axes"]


# ─────────────────────────────────────────────────────────────────────────────
# ENDURECIMIENTO: la etiqueta no puede valer más que la evidencia que la acompaña.
# ─────────────────────────────────────────────────────────────────────────────


def test_self_declared_not_applicable_is_discarded_when_the_evidence_contradicts_it():
    """EL ARCHIVO NO SE CONFÍA: no se puede comprar la compuerta declarándose exento.

    Mismo modelo de amenaza que la compuerta de refugio (P9.5: `metadata["healthy"]` es un
    índice, no una prueba). Un payload que declara `memory_purity: no aplica` mientras su
    PROPIO basis confiesa que SÍ hubo memoria que pudiera contaminarse (`hits > 0`) está
    mintiendo: el eje aplica, y la pureza (baja) debe cerrar la compuerta.

    Sin este chequeo, la no-aplicabilidad seria una PUERTA TRASERA: una etiqueta que exime
    de la verificación sin que nadie contraste la etiqueta contra la evidencia.
    """
    payload = {
        **BASE,
        "memory_purity": 0.33,  # pureza REAL y BAJA: la compuerta debe cerrarse
        "not_applicable_axes": ["memory_purity"],  # ...pero el payload se declara exento
        "metadata": {
            # Su propia evidencia lo desmiente: hubo 5 hits, o sea SÍ había qué contaminar.
            "memory_purity_basis": {"hits": 5, "contamination_opportunity": True}
        },
    }

    snapshot = VitalSignsSnapshot.from_dict(payload)

    # La etiqueta se DESCARTA: el eje vuelve a aplicar...
    assert "memory_purity" not in snapshot.not_applicable_axes
    # ...y la pureza baja cierra la compuerta, como debe.
    assert snapshot.is_restorable is False
    report = snapshot.restorability_report()
    assert "memory_purity" in report["failed_axes"]


def test_honest_not_applicable_still_passes():
    """El caso legítimo NO se rompe: sin hits, la NA se acepta y el refugio sobrevive."""
    payload = {
        **BASE,
        "not_applicable_axes": ["memory_purity"],
        "metadata": {
            "memory_purity_basis": {"hits": 0, "contamination_opportunity": False}
        },
    }

    snapshot = VitalSignsSnapshot.from_dict(payload)

    assert "memory_purity" in snapshot.not_applicable_axes
    assert snapshot.is_restorable is True  # el refugio VIVE
    report = snapshot.restorability_report()
    # No aplicable NO cuenta como verificado.
    assert "memory_purity" not in report["checks_applied"]
