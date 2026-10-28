"""B83 — el organismo no puede quedarse sin refugio EN SILENCIO.

El humano decidió MANTENER el refugio estrechado: un estado con closure/traza rotos y
continuidad mediocre NO es refugio. Esa decisión exige esta red de seguridad.

Hasta ahora, si TODOS los candidatos se rechazaban, `_restore_latest_healthy_checkpoint()`
devolvía `False` y el organismo se quedaba atascado en cuarentena SIN DEJAR RASTRO de por
qué — que es, literalmente, el callejón sin salida (el de aeon-01) que el camino de refugio
E5 existe para romper. `life.refuge` se emitía SOLO en el ÉXITO. Y `restorability_report()`
—el informe honesto de POR QUÉ se rechaza un refugio— no tenía NINGÚN llamador en runtime:
capacidad sin emisión.

Dos eventos nuevos, emitidos desde el KERNEL (nunca desde `checkpoints.py`, que es el camino
de lectura y P9.5 lo dejó sin escrituras a propósito):
  - `life.refuge.rejected`  (por candidato) — este checkpoint no sirve, y acá está el porqué.
  - `life.refuge.exhausted` (búsqueda agotada) — "me quedé sin a dónde volver".
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.life import (
    CheckpointManager,
    LIFE_CHECKPOINT_KIND,
    LifeKernel,
    LifeKernelConfig,
    VitalSignsSnapshot,
)
from runtime.storage import StorageConfig, StorageFactory
from runtime.storage.contract_validation import EVENT_CONTRACTS


HEALTHY_PAYLOAD = {
    "run_id": "life-b83",
    "episode_count": 5,
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


def _kernel(storage, run_id: str) -> LifeKernel:
    return LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )


def _seed(kernel, storage, vitals: VitalSignsSnapshot) -> None:
    """Escribe un checkpoint real por el mismo camino que el kernel (metadata `healthy`)."""
    CheckpointManager(storage=storage).save_checkpoint(
        run_id=kernel.run_id,
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


def _artifacts(storage, run_id: str):
    return storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND, limit=50)


def _degrade_on_disk(artifact, **vital_overrides) -> None:
    """Degrada el ARCHIVO dejando intacta la metadata (que sigue diciendo `healthy: True`).

    Es el escenario peligroso y el único que produce un CANDIDATO rechazable: un checkpoint
    guardado como no-sano nunca entra al índice del refugio.
    """
    path = Path(artifact.abs_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["vital_signs"].update(vital_overrides)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _events(storage, run_id: str, event_type: str):
    return storage.list_events(run_id=run_id, event_types=[event_type], limit=50)


# ── LA SEÑAL QUE FALTABA ────────────────────────────────────────────────────────

def test_exhausted_search_is_announced_not_swallowed(tmp_path: Path):
    """TEST OBLIGATORIO: con TODOS los candidatos degradados, el organismo lo DICE.

    Antes: `return False` y silencio. El organismo se quedaba en cuarentena sin a dónde
    volver y sin decir por qué.
    """
    storage = _storage(tmp_path)
    run_id = "life-b83-exhausted"
    kernel = _kernel(storage, run_id)
    _seed(kernel, storage, _healthy())
    _seed(kernel, storage, _healthy())

    artifacts = _artifacts(storage, run_id)
    assert len(artifacts) == 2
    # Los dos siguen diciendo "sano" en el índice; los dos archivos ya no lo demuestran.
    _degrade_on_disk(artifacts[0], continuity_score=0.10)   # bajo umbral (0.75)
    _degrade_on_disk(artifacts[1], risk_score="high")       # ilegible: float("high") revienta
    assert all(a.metadata["healthy"] is True for a in artifacts)

    assert kernel._restore_latest_healthy_checkpoint() is False

    exhausted = _events(storage, run_id, "life.refuge.exhausted")
    assert len(exhausted) == 1, "quedarse sin refugio no puede ser mudo"
    payload = exhausted[0].payload
    assert payload["reason"] == "no_restorable_checkpoint"
    assert payload["candidates_examined"] == 2, "cuántos examinó"
    assert payload["organism_id"] == kernel.organism_id
    reasons = {r["reason"] for r in payload["rejections"]}
    assert reasons == {"vitals_below_threshold", "vitals_unreadable"}, "por qué cayó cada uno"


def test_every_rejected_candidate_leaves_its_report_in_the_ledger(tmp_path: Path):
    """`life.refuge.rejected` por candidato, con el `restorability_report()` de P9.5.

    El informe existía y se logueaba con `logger.warning`. Un log no sobrevive a la corrida;
    un evento sí. Capacidad sin emisión es la patología que el propio backlog condena (B78).
    """
    storage = _storage(tmp_path)
    run_id = "life-b83-rejected"
    kernel = _kernel(storage, run_id)
    _seed(kernel, storage, _healthy())

    artifact = _artifacts(storage, run_id)[0]
    _degrade_on_disk(artifact, continuity_score=0.10, viability_margin=0.20)

    assert kernel._restore_latest_healthy_checkpoint() is False

    rejected = _events(storage, run_id, "life.refuge.rejected")
    assert len(rejected) == 1
    payload = rejected[0].payload
    assert payload["artifact_id"] == artifact.artifact_id
    assert payload["reason"] == "vitals_below_threshold"

    report = payload["restorability_report"]
    assert report["restorable"] is False
    assert set(report["failed_axes"]) == {"continuity_score", "viability_margin"}
    # Y el informe sigue diciendo qué SÍ se chequeó (no es un "no" mudo).
    assert "risk_score" in report["checks_applied"]


def test_an_organism_with_no_candidates_at_all_says_so(tmp_path: Path):
    """Sin ningún checkpoint sano en el índice: examinó 0, y lo dice igual."""
    storage = _storage(tmp_path)
    run_id = "life-b83-nada"
    kernel = _kernel(storage, run_id)

    assert kernel._restore_latest_healthy_checkpoint() is False

    exhausted = _events(storage, run_id, "life.refuge.exhausted")
    assert len(exhausted) == 1
    assert exhausted[0].payload["candidates_examined"] == 0
    assert exhausted[0].payload["rejections"] == []


# ── LO QUE NO SE PUEDE ROMPER ───────────────────────────────────────────────────

def test_a_found_refuge_emits_no_exhausted_and_still_skips_the_garbage(tmp_path: Path):
    """ROBUSTEZ P9.5 INTACTA: el candidato corrupto se saltea, el sano de atrás se encuentra.

    Y como HAY refugio, no se emite `exhausted`: la señal de agotamiento no puede convertirse
    en ruido de cada búsqueda.
    """
    storage = _storage(tmp_path)
    run_id = "life-b83-skip"
    kernel = _kernel(storage, run_id)
    _seed(kernel, storage, _healthy())
    _seed(kernel, storage, _healthy())

    artifacts = _artifacts(storage, run_id)
    doomed = artifacts[0]  # el PRIMERO que verá el loop
    _degrade_on_disk(doomed, risk_score="high")

    assert kernel._restore_latest_healthy_checkpoint() is True, (
        "el corrupto se saltea; el sano de atrás sigue siendo alcanzable"
    )
    assert _events(storage, run_id, "life.refuge.exhausted") == []

    rejected = _events(storage, run_id, "life.refuge.rejected")
    assert len(rejected) == 1
    assert rejected[0].payload["artifact_id"] == doomed.artifact_id


def test_a_failing_emitter_never_costs_the_refuge(tmp_path: Path):
    """La telemetría del refugio JAMÁS puede matar la búsqueda ni el lazo vital.

    Estos eventos se emiten en el momento más frágil de la vida del organismo — cuando se
    está quedando sin refugio. Si el ledger explota ahí, el organismo NO puede morir por
    haber intentado decir que no tiene a dónde volver.
    """
    storage = _storage(tmp_path)
    run_id = "life-b83-emisor-roto"
    kernel = _kernel(storage, run_id)
    _seed(kernel, storage, _healthy())
    _seed(kernel, storage, _healthy())

    artifacts = _artifacts(storage, run_id)
    _degrade_on_disk(artifacts[0], risk_score="high")

    real_append = storage.append_event

    def _explode(*, event_type: str, **kwargs):
        if event_type.startswith("life.refuge"):
            raise RuntimeError("ledger caído justo cuando el organismo iba a hablar")
        return real_append(event_type=event_type, **kwargs)

    storage.append_event = _explode  # type: ignore[method-assign]
    try:
        # (1) No explota. (2) Sigue encontrando el refugio sano detrás del corrupto.
        assert kernel._restore_latest_healthy_checkpoint() is True
    finally:
        storage.append_event = real_append  # type: ignore[method-assign]


# ── P7 / CANON §13: emitir estos eventos no puede violar un contrato activo ──────

def test_refuge_events_are_not_active_contracts():
    """TRIPWIRE: `life.refuge.*` NO se agrega a `EVENT_CONTRACTS`.

    No están entre los 5 contratos activos de CANON §13, así que `contract_validation` no
    los valida. Mapearlos sin conformar su payload los haría levantar
    `ContractViolationError` bajo `strict` (el default) — y matarían al organismo justo en
    la decisión de refugio, que es el camino que más se necesita.
    """
    assert "life.refuge.rejected" not in EVENT_CONTRACTS
    assert "life.refuge.exhausted" not in EVENT_CONTRACTS


def test_refuge_events_survive_strict_contract_validation(tmp_path: Path, monkeypatch):
    """Bajo `RNFE_CONTRACT_VALIDATION=strict`, emitirlos NO explota."""
    monkeypatch.setenv("RNFE_CONTRACT_VALIDATION", "strict")
    storage = _storage(tmp_path)
    run_id = "life-b83-strict"
    kernel = _kernel(storage, run_id)
    _seed(kernel, storage, _healthy())
    _degrade_on_disk(_artifacts(storage, run_id)[0], continuity_score=0.10)

    assert kernel._restore_latest_healthy_checkpoint() is False

    # Y los eventos QUEDARON escritos (no se los tragó una excepción silenciada).
    assert len(_events(storage, run_id, "life.refuge.rejected")) == 1
    assert len(_events(storage, run_id, "life.refuge.exhausted")) == 1


# ── el camino vivo: la cuarentena atascada ──────────────────────────────────────

def test_quarantine_stuck_without_refuge_is_not_mute(tmp_path: Path):
    """EL CALLEJÓN SIN SALIDA, EN VIVO: cuarentena repetida y ningún refugio al que volver.

    El organismo intenta replegarse (E5), no encuentra nada, y ahora lo DICE en vez de
    quedarse mudo en cuarentena. Es la señal que aeon-01 nunca pudo emitir.
    """
    storage = _storage(tmp_path)
    run_id = "life-b83-cuarentena"
    kernel = _kernel(storage, run_id)
    kernel._consecutive_quarantine = 3  # ya viene atascado

    assert kernel._restore_latest_healthy_checkpoint() is False

    exhausted = _events(storage, run_id, "life.refuge.exhausted")
    assert len(exhausted) == 1
    assert exhausted[0].payload["step_index"] == kernel.total_steps
