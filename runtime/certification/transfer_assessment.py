"""Evaluación de transferibilidad de episodios entre escenarios.

RTCME-v2: Integra certificación Bayesiana con posterior de seguridad,
failure modes y certificate scope, manteniendo compatibilidad con v1.

Verdicts:
- certified_local: sin evidencia cross-scenario, scope=local_only
- certified_transfer_safe: LCB >= threshold, scope=compatible_transfer
- certified_analogical_only: posterior moderado, scope=analogical_hint_only
- rejected_for_transfer: posterior insuficiente o blocking failure, scope=blocked
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .failure_modes import TransferFailureMode, detect_failure_modes
from .trace_integrity import assess_trace_integrity

TransferVerdict = Literal[
    "certified_local",
    "certified_transfer_safe",
    "certified_analogical_only",
    "rejected_for_transfer",
]

# P9.6 — priores NEUTROS para la aritmética del posterior Bayesiano (que no admite None).
# NO son mediciones y NO se reportan como tales: la evidencia que los usó queda listada en
# `TransferAssessment.unmeasured_fields`. Existen porque el posterior necesita un número,
# no porque sepamos algo. Preservan exactamente los valores previos de la rama cross, así
# que ningún veredicto de transferencia cambia por P9.6.
_NEUTRAL_PURITY = 1.0
_NEUTRAL_STABILITY = 1.0
_NEUTRAL_CONFIDENCE = 0.5
_NEUTRAL_SHIFT_KL = 0.0

# ── B85 — LA PUREZA TIENE TRES ESTADOS, NO DOS ────────────────────────────────────
# La compuerta `memory_purity >= 0.85` de `is_restorable` existe para impedir que el
# organismo se refugie en un estado con memoria CONTAMINADA. Si el retrieval no devolvió
# NINGÚN hit, no hay memoria que pueda estar contaminada: ese eje no es "desconocido" ni
# es "pureza verificada en 1.0" — es NO APLICABLE.
#
#   MEASURED       hubo hits ⇒ hubo oportunidad de contaminarse ⇒ el número es evidencia
#                  GANADA. La compuerta lo evalúa.
#   NOT_APPLICABLE cero hits ⇒ no hay nada que contaminar ⇒ el eje NO APLICA. No bloquea
#                  la compuerta, pero TAMPOCO cuenta como eje verificado.
#   UNMEASURED     hubo hits pero faltan las métricas ⇒ ausencia REAL de medición ⇒ el eje
#                  se abstiene y la compuerta se CIERRA (patrón P9.5).
#
# El valor numérico del caso NOT_APPLICABLE sigue siendo 1.0 —bajarlo sería fabricar en el
# otro sentido y mataría el refugio— pero deja de venderse como una medición: viaja
# etiquetado y `runtime/life/contracts.py` lo consume como eje no aplicable.
PURITY_MEASURED = "measured"
PURITY_NOT_APPLICABLE = "not_applicable"
PURITY_UNMEASURED = "unmeasured"


def purity_not_applicable(basis: Any) -> bool:
    """¿La pureza de este certificado es NO APLICABLE (no había memoria que contaminar)?

    SSOT del predicado que consumen las compuertas (`runtime/life/vitals.py`). Acepta el
    `memory_purity_basis` tal como viaja en el certificado (dict JSON). Back-compat: los
    certificados de antes de B85 no traen `status`, pero sí `contamination_opportunity`,
    que es exactamente la misma pregunta.
    """
    if not isinstance(basis, dict):
        return False
    status = basis.get("status")
    if status is not None:
        return status == PURITY_NOT_APPLICABLE
    return basis.get("contamination_opportunity") is False


@dataclass(frozen=True)
class TransferAssessment:
    """Resultado de evaluación de transferibilidad de un episodio."""

    episode_id: str
    source_scenario: str
    target_scenario: str
    compatibility_class: str
    closure_profile: str
    memory_mode: str
    cross_scenario_evidence_used: bool
    analogical_source_present: bool
    # P9.6: `None` = NO MEDIDO. Antes eran `float` y la ausencia se rellenaba con el valor
    # más favorable (1.0), así que el certificado no podía distinguir "impecable" de
    # "no lo miré". Quien los consuma DEBE tratar el None como ausencia de evidencia
    # (ver `vitals.py` → `VitalSignsSnapshot.unverified_fields`).
    memory_purity_score: float | None
    transition_stability_score: float | None
    transfer_verdict: TransferVerdict
    # RTCME-v2 fields (optional for backward compat)
    transfer_posterior: float = 0.0
    lower_confidence_bound: float = 0.0
    certificate_scope: str = "local_only"
    canonical_scope: str = "local_safe"
    failure_mode_count: int = 0
    morphism_score: float = 0.0
    # B1: integridad de traza REALMENTE verificada (antes era constante True e
    # invisible para el llamador). `trace_integrity_reason` dice por qué.
    trace_integrity: bool = False
    trace_integrity_reason: str = "trace_missing"
    # P9.6 — las patologías dejan de ser un contador mudo e inalcanzable.
    # `failure_modes`: las detectadas, con nombre y severidad (METADATA: no gatean).
    # `failure_mode_scope`: qué familia se evaluó — `local` (episodio intra-escenario),
    #   `all` (hubo transferencia) o `none`.
    # `detector_checks_applied`: qué detectores SÍ pudieron correr. Los que no corrieron
    #   NO cuentan como aprobados (patrón `trace_integrity.checks_applied`).
    failure_modes: tuple[TransferFailureMode, ...] = ()
    failure_mode_scope: str = "none"
    detector_checks_applied: tuple[str, ...] = ()
    # P9.6 — qué NO se pudo medir en este episodio, dicho por nombre. Un certificado con
    # `unmeasured_fields` no vacío NO es un certificado de salud: es un certificado con
    # agujeros, y los agujeros están declarados.
    unmeasured_fields: tuple[str, ...] = ()
    # B85 — qué ejes NO APLICAN a este episodio. TERCER estado, distinto de los otros dos:
    # `unmeasured_fields` dice "no lo miré" (ausencia ⇒ la compuerta se cierra);
    # `not_applicable_fields` dice "no había NADA que mirar" (el eje no aplica ⇒ no bloquea,
    # pero TAMPOCO cuenta como verificado). Sin esta distinción, la pureza vacua de un
    # episodio sin memoria se leía como una medición de 1.0 — una verificación que jamás
    # ocurrió. Lo consume `runtime/life/vitals.py` → `VitalSignsSnapshot.not_applicable_axes`.
    not_applicable_fields: tuple[str, ...] = ()
    # P9.6 — CÓMO se obtuvo la pureza. Un 1.0 sobre cero hits (`contamination_opportunity:
    # False`) es ausencia de oportunidad de contaminarse, NO pureza verificada. El número no
    # cambia; su sustento se vuelve legible. B85: además lleva `status` (measured /
    # not_applicable / unmeasured).
    memory_purity_basis: dict = field(default_factory=dict)


def retrieval_metrics_from_hits(hits: Any) -> dict | None:
    """Métricas de retrieval que el episodio registró, o ``None`` si no registró ninguna.

    P9.6: ``None`` significa **NO MEDIDO** (el episodio no dejó evidencia de retrieval),
    NO "retrieval limpio". La diferencia importa: con 0 hits no hubo *oportunidad* de
    contaminarse, que no es lo mismo que haber verificado que no hubo contaminación.
    Quien consume esto debe distinguir los dos casos (ver ``memory_purity_basis``).

    El retriever (``runtime/memory/mfm_lite/retrieval.py``) adjunta el MISMO dict de
    métricas a cada hit devuelto, así que alcanza con el primero que lo traiga.
    """
    if not isinstance(hits, (list, tuple)):
        return None
    for hit in hits:
        if isinstance(hit, dict):
            metrics = hit.get("retrieval_metrics")
            if isinstance(metrics, dict):
                return dict(metrics)
    return None


def _measure_memory_purity(
    *,
    transition_vector: Any | None,
    retrieval_metrics: dict | None,
    retrieved: Any,
) -> tuple[float | None, dict]:
    """Mide la pureza de memoria Y DEJA VISIBLE CÓMO SE OBTUVO.

    P9.6 — la procedencia importa tanto como el número. Un ``memory_purity = 1.0`` calculado
    sobre CERO hits de memoria **no es lo mismo** que uno calculado sobre 50 hits sin
    contaminación: el primero es *ausencia de oportunidad de contaminarse*, no evidencia de
    pureza. Los dos valen 1.0 y los dos son honestos — pero solo uno es una verificación.

    B85 — y la salida NO es bajar el número (eso mataría el refugio) ni declararlo "no
    medido" (tampoco: no hay nada que medir). Es reconocer que el eje **NO APLICA**. Tres
    estados, no dos — ver ``PURITY_MEASURED`` / ``PURITY_NOT_APPLICABLE`` /
    ``PURITY_UNMEASURED``. El estado viaja en ``basis["status"]`` y las compuertas lo leen.

    Returns:
        ``(purity, basis)``.
        - ``purity is None`` ⇒ ``status == "unmeasured"``: hubo hits y no hay métricas.
          Ausencia REAL: la compuerta se cierra.
        - ``purity == 1.0`` con ``status == "not_applicable"``: cero hits. No hay memoria que
          pueda estar contaminada. La compuerta pasa POR NO APLICABILIDAD, y el eje NO se
          cuenta como verificado.
        - cualquier otro caso ⇒ ``status == "measured"``: el número es evidencia ganada.
    """
    hits = retrieved if isinstance(retrieved, list) else []
    hit_count = len(hits)
    cross = None
    same = None
    if retrieval_metrics:
        cross = retrieval_metrics.get("retrieved_cross_scenario_count")
        same = retrieval_metrics.get("retrieved_same_scenario_count")
    counts_present = cross is not None or same is not None
    cross_n = int(cross or 0)
    same_n = int(same or 0)
    counted = cross_n + same_n

    # ¿HUBO SIQUIERA MEMORIA QUE PUDIERA CONTAMINARSE? Esta —y no "¿tengo un número?"— es la
    # pregunta que decide si el eje aplica. Se responde con lo que haya: los hits del contexto
    # del episodio o los conteos del retriever (cualquiera de los dos > 0 ⇒ hubo memoria).
    contamination_opportunity = hit_count > 0 or counted > 0

    def _basis(source: str, status: str) -> dict:
        return {
            "source": source,
            "status": status,
            "hits": hit_count,
            "cross_scenario_hits": cross_n if counts_present else None,
            "same_scenario_hits": same_n if counts_present else None,
            "contamination_opportunity": contamination_opportunity,
        }

    # 1. NO APLICABLE — cero memoria recuperada. No hay nada que contaminar, así que no hay
    #    nada que verificar. El 1.0 se conserva (es verdadero: no hubo contaminación porque
    #    no hubo memoria), pero se declara VACUO: no es una medición y no puede consumirse
    #    como evidencia de salud. La compuerta pasará por NO APLICABILIDAD, no por un 1.0.
    if not contamination_opportunity:
        return (
            1.0,
            _basis(
                "transition_vector" if transition_vector is not None else "no_memory_retrieved",
                PURITY_NOT_APPLICABLE,
            ),
        )

    # 2. MEDIDA (grado-transferencia): el vector de transición ya midió la pureza sobre estas
    #    mismas métricas (`reality/transition_analysis`). Es la medición más rica: se usa.
    if transition_vector is not None:
        return (
            float(transition_vector.memory_purity),
            _basis("transition_vector", PURITY_MEASURED),
        )

    # 3. MEDIDA (retrieval del propio episodio): la pureza es una propiedad del retrieval de
    #    ESTE episodio, así que es medible incluso sin transición previa (primer episodio).
    #    Acá es donde sobrevive el refugio, con pureza GANADA.
    if counts_present and counted > 0:
        return (
            1.0 - (cross_n / counted),
            _basis("episode_retrieval_metrics", PURITY_MEASURED),
        )

    # 4. NO MEDIDA — hubo hits (oportunidad de contaminarse) pero el retriever no dejó
    #    conteos: no sabemos si se contaminó. Esto SÍ es ausencia de medición, y no se
    #    rellena con un 1.0 favorable: el eje se abstiene y la compuerta se cierra.
    return (None, _basis("unmeasured", PURITY_UNMEASURED))


def assess_transfer(
    *,
    episode_result: dict,
    compatibility: Any | None = None,
    retrieval_metrics: dict | None = None,
    transition_vector: Any | None = None,
    morphism: Any | None = None,
    belief_shift: Any | None = None,
    eml_concurrence: float = 0.5,
    historical_success_rate: float | None = None,
    n_historical: int = 0,
) -> TransferAssessment:
    """Evalúa transferibilidad de un episodio usando Bayesian posterior.

    RTCME-v2: When morphism and belief_shift are provided, uses
    Bayesian posterior for verdict instead of threshold rules.
    Falls back to v1 heuristics when new data is unavailable.

    Args:
        episode_result: Resultado completo del episodio.
        compatibility: Evaluación de compatibilidad (None si intra-escenario).
        retrieval_metrics: Métricas de retrieval de memoria.
        transition_vector: Vector de continuidad (None si primer episodio).
        morphism: DirectedScenarioMorphism (RTCME-v2).
        belief_shift: BeliefShift (RTCME-v2).
        eml_concurrence: EML concordance score.
        historical_success_rate: Historical success rate for this edge.
        n_historical: Number of historical observations.

    Returns:
        TransferAssessment con veredicto y posterior Bayesiano.
    """
    episode = episode_result.get("episode", {})
    episode_id = episode.get("episode_id", "unknown")
    scenario_metadata = episode.get("scenario_metadata", {})
    source_scenario = scenario_metadata.get("scenario_name", "unknown")
    closure_profile = episode.get("closure_profile", "baseline_fixed")

    # Determine target scenario and cross-scenario flags
    cross_evidence = False
    analogical_present = False
    memory_mode = "strict_same_scenario"

    context = episode.get("context", {})
    retrieved = context.get("retrieved_memory", [])
    # P9.6: si el llamador no pasó las métricas, se leen del propio episodio (el retriever las
    # adjunta a cada hit). El dato ESTÁ: no hay por qué declararlo ausente.
    if retrieval_metrics is None:
        retrieval_metrics = retrieval_metrics_from_hits(retrieved)
    if isinstance(retrieved, list):
        for hit in retrieved:
            if isinstance(hit, dict):
                if hit.get("analogical_source"):
                    analogical_present = True
                    cross_evidence = True
                metrics = hit.get("retrieval_metrics", {})
                if metrics.get("retrieved_cross_scenario_count", 0) > 0:
                    cross_evidence = True

    # Target scenario
    target_scenario = source_scenario
    if compatibility is not None:
        target_scenario = compatibility.target_scenario

    # Compatibility class
    compat_class = "equivalent"
    if compatibility is not None:
        compat_class = compatibility.compatibility_class

    # ── P9.6 paso 5 — DES-FABRICAR ───────────────────────────────────────────
    # Antes, cada evidencia ausente se rellenaba con su valor MÁS FAVORABLE:
    #     purity = 1.0; stability = 1.0; shift_kl = 0.0; policy_conf = 0.5; causal_supp = 0.5
    # Eso no era un default: era una MENTIRA con forma de medición. El certificado no podía
    # distinguir "memoria impecable" de "nunca miré la memoria", y como los detectores leían
    # esos mismos números, la ausencia de dato se volvía evidencia a favor del organismo.
    #
    # Ahora: dato medido ⇒ el número real. Dato ausente ⇒ None (AUSENCIA), registrado en
    # `unmeasured_fields`. Los detectores se abstienen ante None (no lo leen como salud ni
    # como enfermedad). Patrón: `checks_applied` (trace_integrity.py), `unmeasured_vitals`
    # (control/homeostasis/life_monitor.py), `unverified_fields` (life/contracts.py).
    unmeasured: list[str] = []
    # B85 — el tercer estado. Un eje acá NO es un agujero: es un eje sin sujeto.
    not_applicable: list[str] = []

    # Memory purity — LA PIEZA DELICADA.
    # De acá cuelga el REFUGIO del organismo: memory_purity_score → metadata del certificado
    # → vitals.py → VitalSignsSnapshot.memory_purity → is_restorable (≥0.85) →
    # checkpoints.py (`healthy`) → kernel.py (el rollback se BLOQUEA sin healthy_checkpoint).
    # Si la pureza quedara "no medida" en el episodio típico, NINGÚN checkpoint volvería a
    # marcarse sano y el organismo no podría refugiarse nunca más: cambiaríamos "acepta
    # cualquier cosa" por "no acepta nada", que es peor.
    #
    # La salida NO es fabricar: es MEDIR de verdad, y la pureza SÍ se puede medir en todo
    # episodio, porque es una propiedad del retrieval de ESTE episodio (cuánta memoria de
    # otro escenario entró), no de la transición. Dos fuentes reales, en orden:
    #   1. El transition_vector (grado-transferencia), cuando hay episodio previo.
    #   2. Las métricas de retrieval del propio episodio — disponibles SIEMPRE, incluso en
    #      el primer episodio, donde no hay transición que medir.
    # El valor honesto de un episodio limpio sigue siendo 1.0 — pero GANADO, no inventado.
    #
    # B85 — y hay un tercer estado que ni "medido" ni "no medido" capturan: NO APLICABLE.
    # Con cero hits no hay memoria que pueda estar contaminada, que es lo ÚNICO que esa
    # compuerta existe para impedir. El eje no es desconocido: no tiene sujeto. Pasa la
    # compuerta —correctamente— pero NO como un 1.0 verificado.
    purity, purity_basis = _measure_memory_purity(
        transition_vector=transition_vector,
        retrieval_metrics=retrieval_metrics,
        retrieved=retrieved,
    )
    if purity is None:
        unmeasured.append("memory_purity")
    elif purity_basis.get("status") == PURITY_NOT_APPLICABLE:
        not_applicable.append("memory_purity")

    # Transition stability: SIN episodio previo NO hay transición que medir. Acá la ausencia
    # es genuina (no hay de dónde sacarla) y no se rellena con 1.0.
    stability = transition_vector.composite_score if transition_vector is not None else None
    if stability is None:
        unmeasured.append("transition_stability")

    # Extract morphism data
    m_score = 0.0
    m_class = compat_class
    polarity_inv = False
    if morphism is not None:
        m_score = getattr(morphism, "overall_score", 0.0)
        m_class = getattr(morphism, "morphism_class", compat_class)
        op = getattr(morphism, "transport_operator", None)
        if op is not None:
            polarity_inv = getattr(op, "polarity_inversion", False)

    # Belief shift: sin prior no hay shift. `0.0` significaba "la creencia no se movió",
    # que es justo lo que NO sabemos en el primer episodio.
    shift_kl = (
        float(getattr(belief_shift, "kl_divergence_approx", 0.0))
        if belief_shift is not None
        else None
    )
    if shift_kl is None:
        unmeasured.append("belief_shift_kl")

    # Belief state: sin belief_state no hay confianza que reportar. `0.5` era un "ni sí ni
    # no" fabricado que además caía JUSTO en el umbral de `policy_drift` (< 0.50).
    policy_conf: float | None = None
    causal_supp: float | None = None
    belief_data = episode_result.get("belief_state", {})
    if belief_data and belief_data.get("posterior"):
        posterior_data = belief_data["posterior"]
        raw_policy = posterior_data.get("policy_confidence")
        raw_causal = posterior_data.get("causal_support_confidence")
        policy_conf = float(raw_policy) if raw_policy is not None else None
        causal_supp = float(raw_causal) if raw_causal is not None else None
    if policy_conf is None:
        unmeasured.append("policy_confidence")
    if causal_supp is None:
        unmeasured.append("causal_support")

    # Trace integrity — verificación REAL (B1).
    # Antes: `len(trace) > 0 if trace else True` → True en ambas ramas (constante
    # disfrazada de medición): inflaba la likelihood del posterior y volvía
    # inalcanzable el failure mode `trace_discontinuity`. Ahora se verifica
    # presencia, buena formación y continuidad contra la secuencia ejecutada.
    trace_result = assess_trace_integrity(episode)
    trace_integrity = trace_result.integral

    # ── Bayesian posterior path (RTCME-v2) ────────────────────────────────
    transfer_post = 0.0
    lcb = 0.0
    cert_scope = "local_only"
    fm_count = 0

    is_cross = source_scenario != target_scenario or cross_evidence

    if is_cross:
        from .transfer_posterior import compute_transfer_posterior

        # El posterior Bayesiano es aritmética: necesita números, no None. Cuando una
        # evidencia no se midió se le pasa un PRIOR NEUTRO explícito y nombrado — no un
        # "valor favorable" disfrazado de medición. La diferencia no es cosmética: el
        # certificado dice cuáles de estas entradas NO eran mediciones
        # (`unmeasured_fields`), así que nadie puede leer el posterior como si se hubiera
        # calculado sobre evidencia completa.
        #
        # NOTA (backlog): el camino del posterior todavía no propaga la ausencia hacia
        # `detect_failure_modes` (los detectores de la rama cross reciben los neutros y no
        # pueden abstenerse). La rama LOCAL —la que este paquete resucita— sí lo hace.
        # En la práctica, en un episodio cross la pureza SIEMPRE está medida: la evidencia
        # cross viene precisamente de hits de retrieval, que traen sus métricas.
        posterior_result = compute_transfer_posterior(
            source_scenario=source_scenario,
            target_scenario=target_scenario,
            morphism_class=m_class if morphism is not None else _compat_to_morphism_class(compat_class),
            morphism_score=m_score if morphism is not None else (compatibility.overall_score if compatibility else 0.5),
            memory_purity=purity if purity is not None else _NEUTRAL_PURITY,
            transfer_stability=stability if stability is not None else _NEUTRAL_STABILITY,
            trace_integrity=trace_integrity,
            eml_concurrence=eml_concurrence,
            polarity_inversion=polarity_inv,
            policy_confidence=policy_conf if policy_conf is not None else _NEUTRAL_CONFIDENCE,
            causal_support=causal_supp if causal_supp is not None else _NEUTRAL_CONFIDENCE,
            belief_shift_kl=shift_kl if shift_kl is not None else _NEUTRAL_SHIFT_KL,
            historical_success_rate=historical_success_rate,
            n_historical=n_historical,
        )
        transfer_post = posterior_result.transfer_posterior
        lcb = posterior_result.lower_confidence_bound
        cert_scope = posterior_result.certificate_scope

        # P9.6 (fix) — EL CERTIFICADO NO PUEDE DECLARAR QUE CHEQUEÓ LO QUE CONFIESA NO HABER
        # MEDIDO. El posterior necesita NÚMEROS, y por eso corre su aritmética sobre los
        # priores neutros DECLARADOS (arriba). Pero `posterior_result.failure_modes` venía de
        # esa MISMA corrida, así que el certificado terminaba afirmando haber chequeado
        # `belief_collapse` (sobre un `kl = 0.0` fabricado) o `morphism_failure` (sobre un
        # morfismo inexistente) mientras EL MISMO dict listaba esos campos en
        # `unmeasured_fields`. Se autocontradecía — y justo en el vocabulario que este paquete
        # inventó para impedir que la ausencia se lea como salud.
        #
        # Re-derivamos la evaluación con la evidencia REAL: `None` donde no se midió (el
        # detector se ABSTIENE) y sin modos de transferencia cuando no hay con qué evaluarlos.
        # `compatibility.overall_score` SÍ es una medición real y se usa; el `0.5` de relleno,
        # no. Los neutros están todos del lado que NO dispara, así que los modos detectados
        # son los mismos: lo único que cambia es que el certificado deja de mentir sobre qué
        # verificó. Cero cambio en el posterior, en el scope ni en el veredicto.
        detect_morphism_score = (
            m_score
            if morphism is not None
            else (compatibility.overall_score if compatibility is not None else None)
        )
        fm_assessment = detect_failure_modes(
            memory_purity=purity,
            belief_shift_kl=shift_kl,
            policy_confidence=policy_conf,
            causal_support=causal_supp,
            trace_integrity=trace_integrity,
            morphism_score=detect_morphism_score,
            polarity_inversion=polarity_inv,
            scope="all" if detect_morphism_score is not None else "local",
        )
        fm_count = len(fm_assessment.detected_modes)
        fm_scope = "all" if detect_morphism_score is not None else "local"

        # Verdict from posterior
        verdict = _verdict_from_scope(cert_scope)
    else:
        # ── Episodio LOCAL (intra-escenario) ─────────────────────────────────
        # P9.6 paso 2 — ABRIR EL GATE. Antes, esta rama era un `pass`: `detect_failure_modes`
        # solo se alcanzaba vía `compute_transfer_posterior`, que corre únicamente dentro de
        # `if is_cross:`. Es decir: en un episodio intra-escenario con memoria limpia —que es
        # DONDE EL ORGANISMO VIVE— no se evaluaba ninguna patología. Contaminación de memoria,
        # deriva de política y colapso de creencias estaban archivadas detrás de un gate de
        # TRANSFERENCIA, y por eso el organismo nunca se veía enfermo: no se miraba.
        #
        # Ahora las patologías LOCALES se evalúan igual. Lo de transferencia NO se mezcla:
        # `causal_inversion` y `morphism_failure` exigen un morfismo dirigido que en un
        # episodio local no existe — pedirlos acá sería inventar transferencia donde no hay.
        #
        # NO GATEA (decisión conservadora explícita de P9.6): el veredicto local sigue siendo
        # `certified_local` aunque se detecten patologías. Los failure modes entran al
        # certificado como METADATA, igual que antes; lo que cambia es que ahora son
        # ALCANZABLES y REALES en vez de inalcanzables. Convertirlos en compuerta es otra
        # decisión, y no es esta.
        fm_assessment = detect_failure_modes(
            memory_purity=purity,
            belief_shift_kl=shift_kl,
            policy_confidence=policy_conf,
            causal_support=causal_supp,
            trace_integrity=trace_integrity,
            morphism_score=None,      # no hay morfismo en un episodio local
            polarity_inversion=False,
            scope="local",
        )
        fm_count = len(fm_assessment.detected_modes)
        fm_scope = "local"
        verdict = "certified_local"
        cert_scope = "local_only"

    return TransferAssessment(
        episode_id=episode_id,
        source_scenario=source_scenario,
        target_scenario=target_scenario,
        compatibility_class=compat_class,
        closure_profile=closure_profile,
        memory_mode=memory_mode,
        cross_scenario_evidence_used=cross_evidence,
        analogical_source_present=analogical_present,
        memory_purity_score=round(purity, 4) if purity is not None else None,
        transition_stability_score=round(stability, 4) if stability is not None else None,
        transfer_verdict=verdict,
        transfer_posterior=round(transfer_post, 4),
        lower_confidence_bound=round(lcb, 4),
        certificate_scope=cert_scope,
        canonical_scope=_canonical_scope_from_legacy(cert_scope),
        failure_mode_count=fm_count,
        morphism_score=round(m_score, 4),
        trace_integrity=trace_integrity,
        trace_integrity_reason=trace_result.reason,
        failure_modes=fm_assessment.detected_modes,
        failure_mode_scope=fm_scope,
        detector_checks_applied=fm_assessment.checks_applied,
        unmeasured_fields=tuple(unmeasured),
        not_applicable_fields=tuple(not_applicable),
        memory_purity_basis=purity_basis,
    )


def _compat_to_morphism_class(compat_class: str) -> str:
    """Map old compatibility class to morphism class for backward compat."""
    mapping = {
        "equivalent": "isomorphic",
        "compatible": "homomorphic",
        "analogical": "analogical",
        "incompatible": "incompatible",
    }
    return mapping.get(compat_class, "analogical")


def _verdict_from_scope(scope: str) -> TransferVerdict:
    """Map certificate scope to transfer verdict."""
    scope_to_verdict = {
        "local_only": "certified_local",
        "compatible_transfer": "certified_transfer_safe",
        "analogical_hint_only": "certified_analogical_only",
        "blocked": "rejected_for_transfer",
    }
    return scope_to_verdict.get(scope, "certified_local")


def _canonical_scope_from_legacy(scope: str) -> str:
    mapping = {
        "local_only": "local_safe",
        "compatible_transfer": "transfer_safe",
        "analogical_hint_only": "quarantine_only",
        "blocked": "blocked",
    }
    return mapping.get(scope, "blocked")
