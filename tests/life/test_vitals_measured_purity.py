"""P9.6 — la SEGUNDA fabricación (vitals) y la supervivencia del refugio.

`vitals.py` re-fabricaba por su cuenta: `continuity` default 1.0 y `memory_purity` default
1.0. Aunque `transfer_assessment` dejara de emitir la clave, ESTA capa la reinventaba: dos
mentiras independientes, cada una capaz de sostener la ilusión sola.

LA TRAMPA que estos tests custodian:

    memory_purity → is_restorable (≥0.85) → checkpoints.py (`healthy`)
                  → kernel.py:530 (el rollback se BLOQUEA sin `healthy_checkpoint`)

Des-fabricar la pureza SIN medirla dejaría al organismo SIN REFUGIO: ningún checkpoint
volvería a marcarse sano y no podría rodar atrás nunca más. Se cambiaría "acepta cualquier
cosa" por "no acepta nada", que es PEOR. Por eso hay dos tests que hay que sostener JUNTOS:

  1. El refugio SOBREVIVE — el organismo vivo sigue produciendo checkpoints sanos, con
     pureza MEDIDA (ganada), no fabricada.
  2. La pureza AUSENTE cierra la compuerta — no se rellena con un 1.0 favorable.
"""

from pathlib import Path

from runtime.life.checkpoints import LIFE_CHECKPOINT_KIND
from runtime.life.kernel import LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory


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


def test_the_refuge_survives_de_fabrication(tmp_path: Path):
    """LA PREGUNTA QUE PUEDE MATAR AL ORGANISMO: ¿sigue habiendo checkpoints sanos?

    Si al des-fabricar la pureza ningún checkpoint volviera a marcarse `healthy`, el
    organismo perdería el refugio para siempre. Sobrevive porque la pureza ahora se MIDE
    (del retrieval del propio episodio) en vez de rellenarse: el valor honesto de un
    episodio limpio sigue siendo 1.0 — pero ganado.
    """
    storage = _storage(tmp_path)
    run_id = "life-p96-refuge"
    kernel = _kernel(storage, run_id)

    kernel.run_until_stopped(max_steps=4)

    checkpoints = storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND, limit=50)
    healthy = [c for c in checkpoints if (c.metadata or {}).get("healthy")]

    assert checkpoints, "el organismo tiene que estar guardando checkpoints"
    assert healthy, (
        "REFUGIO MUERTO: ningún checkpoint quedó `healthy` ⇒ el organismo no puede volver "
        "atrás nunca más. Des-fabricar sin medir es peor que fabricar."
    )


def test_the_surviving_refuge_rests_on_measured_purity_not_on_a_default(tmp_path: Path):
    """El refugio sobrevive por MEDICIÓN, no porque quedara algún relleno favorable.

    Sin este test, el anterior podría pasar por la razón equivocada (que la fabricación
    siguiera viva en algún rincón).
    """
    storage = _storage(tmp_path)
    run_id = "life-p96-earned"
    kernel = _kernel(storage, run_id)

    kernel.run_until_stopped(max_steps=4)

    certificates = storage.list_episode_certificates(run_id=run_id, limit=10)
    assert certificates

    latest = certificates[0]
    transfer = latest.metadata["transfer_assessment"]

    assert transfer["memory_purity_score"] is not None, "la pureza tiene que estar MEDIDA"
    assert "memory_purity" not in transfer["unmeasured_fields"]

    basis = transfer["memory_purity_basis"]
    assert basis["source"] in ("transition_vector", "episode_retrieval_metrics")
    assert basis["contamination_opportunity"] is True, (
        "hubo memoria que PUDO contaminar y no contaminó: el 1.0 se ganó"
    )

    vitals = kernel.last_vitals
    assert vitals is not None
    assert "memory_purity" not in vitals.unverified_fields
    assert vitals.is_restorable is True


def test_absent_purity_closes_the_gate_instead_of_fabricating_health(tmp_path: Path):
    """Pureza ausente ⇒ eje NO VERIFICADO ⇒ NO restaurable. Ausencia de dato no es salud.

    Antes, `_as_float(transfer.get("memory_purity_score"), 1.0)` inventaba una pureza
    perfecta cuando el certificado no traía ninguna, y el checkpoint se declaraba refugio
    válido sobre un dato que nadie midió.
    """
    storage = _storage(tmp_path)
    run_id = "life-p96-absent"
    kernel = _kernel(storage, run_id)
    kernel.step()

    # Un certificado SIN pureza (p.ej. anterior a P9.6): la capa de vitales no debe rellenarlo.
    storage.write_episode_certificate(
        episode_id="ep-sin-pureza",
        run_id=run_id,
        trace_id="trace-sin-pureza",
        smg_artifacts={},
        lotf_artifacts={},
        world_artifacts={},
        continuity_score=1.0,
        ioc_proxy=0.95,
        risk_score=0.05,
        verdict="certified",
        rollback_ready=True,
        promotion_candidate=True,
        metadata={"transfer_assessment": {}},  # sin `memory_purity_score`
    )

    vitals = kernel.vitals_service.from_state(
        run_id=run_id,
        organism_state=kernel.organism_state,
        lineage=kernel.lineage,
    )

    assert "memory_purity" in vitals.unverified_fields
    assert vitals.is_restorable is False, "un eje no verificado NO puede sostener el refugio"
    assert "memory_purity" in vitals.unverified_restore_axes
    assert vitals.restorability_report()["reason"] == "vitals_unverified"
