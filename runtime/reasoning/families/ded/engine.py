"""Primer engine real para DED usando Z3.

Este corte es deliberadamente pequeno:
- reusa LOTFMin como parser/checker
- soporta solo logica proposicional booleana
- deja evidencia auditable en state_delta y artifacts

No intenta extender LOT-F completo ni meter logica causal/contrafactual.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping

from z3 import Bool, BoolRef, Not, Solver, Z3Exception, sat, unsat

from runtime.lotf import LOTFMin
from runtime.reasoning.contracts import FamilyResult

from .translator import (
    UnsupportedLOTFNodeError,
    build_type_env,
    collect_symbols,
    translate_lotf,
)


FAMILY_ID = "DED"
SUPPORTED_SUBSET = "lotf_bool_v1"
SOLVER_BACKEND = "z3"

_INTERVENTION_ALIASES = {
    "activate_cooling": "ACTIVATE_COOLING",
    "deactivate_cooling": "KEEP_IDLE",
    "keep_idle": "KEEP_IDLE",
    "start_production": "START_PRODUCTION",
    "stop_production": "KEEP_IDLE",
}

_MISSING_CONCLUSION = "missing formula"
_UNSUPPORTED_CONCLUSION = "unsupported formula subset"
_UNKNOWN_CONCLUSION = "solver returned unknown"
_UNSAT_CONCLUSION = "formula contradicts current assumptions"
_SAT_GENERIC_CONCLUSION = "satisfiable under current assumptions"


@dataclass(frozen=True)
class DedAssumption:
    symbol: str
    source: str
    value: bool = True


def _safe_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_formula(raw_formula: Any) -> str:
    if not isinstance(raw_formula, str):
        return ""
    return raw_formula.strip()


def _normalize_formula_tokens(formula: str, lotf: LOTFMin) -> str:
    return " ".join(lotf.tokenize(formula))


def _extract_symbolic_propositions(
    payload: Mapping[str, Any],
    *,
    source: str,
) -> List[DedAssumption]:
    propositions = payload.get("propositions")
    if not isinstance(propositions, list):
        return []

    assumptions: List[DedAssumption] = []
    for proposition in propositions:
        if isinstance(proposition, str) and proposition.strip():
            assumptions.append(
                DedAssumption(symbol=proposition.strip().upper(), source=f"{source}.propositions")
            )
    return assumptions


def _extract_alarm_aliases(payload: Mapping[str, Any], *, source: str) -> List[DedAssumption]:
    alarm = payload.get("alarm")
    if alarm is True:
        return [DedAssumption(symbol="TEMP_HIGH", source=f"{source}.alarm")]
    if alarm is False:
        return [DedAssumption(symbol="TEMP_NORMAL", source=f"{source}.alarm")]
    return []


def _extract_intervention_alias(intervention: Any) -> List[DedAssumption]:
    if not isinstance(intervention, str):
        return []
    alias = _INTERVENTION_ALIASES.get(intervention.strip().lower())
    if not alias:
        return []
    return [DedAssumption(symbol=alias, source="intervention")]


def _extract_assumptions(state: Mapping[str, Any], *, allowed_symbols: Iterable[str]) -> List[DedAssumption]:
    allowed = set(allowed_symbols)
    ordered: List[DedAssumption] = []
    seen: set[tuple[str, bool]] = set()

    candidates: List[DedAssumption] = []
    observation = _safe_mapping(state.get("observation"))
    updated_world = _safe_mapping(state.get("updated_world"))
    counterfactual = _safe_mapping(state.get("counterfactual"))

    candidates.extend(_extract_symbolic_propositions(observation, source="observation"))
    candidates.extend(_extract_alarm_aliases(observation, source="observation"))
    candidates.extend(_extract_intervention_alias(state.get("intervention")))
    candidates.extend(_extract_symbolic_propositions(updated_world, source="updated_world"))
    candidates.extend(_extract_symbolic_propositions(counterfactual, source="counterfactual"))

    for assumption in candidates:
        marker = (assumption.symbol, assumption.value)
        if assumption.symbol not in allowed or marker in seen:
            continue
        seen.add(marker)
        ordered.append(assumption)

    return ordered


def _serialize_model(symbol_table: Mapping[str, BoolRef], solver_model: Any) -> Dict[str, str]:
    serialized: Dict[str, str] = {}
    for symbol in sorted(symbol_table):
        serialized[symbol] = str(
            solver_model.evaluate(symbol_table[symbol], model_completion=True)
        )
    return serialized


def _build_base_solver(
    formula_expr: BoolRef,
    assumptions: Iterable[DedAssumption],
    symbol_table: Mapping[str, BoolRef],
) -> Solver:
    solver = Solver()
    solver.add(formula_expr)
    for assumption in assumptions:
        expr = symbol_table[assumption.symbol]
        solver.add(expr if assumption.value else Not(expr))
    return solver


def _derive_entailed_literals(
    *,
    formula_expr: BoolRef,
    assumptions: Iterable[DedAssumption],
    symbol_table: Mapping[str, BoolRef],
) -> List[str]:
    entailed: List[str] = []
    solver = _build_base_solver(formula_expr, assumptions, symbol_table)
    for symbol in sorted(symbol_table):
        expr = symbol_table[symbol]
        solver.push()
        solver.add(Not(expr))
        if solver.check() == unsat:
            entailed.append(symbol)
            solver.pop()
            continue
        solver.pop()

        solver.push()
        solver.add(expr)
        if solver.check() == unsat:
            entailed.append(f"NOT {symbol}")
        solver.pop()
    return entailed


def _artifacts_base(*, formula_normalized: str, symbol_table: Mapping[str, BoolRef]) -> Dict[str, Any]:
    return {
        "formula_normalized": formula_normalized,
        "supported_subset": SUPPORTED_SUBSET,
        "symbol_table": {symbol: {"sort": "Bool"} for symbol in sorted(symbol_table)},
        "z3_expression": "",
        "solver_result": "",
        "assumptions_used": [],
        "model": {},
        "unsat_core": [],
    }


def _build_result(
    *,
    status: str,
    ded_status: str,
    ded_consistent: bool,
    ded_conclusion: str,
    ded_assumptions_used: List[str],
    ded_formula_normalized: str,
    confidence: float,
    cost: float,
    artifacts: Dict[str, Any],
    ded_validated: bool,
    failure_mode: str | None = None,
) -> Dict[str, Any]:
    state_delta = {
        "ded_validated": ded_validated,
        "ded_status": ded_status,
        "ded_consistent": ded_consistent,
        "ded_conclusion": ded_conclusion,
        "ded_assumptions_used": list(ded_assumptions_used),
        "ded_formula_normalized": ded_formula_normalized,
        "ded_solver_backend": SOLVER_BACKEND,
    }
    return FamilyResult(
        family=FAMILY_ID,
        status=status,
        state_delta=state_delta,
        confidence=confidence,
        cost=cost,
        artifacts=artifacts,
        failure_mode=failure_mode,
    ).to_dict()


def run_ded_engine(state: Mapping[str, Any] | None) -> Dict[str, Any]:
    payload = dict(state or {})
    raw_formula = _normalize_formula(payload.get("formula"))
    if not raw_formula:
        return _build_result(
            status="skip",
            ded_status="missing_formula",
            ded_consistent=False,
            ded_conclusion=_MISSING_CONCLUSION,
            ded_assumptions_used=[],
            ded_formula_normalized="",
            confidence=0.0,
            cost=0.1,
            artifacts={
                "formula_normalized": "",
                "supported_subset": SUPPORTED_SUBSET,
                "symbol_table": {},
                "z3_expression": "",
                "solver_result": "missing_formula",
                "assumptions_used": [],
                "model": {},
                "unsat_core": [],
            },
            ded_validated=False,
            failure_mode="missing_formula",
        )

    lotf = LOTFMin()
    try:
        formula_normalized = _normalize_formula_tokens(raw_formula, lotf)
        ast = lotf.parse(formula_normalized)
        symbols = collect_symbols(ast)
        lotf.check(ast, build_type_env(symbols))
        translation = translate_lotf(ast)
    except (TypeError, ValueError, UnsupportedLOTFNodeError) as exc:
        return _build_result(
            status="skip",
            ded_status="unsupported",
            ded_consistent=False,
            ded_conclusion=_UNSUPPORTED_CONCLUSION,
            ded_assumptions_used=[],
            ded_formula_normalized=raw_formula,
            confidence=0.0,
            cost=0.1,
            artifacts={
                "formula_normalized": raw_formula,
                "supported_subset": SUPPORTED_SUBSET,
                "symbol_table": {},
                "z3_expression": "",
                "solver_result": "unsupported",
                "assumptions_used": [],
                "model": {},
                "unsat_core": [],
                "parse_error": str(exc),
            },
            ded_validated=False,
            failure_mode="unsupported_formula",
        )

    assumptions = _extract_assumptions(payload, allowed_symbols=translation.symbol_table)
    assumption_artifacts = [
        {
            "symbol": assumption.symbol,
            "value": bool(assumption.value),
            "source": assumption.source,
        }
        for assumption in assumptions
    ]

    artifacts = _artifacts_base(
        formula_normalized=formula_normalized,
        symbol_table=translation.symbol_table,
    )
    artifacts["z3_expression"] = str(translation.expression)
    artifacts["assumptions_used"] = assumption_artifacts

    try:
        solver = Solver()
        solver.add(translation.expression)
        trackers: Dict[str, DedAssumption] = {}
        for idx, assumption in enumerate(assumptions):
            tracker_name = f"ded_assumption_{idx}_{assumption.symbol}"
            tracker = Bool(tracker_name)
            expr = translation.symbol_table[assumption.symbol]
            solver.assert_and_track(expr if assumption.value else Not(expr), tracker)
            trackers[tracker_name] = assumption

        solver_result = solver.check()
        artifacts["solver_result"] = str(solver_result)

        if solver_result == sat:
            entailed_literals = _derive_entailed_literals(
                formula_expr=translation.expression,
                assumptions=assumptions,
                symbol_table=translation.symbol_table,
            )
            artifacts["model"] = _serialize_model(translation.symbol_table, solver.model())
            ded_conclusion = (
                f"entailed: {', '.join(entailed_literals)}"
                if entailed_literals
                else _SAT_GENERIC_CONCLUSION
            )
            return _build_result(
                status="ok",
                ded_status="sat",
                ded_consistent=True,
                ded_conclusion=ded_conclusion,
                ded_assumptions_used=[assumption.symbol for assumption in assumptions],
                ded_formula_normalized=formula_normalized,
                confidence=0.95,
                cost=1.0,
                artifacts=artifacts,
                ded_validated=True,
            )

        if solver_result == unsat:
            unsat_core = []
            for tracker in solver.unsat_core():
                assumption = trackers.get(str(tracker))
                if not assumption:
                    continue
                unsat_core.append(
                    {
                        "symbol": assumption.symbol,
                        "value": bool(assumption.value),
                        "source": assumption.source,
                    }
                )
            artifacts["unsat_core"] = unsat_core
            return _build_result(
                status="ok",
                ded_status="unsat",
                ded_consistent=False,
                ded_conclusion=_UNSAT_CONCLUSION,
                ded_assumptions_used=[assumption.symbol for assumption in assumptions],
                ded_formula_normalized=formula_normalized,
                confidence=0.95,
                cost=1.0,
                artifacts=artifacts,
                ded_validated=True,
            )

        return _build_result(
            status="warn",
            ded_status="unknown",
            ded_consistent=False,
            ded_conclusion=_UNKNOWN_CONCLUSION,
            ded_assumptions_used=[assumption.symbol for assumption in assumptions],
            ded_formula_normalized=formula_normalized,
            confidence=0.25,
            cost=1.0,
            artifacts=artifacts,
            ded_validated=True,
            failure_mode="solver_unknown",
        )
    except Z3Exception as exc:
        artifacts["solver_result"] = "solver_error"
        artifacts["solver_error"] = str(exc)
        return _build_result(
            status="warn",
            ded_status="unknown",
            ded_consistent=False,
            ded_conclusion=_UNKNOWN_CONCLUSION,
            ded_assumptions_used=[assumption.symbol for assumption in assumptions],
            ded_formula_normalized=formula_normalized,
            confidence=0.25,
            cost=1.0,
            artifacts=artifacts,
            ded_validated=True,
            failure_mode="solver_error",
        )
