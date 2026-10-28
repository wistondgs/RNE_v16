"""Verificación REAL de integridad de la traza de razonamiento (B1).

Antes (``transfer_assessment.py``)::

    trace = episode.get("trace", [])
    trace_integrity = len(trace) > 0 if trace else True   # True en AMBAS ramas

Eso era una **constante disfrazada de medición**: el llamador no podía
distinguirla de una verificación real, el término de traza siempre aportaba su
máximo y el failure mode ``trace_discontinuity`` era inalcanzable por
construcción.

## Qué es "íntegra"

La traza la arma ``runtime/reasoning/scheduler_meta/meta_scheduler.py`` como
``[t.__dict__ for t in traces]`` sobre ``ReasoningTraceStep``
(``family: str``, ``status: str``, ``detail: dict``, ``timestamp: float``),
un paso por familia efectivamente ejecutada, y publica en paralelo la secuencia
ejecutada en ``episode["result"]["reasoning_sequence"]``.

El canon (``canon/normative/RUNTIME_SSOT_v1.md`` §9.1) lista ``trace_integrity``
como métrica mínima pero **no la define operativamente**. La única definición
operativa del repo es ``runtime/reality/evaluator.py:314``::

    trace_integrity = has_episode_closed and meta_trace_complete

es decir: **evento de cierre presente** + **traza completa respecto de la
secuencia esperada**. Ese chequeo necesita el storage (para el evento de cierre)
y el perfil de cierre; ``assess_transfer`` no recibe ninguno de los dos, así que
acá se implementa la parte que **sí es verificable con el episodio en mano**:

1. ``present``      — la clave ``trace`` existe y es una lista (ausente → NO íntegra).
2. ``non_empty``    — tiene al menos un paso (vacía → NO íntegra).
3. ``well_formed``  — cada paso es un mapping con ``family`` (str no vacío) y
                      ``status`` (str no vacío).
4. ``monotonic_ts`` — los ``timestamp`` (cuando están en todos los pasos) no
                      retroceden. Un retroceso = pasos reordenados/mezclados de
                      otra corrida → discontinuidad.
5. ``sequence_match`` — **el chequeo de discontinuidad fuerte**: las familias de
                      la traza coinciden 1:1 y en orden con
                      ``episode["result"]["reasoning_sequence"]``, que se registra
                      de forma independiente. Si faltan pasos, sobran o están
                      reordenados, la cadena de razonamiento **está rota**.

## Honestidad

- Los chequeos 4 y 5 **solo se aplican si hay con qué aplicarlos** (timestamps en
  todos los pasos / secuencia registrada). Cuando no se pueden aplicar, NO se
  fabrica evidencia: quedan fuera de ``checks_applied`` y el resultado dice
  explícitamente cuáles corrieron.
- Traza **ausente o vacía NO es integridad**: es la ausencia de la evidencia
  misma → ``integral=False`` (antes devolvía ``True``, lo peor posible).
- El ``status`` de un paso NO se juzga acá: los valores reales del scheduler son
  ``ok``/``idle``/``warn``/``goal_reached``/``no_model_or_observation`` — describen
  el *resultado* del paso, no la integridad del *registro*. Un paso que reporta
  ``idle`` está bien registrado. Integridad = el registro está completo y es
  continuo, no que al organismo le haya ido bien.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Razones de no-integridad (motivo por el que la cadena está rota o ausente).
TRACE_MISSING = "trace_missing"
TRACE_MALFORMED = "trace_malformed"
TRACE_EMPTY = "trace_empty"
STEP_MALFORMED = "step_malformed"
TIMESTAMP_REGRESSION = "timestamp_regression"
SEQUENCE_MISMATCH = "sequence_mismatch"
OK = "ok"

_ALL_CHECKS = ("present", "non_empty", "well_formed", "monotonic_ts", "sequence_match")


@dataclass(frozen=True)
class TraceIntegrityResult:
    """Resultado de la verificación de integridad de traza.

    Attributes:
        integral: True solo si todos los chequeos aplicables pasaron.
        reason: ``ok`` o el motivo de la ruptura (ver constantes del módulo).
        step_count: Pasos efectivamente presentes en la traza.
        checks_applied: Chequeos que se pudieron ejecutar (los que no tenían
            insumos NO se cuentan como aprobados: simplemente no corrieron).
        details: Evidencia del chequeo (índices, secuencias comparadas, etc.).
    """

    integral: bool
    reason: str
    step_count: int
    checks_applied: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # permite `if result:` sin perder la razón
        return self.integral


def assess_trace_integrity(episode: Mapping[str, Any] | None) -> TraceIntegrityResult:
    """Verifica de verdad la integridad de la traza de razonamiento de un episodio.

    Args:
        episode: Dict del episodio (``episode_result["episode"]``). Se leen
            ``episode["trace"]`` y, si está, ``episode["result"]["reasoning_sequence"]``.

    Returns:
        TraceIntegrityResult. ``integral=False`` cuando la traza falta, está
        vacía, tiene pasos malformados o presenta discontinuidad respecto de la
        secuencia ejecutada registrada.
    """
    if not isinstance(episode, Mapping):
        return TraceIntegrityResult(
            integral=False,
            reason=TRACE_MISSING,
            step_count=0,
            details={"episode_type": type(episode).__name__},
        )

    # 1. present
    if "trace" not in episode or episode.get("trace") is None:
        return TraceIntegrityResult(
            integral=False,
            reason=TRACE_MISSING,
            step_count=0,
            checks_applied=("present",),
            details={"note": "el episodio no registra traza de razonamiento"},
        )

    trace = episode.get("trace")
    if isinstance(trace, (str, bytes)) or not isinstance(trace, Sequence):
        return TraceIntegrityResult(
            integral=False,
            reason=TRACE_MALFORMED,
            step_count=0,
            checks_applied=("present",),
            details={"trace_type": type(trace).__name__},
        )

    step_count = len(trace)

    # 2. non_empty
    if step_count == 0:
        return TraceIntegrityResult(
            integral=False,
            reason=TRACE_EMPTY,
            step_count=0,
            checks_applied=("present", "non_empty"),
            details={"note": "traza presente pero sin pasos: no hay razonamiento registrado"},
        )

    checks: list[str] = ["present", "non_empty"]

    # 3. well_formed
    checks.append("well_formed")
    families: list[str] = []
    timestamps: list[float] = []
    for index, step in enumerate(trace):
        if not isinstance(step, Mapping):
            return TraceIntegrityResult(
                integral=False,
                reason=STEP_MALFORMED,
                step_count=step_count,
                checks_applied=tuple(checks),
                details={"step_index": index, "step_type": type(step).__name__},
            )
        family = step.get("family")
        status = step.get("status")
        if not isinstance(family, str) or not family.strip():
            return TraceIntegrityResult(
                integral=False,
                reason=STEP_MALFORMED,
                step_count=step_count,
                checks_applied=tuple(checks),
                details={"step_index": index, "missing_field": "family"},
            )
        if not isinstance(status, str) or not status.strip():
            return TraceIntegrityResult(
                integral=False,
                reason=STEP_MALFORMED,
                step_count=step_count,
                checks_applied=tuple(checks),
                details={"step_index": index, "missing_field": "status"},
            )
        families.append(family.strip().upper())
        ts = step.get("timestamp")
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            timestamps.append(float(ts))

    # 4. monotonic_ts — solo si TODOS los pasos traen timestamp numérico.
    if len(timestamps) == step_count:
        checks.append("monotonic_ts")
        for index in range(1, len(timestamps)):
            if timestamps[index] < timestamps[index - 1]:
                return TraceIntegrityResult(
                    integral=False,
                    reason=TIMESTAMP_REGRESSION,
                    step_count=step_count,
                    checks_applied=tuple(checks),
                    details={
                        "step_index": index,
                        "previous_timestamp": timestamps[index - 1],
                        "timestamp": timestamps[index],
                    },
                )

    # 5. sequence_match — discontinuidad fuerte contra la secuencia registrada.
    expected = _expected_sequence(episode)
    if expected is not None:
        checks.append("sequence_match")
        if families != expected:
            return TraceIntegrityResult(
                integral=False,
                reason=SEQUENCE_MISMATCH,
                step_count=step_count,
                checks_applied=tuple(checks),
                details={
                    "trace_families": families,
                    "reasoning_sequence": expected,
                    "note": "la traza no cubre la secuencia ejecutada: pasos faltantes, sobrantes o reordenados",
                },
            )

    return TraceIntegrityResult(
        integral=True,
        reason=OK,
        step_count=step_count,
        checks_applied=tuple(checks),
        details={"trace_families": families},
    )


def _expected_sequence(episode: Mapping[str, Any]) -> list[str] | None:
    """Secuencia de razonamiento registrada de forma independiente, o None.

    None significa **no verificable** (el episodio no registró la secuencia), no
    "verificado ok": el chequeo ``sequence_match`` simplemente no corre.
    """
    output = episode.get("result")
    if not isinstance(output, Mapping):
        return None
    sequence = output.get("reasoning_sequence")
    if not isinstance(sequence, Sequence) or isinstance(sequence, (str, bytes)):
        return None
    if not sequence:
        return None
    expected: list[str] = []
    for item in sequence:
        if not isinstance(item, str) or not item.strip():
            return None
        expected.append(item.strip().upper())
    return expected
