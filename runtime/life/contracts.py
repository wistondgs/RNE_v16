"""Contratos publicos del Life Kernel RNFE.

Estos tipos son deliberadamente pequenos y JSON-friendly: el runtime vivo los
usa para dejar evidencia auditable sin requerir migraciones de schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Literal
from uuid import uuid4

from runtime.storage.records import utc_now_iso


GoalKind = Literal[
    "survival",
    "continuity",
    "risk_reduction",
    "cognitive_gain",
    "exploration",
    "memory_maintenance",
]
GoalStatus = Literal["active", "satisfied", "paused", "failed"]
AutonomyAction = Literal[
    "act",
    "observe",
    "explore",
    "consult_external",
    "self_modify",
    "rollback",
    "quarantine",
    "sleep",
    "shutdown",
]
VitalMode = Literal[
    "normal",
    "conservative",
    "recovery",
    "quarantine",
    "rollback",
    "shutdown_safe",
]
EvolutionProposalStatus = Literal[
    "proposed",
    "sandboxed",
    "shadowing",
    "accepted",
    "committed",
    "reverted",
    "rejected",
]

# B73 — ejes que cada compuerta de salud NECESITA para poder pronunciarse.
# Si uno de estos ejes no viene en el payload, NO se puede evaluar: el estado queda
# NO VERIFICADO en ese eje (ver ``VitalSignsSnapshot.unverified_fields``), y la
# compuerta se cierra. Ausencia de dato NO es salud.
RESTORE_REQUIRED_AXES: tuple[str, ...] = (
    "reversible",
    "viability_margin",
    "continuity_score",
    "risk_score",
    "memory_purity",
)
STABILITY_REQUIRED_AXES: tuple[str, ...] = (
    "certified",
    "viability_margin",
    "continuity_score",
    "risk_score",
    "memory_purity",
)
# Union: los ejes cuya AUSENCIA rastreamos al deserializar. Deliberadamente acotado a
# los que gobiernan una compuerta (no se marca todo campo faltante: los demás no deciden
# nada y marcarlos sería ruido).
GATED_AXES: tuple[str, ...] = (
    "viability_margin",
    "continuity_score",
    "risk_score",
    "memory_purity",
    "reversible",
    "certified",
)

# ── B85 — el TERCER estado de un eje: NO APLICABLE ────────────────────────────────
# Un eje puede estar MEDIDO (hay evidencia), NO VERIFICADO (falta la evidencia ⇒ la
# compuerta se CIERRA, B73) o NO APLICABLE (no hay SUJETO que medir ⇒ la compuerta no
# tiene nada que impedir y pasa, pero el eje NO cuenta como verificado).
#
# El caso vivo: `memory_purity >= 0.85` existe para impedir que el organismo se refugie en
# un estado con memoria CONTAMINADA. Si el episodio no recuperó NINGÚN hit, no hay memoria
# que pueda estar contaminada. `transfer_assessment` reportaba un `memory_purity = 1.0` y la
# compuerta lo consumía como evidencia: una MEDICIÓN QUE NUNCA SE HIZO. Pasar era correcto;
# decir "pureza verificada 1.0" era mentira.
#
# LISTA BLANCA, y es una PROPIEDAD DE SEGURIDAD, no burocracia: solo un eje cuyo sujeto puede
# estar genuinamente ausente puede declararse no aplicable. Sin este cerrojo, un payload
# corrupto o adversario podría declarar `reversible`/`risk_score` "no aplicables" y VACIAR la
# compuerta del refugio — pasar por no tener nada que chequear. `memory_purity` es el único
# eje cuyo sujeto (la memoria recuperada) puede simplemente no existir; la viabilidad, el
# riesgo, la continuidad y la reversibilidad SIEMPRE tienen sujeto: el organismo mismo.
NOT_APPLICABLE_ELIGIBLE_AXES: frozenset[str] = frozenset({"memory_purity"})

VITALS_UNVERIFIED = "vitals_unverified"
VITALS_BELOW_THRESHOLD = "vitals_below_threshold"
VITALS_OK = "ok"


@dataclass(frozen=True, slots=True)
class GoalState:
    """Objetivo interno persistente del organismo."""

    goal_id: str
    kind: GoalKind
    priority: float
    horizon_episodes: int
    success_metric: str
    risk_budget: float
    status: GoalStatus = "active"
    progress: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        kind: GoalKind,
        priority: float,
        horizon_episodes: int,
        success_metric: str,
        risk_budget: float,
        metadata: Dict[str, Any] | None = None,
    ) -> "GoalState":
        return cls(
            goal_id=f"goal-{kind}-{uuid4().hex[:10]}",
            kind=kind,
            priority=float(priority),
            horizon_episodes=int(horizon_episodes),
            success_metric=success_metric,
            risk_budget=float(risk_budget),
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "GoalState":
        return cls(
            goal_id=str(payload.get("goal_id") or f"goal-restored-{uuid4().hex[:10]}"),
            kind=payload.get("kind", "survival"),
            priority=float(payload.get("priority", 1.0)),
            horizon_episodes=int(payload.get("horizon_episodes", 1)),
            success_metric=str(payload.get("success_metric", "")),
            risk_budget=float(payload.get("risk_budget", 0.5)),
            status=payload.get("status", "active"),
            progress=float(payload.get("progress", 0.0)),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class AutonomyDecision:
    """Decision soberana de alto nivel para un ciclo vital."""

    action: AutonomyAction
    mode: VitalMode
    reason: str
    priority: float = 0.5
    scenario: str | None = None
    external_input: float | None = None
    directives: Dict[str, Any] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: f"dec-{uuid4().hex[:12]}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvolutionProposalV2:
    """Mutacion versionada, auditable y reversible."""

    proposal_id: str
    target: str
    semantic_diff: Dict[str, Any]
    sandbox_result: Dict[str, Any]
    shadow_evidence: Dict[str, Any]
    rollback_plan: Dict[str, Any]
    certificate: Dict[str, Any]
    status: EvolutionProposalStatus = "proposed"
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        target: str,
        semantic_diff: Dict[str, Any],
        rollback_plan: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> "EvolutionProposalV2":
        return cls(
            proposal_id=f"evo2-{uuid4().hex[:12]}",
            target=target,
            semantic_diff=dict(semantic_diff),
            sandbox_result={},
            shadow_evidence={},
            rollback_plan=dict(rollback_plan),
            certificate={},
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VitalSignsSnapshot:
    """Snapshot compacto de salud viva y autonomia operacional."""

    run_id: str
    episode_count: int
    mode: VitalMode
    viability_margin: float
    continuity_score: float
    ioc_proxy: float
    risk_score: float
    memory_purity: float
    cognitive_quality: float
    resource_pressure: float
    recovery_debt: float
    accumulated_drift: float
    reversible: bool
    identity_continuity: float
    certified: bool
    snapshot_id: str = field(default_factory=lambda: f"vital-{uuid4().hex[:12]}")
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # B73: ejes que este snapshot NO pudo verificar (venían ausentes del payload del que
    # se deserializó). Vacío = todo medido, que es el caso de un snapshot construido en
    # vivo por `VitalsService`. NO es "salud pésima": es "no hay dato" — los campos
    # conservan su valor de relleno, pero ninguna compuerta puede apoyarse en ellos.
    unverified_fields: frozenset[str] = frozenset()
    # B85: ejes que NO APLICAN a este estado — no hay sujeto que medir (p. ej. `memory_purity`
    # en un episodio que no recuperó NINGÚN hit: no hay memoria que pueda estar contaminada).
    # NO es lo mismo que `unverified_fields` (ahí falta el dato y la compuerta se cierra) ni
    # que un eje medido (ahí el número es evidencia). Un eje no aplicable NO bloquea la
    # compuerta, pero TAMPOCO se cuenta como verificado: ver `restorability_report()`.
    not_applicable_axes: frozenset[str] = frozenset()

    def _restore_axis_ok(self, axis: str) -> bool:
        """Umbral de refugio de UN eje (fuente única de verdad de los umbrales E5)."""
        if axis == "reversible":
            return bool(self.reversible)
        if axis == "viability_margin":
            return self.viability_margin >= 0.55
        if axis == "continuity_score":
            return self.continuity_score >= 0.75
        if axis == "risk_score":
            return self.risk_score < 0.50
        if axis == "memory_purity":
            return self.memory_purity >= 0.85
        return False

    def _stability_axis_ok(self, axis: str) -> bool:
        """Umbral de estabilidad de UN eje (fuente única de verdad de `is_stable`)."""
        if axis == "certified":
            return bool(self.certified)
        if axis == "viability_margin":
            return self.viability_margin >= 0.45
        if axis == "continuity_score":
            return self.continuity_score >= 0.60
        if axis == "risk_score":
            return self.risk_score < 0.60
        if axis == "memory_purity":
            return self.memory_purity >= 0.75
        return False

    @property
    def unverified_restore_axes(self) -> tuple[str, ...]:
        """Ejes que el refugio necesita y este snapshot no pudo verificar."""
        return tuple(a for a in RESTORE_REQUIRED_AXES if a in self.unverified_fields)

    @property
    def unverified_stability_axes(self) -> tuple[str, ...]:
        """Ejes que la estabilidad necesita y este snapshot no pudo verificar."""
        return tuple(a for a in STABILITY_REQUIRED_AXES if a in self.unverified_fields)

    def _not_applicable(self, required_axes: tuple[str, ...]) -> tuple[str, ...]:
        """Ejes de `required_axes` que NO APLICAN a este estado (B85).

        Tres cerrojos, y ninguno es decorativo:
        1. Solo ejes de la LISTA BLANCA (`NOT_APPLICABLE_ELIGIBLE_AXES`): nadie puede vaciar
           la compuerta declarando "no aplica" sobre `reversible` o `risk_score`.
        2. La NO VERIFICACIÓN GANA: un eje ausente del payload (B73) no puede reciclarse como
           "no aplicable" — la ausencia de dato cierra la compuerta y eso no se negocia.
        3. Aun así, siempre queda al menos un eje real por chequear: la lista blanca tiene un
           solo eje y el refugio exige cinco.
        """
        return tuple(
            a
            for a in required_axes
            if a in self.not_applicable_axes
            and a in NOT_APPLICABLE_ELIGIBLE_AXES
            and a not in self.unverified_fields
        )

    @property
    def not_applicable_restore_axes(self) -> tuple[str, ...]:
        """Ejes del refugio que no aplican a este estado (sin sujeto que medir)."""
        return self._not_applicable(RESTORE_REQUIRED_AXES)

    @property
    def not_applicable_stability_axes(self) -> tuple[str, ...]:
        """Ejes de la estabilidad que no aplican a este estado."""
        return self._not_applicable(STABILITY_REQUIRED_AXES)

    @property
    def is_stable(self) -> bool:
        """Estado estable y CERTIFICADO.

        B73: si algún eje que la estabilidad necesita no se pudo verificar, se ABSTIENE
        (False) en vez de evaluarse contra el relleno. Antes el agujero estaba tapado por
        casualidad — el default de `certified` era `False` —, pero un payload que trajera
        `certified: true` y nada más se declaraba estable con los cuatro ejes de salud
        FABRICADOS en su óptimo. La razón vive en `unverified_stability_axes`.
        """
        if self.unverified_stability_axes:
            return False
        skip = set(self.not_applicable_stability_axes)
        return all(
            self._stability_axis_ok(axis)
            for axis in STABILITY_REQUIRED_AXES
            if axis not in skip
        )

    @property
    def is_restorable(self) -> bool:
        """Estado sano y REVERSIBLE al que es seguro rodar atrás (refugio E5).

        A diferencia de ``is_stable``, NO exige la certificación formal del episodio
        (``certified``): en vida real las certificaciones suelen quedar ``rejected``
        por closure/trace, de modo que ``is_stable`` es inalcanzable y el organismo
        nunca acumula un refugio — el callejón sin salida que dejó a aeon-01 atascado
        en cuarentena sin a dónde volver. Para el refugio lo que importa es la salud
        genuina: viabilidad, continuidad, riesgo acotado, memoria pura y REVERSIBILIDAD.
        Umbrales de salud MÁS estrictos que ``is_stable`` para compensar la ausencia
        del sello de certificación: solo un estado realmente bueno sirve de refugio.

        B73 — ESTO ES UNA COMPUERTA, NO UN DETECTOR: acá la acción peligrosa es ACEPTAR
        basura, así que dato ausente ⇒ NO restaurable. Si algún eje quedó NO VERIFICADO
        (payload truncado/corrupto/ajeno), la compuerta se cierra sin mirar el relleno:
        antes, `from_dict({})` fabricaba salud perfecta en los cinco ejes y un checkpoint
        vacío se declaraba refugio válido. El motivo nunca es mudo: ver
        `unverified_restore_axes` y `restorability_report()`.

        B85 — TRES estados, no dos. Un eje NO APLICABLE (sin sujeto que medir: `memory_purity`
        cuando el episodio no recuperó ni un hit ⇒ no hay memoria que pueda estar contaminada)
        no bloquea la compuerta —correctamente: no hay nada que impedir— pero TAMPOCO se
        cuenta como verificado. El comportamiento no cambia; la afirmación sí: el refugio pasa
        por NO APLICABILIDAD, no por una medición de 1.0 que nunca se hizo.
        """
        if self.unverified_restore_axes:
            return False
        skip = set(self.not_applicable_restore_axes)
        return all(
            self._restore_axis_ok(axis)
            for axis in RESTORE_REQUIRED_AXES
            if axis not in skip
        )

    def _not_applicable_reason(self, axis: str) -> str:
        """POR QUÉ un eje no aplica, en castellano y con la evidencia a la vista."""
        if axis == "memory_purity":
            basis = self.metadata.get("memory_purity_basis") or {}
            hits = basis.get("hits", 0) if isinstance(basis, dict) else 0
            return f"no aplica (no había memoria que contaminar: hits={hits or 0})"
        return "no aplica (el eje no tiene sujeto en este estado)"

    def restorability_report(self) -> Dict[str, Any]:
        """Por qué este estado sirve —o no— de refugio. Un `False` no puede ser mudo.

        Sigue el patrón de `checks_applied` (runtime/certification/trace_integrity.py):
        los ejes que no se pudieron verificar NO cuentan como aprobados; simplemente no
        corrieron, y se dicen por nombre.

        B85 — y un eje NO APLICABLE tampoco cuenta como aprobado: no corrió porque no tenía
        nada que chequear. Va en `not_applicable_axes` (con su motivo), NO en
        `checks_applied`. Así el informe puede decir "memory_purity: no aplica (no había
        memoria que contaminar)" en vez de "memory_purity: 1.0 ✓" — que era una verificación
        inventada.
        """
        unverified = self.unverified_restore_axes
        not_applicable = self.not_applicable_restore_axes
        checks_applied = tuple(
            a
            for a in RESTORE_REQUIRED_AXES
            if a not in self.unverified_fields and a not in not_applicable
        )
        failed = tuple(a for a in checks_applied if not self._restore_axis_ok(a))
        if unverified:
            reason = VITALS_UNVERIFIED
        elif failed:
            reason = VITALS_BELOW_THRESHOLD
        else:
            reason = VITALS_OK
        return {
            "restorable": self.is_restorable,
            "reason": reason,
            "checks_applied": list(checks_applied),
            "unverified_axes": list(unverified),
            "not_applicable_axes": list(not_applicable),
            "not_applicable_reasons": {
                axis: self._not_applicable_reason(axis) for axis in not_applicable
            },
            "failed_axes": list(failed),
        }

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        # B73: la no-verificación viaja CON el estado (si no, un snapshot no verificado
        # se "lavaría" al re-serializarse: todos los campos presentes con su relleno).
        # Se omite cuando está vacío ⇒ el payload de un checkpoint sano queda BYTE POR
        # BYTE igual que antes de B73, y no se cuela un frozenset en la ruta JSON.
        unverified = payload.pop("unverified_fields", None) or frozenset()
        if unverified:
            payload["unverified_fields"] = sorted(unverified)
        # B85: ídem para la NO APLICABILIDAD. Si no viajara, el checkpoint de un episodio sin
        # memoria se releería con `memory_purity: 1.0` a secas y volvería a leerse como una
        # pureza VERIFICADA — la mentira que este paquete vino a matar, resucitada por la
        # serialización. Se omite si está vacío ⇒ el payload de un snapshot con memoria queda
        # byte por byte igual que antes de B85.
        not_applicable = payload.pop("not_applicable_axes", None) or frozenset()
        if not_applicable:
            payload["not_applicable_axes"] = sorted(not_applicable)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "VitalSignsSnapshot":
        """Deserializa vitales SIN fabricar verificación.

        B73: `to_dict()` es `asdict()` — escribe SIEMPRE los 18 campos. Por lo tanto un
        payload al que le falte un eje NO puede ser un checkpoint legítimo: es truncado,
        corrupto o de otra fuente. Los rellenos se conservan (para no mentir en el otro
        sentido, "el organismo agoniza"), pero cada eje ausente queda anotado en
        `unverified_fields` y las compuertas (`is_restorable`, `is_stable`) se cierran.
        """
        # Ausente = clave faltante O `null` explícito (JSON null tampoco es una medición).
        # Normalizarlo acá también cierra un crash latente: antes, un payload con
        # `"memory_purity": null` reventaba en `float(None)` en vez de restaurar.
        payload = {k: v for k, v in (payload or {}).items() if v is not None}
        unverified = {axis for axis in GATED_AXES if axis not in payload}
        # Anti-lavado: si el payload ya venía declarando ejes no verificados, se respetan.
        declared = payload.get("unverified_fields") or ()
        if isinstance(declared, (list, tuple, set, frozenset)):
            unverified.update(str(axis) for axis in declared)
        # B85: la NO APLICABILIDAD también sobrevive el viaje — pero filtrada por la lista
        # blanca (`_not_applicable`), así que un payload que declare "reversible: no aplica"
        # NO puede vaciar la compuerta del refugio. Y la ausencia gana sobre la no
        # aplicabilidad: un eje que falta del payload sigue siendo NO VERIFICADO.
        declared_na = payload.get("not_applicable_axes") or ()
        not_applicable: set[str] = set()
        if isinstance(declared_na, (list, tuple, set, frozenset)):
            not_applicable.update(str(axis) for axis in declared_na)
        # B85 (endurecimiento) — EL ARCHIVO NO SE CONFÍA. Es el mismo modelo de amenaza que
        # la compuerta de refugio (P9.5: `metadata["healthy"]` es un índice, no una prueba).
        # Una NO APLICABILIDAD **auto-declarada** se DESCARTA si la evidencia que viaja en el
        # MISMO snapshot la contradice: si el basis dice que sí hubo memoria que pudiera
        # contaminarse (`hits > 0` o `contamination_opportunity: True`), entonces el eje SÍ
        # aplica — y aceptar la etiqueta sería dejar que un payload se **compre la compuerta
        # declarándose exento**. La etiqueta no puede valer más que la evidencia que la
        # acompaña.
        meta = payload.get("metadata")
        basis = meta.get("memory_purity_basis") if isinstance(meta, dict) else None
        if "memory_purity" in not_applicable and isinstance(basis, dict):
            hits = basis.get("hits")
            had_opportunity = basis.get("contamination_opportunity") is True or (
                isinstance(hits, (int, float))
                and not isinstance(hits, bool)
                and hits > 0
            )
            if had_opportunity:
                not_applicable.discard("memory_purity")
        return cls(
            run_id=str(payload.get("run_id") or "unknown"),
            episode_count=int(payload.get("episode_count", 0)),
            mode=payload.get("mode", "normal"),
            viability_margin=float(payload.get("viability_margin", 1.0)),
            continuity_score=float(payload.get("continuity_score", 1.0)),
            ioc_proxy=float(payload.get("ioc_proxy", 0.0)),
            risk_score=float(payload.get("risk_score", 0.0)),
            memory_purity=float(payload.get("memory_purity", 1.0)),
            cognitive_quality=float(payload.get("cognitive_quality", 0.5)),
            resource_pressure=float(payload.get("resource_pressure", 0.0)),
            recovery_debt=float(payload.get("recovery_debt", 0.0)),
            accumulated_drift=float(payload.get("accumulated_drift", 0.0)),
            reversible=bool(payload.get("reversible", True)),
            identity_continuity=float(payload.get("identity_continuity", 1.0)),
            certified=bool(payload.get("certified", False)),
            snapshot_id=str(payload.get("snapshot_id") or f"vital-{uuid4().hex[:12]}"),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            metadata=dict(payload.get("metadata") or {}),
            unverified_fields=frozenset(unverified),
            not_applicable_axes=frozenset(not_applicable),
        )


@dataclass(frozen=True, slots=True)
class RestoredIdentity:
    """Identidad viva restaurada desde el ultimo checkpoint.

    B41: separa los tres ejes. ``run_id`` es el de la corrida bajo la que se guardó
    el checkpoint (queda como ``run_id`` ANTERIOR en la genealogía de corridas);
    ``organism_id`` es el genoma persistente que el kernel adopta como clave (con
    fallback legado ``organism_id := run_id``); ``lineage_id`` es el linaje μ_t.
    """

    run_id: str
    organism_state: Any
    lineage: Any
    goals: list[GoalState]
    vital_signs: VitalSignsSnapshot | None
    total_steps: int
    scenario_index: int
    checkpoint_payload: Dict[str, Any]
    checkpoint_artifact_id: str | None = None
    organism_id: str = ""
    lineage_id: str = ""


@dataclass(frozen=True, slots=True)
class LifeStepResult:
    """Resultado de un ciclo vital del Life Kernel."""

    run_id: str
    step_index: int
    decision: AutonomyDecision
    vital_signs: VitalSignsSnapshot
    goals: list[GoalState]
    episode_result: Dict[str, Any] | None
    checkpoint_artifact_id: str | None
    msrc: Dict[str, Any] = field(default_factory=dict)
    operational: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_index": self.step_index,
            "decision": self.decision.to_dict(),
            "vital_signs": self.vital_signs.to_dict(),
            "goals": [goal.to_dict() for goal in self.goals],
            "episode_result": self.episode_result,
            "checkpoint_artifact_id": self.checkpoint_artifact_id,
            "msrc": dict(self.msrc),
            "operational": dict(self.operational),
        }
