"""H-046 — el estado longitudinal del lazo ρₜ debe sobrevivir a la muerte del controller.

`AutoEvolutionController` se construye dentro de `ScenarioEpisodeRunner`, y el kernel
reconstruye el runner cada `block_size` episodios (kernel.py:353-358), tras cada refugio
(kernel.py:951-952) y cuando cambia la clave de `_runner_for`. Medido en 40 pasos: 6
reconstrucciones, 3 checkpoints sanos perdidos, 2 ventanas post-aplicación abandonadas
(propuesta aplicada, ni commit ni revert), 1 cooldown perdido.

Estas pruebas fijan el invariante a nivel de controller, sin kernel: un controller
reconstruido en CADA observación, rehidratado con `restore_state(export_state())`, debe
recorrer exactamente la misma trayectoria que uno que nunca muere. "Rebuild" aquí es
literal: se instancia un `AutoEvolutionController` nuevo y se le entrega el payload.

Lo que NO cambia: ecuaciones, `viability_trigger`, `patience`, `post_window`,
`cooldown`, `retention_signal`. Sólo QUIÉN POSEE el estado entre observaciones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.organism.autoevolution import AutoEvolutionController
from runtime.organism.state import (
    OrganismBeliefState,
    OrganismState,
    PolicyState,
    ViabilityState,
)
from runtime.storage import StorageConfig, StorageFactory

# Commit ii retiró la marca xfail del módulo: el controller exporta y restaura.
# A10 (fisiología adoptada) sigue marcada hasta el commit iv.
XF_IV = pytest.mark.xfail(strict=True, reason="H-046: los knobs adoptados no se reaplican aún (commit iv)")


# ── helpers (espejo de tests/organism/test_autoevolution.py) ─────────────────


def _storage(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)  # los brazos usan subdirectorios propios
    return StorageFactory.create_facade(
        StorageConfig(
            mode="sqlite",
            sqlite_db_path=str(tmp_path / "evo-state.db"),
            postgres_dsn=None,
            artifact_root=tmp_path / "artifacts",
            prefer_postgres_reads=False,
            strict_dual_write=False,
        )
    )


def _state(*, margin: float = 1.0, drift: float = 0.0, episode: int = 1) -> OrganismState:
    return OrganismState(
        state_id=f"state-{episode}",
        timestamp="2026-06-10T00:00:00Z",
        episode_count=episode,
        belief=OrganismBeliefState(
            intervention_efficacy=0.9,
            causal_support_confidence=0.9,
            memory_purity_estimate=0.95,
            trace_integrity_confidence=0.8,
        ),
        policy=PolicyState(accumulated_drift=drift),
        viability=ViabilityState(viability_margin=margin),
    )


def _episode_result(
    *, margin: float = 1.0, rollback_required: bool = False, verdict: str = "valid", retrieved: int = 0
) -> dict:
    return {
        "episode": {"context": {"retrieved_memory": [{"m": i} for i in range(retrieved)]}},
        "viability_assessment": {
            "is_viable": True,
            "viability_margin": margin,
            "distance_to_edge": margin,
            "rollback_required": rollback_required,
        },
        "constitutional_validation": {"verdict": verdict, "hard_violation_count": 0},
    }


class _Knobs:
    def __init__(self, limit=3, mode="cross_scenario_analogical"):
        self.values = {"memory_retrieval_limit": limit, "memory_filter_mode": mode}

    def read(self):
        return dict(self.values)

    def write(self, changes):
        self.values.update(changes)


_CFG = dict(patience=2, post_window=2, cooldown=2, enabled=True)


def _controller(knobs: _Knobs, *, storage=None, lineage=None, **kw) -> AutoEvolutionController:
    cfg = {**_CFG, **kw}
    return AutoEvolutionController(
        run_id="run-evo",
        storage=storage,
        lineage=lineage,
        knob_reader=knobs.read,
        knob_writer=knobs.write,
        **cfg,
    )


def _seed_evidence(ctrl: AutoEvolutionController, n: int = 20, ok: int = 19):
    ctrl._evidence = {"n": n, "ok": ok}
    return ctrl


def _rebuild(ctrl: AutoEvolutionController, knobs: _Knobs, **kw) -> AutoEvolutionController:
    """Mata el controller y construye otro rehidratado. Comparte linaje y storage."""
    nuevo = _controller(knobs, storage=ctrl.storage, lineage=ctrl.lineage, **kw)
    nuevo.restore_state(ctrl.export_state())
    return nuevo


def _canon(payload: dict) -> dict:
    """Payload comparable entre brazos: los uuid de propuesta pasan a índices posicionales.

    Un controller reconstruido acuña su propio `mod-<hex>`; lo que debe coincidir es la
    ESTRUCTURA del lifecycle, no el azar del identificador.
    """
    payload = dict(payload, lineage_id="L")  # dos brazos = dos organismos; la estructura es lo que se compara
    text = json.dumps(payload, sort_keys=True)
    ids: list[str] = []
    for rec in payload.get("proposals") or []:
        pid = rec.get("proposal_id")
        if pid and pid not in ids:
            ids.append(pid)
    for i, pid in enumerate(ids):
        text = text.replace(pid, f"P{i}")
    return json.loads(text)


# La secuencia recorre TODO el lifecycle con post_window=2, patience=2, cooldown=2:
#   sano · degradado×2 → applied · monitoring → committed · degradado×2 → applied ·
#   monitoring → reverted (cooldown=2) · cooldown×2 · sano (checkpoint) · rollback duro
_GUION = [
    # (margen, retrieved, delta_ioc, rollback_required)
    (0.90, 0, None, False),
    (0.30, 3, None, False),
    (0.30, 3, None, False),
    (0.35, 0, +0.02, False),
    (0.40, 0, +0.03, False),
    (0.30, 3, None, False),
    (0.30, 3, None, False),
    (0.25, 0, -0.05, False),
    (0.20, 0, -0.04, False),
    (0.30, 3, None, False),
    (0.30, 3, None, False),
    (0.90, 0, None, False),
    (0.90, 0, None, True),
]


def _observar(ctrl, knobs, ep, margen, retrieved, delta, rb):
    meta = {"risk_plus": {"delta_ioc": delta}} if delta is not None else {}
    out = ctrl.observe_episode(
        organism_state=_state(margin=margen, episode=ep),
        episode_result=_episode_result(margin=margen, retrieved=retrieved, rollback_required=rb),
        certificate_metadata=meta,
        certificate_verdict="certified",
    )
    restored = out.pop("restored_state", None)
    return out, (restored.state_id if restored is not None else None), knobs.read()


def _correr(rebuild_each_step: bool, tmp_path: Path, knobs_factory=None):
    storage = _storage(tmp_path / ("b" if rebuild_each_step else "a"))
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs, storage=storage))
    filas = []
    for ep, (m, r, d, rb) in enumerate(_GUION, start=1):
        if rebuild_each_step and ep > 1:
            if knobs_factory is not None:
                knobs = knobs_factory()
            ctrl = _rebuild(ctrl, knobs)
        out, restored_id, kn = _observar(ctrl, knobs, ep, m, r, d, rb)
        filas.append(
            {
                "ep": ep,
                "action": out["action"],
                "restored": restored_id,
                "knobs": kn,
                "state": _canon(ctrl.export_state()),
                "generation": ctrl.lineage.generation,
                "rollbacks": len(ctrl.lineage.rollback_ancestry),
            }
        )
    return filas, ctrl, storage


# ── A1 · diferencial: rebuild en cada paso ≡ sin rebuild ─────────────────────


def test_a1_rebuild_en_cada_paso_es_neutro(tmp_path):
    a, _, _ = _correr(False, tmp_path)
    b, _, _ = _correr(True, tmp_path)
    acciones_a = [f["action"] for f in a]
    assert "applied" in acciones_a and "committed" in acciones_a and "reverted" in acciones_a
    assert "rollback" in acciones_a, acciones_a
    for fa, fb in zip(a, b):
        assert fa == fb, f"divergencia en ep {fa['ep']}: {fa['action']} vs {fb['action']}"


# ── A2 · paciencia ────────────────────────────────────────────────────────────


def test_a2_rebuild_durante_paciencia_no_la_resetea(tmp_path):
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs))
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)  # sano, checkpoint
    out, *_ = _observar(ctrl, knobs, 2, 0.3, 3, None, False)
    assert out == {"action": "none", "degraded": True, "consecutive": 1}
    ctrl = _rebuild(ctrl, knobs)
    assert ctrl._consecutive_degraded == 1
    out, *_ = _observar(ctrl, knobs, 3, 0.3, 3, None, False)
    assert out["action"] == "applied", out  # llegó a n=2, no volvió a 1


# ── A3 · cooldown ─────────────────────────────────────────────────────────────


def test_a3_rebuild_durante_cooldown_no_lo_resetea(tmp_path):
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs))
    ctrl._cooldown_left = 2
    out, *_ = _observar(ctrl, knobs, 1, 0.3, 3, None, False)
    assert out["cooldown"] == 2 and ctrl._cooldown_left == 1
    ctrl = _rebuild(ctrl, knobs)
    assert ctrl._cooldown_left == 1
    out, *_ = _observar(ctrl, knobs, 2, 0.3, 3, None, False)
    assert out["cooldown"] == 1 and ctrl._cooldown_left == 0


# ── A4 · checkpoint sano ──────────────────────────────────────────────────────


def test_a4_rebuild_conserva_el_checkpoint_sano_para_rollback(tmp_path):
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs))
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)
    knobs.write({"memory_retrieval_limit": 7})  # el mundo mueve el mando después
    ctrl = _rebuild(ctrl, knobs)
    out, restored_id, kn = _observar(ctrl, knobs, 2, 0.9, 0, None, True)
    assert out["action"] == "rollback" and out["checkpoint_available"] is True
    assert restored_id == "state-1"
    assert kn["memory_retrieval_limit"] == 3  # los knobs del checkpoint, no los actuales


# ── A5 · mitad de la ventana post-aplicación ─────────────────────────────────


def test_a5_rebuild_en_mitad_del_monitor_conserva_la_ventana(tmp_path):
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs, post_window=3))
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)
    _observar(ctrl, knobs, 2, 0.3, 3, None, False)
    out, *_ = _observar(ctrl, knobs, 3, 0.3, 3, None, False)
    assert out["action"] == "applied"
    pid = out["proposal_id"]
    backup = dict(ctrl._post_monitor["knob_backup"])
    out, *_ = _observar(ctrl, knobs, 4, 0.35, 0, +0.02, False)
    assert out == {"action": "monitoring", "proposal_id": pid, "episodes_left": 2}

    ctrl = _rebuild(ctrl, knobs, post_window=3)
    mon = ctrl._post_monitor
    assert mon is not None
    assert mon["proposal_id"] == pid
    assert mon["knob_backup"] == backup
    assert mon["episodes_left"] == 2
    assert mon["deltas"] == [0.02] and mon["margins"] == [0.35]
    assert mon["margin_baseline"] == 0.30

    out, *_ = _observar(ctrl, knobs, 5, 0.40, 0, +0.03, False)
    assert out["action"] == "monitoring" and out["episodes_left"] == 1
    out, *_ = _observar(ctrl, knobs, 6, 0.42, 0, +0.01, False)
    assert out["action"] == "committed" and out["proposal_id"] == pid
    # Exactamente una transición terminal para esa propuesta.
    rec = next(r for r in ctrl.export_state()["proposals"] if r["proposal_id"] == pid)
    terminales = [t for t in rec["transitions"] if t["status"] in {"committed", "reverted", "aborted"}]
    assert len(terminales) == 1 and rec["status"] == "committed"


# ── A6 · rollback duro en pleno monitoreo → ABORT explícito ──────────────────


def test_a6_rollback_duro_en_monitoreo_registra_abort(tmp_path):
    storage = _storage(tmp_path)
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs, storage=storage, post_window=3))
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)
    _observar(ctrl, knobs, 2, 0.3, 3, None, False)
    out, *_ = _observar(ctrl, knobs, 3, 0.3, 3, None, False)
    pid = out["proposal_id"]
    out, *_ = _observar(ctrl, knobs, 4, 0.9, 0, None, True)  # rollback_required en la ventana
    assert out["action"] == "rollback"
    assert ctrl._post_monitor is None

    rec = next(r for r in ctrl.export_state()["proposals"] if r["proposal_id"] == pid)
    assert rec["status"] == "aborted"
    assert rec["outcome_reason"].startswith("hard_rollback:")
    ev = storage.list_events(run_id="run-evo", event_types=["autoevolution.aborted"], limit=10)
    assert len(ev) == 1 and ev[0].payload["proposal_id"] == pid


# ── A7 · la evidencia viaja, no se resiembra ─────────────────────────────────


def test_a7_evidencia_se_lleva_no_se_resiembra(tmp_path):
    storage = _storage(tmp_path)  # cero certificados en storage
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs, storage=storage), n=10, ok=9)
    ctrl = _rebuild(ctrl, knobs)
    assert ctrl._evidence == {"n": 10, "ok": 9}  # sin carry, el reseed daría {0, 0}
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)
    assert ctrl._evidence == {"n": 11, "ok": 10}


# ── A8 · restore estricto ─────────────────────────────────────────────────────


def test_a8_restore_rechaza_linaje_ajeno_y_esquema_desconocido(tmp_path):
    knobs = _Knobs()
    ctrl = _seed_evidence(_controller(knobs))
    _observar(ctrl, knobs, 1, 0.9, 0, None, False)
    payload = ctrl.export_state()

    ajeno = _controller(_Knobs())  # linaje propio, distinto
    with pytest.raises(ValueError, match="autoevolution_state_lineage_mismatch"):
        ajeno.restore_state(payload)

    roto = dict(payload, schema_version="autoevolution-state-v0")
    with pytest.raises(ValueError, match="autoevolution_state_schema_unknown"):
        _controller(knobs, lineage=ctrl.lineage).restore_state(roto)

    assert _controller(knobs, lineage=ctrl.lineage).restore_state(None) is False
    assert _controller(knobs, lineage=ctrl.lineage).restore_state({}) is False


# ── A9 · roundtrip JSON estable ──────────────────────────────────────────────


def test_a9_export_restore_roundtrip_es_json_estable(tmp_path):
    a, ctrl, _ = _correr(False, tmp_path)
    exp = ctrl.export_state()
    otra = _rebuild(ctrl, _Knobs())
    assert json.dumps(exp, sort_keys=True) == json.dumps(otra.export_state(), sort_keys=True)
    json.loads(json.dumps(exp))  # serializable sin ayuda


# ── A10 · fisiología adoptada: el mando que el lazo escribió viaja con el estado ──


@XF_IV
def test_a10_knobs_adoptados_se_reaplican_en_knobs_frescos(tmp_path):
    # Brazo B con mandos FRESCOS (limit=3) en cada rebuild: el estado debe devolverlos.
    a, _, _ = _correr(False, tmp_path)
    b, ctrl_b, _ = _correr(True, tmp_path, knobs_factory=_Knobs)
    for fa, fb in zip(a, b):
        assert fa["knobs"] == fb["knobs"], f"ep {fa['ep']}: {fa['knobs']} vs {fb['knobs']}"

    # Un controller que nunca escribió deja intactos unos mandos frescos.
    knobs = _Knobs(limit=5)
    virgen = _seed_evidence(_controller(knobs))
    _observar(virgen, knobs, 1, 0.9, 0, None, False)
    frescos = _Knobs(limit=9)
    _controller(frescos, lineage=virgen.lineage).restore_state(virgen.export_state())
    assert frescos.read()["memory_retrieval_limit"] == 9
