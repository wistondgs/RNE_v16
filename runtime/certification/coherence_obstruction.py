"""Ωₜ: obstrucción de coherencia multi-contexto (canon RNFE f2.4 §4).

El IoC clásico mide cierre *local* por episodio; un sistema puede puntuar alto
localmente mientras deriva semánticamente a escala global. El canon define

    Ωₜ = Σ_{i~j} ( d_S(r_ij·σᵢ, σⱼ) + d_F(r_ij·fᵢ, fⱼ) + d_W(r_ij·wᵢ, wⱼ) )
         + λ_◯·|Φ_{M→S}·Φ_{F→M}·Φ_{S→F} − I|
    IoC*ₜ = IoCₜ − λΩ·Ωₜ

Materialización sobre el organismo vivo:

- **Contexto Uᵢ** = episodio del run (con su escenario/régimen). En el
  life-loop un run cruza regímenes ⇒ contextos genuinamente heterogéneos.
- **Sección local ωᵢ = (σᵢ, fᵢ, wᵢ)**: símbolos proposicionales de la fórmula
  LOT-F + relation_kind (σ, significado), fórmula normalizada (f, forma), y
  valor de la variable principal con su umbral (w, mundo).
- **Operador de restricción r_ij**: identidad dentro del mismo escenario; entre
  escenarios, el morfismo causal dirigido (`MorphismEngine`) transporta las
  proposiciones (proposition_map) y atenúa/penaliza por `overall_score` y
  pérdida de información — el motor de morfismos entra así al camino vivo.
- **Error de ciclo F→M→S** por episodio, con señales ya computadas: cobertura
  de símbolos en el vocabulario de la firma (S→F), validación Z3 de la fórmula
  contra el mundo (F→M, `ded_validated`), y acuerdo causal/contrafactual con la
  relación semiótica (M→S, `direction_match` / `agreement_with_relation_kind`).

**Modo sombra**: el bloque se registra en `metadata["omega"]` del certificado y
NO altera el veredicto clásico (reproducibilidad intacta); IoC* queda
disponible para la recompensa semi-Markov y para gobernar gates vía flags
futuros. Python puro; los imports de runtime.world son lazy (scenario_runner
importa certification en import-time). Hiperparámetros por entorno:
``RNFE_OMEGA_LAMBDA`` (λΩ, default 0.30), ``RNFE_OMEGA_LAMBDA_CYCLE``
(λ_◯, default 0.50), ``RNFE_OMEGA_WINDOW`` (K, default 4).
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

_LOTF_OPERATORS = {"->", "(", ")", "NOT", "AND", "OR"}


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name)
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name)
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ───────────────────────────── secciones locales ─────────────────────────────

@dataclass(frozen=True)
class Section:
    """Sección local ωᵢ = (σᵢ, fᵢ, wᵢ) de un contexto (episodio)."""

    scenario: str
    symbols: frozenset
    relation_kind: Optional[str]
    formula_norm: str
    formula_tokens: frozenset
    main_variable: str
    value: Optional[float]
    alarm_threshold: Optional[float]


def _normalize_formula(formula: Any) -> Tuple[str, frozenset, frozenset]:
    """(fórmula normalizada, tokens, símbolos) — tolerante a fórmulas inválidas."""
    if not isinstance(formula, str) or not formula.strip():
        return "", frozenset(), frozenset()
    try:
        from runtime.lotf import LOTFMin

        tokens = LOTFMin().tokenize(formula)
    except Exception:
        tokens = formula.split()
    norm = " ".join(tokens)
    symbols = frozenset(t for t in tokens if t not in _LOTF_OPERATORS)
    return norm, frozenset(tokens), symbols


def section_from_episode_result(episode_result: Mapping[str, Any]) -> Section:
    """Extrae la sección local del payload vivo de un episodio."""
    episode = _safe_dict(episode_result.get("episode"))
    context = _safe_dict(episode.get("context"))
    result = _safe_dict(episode.get("result"))
    md = _safe_dict(episode.get("scenario_metadata"))
    mv = str(md.get("main_variable") or "temperature")
    norm, tokens, symbols = _normalize_formula(context.get("formula"))
    world = _safe_dict(result.get("updated_world"))
    return Section(
        scenario=str(episode.get("scenario") or md.get("scenario_name") or ""),
        symbols=symbols,
        relation_kind=result.get("relation_kind"),
        formula_norm=norm,
        formula_tokens=tokens,
        main_variable=mv,
        value=_num(world.get(mv)),
        alarm_threshold=_num(md.get("alarm_threshold")),
    )


def section_from_certificate(cert: Any) -> Section:
    """Extrae la MISMA sección desde un certificado persistido (simétrica)."""
    lotf = _safe_dict(getattr(cert, "lotf_artifacts", None))
    world_art = _safe_dict(getattr(cert, "world_artifacts", None))
    meta = _safe_dict(getattr(cert, "metadata", None))
    md = _safe_dict(meta.get("scenario_metadata"))
    mv = str(meta.get("world_main_variable") or md.get("main_variable") or "temperature")
    norm, tokens, symbols = _normalize_formula(lotf.get("formula"))
    world = _safe_dict(world_art.get("updated_world"))
    value = _num(world.get(mv))
    if value is None:
        value = _num(meta.get("world_main_variable_value"))
    return Section(
        scenario=str(md.get("scenario_name") or ""),
        symbols=symbols,
        relation_kind=world_art.get("relation_kind"),
        formula_norm=norm,
        formula_tokens=tokens,
        main_variable=mv,
        value=value,
        alarm_threshold=_num(md.get("alarm_threshold")),
    )


# ───────────────────────── divergencia entre secciones ───────────────────────

def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def section_divergence(a: Section, b: Section, morphism: Any = None) -> Dict[str, Any]:
    """d_S + d_F + d_W entre dos secciones, con transporte r_ij opcional.

    Mismo escenario ⇒ comparación directa (r_ij = identidad). Entre escenarios,
    el morfismo transporta los símbolos de ``a`` (proposition_map) y la
    divergencia de mundo se mezcla con la (in)compatibilidad estructural
    (1 − overall_score, pérdida de información estimada).
    """
    symbols_a = a.symbols
    morphism_class: Optional[str] = None
    if morphism is not None:
        morphism_class = str(getattr(morphism, "morphism_class", None))
        prop_map = dict(getattr(getattr(morphism, "transport_operator", None), "proposition_map", ()) or ())
        symbols_a = frozenset(prop_map.get(s, s) for s in a.symbols)

    d_s = _clamp01(
        0.7 * (1.0 - _jaccard(symbols_a, b.symbols))
        + 0.3 * (1.0 if (a.relation_kind or "") != (b.relation_kind or "") else 0.0)
    )
    if a.formula_norm == b.formula_norm and a.formula_norm:
        d_f = 0.0
    else:
        d_f = _clamp01(1.0 - _jaccard(a.formula_tokens, b.formula_tokens))

    if a.value is not None and b.value is not None:
        raw_dw = _clamp01(abs(a.value - b.value))
    else:
        raw_dw = 0.5  # mundo no comparable: divergencia neutra, nunca crash
    if morphism is not None:
        overall = _clamp01(_num(getattr(morphism, "overall_score", 0.0)) or 0.0)
        # Sin `or 1.0`: `_num` devuelve None cuando falta, así que la guarda es
        # explícita. El `or` convertía una pérdida MEDIDA de 0.0 —transporte
        # perfecto, sin pérdida— en 1.0, pérdida total. Invierte el dato en el
        # caso más favorable, que es el que más importa no perder.
        _il = _num(getattr(getattr(morphism, "transport_operator", None), "estimated_information_loss", None))
        info_loss = _clamp01(1.0 if _il is None else _il)
        # El mundo solo es comparable en la medida en que el morfismo lo
        # transporta: la incompatibilidad estructural domina la divergencia.
        d_w = _clamp01(overall * raw_dw + (1.0 - overall) * max(info_loss, raw_dw))
        if morphism_class in {"adversarial", "incompatible"}:
            d_w = max(d_w, 0.70)
    else:
        d_w = raw_dw

    divergence = _clamp01((d_s + d_f + d_w) / 3.0)
    return {
        "d_s": round(d_s, 6),
        "d_f": round(d_f, 6),
        "d_w": round(d_w, 6),
        "divergence": round(divergence, 6),
        "cross_context": bool(a.scenario and b.scenario and a.scenario != b.scenario),
        "morphism_class": morphism_class,
        "scenarios": [a.scenario, b.scenario],
    }


# ─────────────────────────── error del ciclo F→M→S ───────────────────────────

def cycle_error(episode_result: Mapping[str, Any]) -> Dict[str, Any]:
    """|Φ_{M→S}·Φ_{F→M}·Φ_{S→F} − I| en miniatura, con señales ya computadas.

    Componentes en [0,1] (0 = ese tramo del ciclo cierra); las señales ausentes
    valen 0.5 (neutro). Nunca lanza.
    """
    reasoning = _safe_dict(episode_result.get("reasoning"))
    state = _safe_dict(reasoning.get("state"))
    episode = _safe_dict(episode_result.get("episode"))
    context = _safe_dict(episode.get("context"))
    md = _safe_dict(episode.get("scenario_metadata"))

    # S→F: ¿los símbolos de la fórmula viven en el vocabulario del escenario?
    _, _, symbols = _normalize_formula(context.get("formula"))
    s_to_f = 0.5
    scenario_name = str(episode.get("scenario") or md.get("scenario_name") or "")
    if symbols and scenario_name:
        try:  # lazy: no acoplar certification→world en import-time
            from runtime.world.registry import get_scenario

            vocab = frozenset(get_scenario(scenario_name).causal_signature.proposition_vocabulary)
            s_to_f = 1.0 - (len(symbols & vocab) / len(symbols)) if vocab else 0.5
        except Exception:
            s_to_f = 0.5

    # F→M: ¿la fórmula es consistente con el mundo observado? (Z3 vía DED)
    if "ded_validated" in state:
        f_to_m = 0.0 if state.get("ded_validated") else 1.0
    elif state.get("ded_status"):
        f_to_m = 0.0 if state.get("ded_status") == "sat" else 1.0
    else:
        f_to_m = 0.5

    # M→S: ¿la dinámica del mundo concuerda con la relación semiótica?
    cau = _safe_dict(state.get("cau_link"))
    ctf = _safe_dict(state.get("ctf_checked"))
    signals: List[float] = []
    if "direction_match" in cau:
        signals.append(0.0 if cau.get("direction_match") else 1.0)
    agreement = ctf.get("agreement_with_relation_kind")
    if agreement is not None:
        signals.append(0.0 if agreement else 1.0)
    m_to_s = (sum(signals) / len(signals)) if signals else 0.5

    error = _clamp01((s_to_f + f_to_m + m_to_s) / 3.0)
    return {
        "s_to_f": round(_clamp01(s_to_f), 6),
        "f_to_m": round(_clamp01(f_to_m), 6),
        "m_to_s": round(_clamp01(m_to_s), 6),
        "error": round(error, 6),
    }


# ─────────────────────────────── tracker por run ─────────────────────────────

class CoherenceObstructionTracker:
    """Mantiene la ventana de secciones por run y emite el bloque ``omega``.

    Espejo del ``EpisodeRiskTracker`` (R1): ventana acotada, sembrada una vez
    desde los certificados persistidos del run, caché de morfismos por par de
    escenarios, salida JSON-safe en modo sombra.
    """

    def __init__(
        self,
        *,
        storage=None,
        lambda_omega: float | None = None,
        lambda_cycle: float | None = None,
        window: int | None = None,
    ):
        self.storage = storage
        self.lambda_omega = (
            lambda_omega if lambda_omega is not None else _env_float("RNFE_OMEGA_LAMBDA", 0.30)
        )
        self.lambda_cycle = (
            lambda_cycle if lambda_cycle is not None else _env_float("RNFE_OMEGA_LAMBDA_CYCLE", 0.50)
        )
        self.window = window if window is not None else _env_int("RNFE_OMEGA_WINDOW", 4)
        self._sections: Dict[str, Deque[Section]] = {}
        self._ioc_star_prev: Dict[str, float] = {}
        self._morphism_cache: Dict[Tuple[str, str], Any] = {}

    def _seed(self, run_id: str) -> Deque[Section]:
        sections: Deque[Section] = deque(maxlen=self.window)
        if self.storage is not None:
            try:
                certs = self.storage.list_episode_certificates(run_id=run_id, limit=self.window)
                for cert in reversed(certs):  # más-reciente-primero → cronológico
                    sections.append(section_from_certificate(cert))
                if certs and run_id not in self._ioc_star_prev:
                    # Restaurar la serie IoC* para que ΔIoC* sobreviva a trackers
                    # nuevos sobre el mismo run (runner fresco por episodio).
                    prev_block = (getattr(certs[0], "metadata", None) or {}).get("omega") or {}
                    prev_star = prev_block.get("ioc_star")
                    if isinstance(prev_star, (int, float)):
                        self._ioc_star_prev[run_id] = float(prev_star)
            except Exception:
                sections = deque(maxlen=self.window)
        self._sections[run_id] = sections
        return sections

    def _morphism_for(self, source: str, target: str) -> Any:
        if not source or not target or source == target:
            return None
        key = (source, target)
        if key in self._morphism_cache:
            return self._morphism_cache[key]
        morphism = None
        try:  # lazy + tolerante: escenarios desconocidos ⇒ sin transporte
            from runtime.world.morphism_engine import MorphismEngine
            from runtime.world.registry import get_scenario

            morphism = MorphismEngine().compute_morphism(
                get_scenario(source).causal_signature,
                get_scenario(target).causal_signature,
            )
        except Exception:
            morphism = None
        self._morphism_cache[key] = morphism
        return morphism

    def assess(
        self,
        *,
        run_id: str,
        episode_result: Mapping[str, Any],
        ioc_value: float,
    ) -> Dict[str, Any]:
        sections = self._sections.get(run_id)
        if sections is None:
            sections = self._seed(run_id)

        current = section_from_episode_result(episode_result)
        pairs: List[Dict[str, Any]] = []
        for previous in sections:
            morphism = self._morphism_for(previous.scenario, current.scenario)
            pairs.append(section_divergence(previous, current, morphism=morphism))
        pairwise_mean = (
            sum(p["divergence"] for p in pairs) / len(pairs) if pairs else 0.0
        )

        cycle = cycle_error(episode_result)
        omega = pairwise_mean + self.lambda_cycle * cycle["error"]
        ioc_star = _clamp01(float(ioc_value) - self.lambda_omega * omega)

        previous_star = self._ioc_star_prev.get(run_id)
        delta_star = None if previous_star is None else (ioc_star - previous_star)
        self._ioc_star_prev[run_id] = ioc_star
        sections.append(current)

        return {
            "schema": "omega.v1",
            "omega": round(omega, 6),
            "pairwise_mean": round(pairwise_mean, 6),
            "pair_divergences": pairs,
            "cycle": cycle,
            "cross_context": any(p["cross_context"] for p in pairs),
            "n_window": len(pairs),
            "ioc_star": round(ioc_star, 6),
            "delta_ioc_star": None if delta_star is None else round(delta_star, 6),
            "lambda_omega": self.lambda_omega,
            "lambda_cycle": self.lambda_cycle,
        }
