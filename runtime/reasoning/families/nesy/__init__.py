"""Familia NESY (neuro-simbólica) — coherencia símbolo↔número.

OFF (byte-idéntico): idle (stub original).
DEEP (opt-in, RNFE_NESY_DEEP / RNFE_REASONING_DEEP): puente real entre la capa
simbólica (validez DED, conclusión, refutación) y la subsimbólica/numérica
(posterior PROB, fuerza causal, recomendación). Detecta **disonancia
neuro-simbólica** y produce una confianza fusionada. Determinista.
"""

from runtime.reasoning.families import core_inference as ci
from runtime.reasoning.families import _deep_common as dc

FAMILY_ID = "NESY"


def execute(state):
    # El coordinador simbiótico usa NESY como verificador shadow de N2 aunque el
    # overlay profundo no esté en la secuencia autoritativa. Esto no agenda la
    # familia ni le concede autoridad; solo consume su computación determinista.
    symbiotic_verify = state.get("_symbiotic_n2_verify") is True
    if not ci.family_deep_enabled(FAMILY_ID) and not symbiotic_verify:
        return {
            "family": FAMILY_ID,
            "status": "idle",
            "state_delta": {},
            "confidence": 0.0,
            "cost": 0.0,
        }

    chosen = state.get("intervention")

    # Capa simbólica: ¿la deducción refuta el estado? (sin conclusión ⇒ no refuta)
    ded_conclusion = state.get("ded_conclusion")
    symbolic_ok = bool(state.get("ded_validated")) or (ded_conclusion is None)

    # Capa numérica/subsimbólica.
    cau = dc.safe_dict(state.get("cau_link"))
    prob = dc.safe_dict(state.get("prob_posterior"))
    point = dc.num(prob.get("point"), 0.5)
    numeric_support = (cau.get("helps_goal") is True) or (point >= 0.55)

    numeric_action = state.get("abd_top_intervention") or state.get("opt_intervention")
    action_agree = (numeric_action is None) or (chosen is None) or (numeric_action == chosen)

    dissonance = []
    if not symbolic_ok:
        dissonance.append("symbolic_refutation")
    if not numeric_support:
        dissonance.append("numeric_unsupport")
    if not action_agree:
        dissonance.append("symbolic_numeric_action_mismatch")

    coherent = not dissonance
    fused = dc.clamp(0.5 * (1.0 if symbolic_ok else 0.0) + 0.5 * point)
    status = "ok" if coherent else "warn"
    return {
        "family": FAMILY_ID,
        "status": status,
        "state_delta": {
            "nesy_coherent": coherent,
            "nesy_dissonance": dissonance,
            "nesy_symbolic_ok": symbolic_ok,
            "nesy_numeric_support": numeric_support,
            "nesy_fused_confidence": round(fused, 4),
        },
        "confidence": round(fused, 4),
        "cost": 0.8,
        "recommended_next_family": "PROB",
        "failure_mode": None if coherent else "neuro_symbolic_dissonance",
        "artifacts": {
            "symbolic": {"ded_validated": bool(state.get("ded_validated")), "ded_conclusion": ded_conclusion},
            "numeric": {"prob_point": point, "cau_helps_goal": cau.get("helps_goal")},
            "dissonance": dissonance,
        },
    }
