"""B41 — path LEGADO PURO de identidad (gate bloqueante de promoción a main).

Un checkpoint/memoria PRE-B41 escribió su payload SIN el campo ``organism_id`` (la
identidad era mono-eje: el ``run_id`` era todo lo que había). B41 introdujo los tres
ejes (``run_id`` / ``organism_id`` / ``lineage_id``) con ``CausalContext.v1`` GATED por
``RNFE_CAUSAL_CONTEXT`` (off por defecto) y compat ``organism_id_legacy := run_id``.

Este test funcional atraviesa la RUTA DE RESTAURACIÓN REAL de un artefacto legado
(payload sin ``organism_id``) con ``RNFE_CAUSAL_CONTEXT`` OFF y demuestra, de punta a
punta, que el caso histórico sigue vivo sin regresión:

1. el camino legado se ejecuta (el restore funciona);
2. el contrato observable NO cambia (mismos campos que pre-B41, sin ``causal_context``);
3. NO se requiere ``CausalContext`` para el caso histórico;
4. NO se pierde trazabilidad (el ``run_id`` legado se conserva en eventos/ejecución);
5. NO se acuña identidad incorrecta: ``organism_id`` se DERIVA del ``run_id`` legado
   (fallback :func:`legacy_organism_id`), no un uuid ``org-`` nuevo;
6. la memoria/experiencia vieja (namespaceada por el ``run_id`` legado) SE RECUPERA;
7. NO hay contaminación entre runs (otro run legado con otro ``run_id`` no ve la
   memoria del primero);
8. serialización/persistencia/restauración intactas (round-trip);
9. determinismo bajo la misma entrada + estado restaurado.

Aditivo: NO modifica tests ni código de runtime. La ÚNICA "manipulación" es despojar
el campo ``organism_id``/``lineage_id`` del payload EN DISCO para reproducir fielmente
un artefacto pre-B41; el restore que se ejercita es el real
(``LifeKernel._restore_initial_identity`` → ``OrganismPersistence.load_latest_identity``
→ ``legacy_organism_id``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from runtime.life import LIFE_CHECKPOINT_KIND, LifeKernel, LifeKernelConfig
from runtime.organism.experience import ExperienceStore
from runtime.organism.identity import ORGANISM_ID_PREFIX, legacy_organism_id
from runtime.storage import StorageConfig, StorageFactory

# Fields observables del evento life.step.completed que existían pre-B41 (contrato).
_PRE_B41_STEP_FIELDS = {"step_index", "scenario", "decision", "vital_signs", "goals"}


def _storage(tmp_path: Path):
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "legacy.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _seed_pre_b41_organism(storage, *, run_id: str, steps: int) -> tuple[int, int]:
    """Siembra un organismo PRE-B41: ``organism_id == run_id`` (identidad mono-eje).

    Corre pasos reales (con RNFE_EXPERIENCE on ⇒ el runner destila experiencia bajo el
    namespace del organismo, que aquí ES el run_id) y persiste checkpoints reales.
    Devuelve (total_steps, episode_count) del organismo sembrado.
    """
    kernel = LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            organism_id=run_id,  # pre-B41: el genoma y la corrida colapsaban en run_id
            scenarios=("thermal_homeostasis",),
            restore=False,
            enable_msrc=False,
        ),
        storage=storage,
    )
    # Setup fidelity: el organismo sembrado tiene organism_id == run_id (mono-eje).
    assert kernel.organism_id == run_id
    for _ in range(steps):
        kernel.step(external_input=0.05)
    return kernel.total_steps, kernel.organism_state.episode_count


def _strip_organism_id_on_disk(storage, *, run_id: str) -> Dict[str, Any]:
    """Convierte los checkpoints en disco de ``run_id`` en artefactos PRE-B41.

    Quita los campos que B41 agregó al payload (``organism_id``/``lineage_id``) dejando
    ``run_id`` como única identidad — exactamente la forma de un artefacto pre-B41.
    Devuelve el último payload despojado (para aserciones sobre su forma).
    """
    artifacts = storage.list_artifacts(run_id=run_id, kind=LIFE_CHECKPOINT_KIND, limit=400)
    assert artifacts, f"el seed de {run_id} no dejó checkpoints"
    last_stripped: Dict[str, Any] | None = None
    for artifact in artifacts:
        path = Path(artifact.abs_path)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("organism_id", None)
        payload.pop("lineage_id", None)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        last_stripped = payload
    assert last_stripped is not None
    return last_stripped


def _restore_legacy(storage, *, run_id: str) -> LifeKernel:
    """Restaura por RUTA LEGADA PURA: SOLO run_id, SIN organism_id de config/entorno."""
    return LifeKernel(
        config=LifeKernelConfig(
            run_id=run_id,
            # organism_id AUSENTE a propósito: sin genoma explícito, el descubrimiento
            # se scopea por run_id y el genoma se deriva del payload legado (fallback).
            scenarios=("thermal_homeostasis",),
            restore=True,
            enable_msrc=False,
        ),
        storage=storage,
    )


def test_legacy_pure_path_restores_via_run_id_fallback(tmp_path: Path, monkeypatch):
    """Un checkpoint sin ``organism_id`` restaura vía fallback y no rompe nada pre-B41."""
    # Gate del caso histórico: CausalContext OFF y sin genoma en el entorno.
    monkeypatch.delenv("RNFE_CAUSAL_CONTEXT", raising=False)
    monkeypatch.delenv("RNFE_ORGANISM_ID", raising=False)
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")

    storage = _storage(tmp_path)
    legacy_a = "aeon-legacy-01"
    legacy_b = "aeon-legacy-02"

    # ── Fase 1 — sembrar DOS organismos pre-B41 y despojar sus payloads ──────────
    a_steps, a_episodes = _seed_pre_b41_organism(storage, run_id=legacy_a, steps=2)
    b_steps, b_episodes = _seed_pre_b41_organism(storage, run_id=legacy_b, steps=1)

    stripped_a = _strip_organism_id_on_disk(storage, run_id=legacy_a)
    _strip_organism_id_on_disk(storage, run_id=legacy_b)

    # El artefacto quedó como pre-B41: run_id presente, organism_id/lineage_id ausentes.
    assert "organism_id" not in stripped_a
    assert "lineage_id" not in stripped_a
    assert stripped_a["run_id"] == legacy_a
    assert stripped_a.get("version")  # sigue siendo un checkpoint válido (round-trip)
    # (5) El fallback funcional deriva el genoma del run_id legado, no un uuid nuevo.
    assert legacy_organism_id(stripped_a) == legacy_a

    # ── Fase 2 — restaurar por ruta legada pura (organism_id derivado del run_id) ─
    restored_a = _restore_legacy(storage, run_id=legacy_a)

    # (1) El restore se ejecutó: hay estado vivo restaurado.
    assert restored_a.organism_state is not None
    # (8) Round-trip intacto: contadores serializados == los del organismo sembrado.
    assert restored_a.total_steps == a_steps == 2
    assert restored_a.organism_state.episode_count == a_episodes == 2
    # (5) organism_id DERIVADO del run_id legado — NO un genoma org-<uuid> nuevo.
    assert restored_a.organism_id == legacy_a
    assert not restored_a.organism_id.startswith(ORGANISM_ID_PREFIX)
    assert ORGANISM_ID_PREFIX not in restored_a.organism_id
    # (4) Trazabilidad: el run_id legado se conserva como marca de esta ejecución.
    assert restored_a.run_id == legacy_a
    # lineage_id restaurado (no vacío) aunque el payload no lo trajera.
    assert restored_a.lineage_id

    # (4) El evento life.identity.restored carga la genealogía bajo el run_id legado.
    restored_events = storage.list_events(
        run_id=legacy_a, event_types=["life.identity.restored"], limit=5
    )
    assert restored_events
    ident = restored_events[0].payload
    assert ident["organism_id"] == legacy_a
    assert ident["run_id"] == legacy_a
    assert ident["previous_run_id"] == legacy_a  # corrida estable == genoma legado

    # ── Fase 3 — (6) la memoria/experiencia vieja SE RECUPERA por el genoma legado ─
    store = ExperienceStore(storage=storage)
    recovered = store.recall(organism_id=restored_a.organism_id)
    assert recovered, "el organismo legado no recuperó su experiencia vieja"
    # No hay fuga hacia genomas inexistentes.
    assert store.recall(organism_id="org-nonexistent") == []

    # ── Fase 4 — (7) sin contaminación: otro run legado no ve la memoria del primero ─
    restored_b = _restore_legacy(storage, run_id=legacy_b)
    assert restored_b.organism_id == legacy_b
    assert not restored_b.organism_id.startswith(ORGANISM_ID_PREFIX)
    assert restored_b.run_id == legacy_b
    assert restored_b.total_steps == b_steps == 1

    recs_a = storage.retrieve_memory_records(run_id=legacy_a, scales=["experience"])
    recs_b = storage.retrieve_memory_records(run_id=legacy_b, scales=["experience"])
    assert recs_a and recs_b
    prov_a = {(r.metadata or {}).get("run_id") for r in recs_a}
    prov_b = {(r.metadata or {}).get("run_id") for r in recs_b}
    # Cada genoma legado solo ve SU propia memoria; los namespaces son disjuntos.
    assert prov_a == {legacy_a}
    assert prov_b == {legacy_b}
    assert prov_a.isdisjoint(prov_b)

    # ── Fase 5 — (9) determinismo + (2)(3)(4) contrato observable al continuar ────
    # Dos restauraciones del MISMO checkpoint legado (ninguna corrida las contaminó aún)
    # rinden identidad y contadores idénticos ⇒ restore determinista.
    det1 = _restore_legacy(storage, run_id=legacy_a)
    det2 = _restore_legacy(storage, run_id=legacy_a)
    assert det1.organism_id == det2.organism_id == legacy_a
    assert det1.run_id == det2.run_id == legacy_a
    assert det1.total_steps == det2.total_steps == a_steps
    assert det1.organism_state.episode_count == det2.organism_state.episode_count

    # Bajo la misma entrada, ambos avanzan idéntico (contadores deterministas).
    r1 = det1.step(external_input=0.05)
    r2 = det2.step(external_input=0.05)
    assert r1.step_index == r2.step_index == a_steps + 1
    assert det1.organism_state.episode_count == det2.organism_state.episode_count

    # (3)(2) El caso histórico NO requiere CausalContext y su contrato es byte-idéntico:
    # con RNFE_CAUSAL_CONTEXT off la clave NUNCA viaja y los campos son los pre-B41.
    step_events = storage.list_events(
        run_id=legacy_a, event_types=["life.step.completed"], limit=10
    )
    assert step_events
    latest = step_events[0].payload
    assert "causal_context" not in latest
    assert _PRE_B41_STEP_FIELDS <= set(latest.keys())
    # (4) Trazabilidad en ejecución: el evento del step vive bajo el run_id legado.
    assert r1.run_id == legacy_a
    assert all(ev.run_id == legacy_a for ev in step_events)
