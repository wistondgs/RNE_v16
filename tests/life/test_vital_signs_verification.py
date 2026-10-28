"""B73 — vitales ausentes NO son vitales sanas (compuerta de refugio E5).

El agujero: `VitalSignsSnapshot.from_dict()` rellenaba con salud PERFECTA los cinco ejes
que `is_restorable` exige (viability_margin=1.0, continuity_score=1.0, risk_score=0.0,
memory_purity=1.0, reversible=True). Consecuencia: `from_dict({})` — payload VACÍO —
pasaba los cinco ejes y se declaraba refugio válido. Y el consumidor está vivo:
`persistence.py:38` deserializa así al restaurar, y `checkpoints.py:91,105` escribe
`"healthy": vital_signs.is_restorable`, el criterio con el que el kernel elige a qué
checkpoint refugiarse (camino E5).

El criterio: esto es una COMPUERTA, no un detector. La acción peligrosa es ACEPTAR basura
⇒ dato ausente ⇒ NO restaurable. Pero la ausencia se representa COMO AUSENCIA (eje NO
VERIFICADO, nombrable), no como "el organismo agoniza" — esa sería la mentira simétrica.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.life import (
    CheckpointManager,
    LIFE_CHECKPOINT_KIND,
    LifeKernel,
    LifeKernelConfig,
    OrganismPersistence,
    VitalSignsSnapshot,
)
from runtime.life.contracts import (
    RESTORE_REQUIRED_AXES,
    STABILITY_REQUIRED_AXES,
    VITALS_BELOW_THRESHOLD,
    VITALS_OK,
    VITALS_UNVERIFIED,
)
from runtime.storage import StorageConfig, StorageFactory


HEALTHY_PAYLOAD = {
    "run_id": "life-b73",
    "episode_count": 7,
    "mode": "normal",
    "viability_margin": 0.80,
    "continuity_score": 0.90,
    "ioc_proxy": 0.80,
    "risk_score": 0.20,
    "memory_purity": 0.95,
    "cognitive_quality": 0.78,
    "resource_pressure": 0.10,
    "recovery_debt": 0.0,
    "accumulated_drift": 0.0,
    "reversible": True,
    "identity_continuity": 0.90,
    "certified": True,
}

# Los 18 campos que `to_dict()` (== asdict) escribía ANTES de B73. Un checkpoint sano debe
# seguir escribiendo exactamente estos, ni uno más: cero migración, cero cambio de bytes.
PRE_B73_KEYS = frozenset(HEALTHY_PAYLOAD) | {"snapshot_id", "created_at", "metadata"}


def _healthy(**overrides) -> VitalSignsSnapshot:
    payload = dict(HEALTHY_PAYLOAD)
    payload.update(overrides)
    return VitalSignsSnapshot(**payload)


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


# ---------------------------------------------------------------- el bug, desnudo

def test_empty_payload_is_not_a_refuge():
    """EL BUG: `from_dict({})` se declaraba refugio válido. Payload vacío, salud perfecta."""
    snapshot = VitalSignsSnapshot.from_dict({})

    assert snapshot.is_restorable is False
    # ...y no es un False mudo: los cinco ejes se nombran como NO VERIFICADOS.
    assert set(snapshot.unverified_restore_axes) == set(RESTORE_REQUIRED_AXES)

    report = snapshot.restorability_report()
    assert report["restorable"] is False
    assert report["reason"] == VITALS_UNVERIFIED
    assert report["checks_applied"] == []  # ningún chequeo llegó a correr
    assert set(report["unverified_axes"]) == set(RESTORE_REQUIRED_AXES)


def test_empty_payload_is_not_stable_either():
    """`is_stable` tenía el MISMO agujero, tapado por casualidad (certified default False)."""
    assert VitalSignsSnapshot.from_dict({}).is_stable is False


def test_certified_alone_does_not_buy_stability():
    """El agujero de `is_stable`, destapado: `certified: true` + CUATRO ejes fabricados.

    Antes de B73 esto devolvía True — estabilidad declarada sobre viabilidad, continuidad,
    riesgo y pureza que nadie midió.
    """
    snapshot = VitalSignsSnapshot.from_dict({"certified": True})

    assert snapshot.is_stable is False
    assert set(snapshot.unverified_stability_axes) == set(STABILITY_REQUIRED_AXES) - {
        "certified"
    }


@pytest.mark.parametrize("axis", RESTORE_REQUIRED_AXES)
def test_each_missing_restore_axis_closes_the_gate(axis: str):
    """Falta UN eje (de a uno) ⇒ no restaurable, y el eje faltante es IDENTIFICABLE."""
    payload = dict(HEALTHY_PAYLOAD)
    payload.pop(axis)

    snapshot = VitalSignsSnapshot.from_dict(payload)

    assert snapshot.is_restorable is False
    assert snapshot.unverified_restore_axes == (axis,)
    report = snapshot.restorability_report()
    assert report["reason"] == VITALS_UNVERIFIED
    assert report["unverified_axes"] == [axis]
    # Los otros cuatro SÍ se pudieron verificar: la abstención es quirúrgica, no total.
    assert set(report["checks_applied"]) == set(RESTORE_REQUIRED_AXES) - {axis}


@pytest.mark.parametrize("axis", RESTORE_REQUIRED_AXES)
def test_explicit_null_is_absence_not_measurement(axis: str):
    """`null` en JSON tampoco es una medición: se trata como ausencia."""
    payload = dict(HEALTHY_PAYLOAD)
    payload[axis] = None

    snapshot = VitalSignsSnapshot.from_dict(payload)

    assert snapshot.is_restorable is False
    assert snapshot.unverified_restore_axes == (axis,)


def test_absence_is_not_agony():
    """La ausencia se representa como AUSENCIA, no como salud pésima (la mentira simétrica).

    Un payload incompleto NO debe convertir al organismo en un moribundo: los rellenos
    siguen ahí, intactos; lo que cambia es que la compuerta ya no se apoya en ellos.
    """
    snapshot = VitalSignsSnapshot.from_dict({})

    assert snapshot.viability_margin == 1.0
    assert snapshot.continuity_score == 1.0
    assert snapshot.memory_purity == 1.0
    assert snapshot.risk_score == 0.0
    assert snapshot.reversible is True
    # ...pero ninguno de esos números cuenta como evidencia.
    assert snapshot.is_restorable is False


def test_unhealthy_but_complete_is_a_different_no():
    """Distinguir las dos negativas: 'medido y malo' ≠ 'no medido'."""
    snapshot = VitalSignsSnapshot.from_dict({**HEALTHY_PAYLOAD, "memory_purity": 0.10})

    report = snapshot.restorability_report()
    assert snapshot.is_restorable is False
    assert report["reason"] == VITALS_BELOW_THRESHOLD  # no `vitals_unverified`
    assert report["failed_axes"] == ["memory_purity"]
    assert report["unverified_axes"] == []


def test_missing_non_gated_field_does_not_close_the_gate():
    """No expandimos la paranoia: un campo que no gobierna ninguna compuerta no la cierra."""
    payload = dict(HEALTHY_PAYLOAD)
    payload.pop("ioc_proxy")
    payload.pop("cognitive_quality")

    snapshot = VitalSignsSnapshot.from_dict(payload)

    assert snapshot.is_restorable is True
    assert snapshot.unverified_fields == frozenset()


# ------------------------------------------------- el camino sano: CERO regresión

def test_round_trip_of_a_healthy_snapshot_is_identical():
    """CERO cambio de comportamiento para checkpoints sanos: to_dict → from_dict."""
    original = _healthy()

    restored = VitalSignsSnapshot.from_dict(original.to_dict())

    assert restored == original  # todos los campos, uno por uno (dataclass eq)
    assert restored.is_restorable is True
    assert restored.is_stable is True
    assert restored.unverified_fields == frozenset()
    assert restored.restorability_report()["reason"] == VITALS_OK


def test_healthy_payload_keeps_the_pre_b73_shape():
    """El payload de un snapshot sano no gana ni pierde claves: byte por byte, el de antes.

    `unverified_fields` se OMITE cuando está vacío ⇒ ningún checkpoint sano cambia de forma
    (y no se cuela un frozenset no-serializable en la ruta JSON).
    """
    payload = _healthy().to_dict()

    assert set(payload) == PRE_B73_KEYS
    assert "unverified_fields" not in payload
    json.dumps(payload)  # sigue siendo JSON puro


def test_unverified_marker_survives_serialization():
    """Anti-lavado: un snapshot NO VERIFICADO no se blanquea al re-serializarse.

    Sin esto, `to_dict()` volvería a escribir los 18 campos (con sus rellenos) y el
    siguiente `from_dict()` lo vería completo y sano: la mentira se lavaría sola.
    """
    dirty = VitalSignsSnapshot.from_dict({})
    payload = dirty.to_dict()

    assert payload["unverified_fields"] == sorted(dirty.unverified_fields)
    json.dumps(payload)  # el marcador viaja como lista, no como frozenset

    relaundered = VitalSignsSnapshot.from_dict(payload)
    assert relaundered.is_restorable is False
    assert set(relaundered.unverified_restore_axes) == set(RESTORE_REQUIRED_AXES)


# ------------------------------------------------------- el camino real (E5 / storage)

def _seed_checkpoint(storage, vitals: VitalSignsSnapshot, run_id: str) -> str:
    """Escribe un checkpoint real (mismo camino que el kernel) con los vitales dados."""
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    manager = CheckpointManager(storage=storage)
    manager.save_checkpoint(
        run_id=run_id,
        organism_id=kernel.organism_id,
        lineage_id=kernel.lineage_id,
        organism_state=kernel.organism_state,
        lineage=kernel.lineage,
        goals=[],
        vital_signs=vitals,
        total_steps=3,
        scenario_index=0,
        scenario_episode_index=0,
        memory_filter_mode="strict",
        closure_profile="default",
    )
    return kernel.organism_id


def _truncate_vitals_on_disk(storage, run_id: str, axis: str) -> None:
    """Simula el checkpoint truncado/corrupto: le arranca un eje a los vitales YA escritos.

    La metadata del artifact (incluido `healthy: True`) queda intacta — que es exactamente
    el escenario peligroso: el índice dice 'sano', el archivo ya no lo demuestra.
    """
    artifact = storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND)[0]
    path = Path(artifact.abs_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["vital_signs"].pop(axis)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_healthy_checkpoint_is_still_an_eligible_refuge(tmp_path: Path):
    """El camino sano sigue funcionando: un checkpoint sano SIGUE siendo refugio elegible."""
    storage = _storage(tmp_path)
    organism_id = _seed_checkpoint(storage, _healthy(), run_id="life-b73-ok")

    manager = CheckpointManager(storage=storage)
    loaded = manager.load_latest_payload(organism_id=organism_id, healthy_only=True)

    assert loaded is not None
    payload, artifact = loaded
    assert artifact.metadata["healthy"] is True
    assert VitalSignsSnapshot.from_dict(payload["vital_signs"]).is_restorable is True


def test_truncated_checkpoint_is_not_an_eligible_refuge(tmp_path: Path):
    """EL CAMINO REAL DEL BUG: vitales truncadas ⇒ no puede pasar por refugio.

    Antes: el archivo truncado se deserializaba como salud perfecta y el kernel se refugiaba
    en él (`_restore_latest_healthy_checkpoint`), que además confiaba a ciegas en el flag
    `healthy` escrito al GUARDAR — un índice, no una prueba del contenido actual.
    """
    storage = _storage(tmp_path)
    organism_id = _seed_checkpoint(storage, _healthy(), run_id="life-b73-trunc")
    _truncate_vitals_on_disk(storage, "life-b73-trunc", axis="memory_purity")

    # El flag guardado SIGUE diciendo "sano": por eso el archivo debe re-verificarse.
    artifact = storage.list_artifacts(run_id="life-b73-trunc", kind=LIFE_CHECKPOINT_KIND)[0]
    assert artifact.metadata["healthy"] is True

    manager = CheckpointManager(storage=storage)
    assert manager.load_latest_payload(organism_id=organism_id, healthy_only=True) is None


def test_a_mistyped_candidate_is_skipped_not_fatal(tmp_path: Path):
    """ROBUSTEZ: un candidato ilegible se SALTEA; jamás aborta la búsqueda de refugio.

    `from_dict` no es total: un bloque `vital_signs` JSON-válido pero **mal tipado**
    (`"risk_score": "high"`) revienta en `float(...)`. Si esa excepción escapara de
    `load_latest_payload`, mataría `_restore_latest_healthy_checkpoint` y con él el lazo
    vital — y, peor todavía, un checkpoint **sano** que estuviera detrás del corrupto
    **nunca se alcanzaría**.

    Endurecer la compuerta del refugio no puede volverla frágil: el organismo tiene que
    poder saltear la basura y seguir buscando dónde refugiarse.
    """
    storage = _storage(tmp_path)
    run_id = "life-b73-mistyped"
    organism_id = _seed_checkpoint(storage, _healthy(), run_id=run_id)
    _seed_checkpoint(storage, _healthy(), run_id=run_id)

    artifacts = storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND)
    assert len(artifacts) == 2
    # Corrompemos el PRIMERO que verá el loop, sea cual sea el orden: así garantizamos que
    # el candidato malo se examina ANTES que el sano (si no, el test no probaría nada).
    doomed = artifacts[0]
    path = Path(doomed.abs_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["vital_signs"]["risk_score"] = "high"    # float("high") -> ValueError
    payload["vital_signs"]["viability_margin"] = {}  # float({})     -> TypeError
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # El flag guardado sigue mintiendo: dice "sano".
    assert doomed.metadata["healthy"] is True

    manager = CheckpointManager(storage=storage)
    loaded = manager.load_latest_payload(organism_id=organism_id, healthy_only=True)

    # (1) No explota. (2) Encuentra el checkpoint SANO que estaba detrás del corrupto.
    assert loaded is not None
    payload_ok, artifact_ok = loaded
    assert artifact_ok.artifact_id != doomed.artifact_id
    assert VitalSignsSnapshot.from_dict(payload_ok["vital_signs"]).is_restorable is True


def test_checkpoint_without_vitals_is_not_an_eligible_refuge(tmp_path: Path):
    """Vitales enteramente ausentes del payload: tampoco hay refugio."""
    storage = _storage(tmp_path)
    organism_id = _seed_checkpoint(storage, _healthy(), run_id="life-b73-novitals")
    artifact = storage.list_artifacts(run_id="life-b73-novitals", kind=LIFE_CHECKPOINT_KIND)[0]
    path = Path(artifact.abs_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("vital_signs")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manager = CheckpointManager(storage=storage)
    assert manager.load_latest_payload(organism_id=organism_id, healthy_only=True) is None


def test_restore_still_recovers_identity_but_not_fake_health(tmp_path: Path):
    """Restaurar ≠ refugiarse: la identidad se recupera igual, la SALUD no se inventa.

    La compuerta que se cierra es la del refugio. El restore ordinario (arranque) sigue
    devolviendo la identidad — cerrarlo también dejaría al organismo sin poder volver a
    existir —, pero los vitales restaurados dicen la verdad: no se pudieron verificar.
    """
    storage = _storage(tmp_path)
    _seed_checkpoint(storage, _healthy(), run_id="life-b73-restore")
    _truncate_vitals_on_disk(storage, "life-b73-restore", axis="continuity_score")

    restored = OrganismPersistence(storage=storage).load_latest_identity(
        run_id="life-b73-restore"
    )

    assert restored is not None
    assert restored.organism_state is not None  # la identidad sigue viva
    assert restored.vital_signs is not None
    assert restored.vital_signs.is_restorable is False
    assert restored.vital_signs.unverified_restore_axes == ("continuity_score",)
