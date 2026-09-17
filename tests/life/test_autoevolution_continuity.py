"""H-046 a nivel de kernel: la reconstrucción del runner no puede costarle al organismo
su estado adaptativo.

El kernel reconstruye el runner —y con él el `AutoEvolutionController`— cada
`block_size` episodios (kernel.py:353-358), tras cada refugio (kernel.py:951-952) y al
cambiar la clave de `_runner_for`. Aquí se recorre el camino real
`kernel → runner → controller` y se exige:

  · B7  gate de congelamiento: sin rebuild, la fisiología adoptada es determinista y la
        autoevolución no actúa en régimen sano. PASA en HEAD; fija la línea base.
  · B1  con `block_size=1` toda propuesta aplicada termina exactamente una vez.
  · B2  dos brazos, uno con rebuild forzado en los cuatro momentos de §VII, misma
        trayectoria de estado adaptativo.
  · B3  save/load en mitad de una ventana de monitoreo: mismo lifecycle al reanudar.
  · B4  el refugio no hace desaparecer una propuesta activa: la ABORTA con registro.
  · B5  los dos caminos de restore (identidad y refugio) rehidratan el mismo slot.
  · B6  el checkpoint lleva el slot y es serializable.

El lazo se EXCITA sin tocar el trigger de producción (§XXIII): la subclase de test fija
`viability_trigger=1.1` sobre el controller de cada runner nuevo — el trigger es
CONFIGURATION y se pierde legítimamente al reconstruir; la subclase lo re-aplica.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from runtime.life import CheckpointManager, LIFE_CHECKPOINT_KIND, LifeKernel, LifeKernelConfig
from runtime.storage import StorageConfig, StorageFactory

# Commit iii retiró las marcas xfail: el kernel posee el estado en los cuatro caminos.

ORGANISM = "organism-ae-continuity"
SNAP = {
    "cpu_pressure": 0.1,
    "memory_pressure": 0.1,
    "thermal_pressure": 0.1,
    "vram_pressure": 0.1,
    "gpu_available": False,
}


def _storage(tmp_path: Path, name: str = "life"):
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


def _config(*, run_id: str, restore: bool = False, block_size: int = 50, mode: str = "cross_scenario_analogical"):
    return LifeKernelConfig(
        run_id=run_id,
        organism_id=ORGANISM,
        scenarios=("thermal_homeostasis",),
        block_size=block_size,
        max_steps=0,
        restore=restore,
        checkpoint_interval=1,
        memory_filter_mode=mode,
        allow_external_reasoner=False,
        enable_msrc=False,
        enable_operational_conjunction=False,
        resource_snapshot_override=dict(SNAP),
    )


class _ExcitedKernel(LifeKernel):
    """Excita el lazo ρₜ a partir de `excite_from` sin tocar el trigger de producción."""

    excite_from: int = 2

    def _runner_for(self, **kw):
        runner = super()._runner_for(**kw)
        ae = runner._autoevolution
        if self.total_steps >= self.excite_from:
            ae.viability_trigger = 1.1
        ae.patience = 2
        ae.cooldown = 2
        if ae._evidence is None:
            ae._evidence = {"n": 20, "ok": 19}
        return runner


# ── digests ──────────────────────────────────────────────────────────────────


def _physio_row(kernel: LifeKernel, result) -> Dict[str, Any]:
    """Sólo superficie pública: sirve en HEAD y fija el congelamiento."""
    ev = (result.episode_result or {}).get("autoevolution") or {}
    org = kernel.organism_state
    runner = kernel._runner
    return {
        "step": result.step_index,
        "action": ev.get("action"),
        "decision": result.decision.action,
        "episode_count": org.episode_count,
        "margin": round(float(org.viability.viability_margin), 6),
        "degradation": round(float(org.viability.accumulated_degradation), 6),
        "generation": kernel.lineage.generation,
        "rollbacks": len(kernel.lineage.rollback_ancestry),
        "limit": getattr(runner, "memory_retrieval_limit", None),
        "mode": getattr(runner, "memory_filter_mode", None),
    }


def _ae_payload(kernel: LifeKernel) -> Dict[str, Any] | None:
    """Estado adaptativo vivo: del runner si existe, si no del slot del kernel."""
    runner = kernel._runner
    if runner is not None:
        return runner.export_autoevolution_state()
    return dict(kernel._autoevolution_state)


def _ae_row(kernel: LifeKernel, result) -> Dict[str, Any]:
    ev = (result.episode_result or {}).get("autoevolution") or {}
    p = _ae_payload(kernel) or {}
    mon = p.get("post_monitor") or {}
    return {
        "step": result.step_index,
        "action": ev.get("action"),
        "target": ev.get("target"),
        "changes": ev.get("changes"),
        "consecutive": p.get("consecutive_degraded"),
        "cooldown": p.get("cooldown_left"),
        "episodes_left": mon.get("episodes_left"),
        "active": p.get("active_proposal_id") is not None,
        "n_proposals": len(p.get("proposals") or []),
        "adopted": p.get("adopted_knobs"),
        "ckpt_ep": ((p.get("checkpoint") or {}).get("state") or {}).get("episode_count"),
        "generation": kernel.lineage.generation,
        "rollbacks": len(kernel.lineage.rollback_ancestry),
    }


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _run(kernel: LifeKernel, steps: int, row_fn, rebuild_before: set[int] = frozenset()):
    rows = []
    for i in range(steps):
        if i in rebuild_before:
            kernel._runner = None
            kernel._runner_key = None
        r = kernel.step()
        rows.append(row_fn(kernel, r))
    return rows


def _events(storage, run_id: str, kinds):
    return storage.list_events(run_id=run_id, event_types=list(kinds), limit=500)


# ── B7 · gate de congelamiento (pasa en HEAD) ────────────────────────────────


def test_b7_healthy_run_physiology_digest_is_unchanged_without_rebuild(tmp_path):
    """Determinismo del lazo sin rebuild + la AE no actúa en régimen sano.

    Corre el mismo fixture dos veces en proceso. Si los digests difieren, el lazo no es
    determinista y el gate byte-a-byte degrada a comparación estructural — se registra.
    """
    d = []
    for k in ("a", "b"):
        kernel = LifeKernel(config=_config(run_id=f"freeze-{k}"), storage=_storage(tmp_path, k))
        rows = _run(kernel, 12, _physio_row)
        assert all(r["action"] in {"none", "disabled"} for r in rows), [r["action"] for r in rows]
        assert all(r["generation"] == 0 for r in rows)
        d.append(_digest(rows))
    assert d[0] == d[1], f"el lazo sin rebuild no es determinista: {d}"


# ── B1 · toda propuesta aplicada termina exactamente una vez ────────────────


def test_b1_every_applied_proposal_reaches_exactly_one_terminal_outcome(tmp_path):
    storage = _storage(tmp_path)
    kernel = _ExcitedKernel(config=_config(run_id="b1", block_size=1), storage=storage)
    rows = _run(kernel, 40, _ae_row)

    applied = _events(storage, "b1", ["autoevolution.applied"])
    assert applied, "el lazo excitado nunca aplicó: la prueba no ejercita nada"
    terminal = _events(storage, "b1", ["autoevolution.committed", "autoevolution.reverted", "autoevolution.aborted"])
    por_id: Dict[str, int] = {}
    for e in terminal:
        por_id[e.payload["proposal_id"]] = por_id.get(e.payload["proposal_id"], 0) + 1
    # ∀ applied ∃! outcome — salvo la que sigue VIVA al acabar la corrida: ésa no está
    # abandonada, su ventana está abierta en el slot. A lo sumo una, y debe ser la activa.
    p = _ae_payload(kernel) or {}
    activa = p.get("active_proposal_id")
    sin_desenlace = []
    for e in applied:
        pid = e.payload["proposal_id"]
        n = por_id.get(pid, 0)
        assert n <= 1, f"{pid}: {n} desenlaces terminales (nunca más de uno)"
        if n == 0:
            sin_desenlace.append(pid)
    assert len(sin_desenlace) <= 1, f"más de una propuesta aplicada sin desenlace: {sin_desenlace}"
    if sin_desenlace:
        assert sin_desenlace[0] == activa, (
            f"{sin_desenlace[0]} fue aplicada y no es la activa ({activa}): ventana ABANDONADA"
        )
        assert (p.get("post_monitor") or {}).get("proposal_id") == activa
    assert len([e for e in applied if e.payload["proposal_id"] != activa]) >= 1


# ── B2 · dos brazos: estable vs rebuild forzado en los cuatro momentos ───────


def test_b2_forced_rebuild_arm_matches_stable_arm(tmp_path):
    ka = _ExcitedKernel(config=_config(run_id="b2-a"), storage=_storage(tmp_path, "a"))
    a = _run(ka, 40, _ae_row)

    # Los cuatro momentos de §VII, localizados en el brazo estable.
    def primero(pred):
        return next((r["step"] for r in a if pred(r)), None)

    momentos = {
        "paciencia": primero(lambda r: r["consecutive"] == 1),
        "checkpoint_sano": primero(lambda r: r["ckpt_ep"] is not None),
        "mitad_monitor": primero(lambda r: (r["episodes_left"] or 0) == 2),
        "cooldown": primero(lambda r: (r["cooldown"] or 0) > 0),
    }
    assert all(v is not None for v in momentos.values()), f"el brazo estable no recorrió los 4 momentos: {momentos}"
    rebuild_before = {v + 1 for v in momentos.values()}  # reconstruir ANTES del paso siguiente

    kb = _ExcitedKernel(config=_config(run_id="b2-b"), storage=_storage(tmp_path, "b"))
    b = _run(kb, 40, _ae_row, rebuild_before=rebuild_before)

    for ra, rb in zip(a, b):
        assert ra == rb, f"paso {ra['step']} (rebuilds en {sorted(rebuild_before)}): {ra} != {rb}"


# ── B3 · save/load en mitad de una ventana ───────────────────────────────────


def test_b3_resume_mid_monitor_continues_the_same_lifecycle(tmp_path):
    storage = _storage(tmp_path)
    ka = _ExcitedKernel(config=_config(run_id="b3-before"), storage=storage)
    rows = []
    for _ in range(40):
        r = ka.step()
        rows.append(_ae_row(ka, r))
        if rows[-1]["episodes_left"] == 2:  # en mitad de la ventana, checkpoint recién guardado
            break
    assert rows[-1]["active"], "no se llegó a una ventana activa"
    p_before = _ae_payload(ka)
    pid = p_before["active_proposal_id"]
    evidence_before = dict(p_before["evidence"])

    kb = _ExcitedKernel(config=_config(run_id="b3-after", restore=True), storage=storage)
    assert kb.organism_id == ka.organism_id
    p_after = dict(kb._autoevolution_state)
    assert p_after["active_proposal_id"] == pid
    assert p_after["post_monitor"]["episodes_left"] == 2
    assert p_after["evidence"] == evidence_before

    for _ in range(6):
        kb.step()
    terminal = _events(storage, "b3-after", ["autoevolution.committed", "autoevolution.reverted", "autoevolution.aborted"])
    mios = [e for e in terminal if e.payload.get("proposal_id") == pid]
    assert len(mios) == 1, f"{pid} terminó {len(mios)} veces tras reanudar"


# ── B4 · refugio con propuesta activa → ABORT explícito ──────────────────────


def test_b4_refuge_restore_aborts_the_in_flight_proposal_explicitly(tmp_path):
    storage = _storage(tmp_path)
    kernel = _ExcitedKernel(config=_config(run_id="b4"), storage=storage)
    for _ in range(40):
        r = kernel.step()
        if (_ae_payload(kernel) or {}).get("active_proposal_id"):
            break
    pid = _ae_payload(kernel)["active_proposal_id"]
    assert pid

    # Los checkpoints que ya conocen la propuesta se degradan en disco, para que el
    # refugio caiga a uno ANTERIOR (mismo mecanismo que test_refuge_exhausted).
    for art in storage.list_artifacts(run_id="b4", kind=LIFE_CHECKPOINT_KIND, limit=200):
        path = Path(art.abs_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("autoevolution_state") or {}).get("active_proposal_id") == pid:
            payload["vital_signs"]["viability_margin"] = 0.0
            payload["vital_signs"]["reversible"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")

    assert kernel._restore_latest_healthy_checkpoint() is True
    assert kernel._runner is None
    aborted = _events(storage, "b4", ["autoevolution.aborted"])
    mios = [e for e in aborted if e.payload.get("proposal_id") == pid]
    assert len(mios) == 1 and mios[0].payload["reason"] == "refuge_restore"
    assert kernel._autoevolution_state.get("active_proposal_id") != pid


# ── B5 · los dos caminos de restore rehidratan el mismo slot ─────────────────


def test_b5_both_restore_paths_rehydrate_the_slot(tmp_path):
    storage = _storage(tmp_path)
    kernel = LifeKernel(config=_config(run_id="b5"), storage=storage)
    kernel.step()
    conocido = {
        "schema_version": "autoevolution-state-v1",
        "lineage_id": kernel.lineage.lineage_id,
        "consecutive_degraded": 1,
        "cooldown_left": 2,
        "checkpoint": None,
        "post_monitor": None,
        "evidence": {"n": 7, "ok": 6},
        "adopted_knobs": None,
        "active_proposal_id": None,
        "proposals": [],
    }
    CheckpointManager(storage=storage).save_checkpoint(
        run_id="b5",
        organism_id=kernel.organism_id,
        lineage_id=kernel.lineage_id,
        organism_state=kernel.organism_state,
        lineage=kernel.lineage,
        goals=list(kernel.goal_manager.goals),
        vital_signs=kernel.last_vitals,
        total_steps=kernel.total_steps,
        scenario_index=0,
        scenario_episode_index=0,
        memory_filter_mode="strict_same_scenario",
        closure_profile="baseline_fixed",
        neural_state={},
        autoevolution_state=conocido,
    )
    # camino 1: identidad al arrancar
    k2 = LifeKernel(config=_config(run_id="b5-restore", restore=True), storage=storage)
    assert k2._autoevolution_state == conocido
    # camino 2: refugio
    assert kernel._restore_latest_healthy_checkpoint() is True
    assert kernel._autoevolution_state == conocido

    # legacy sin slot → {} en ambos
    CheckpointManager(storage=storage).save_checkpoint(
        run_id="b5",
        organism_id=kernel.organism_id,
        lineage_id=kernel.lineage_id,
        organism_state=kernel.organism_state,
        lineage=kernel.lineage,
        goals=[],
        vital_signs=kernel.last_vitals,
        total_steps=kernel.total_steps + 1,
        scenario_index=0,
        scenario_episode_index=0,
        memory_filter_mode="strict_same_scenario",
        closure_profile="baseline_fixed",
    )
    assert kernel._restore_latest_healthy_checkpoint() is True
    assert kernel._autoevolution_state == {}


# ── B6 · el checkpoint lleva el slot ─────────────────────────────────────────


def test_b6_checkpoint_payload_carries_the_autoevolution_slot(tmp_path):
    storage = _storage(tmp_path)
    kernel = LifeKernel(config=_config(run_id="b6"), storage=storage)
    kernel.step()
    art = storage.list_artifacts(run_id="b6", kind=LIFE_CHECKPOINT_KIND, limit=5)
    assert art
    payload = json.loads(Path(art[0].abs_path).read_text(encoding="utf-8"))
    assert "autoevolution_state" in payload
    assert payload["autoevolution_state"].get("schema_version") == "autoevolution-state-v1"
    json.dumps(payload["autoevolution_state"])
