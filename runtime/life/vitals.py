"""Extraccion de signos vitales del organismo autonomo."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from runtime.certification.transfer_assessment import purity_not_applicable
from runtime.organism.lineage import LineageState
from runtime.organism.state import OrganismState

from .contracts import VitalMode, VitalSignsSnapshot


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(max(float(value), lo), hi)


def mode_for_vitals(vitals: VitalSignsSnapshot) -> VitalMode:
    if not vitals.reversible or vitals.viability_margin <= 0.05:
        return "rollback"
    if vitals.viability_margin < 0.15 or vitals.identity_continuity < 0.45:
        return "quarantine"
    if (
        vitals.viability_margin < 0.35
        or vitals.risk_score >= 0.80
        or vitals.recovery_debt >= 0.65
    ):
        return "recovery"
    if (
        vitals.resource_pressure >= 0.80
        or vitals.risk_score >= 0.60
        or vitals.continuity_score < 0.60
    ):
        return "conservative"
    return "normal"


class VitalSignsService:
    """Construye snapshots de salud viva a partir del runtime existente."""

    def __init__(self, *, storage=None):
        self.storage = storage

    def from_state(
        self,
        *,
        run_id: str,
        organism_state: OrganismState,
        lineage: LineageState,
        mode: VitalMode = "normal",
        episode_result: Dict[str, Any] | None = None,
        resource_snapshot: Dict[str, Any] | None = None,
    ) -> VitalSignsSnapshot:
        cert = self._latest_certificate(run_id=run_id, episode_result=episode_result)
        cert_meta = getattr(cert, "metadata", None) or {}
        transfer = cert_meta.get("transfer_assessment") or {}
        risk_plus = cert_meta.get("risk_plus") or {}
        omega = cert_meta.get("omega") or {}

        # ── P9.6 paso 5 — LA SEGUNDA FABRICACIÓN ─────────────────────────────
        # Aunque `transfer_assessment` deje de emitir la clave, ESTA CAPA la reinventaba por
        # su cuenta: `continuity` default 1.0 y `memory_purity` default 1.0. Dos mentiras
        # independientes, cada una capaz de sostener la ilusión sola.
        #
        # Ahora, cuando el dato no existe, el eje se marca NO VERIFICADO (patrón B73 ya en
        # el contrato: `VitalSignsSnapshot.unverified_fields`). El relleno se conserva —para
        # no mentir en el otro sentido, "el organismo agoniza"— pero NINGUNA COMPUERTA puede
        # apoyarse en él: `is_restorable` / `is_stable` se abstienen ante un eje no
        # verificado. Ausencia de dato NO es salud.
        unverified: set[str] = set()
        # B85 — el TERCER estado. Hasta ahora `memory_purity_basis` VIAJABA con el certificado
        # y NINGUNA compuerta lo leía (cero consumidores de producción): la etiqueta existía,
        # pero la compuerta seguía consumiendo el 1.0 vacuo como si fuera evidencia. Acá se
        # empieza a leer.
        not_applicable: set[str] = set()

        # Sin certificado (bootstrap: el organismo todavía no vivió un episodio) no hay
        # NINGUNA medición de continuidad. Nótese que ya hoy el refugio estaba cerrado en ese
        # caso —`risk` cae a 1.0 y `is_restorable` exige < 0.50—, así que marcarlo no le quita
        # al organismo ningún refugio que antes tuviera: solo dice la verdad de por qué.
        if cert is None:
            unverified.add("continuity_score")
        continuity = _as_float(getattr(cert, "continuity_score", None), 1.0)
        ioc = _as_float(getattr(cert, "ioc_proxy", None), 0.0)
        risk = _as_float(getattr(cert, "risk_score", None), 1.0 - ioc)
        certified = getattr(cert, "verdict", None) == "certified"

        viability = episode_result.get("viability_assessment") if episode_result else None
        viability_margin = _as_float(
            (viability or {}).get("viability_margin"),
            organism_state.viability.viability_margin,
        )
        recovery_debt = _as_float(organism_state.viability.recovery_debt, 0.0)
        accumulated_drift = _as_float(organism_state.policy.accumulated_drift, 0.0)
        # LA PIEZA DE LA QUE CUELGA EL REFUGIO:
        #   memory_purity → is_restorable (≥0.85) → checkpoints.py (`healthy`) →
        #   kernel.py:530 (el rollback se BLOQUEA sin `healthy_checkpoint` en la evidencia).
        # Fabricar un 1.0 acá hacía que CUALQUIER checkpoint se declarara refugio válido.
        # Pero marcarlo "no verificado" cuando SÍ se puede medir dejaría al organismo sin
        # refugio ninguno — peor todavía. Por eso el paso 1 cableó la medición: en el camino
        # vivo `memory_purity_score` ahora viene MEDIDO en todo episodio (del retrieval del
        # propio episodio), así que el refugio sobrevive con pureza ganada, no regalada.
        # Si aun así falta (certificado viejo, o pre-P9.6): AUSENCIA, no 1.0.
        #
        # B85 — y hay un tercer caso que ni "medida" ni "ausente" describen. Si el episodio no
        # recuperó NINGÚN hit, no hay memoria que pueda estar contaminada — que es lo único
        # que esa compuerta existe para impedir. El eje NO APLICA: no bloquea el refugio
        # (correcto: no hay nada que impedir) pero tampoco es una pureza verificada. El
        # certificado ya lo dice (`not_applicable_fields` / `memory_purity_basis`); acá se LEE.
        purity_basis = transfer.get("memory_purity_basis") or {}
        declared_na = transfer.get("not_applicable_fields") or ()
        raw_purity = transfer.get("memory_purity_score")
        if raw_purity is None:
            unverified.add("memory_purity")
        elif "memory_purity" in declared_na or purity_not_applicable(purity_basis):
            # `purity_not_applicable` es la SSOT del predicado (incluye el back-compat con
            # `contamination_opportunity` para certificados pre-B85). ANTES esta compuerta
            # REIMPLEMENTABA el predicado inline y las dos versiones YA DIVERGÍAN: la SSOT
            # prioriza `status`, la copia lo ignoraba. Con un basis
            # {"status": "measured", "contamination_opportunity": False} la SSOT decía "sí
            # aplica" y la compuerta decía "no aplica" — la deriva exacta que una SSOT existe
            # para impedir. Y era, además, el mismo pecado que B85 vino a matar: una
            # capacidad declarada que ninguna compuerta consumía.
            not_applicable.add("memory_purity")
        memory_purity = _as_float(raw_purity, 1.0)
        resource_pressure = _as_float(
            (risk_plus.get("b_safe") or {}).get("pressure"),
            0.0,
        )
        if resource_pressure <= 0.0:
            resource_pressure = _as_float((episode_result or {}).get("resource_pressure"), 0.0)
        # Sensado real de host/GPU (opt-in): domina cuando está presente.
        if resource_snapshot:
            sensed = _as_float(resource_snapshot.get("hardware_pressure"), 0.0)
            if sensed > 0.0:
                resource_pressure = max(resource_pressure, sensed)

        reward = episode_result.get("reasoning_reward") if episode_result else None
        reward_scalar = _as_float((reward or {}).get("reward"), 0.0)
        prob_lcb = self._prob_lcb(episode_result or {})
        cognitive_quality = _clamp(
            0.45 * ioc
            + 0.25 * continuity
            + 0.20 * prob_lcb
            + 0.10 * _clamp((reward_scalar + 1.0) / 2.0)
        )
        identity_continuity = _clamp(0.50 * continuity + 0.50 * lineage.consistency_score())
        reversible = bool((viability or {}).get("rollback_required") is not True)
        if cert is not None:
            reversible = reversible and bool(getattr(cert, "rollback_ready", True))

        draft = VitalSignsSnapshot(
            run_id=run_id,
            episode_count=int(organism_state.episode_count),
            mode=mode,
            viability_margin=round(_clamp(viability_margin), 4),
            continuity_score=round(_clamp(continuity), 4),
            ioc_proxy=round(_clamp(ioc), 4),
            risk_score=round(_clamp(risk), 4),
            memory_purity=round(_clamp(memory_purity), 4),
            cognitive_quality=round(_clamp(cognitive_quality), 4),
            resource_pressure=round(_clamp(resource_pressure), 4),
            recovery_debt=round(_clamp(recovery_debt), 4),
            accumulated_drift=round(_clamp(accumulated_drift), 4),
            reversible=reversible,
            identity_continuity=round(_clamp(identity_continuity), 4),
            certified=bool(certified),
            metadata={
                "certificate_id": getattr(cert, "certificate_id", None),
                "episode_id": getattr(cert, "episode_id", None),
                "sie_verdict": risk_plus.get("sie_verdict"),
                "delta_ioc": risk_plus.get("delta_ioc"),
                "omega_delta_ioc_star": omega.get("delta_ioc_star"),
                # P9.6: la procedencia de la pureza viaja con los vitales. Un 1.0 con
                # `contamination_opportunity: False` es un 1.0 vacuo (no hubo memoria que
                # pudiera contaminar), no una pureza verificada.
                "memory_purity_basis": purity_basis if isinstance(purity_basis, dict) else {},
            },
            unverified_fields=frozenset(unverified),
            not_applicable_axes=frozenset(not_applicable),
        )
        # `replace` (y no `VitalSignsSnapshot(**draft.to_dict())`): `to_dict()` serializa
        # `unverified_fields` como lista ordenada —o la omite si está vacía—, así que
        # reconstruir desde ahí metería una list donde el contrato declara frozenset y, peor,
        # PERDERÍA la no-verificación al re-serializar. La ausencia tiene que sobrevivir el
        # viaje: es justamente lo que no puede lavarse.
        return replace(draft, mode=mode_for_vitals(draft))

    def bootstrap(
        self,
        *,
        run_id: str,
        organism_state: OrganismState,
        lineage: LineageState,
        resource_snapshot: Dict[str, Any] | None = None,
    ) -> VitalSignsSnapshot:
        return self.from_state(
            run_id=run_id,
            organism_state=organism_state,
            lineage=lineage,
            mode="normal",
            episode_result=None,
            resource_snapshot=resource_snapshot,
        )

    def _latest_certificate(self, *, run_id: str, episode_result: Dict[str, Any] | None):
        cert_id = ((episode_result or {}).get("certification") or {}).get("certificate_id")
        if self.storage is None:
            return None
        try:
            if cert_id:
                cert = self.storage.get_episode_certificate(certificate_id=cert_id)
                if cert is not None:
                    return cert
            certs = self.storage.list_episode_certificates(run_id=run_id, limit=1)
            return certs[0] if certs else None
        except Exception:
            return None

    @staticmethod
    def _prob_lcb(episode_result: Dict[str, Any]) -> float:
        state = ((episode_result.get("reasoning") or {}).get("state") or {})
        posterior = state.get("prob_posterior") or {}
        return _clamp(_as_float(posterior.get("lower_confidence_bound"), 0.5))
