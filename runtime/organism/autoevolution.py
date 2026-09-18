"""Controlador de autoevolución: cierra el lazo ρₜ del organismo (canon f2.4 §6).

Hasta R1, `SelfModificationPipeline` existía pero nada lo invocaba: el organismo
no podía proponerse cambios. Este controlador lo cablea al lazo episódico:

    degradación sostenida → diagnóstico → propuesta ρₜ → precheck constitucional
    → sandbox → gate de seguridad S-I-E (R1) → aplicar sobre mandos REALES
    → monitoreo post-aplicación (ΔIoC) → commit o rollback ejecutable

Los "mandos" (knobs) son parámetros de comportamiento reales del runner
(límite de recuperación de memoria, modo de filtrado de memoria), accedidos por
closures para no acoplar organism→world. La admisibilidad sigue el canon:

  - Xₜ ∉ safe (violación constitucional hard o barrera B_safe violada según
    ``risk_plus`` del certificado R1) → la modificación se BLOQUEA.
  - El sandbox constitucional (posterior + viabilidad) decide accepted /
    quarantined / rejected.
  - Tras aplicar, una ventana de ``post_window`` episodios vigila ΔIoC: si la
    media es negativa se REVIERTE (mandos + estado del organismo al checkpoint
    pre-modificación) y se registra rollback en el linaje.

El linaje (μₜ) deja de ser pasivo: génesis, modificaciones aceptadas y
rollbacks quedan registrados en ``LineageState`` y como eventos en storage.

Diseño para hardware modesto: cero hilos, cero deps, O(1) por episodio; en runs
sanos el controlador no hace nada (reproducibilidad de baselines intacta).
Kill-switch: ``RNFE_AUTOEVOLUTION=0``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .identity import mint_lineage_id
from .lineage import LineageState
from .self_modification import SelfModificationPipeline
from .state import OrganismState


def _enabled_by_env() -> bool:
    return os.environ.get("RNFE_AUTOEVOLUTION", "1").strip().lower() not in {"0", "false", "no", "off"}


def _risk_enforcement_enabled() -> bool:
    """R1 — ¿el freno de riesgo de cola S-I-E pasa de sombra a enforcement?

    Con ``RNFE_RISK_ENFORCEMENT=1`` el veredicto S-I-E BUFFER *por riesgo* (CVaR_α[−ΔIoC]>τ
    o Pr(ΔIoC≥0)_LCB<umbral) BLOQUEA la auto-modificación ρₜ, no solo la violación
    hard/barrera. Apagado por defecto ⇒ conducta byte-idéntica (solo sombra).
    """
    return os.environ.get("RNFE_RISK_ENFORCEMENT", "0").strip().lower() in {"1", "true", "yes", "on"}


# Criterio de RETENCIÓN: qué cantidad decide si una automodificación se conserva
# o se revierte al cerrarse la ventana post-aplicación.
#
#   "ioc"       — ΔIoC (histórico). Mide buena formación del cierre, no viabilidad.
#   "viability" — Δmargen de viabilidad respecto al momento de aplicar. Es la
#                 variable esencial de Ashby: el organismo conserva lo que lo
#                 mantuvo en la región viable.
#   "both"      — conserva solo lo que no dañó NINGUNA de las dos.
#
# Por qué existe la opción: ΔIoC es una primera diferencia de una cantidad que
# converge. Medido en este árbol, IoC se aplana a un único valor hacia el paso
# ~50 y desde ahí todo ΔIoC vale exactamente 0.0, así que `mean < 0.0` es falso
# siempre y el lazo COMMITEA toda modificación, incluso una que hunda el margen.
# El default se mantiene en "ioc" para que la conducta histórica sea idéntica.
RETENTION_SIGNALS = ("ioc", "viability", "both")


# ── Estado longitudinal del lazo (H-046) ─────────────────────────────────────
#
# El controller es EFÍMERO: lo construye el runner, y el kernel reconstruye el
# runner cada `block_size` episodios, tras cada refugio y al cambiar la clave de
# `_runner_for`. Medido en 40 pasos: 6 reconstrucciones, 3 checkpoints sanos
# perdidos, 2 ventanas post-aplicación abandonadas —propuesta aplicada, ni commit
# ni revert— y 1 cooldown perdido. El estado que sigue NO es del controller: es
# del organismo, y viaja por el mismo camino que `OrganismState` y `LineageState`
# (entra al runner al construirlo, vuelve al kernel tras cada paso, va al
# checkpoint). El controller puede morir; esto no.
#
# Clasificación de cada campo (Orientación §V): CONFIGURATION se reconstruye,
# DERIVED se recalcula, y sólo lo que sigue es LONGITUDINAL_STATE o REFERENCE.
AUTOEVOLUTION_STATE_SCHEMA = "autoevolution-state-v1"
PROPOSAL_STATUSES = (
    "proposed", "validated", "applied", "monitoring",
    "committed", "reverted", "aborted", "rejected",
)
TERMINAL_STATUSES = frozenset({"committed", "reverted", "aborted", "rejected"})
_MAX_PROPOSAL_RECORDS = 32
_MAX_TRANSITIONS_PER_RECORD = 8


@dataclass
class ProposalRecord:
    """Una propuesta ρₜ con lifecycle EXPLÍCITO.

    Invariante: toda propuesta que llega a `applied` termina en exactamente UNA de
    `committed | reverted | aborted`. Nunca cero (la ventana no puede abandonarse),
    nunca dos (`_transition` lo impide). El reloj es `episode_count` del organismo,
    que sobrevive al rebuild y al cambio de run_id.
    """

    proposal_id: str
    target: str
    description: str
    changes: Dict[str, Any]
    status: str = "proposed"
    sandbox_verdict: Optional[str] = None
    opened_at_episode: int = 0
    closed_at_episode: Optional[int] = None
    outcome_reason: Optional[str] = None
    transitions: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target": self.target,
            "description": self.description,
            "changes": dict(self.changes),
            "status": self.status,
            "sandbox_verdict": self.sandbox_verdict,
            "opened_at_episode": self.opened_at_episode,
            "closed_at_episode": self.closed_at_episode,
            "outcome_reason": self.outcome_reason,
            "transitions": [dict(t) for t in self.transitions[-_MAX_TRANSITIONS_PER_RECORD:]],
        }

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "ProposalRecord":
        status = str(data.get("status", "proposed"))
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"autoevolution_state_unknown_status: {status!r}")
        return cls(
            proposal_id=str(data["proposal_id"]),
            target=str(data.get("target", "")),
            description=str(data.get("description", "")),
            changes=dict(data.get("changes") or {}),
            status=status,
            sandbox_verdict=data.get("sandbox_verdict"),
            opened_at_episode=int(data.get("opened_at_episode", 0)),
            closed_at_episode=data.get("closed_at_episode"),
            outcome_reason=data.get("outcome_reason"),
            transitions=[dict(t) for t in (data.get("transitions") or [])],
        )


def _state_to_payload(state: Optional[OrganismState]) -> Optional[Dict[str, Any]]:
    # Mismos bytes que `runtime/life/serialization.organism_to_payload`, sin
    # importar `runtime.life` desde `runtime.organism` (la dirección es life→organism).
    return None if state is None else state.to_dict()


def _state_from_payload(data: Optional[Dict[str, Any]]) -> Optional[OrganismState]:
    return None if data is None else OrganismState.from_dict(dict(data))


class AutoEvolutionController:
    """Lazo ρₜ: observa cada episodio certificado y decide evolución/rollback."""

    def __init__(
        self,
        *,
        run_id: str,
        knob_reader: Callable[[], Dict[str, Any]],
        knob_writer: Callable[..., None],
        storage=None,
        lineage: LineageState | None = None,
        pipeline: SelfModificationPipeline | None = None,
        viability_trigger: float = 0.45,
        drift_trigger: float = 0.50,
        patience: int = 2,
        post_window: int = 3,
        cooldown: int = 4,
        retention_signal: str = "ioc",
        enabled: bool | None = None,
    ):
        self.run_id = run_id
        self.knob_reader = knob_reader
        self.knob_writer = knob_writer
        self.storage = storage
        # B41: el linaje μ_t es del ORGANISMO, no de la corrida. En el life-loop llega
        # siempre desde el runner/kernel (genoma real); el fallback standalone acuña un
        # lineage genuino vía la SSOT en vez de derivarlo del run_id efímero.
        self.lineage = lineage if lineage is not None else LineageState(lineage_id=mint_lineage_id())
        self.pipeline = pipeline or SelfModificationPipeline()
        self.viability_trigger = viability_trigger
        self.drift_trigger = drift_trigger
        self.patience = patience
        self.post_window = post_window
        self.cooldown = cooldown
        _signal = (retention_signal or "ioc").strip().lower()
        if _signal not in RETENTION_SIGNALS:
            raise ValueError(
                f"RETENTION_SIGNAL_UNKNOWN: {retention_signal!r}; "
                f"conocidas: {list(RETENTION_SIGNALS)}"
            )
        self.retention_signal = _signal
        self.enabled = _enabled_by_env() if enabled is None else enabled

        self._consecutive_degraded = 0
        self._cooldown_left = 0
        # Último estado sano conocido: (OrganismState, knobs) para rollback.
        self._checkpoint: Optional[Dict[str, Any]] = None
        # Monitor post-aplicación de una modificación activa.
        self._post_monitor: Optional[Dict[str, Any]] = None
        # Evidencia histórica E para el posterior constitucional (canon: el
        # organismo se gana el derecho a mutar acumulando episodios
        # certificados; sin evidencia, LCB(P) < τ y todo queda en cuarentena).
        self._evidence: Optional[Dict[str, int]] = None
        # Lifecycle explícito de propuestas (H-046): registro por proposal_id,
        # la única propuesta no-terminal, y los mandos que ESTE lazo escribió
        # ("fisiología adoptada"): un runner nuevo debe recibirlos, no decidirlos.
        self._proposals: List[ProposalRecord] = []
        self._active_proposal_id: Optional[str] = None
        self._adopted_knobs: Optional[Dict[str, Any]] = None

    # ── estado longitudinal: export / restore (H-046) ────────────────────────

    def export_state(self) -> Dict[str, Any]:
        """Todo lo que debe sobrevivir a la muerte de este controller, serializable."""
        monitor = None
        if self._post_monitor is not None:
            m = self._post_monitor
            monitor = {
                "proposal_id": m["proposal_id"],
                "episodes_left": int(m["episodes_left"]),
                "knob_backup": dict(m["knob_backup"]),
                "state_checkpoint": _state_to_payload(m["state_checkpoint"]),
                "deltas": [float(x) for x in m.get("deltas", [])],
                "margin_baseline": m.get("margin_baseline"),
                "margins": [float(x) for x in m.get("margins", [])],
            }
        checkpoint = None
        if self._checkpoint is not None:
            checkpoint = {
                "state": _state_to_payload(self._checkpoint["state"]),
                "knobs": dict(self._checkpoint["knobs"]),
            }
        return {
            "schema_version": AUTOEVOLUTION_STATE_SCHEMA,
            "lineage_id": self.lineage.lineage_id,
            "consecutive_degraded": int(self._consecutive_degraded),
            "cooldown_left": int(self._cooldown_left),
            "checkpoint": checkpoint,
            "post_monitor": monitor,
            "evidence": None if self._evidence is None else dict(self._evidence),
            "adopted_knobs": None if self._adopted_knobs is None else dict(self._adopted_knobs),
            "active_proposal_id": self._active_proposal_id,
            "proposals": [r.to_payload() for r in self._proposals[-_MAX_PROPOSAL_RECORDS:]],
        }

    def restore_state(self, payload: Optional[Dict[str, Any]]) -> bool:
        """Rehidrata desde `export_state()`. `None`/`{}` ⇒ controller fresco (no-op).

        Estricto a propósito: esquema desconocido o linaje ajeno ⇒ `ValueError`.
        `runtime/life/serialization.py` ya tiene dos `except: continue` que
        descartan entradas en silencio; aquí no se añade un tercero.
        """
        if not payload:
            return False
        schema = payload.get("schema_version")
        if schema != AUTOEVOLUTION_STATE_SCHEMA:
            raise ValueError(f"autoevolution_state_schema_unknown: {schema!r}")
        lineage_id = payload.get("lineage_id")
        if lineage_id != self.lineage.lineage_id:
            raise ValueError(
                f"autoevolution_state_lineage_mismatch: {lineage_id!r} != {self.lineage.lineage_id!r}"
            )
        self._consecutive_degraded = int(payload.get("consecutive_degraded", 0))
        self._cooldown_left = int(payload.get("cooldown_left", 0))
        ck = payload.get("checkpoint")
        self._checkpoint = (
            None if ck is None
            else {"state": _state_from_payload(ck.get("state")), "knobs": dict(ck.get("knobs") or {})}
        )
        m = payload.get("post_monitor")
        self._post_monitor = (
            None if m is None
            else {
                "proposal_id": m["proposal_id"],
                "episodes_left": int(m["episodes_left"]),
                "knob_backup": dict(m.get("knob_backup") or {}),
                "state_checkpoint": _state_from_payload(m.get("state_checkpoint")),
                "deltas": [float(x) for x in m.get("deltas", [])],
                "margin_baseline": m.get("margin_baseline"),
                "margins": [float(x) for x in m.get("margins", [])],
            }
        )
        ev = payload.get("evidence")
        # La evidencia viaja: NO se resiembra. El reseed por run_id (tope 64) es una
        # caché con pérdida; el organismo —no la corrida— se gana el derecho a mutar.
        self._evidence = None if ev is None else {"n": int(ev["n"]), "ok": int(ev["ok"])}
        ak = payload.get("adopted_knobs")
        self._adopted_knobs = None if ak is None else dict(ak)
        # Fisiología adoptada: los mandos que ESTE lazo escribió vuelven al runner
        # nuevo. Sin esto, `ScenarioEpisodeRunner.__init__` los deja en su literal
        # (3 / config) y una modificación commiteada se esfuma en el siguiente
        # rebuild. Un runner nuevo debe RECIBIR el mando, no decidirlo (§XVI).
        if self._adopted_knobs:
            self._write_knobs(dict(self._adopted_knobs), action="rehydrate")
        self._active_proposal_id = payload.get("active_proposal_id")
        self._proposals = [ProposalRecord.from_payload(r) for r in (payload.get("proposals") or [])]
        return True

    # ── lifecycle de propuestas ──────────────────────────────────────────────

    def _record(self, proposal_id: str) -> Optional[ProposalRecord]:
        for r in self._proposals:
            if r.proposal_id == proposal_id:
                return r
        return None

    def _open_record(self, *, proposal_id: str, target: str, description: str,
                     changes: Dict[str, Any], episode: int) -> ProposalRecord:
        rec = ProposalRecord(
            proposal_id=proposal_id, target=target, description=description,
            changes=dict(changes), opened_at_episode=int(episode),
        )
        rec.transitions.append({"status": "proposed", "episode": int(episode), "reason": None})
        self._proposals.append(rec)
        if len(self._proposals) > _MAX_PROPOSAL_RECORDS:
            del self._proposals[: len(self._proposals) - _MAX_PROPOSAL_RECORDS]
        return rec

    def _transition(self, proposal_id: str, status: str, *, episode: int,
                    reason: Optional[str] = None) -> None:
        """Una transición explícita. Terminal sobre terminal ⇒ error: exactamente una."""
        rec = self._record(proposal_id)
        if rec is None:
            return  # propuesta anterior al registro (payload legacy): nada que cerrar
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"autoevolution_state_unknown_status: {status!r}")
        if rec.status in TERMINAL_STATUSES:
            raise ValueError(
                f"proposal_already_terminal: {proposal_id} está en {rec.status!r}, "
                f"no puede pasar a {status!r}"
            )
        rec.status = status
        rec.transitions.append({"status": status, "episode": int(episode), "reason": reason})
        if status in TERMINAL_STATUSES:
            rec.closed_at_episode = int(episode)
            rec.outcome_reason = reason
            if self._active_proposal_id == proposal_id:
                self._active_proposal_id = None
        elif status in {"applied", "monitoring"}:
            self._active_proposal_id = proposal_id

    # ── helpers ──────────────────────────────────────────────────────────────

    def _write_knobs(
        self, changes: Dict[str, Any], *, action: str, proposal_id: str | None = None
    ) -> None:
        """Escribe mandos diciendo DE QUÉ acción viene (§XLII).

        El lazo escribe en cuatro momentos distintos —aplicar una propuesta,
        revertirla, rodar a un checkpoint sano, rehidratar tras un rebuild— y
        los cuatro llegaban a la autoridad como el mismo `rho_t knob change`.
        En el ledger eso los vuelve indistinguibles: un revert se leería como
        una aplicación nueva. El contexto es lo que los separa.
        """
        self.knob_writer(
            changes,
            {
                "source": f"autoevolution:{action}",
                "reason": f"rho_t {action}",
                "proposal_id": proposal_id,
            },
        )

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.storage is None:
            return
        try:
            self.storage.append_event(
                event_type=event_type,
                run_id=self.run_id,
                source="autoevolution",
                payload=payload,
            )
        except Exception:
            pass  # la evolución nunca debe tumbar el episodio por telemetría

    def _update_evidence(self, certificate_verdict: str | None) -> None:
        """Acumula evidencia (episodios totales/certificados) del run.

        La primera vez siembra desde storage (los certificados ya persistidos
        del run, incluido el del episodio actual); después incrementa.
        """
        if self._evidence is None:
            n = ok = 0
            if self.storage is not None:
                try:
                    certs = self.storage.list_episode_certificates(
                        run_id=self.run_id, limit=64
                    )
                    n = len(certs)
                    ok = sum(1 for c in certs if c.verdict == "certified")
                except Exception:
                    n = ok = 0
            self._evidence = {"n": n, "ok": ok}
            return
        if certificate_verdict is not None:
            self._evidence["n"] += 1
            if certificate_verdict == "certified":
                self._evidence["ok"] += 1

    @property
    def _evidence_params(self) -> Dict[str, Any]:
        ev = self._evidence or {"n": 0, "ok": 0}
        n = int(ev["n"])
        rate = (ev["ok"] / n) if n > 0 else None
        return {"n_historical": n, "historical_success_rate": rate}

    @staticmethod
    def _memory_pressure(episode_result: Dict[str, Any]) -> float:
        context = (episode_result.get("episode") or {}).get("context") or {}
        retrieved = context.get("retrieved_memory") or []
        return min(1.0, len(retrieved) / 5.0)

    def _diagnose(self, episode_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Elige la modificación candidata según la causa probable de degradación.

        Cada candidato mapea un target constitucional MUTABLE a un cambio
        concreto sobre mandos reales del runner.
        """
        knobs = self.knob_reader()
        pressure = self._memory_pressure(episode_result)
        limit = int(knobs.get("memory_retrieval_limit", 3))
        if pressure >= 0.4 and limit > 1:
            return {
                "target": "memory_scoring_secondary_weights",
                "description": (
                    f"reducir memory_retrieval_limit {limit}->{limit - 1} "
                    f"(presión de memoria {pressure:.2f} degrada pureza/viabilidad)"
                ),
                "changes": {"memory_retrieval_limit": limit - 1},
            }
        if knobs.get("memory_filter_mode") == "cross_scenario_analogical":
            return {
                "target": "selection_policy",
                "description": (
                    "endurecer filtrado de memoria a strict_same_scenario "
                    "(recuperación cruzada bajo degradación sostenida)"
                ),
                "changes": {"memory_filter_mode": "strict_same_scenario"},
            }
        return None

    # ── lazo principal ───────────────────────────────────────────────────────

    def observe_episode(
        self,
        *,
        organism_state: OrganismState,
        episode_result: Dict[str, Any],
        certificate_metadata: Dict[str, Any] | None = None,
        certificate_verdict: str | None = None,
    ) -> Dict[str, Any]:
        """Observa un episodio cerrado y devuelve la acción evolutiva tomada.

        El llamador (runner) debe aplicar ``restored_state`` si viene presente.
        """
        if not self.enabled:
            return {"action": "disabled"}

        self._update_evidence(certificate_verdict)

        viability = episode_result.get("viability_assessment") or {}
        constitutional = episode_result.get("constitutional_validation") or {}
        risk_plus = (certificate_metadata or {}).get("risk_plus") or {}

        margin = float(viability.get("viability_margin", 1.0))
        drift = float(organism_state.policy.accumulated_drift)
        degraded = margin < self.viability_trigger or drift > self.drift_trigger
        episode = int(organism_state.episode_count)

        # 1) Rollback duro: la constitución o el kernel lo exigen.
        if viability.get("rollback_required") or constitutional.get("verdict") == "rollback":
            return self._execute_rollback(
                reason="rollback_required"
                if viability.get("rollback_required")
                else "constitutional_rollback",
                episode=episode,
            )

        # 2) Monitor post-aplicación de una modificación activa.
        if self._post_monitor is not None:
            return self._advance_post_monitor(risk_plus=risk_plus, margin=margin, episode=episode)

        # 3) Checkpoint sano (último estado bueno conocido).
        if not degraded and constitutional.get("verdict", "valid") == "valid":
            self._consecutive_degraded = 0
            self._checkpoint = {"state": organism_state, "knobs": dict(self.knob_reader())}
            if self._cooldown_left > 0:
                self._cooldown_left -= 1
            return {"action": "none", "degraded": False}

        # 4) Degradación: acumular paciencia.
        self._consecutive_degraded += 1
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            return {"action": "none", "degraded": True, "cooldown": self._cooldown_left + 1}
        if self._consecutive_degraded < self.patience:
            return {
                "action": "none",
                "degraded": True,
                "consecutive": self._consecutive_degraded,
            }

        # 5) Gate de seguridad S-I-E (R1): Xₜ ∉ safe ⇒ no se muta.
        b_safe = risk_plus.get("b_safe") or {}
        hard_unsafe = int(risk_plus.get("hard_violation_count", 0) or 0) > 0 or bool(b_safe.get("violated"))
        # R1 enforcement (opt-in): el freno de riesgo de cola pasa de sombra a bloquear.
        # Solo cuando hay evidencia suficiente (cvar computado ⇒ n≥min_history): un BUFFER
        # por historial insuficiente NO bloquea (evita falsos positivos), como exige el gate.
        tail_risk_block = (
            _risk_enforcement_enabled()
            and risk_plus.get("sie_verdict") == "BUFFER"
            and risk_plus.get("cvar_neg_delta_ioc") is not None
        )
        if hard_unsafe or tail_risk_block:
            reason = (
                "fuera de región segura (S-I-E RECHAZAR)"
                if hard_unsafe
                else f"riesgo de cola no acotado (S-I-E BUFFER enforced): {risk_plus.get('sie_reason')}"
            )
            summary = {
                "action": "blocked",
                "reason": reason,
                "sie_verdict": risk_plus.get("sie_verdict"),
                "risk_enforced": bool(tail_risk_block and not hard_unsafe),
            }
            self._emit("autoevolution.blocked", summary)
            self._cooldown_left = self.cooldown
            return summary

        # 6) Diagnóstico → propuesta.
        candidate = self._diagnose(episode_result)
        if candidate is None:
            self._cooldown_left = self.cooldown
            return {"action": "no_candidate", "degraded": True}

        proposal = self.pipeline.generate_proposal(
            target=candidate["target"], description=candidate["description"]
        )
        self._open_record(
            proposal_id=proposal.proposal_id, target=candidate["target"],
            description=candidate["description"], changes=candidate["changes"], episode=episode,
        )
        decision = self.pipeline.evaluate_proposal(
            proposal=proposal,
            current_state=organism_state,
            **self._evidence_params,
        )
        rec = self._record(proposal.proposal_id)
        if rec is not None:
            rec.sandbox_verdict = decision.verdict

        summary: Dict[str, Any] = {
            "proposal_id": proposal.proposal_id,
            "target": candidate["target"],
            "description": candidate["description"],
            "changes": candidate["changes"],
            "sandbox_verdict": decision.verdict,
            "risk_level": decision.sandbox_result.risk_level,
            "posterior": round(
                decision.sandbox_result.posterior.constitutional_posterior, 4
            ),
            "posterior_lcb": round(
                decision.sandbox_result.posterior.lower_confidence_bound, 4
            ),
            "evidence": self._evidence_params,
            "sie_verdict": risk_plus.get("sie_verdict"),
        }

        if decision.verdict != "accepted":
            summary["action"] = decision.verdict  # quarantined | rejected
            self._transition(proposal.proposal_id, "rejected", episode=episode,
                             reason=f"sandbox:{decision.verdict}")
            self._emit("autoevolution.proposal", summary)
            self._cooldown_left = self.cooldown
            return summary
        self._transition(proposal.proposal_id, "validated", episode=episode)

        # 7) Aplicar sobre los mandos reales + monitor post-aplicación.
        knob_backup = dict(self.knob_reader())
        self._write_knobs(candidate["changes"], action="apply", proposal_id=proposal.proposal_id)
        self._adopted_knobs = {**(self._adopted_knobs or {}), **candidate["changes"]}
        self._transition(proposal.proposal_id, "applied", episode=episode)
        self.lineage.record_modification(
            modification_id=proposal.proposal_id,
            description=candidate["description"],
            posterior=decision.sandbox_result.posterior.constitutional_posterior,
            state_hash=organism_state.state_id,
            timestamp=organism_state.timestamp,
        )
        self._post_monitor = {
            "proposal_id": proposal.proposal_id,
            "episodes_left": self.post_window,
            "knob_backup": knob_backup,
            "state_checkpoint": organism_state,
            "deltas": [],
            # Línea base de la variable esencial: el margen QUE HABÍA al mutar.
            # Contra esto se compara la ventana, no contra el episodio anterior.
            "margin_baseline": margin,
            "margins": [],
        }
        self._transition(proposal.proposal_id, "monitoring", episode=episode)
        self._consecutive_degraded = 0
        summary["action"] = "applied"
        summary["generation"] = self.lineage.generation
        self._emit("autoevolution.applied", summary)
        return summary

    # ── sub-rutinas ──────────────────────────────────────────────────────────

    def _execute_rollback(self, *, reason: str, episode: int = 0) -> Dict[str, Any]:
        rollback_id = f"rb-{uuid4().hex[:8]}"
        restored_state = None
        if self._checkpoint is not None:
            self._write_knobs(
                self._checkpoint["knobs"],
                action="rollback",
                proposal_id=(self._post_monitor or {}).get("proposal_id"),
            )
            self._adopted_knobs = dict(self._checkpoint["knobs"])
            restored_state = self._checkpoint["state"]
        self.lineage.record_rollback(
            rollback_id=rollback_id,
            description=f"rollback ejecutado ({reason})",
        )
        # H-046: un rollback duro en plena ventana de monitoreo la ABORTA, y lo dice.
        # Antes `_post_monitor = None` la descartaba en silencio: una propuesta
        # APLICADA desaparecía sin commit ni revert, incluso sin ningún rebuild.
        if self._post_monitor is not None:
            pid = self._post_monitor["proposal_id"]
            self._transition(pid, "aborted", episode=episode, reason=f"hard_rollback:{reason}")
            self._emit("autoevolution.aborted", {
                "proposal_id": pid, "rollback_id": rollback_id,
                "reason": f"hard_rollback:{reason}",
            })
        self._post_monitor = None
        self._consecutive_degraded = 0
        self._cooldown_left = self.cooldown
        summary = {
            "action": "rollback",
            "rollback_id": rollback_id,
            "reason": reason,
            "checkpoint_available": restored_state is not None,
        }
        self._emit("autoevolution.rollback", summary)
        if restored_state is not None:
            return {**summary, "restored_state": restored_state}
        return summary

    def _advance_post_monitor(
        self, *, risk_plus: Dict[str, Any], margin: float | None = None, episode: int = 0
    ) -> Dict[str, Any]:
        monitor = self._post_monitor
        assert monitor is not None
        delta = risk_plus.get("delta_ioc")
        if delta is not None:
            monitor["deltas"].append(float(delta))
        if margin is not None:
            monitor.setdefault("margins", []).append(float(margin))
        monitor["episodes_left"] -= 1
        if monitor["episodes_left"] > 0:
            return {
                "action": "monitoring",
                "proposal_id": monitor["proposal_id"],
                "episodes_left": monitor["episodes_left"],
            }

        deltas = monitor["deltas"]
        mean_delta = (sum(deltas) / len(deltas)) if deltas else 0.0

        # Δviabilidad: media de la ventana MENOS el margen que había al aplicar.
        # Se promedia la ventana (y no se mira solo el extremo) porque una sola
        # lectura puede ser ruido de un episodio; el promedio responde a "durante
        # el monitoreo, ¿estuvo el organismo más viable que cuando mutó?".
        margins = monitor.get("margins") or []
        baseline = monitor.get("margin_baseline")
        mean_delta_viab = (
            (sum(margins) / len(margins)) - float(baseline)
            if margins and baseline is not None
            else None
        )
        self._post_monitor = None

        hurt_ioc = bool(deltas) and mean_delta < 0.0
        hurt_viab = mean_delta_viab is not None and mean_delta_viab < 0.0
        if self.retention_signal == "viability":
            revert, decided_by = hurt_viab, "delta_viability"
        elif self.retention_signal == "both":
            revert = hurt_ioc or hurt_viab
            decided_by = "delta_ioc" if hurt_ioc else ("delta_viability" if hurt_viab else "ninguna")
        else:  # "ioc" — criterio histórico, intacto
            revert, decided_by = hurt_ioc, "delta_ioc"

        # Traza: las DOS cantidades se reportan siempre, decida quien decida.
        medidas = {
            "retention_signal": self.retention_signal,
            "retention_decided_by": decided_by,
            "mean_delta_ioc": round(mean_delta, 6),
            "mean_delta_viability": (
                None if mean_delta_viab is None else round(mean_delta_viab, 6)
            ),
        }

        if revert:
            # La modificación empeoró lo que el criterio vigila: revertir mandos + estado.
            self._write_knobs(
                monitor["knob_backup"], action="revert", proposal_id=monitor["proposal_id"]
            )
            self._adopted_knobs = dict(monitor["knob_backup"])
            rollback_id = f"rb-{uuid4().hex[:8]}"
            self._transition(monitor["proposal_id"], "reverted", episode=episode, reason=decided_by)
            self.lineage.record_rollback(
                rollback_id=rollback_id,
                description=(
                    f"revert de {monitor['proposal_id']} por {decided_by}: ΔIoC medio "
                    f"{mean_delta:.4f}, Δviabilidad media "
                    f"{'n/d' if mean_delta_viab is None else format(mean_delta_viab, '.4f')}, "
                    f"en ventana post-aplicación"
                ),
            )
            self._cooldown_left = self.cooldown
            summary = {
                "action": "reverted",
                "proposal_id": monitor["proposal_id"],
                "rollback_id": rollback_id,
                **medidas,
            }
            self._emit("autoevolution.reverted", summary)
            return {**summary, "restored_state": monitor["state_checkpoint"]}

        self._transition(monitor["proposal_id"], "committed", episode=episode, reason=decided_by)
        summary = {
            "action": "committed",
            "proposal_id": monitor["proposal_id"],
            "generation": self.lineage.generation,
            **medidas,
        }
        self._emit("autoevolution.committed", summary)
        return summary
