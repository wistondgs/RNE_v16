"""B17 — Contrato activo mínimo (CANON §13): validación on-write sin dependencias.

CANON §13 (`canon/normative/CANON_RNFE_v3_2_rc1.md:402-408`) exige que exista *contrato
activo* para exactamente cinco cosas: **episodio, propuesta, certificado, rollback y
telemetry snapshot**. "Activo" = el runtime lo hace cumplir en el camino de escritura, no
que el archivo JSON exista.

Este módulo implementa un validador **deliberadamente parcial** de JSON Schema, alineado
con la palabra "mínimo" del canon y con la restricción de no agregar dependencias
(`jsonschema` no está instalado ni es dependencia del proyecto). Valida, a nivel raíz del
payload:

- ``required``            → el campo tiene que estar presente;
- ``properties[*].type``  → si el campo está, su tipo JSON tiene que coincidir;
- ``properties[*].enum``  → si el campo está, su valor tiene que pertenecer al enum.

NO valida (y es a propósito, no un olvido): subesquemas anidados, ``minimum``/``maximum``,
``items``, ``pattern``, ``$ref``, ``additionalProperties: false``. Ver backlog del paquete
P7 si se quiere subir el nivel de cobertura.

Enforcement (reversibilidad, RNFE §14.6) vía ``RNFE_CONTRACT_VALIDATION``:

- ``strict`` (**default**) → levanta :class:`ContractViolationError` y NO persiste;
- ``warn``                 → loguea la violación y persiste igual;
- ``off``                  → no valida.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger("rnfe.contracts")

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"

ENV_VAR = "RNFE_CONTRACT_VALIDATION"
DEFAULT_MODE = "strict"
VALID_MODES = frozenset({"strict", "warn", "off"})

#: Los cinco contratos activos de CANON §13. Ni uno más: `tool_request`/`tool_result` y
#: `session_bridge` son capacidad reservada sin productor (B20/B23), NO contratos activos.
ACTIVE_CONTRACTS = frozenset(
    {"episode", "proposal", "certificate", "rollback", "telemetry_snapshot"}
)

#: Contratos activos que viajan como payload de evento (``append_event``), mapeados por
#: ``event_type`` del writer vivo que los produce.
EVENT_CONTRACTS: Mapping[str, str] = {
    "episode.closed": "episode",  # runtime/world/{scenario_runner,min_cognitive_episode}.py
    "proposal.evaluated": "proposal",  # runtime/certification/promotion_gate.py
    "life.rollback.restored_checkpoint": "rollback",  # runtime/life/kernel.py
}

#: PELIGRO — NO "completes" ``EVENT_CONTRACTS`` con estos ``event_type``.
#:
#: Hay más writers vivos que emiten eventos de rollback/propuesta, pero HOY **no
#: conforman** su schema. Mapearlos arriba sin corregir ANTES su payload los haría
#: levantar ``ContractViolationError`` bajo el modo ``strict`` (el default):
#:
#:   - ``life.rollback`` (``runtime/life/kernel.py:677``, ``event_type=f"life.{action}"``):
#:     su payload no tiene NINGUNO de los 4 ``required`` del rollback, y ese
#:     ``append_event`` **no está envuelto en try/except**. Mapearlo **mata al organismo
#:     justo en la decisión de rollback** — el camino de refugio que más se necesita.
#:   - ``autoevolution.rollback`` (``runtime/organism/autoevolution.py``): faltan
#:     ``target`` y ``timestamp``.
#:   - ``msrc.rollback`` (``runtime/control/msrc/scale_audit_logger.py``): faltan
#:     ``rollback_id``, ``target`` y ``reason``.
#:   - ``autoevolution.proposal`` (``runtime/organism/autoevolution.py``): usa
#:     ``changes``/``risk_level`` en vez de ``change``/``risk``, y no emite ``origin``.
#:
#: El trabajo de hacerlos conformar —y recién entonces mapearlos— es **B60**. Hasta
#: entonces, el "contrato activo" de rollback se hace cumplir en 1 de 4 caminos.
#: ``tests/storage/test_contract_validation.py`` tiene un tripwire que falla si alguien
#: agrega alguno de estos al mapa.
NONCONFORMING_EVENT_TYPES = frozenset(
    {
        "life.rollback",
        "autoevolution.rollback",
        "msrc.rollback",
        "autoevolution.proposal",
    }
)


class ContractViolationError(ValueError):
    """El payload no cumple el contrato activo de CANON §13 y no se persiste."""

    def __init__(self, contract: str, origin: str, violations: Sequence[str]):
        self.contract = contract
        self.origin = origin
        self.violations = list(violations)
        detail = "; ".join(self.violations)
        super().__init__(
            f"Contrato activo '{contract}' violado en '{origin}' "
            f"(CANON §13): {detail}. "
            f"Para degradar el enforcement: {ENV_VAR}=warn|off."
        )


def get_mode() -> str:
    """Modo de enforcement vigente. Se lee del entorno en cada escritura (reversible)."""
    raw = (os.environ.get(ENV_VAR) or DEFAULT_MODE).strip().lower()
    if raw not in VALID_MODES:
        logger.warning(
            "%s='%s' no es un modo valido (%s); se usa '%s'.",
            ENV_VAR,
            raw,
            ",".join(sorted(VALID_MODES)),
            DEFAULT_MODE,
        )
        return DEFAULT_MODE
    return raw


@lru_cache(maxsize=None)
def load_schema(contract: str) -> Mapping[str, Any]:
    """Carga (y cachea) el schema JSON de un contrato por nombre, sin sufijo."""
    path = CONTRACTS_DIR / f"{contract}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"Schema de contrato inexistente: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_json_type(value: Any, json_type: str) -> bool:
    """¿``value`` es del tipo JSON ``json_type``?

    Ojo con la trampa de Python: ``bool`` es subclase de ``int``, así que ``True`` NO puede
    contar como ``number``/``integer`` (JSON Schema los distingue).
    """
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "object":
        return isinstance(value, Mapping)
    if json_type == "array":
        return isinstance(value, (list, tuple))
    if json_type == "null":
        return value is None
    # Tipo JSON desconocido: no inventamos semántica, no bloqueamos la escritura.
    logger.warning("Tipo JSON no soportado por el validador minimo: '%s'", json_type)
    return True


def validate_payload(contract: str, payload: Any) -> list[str]:
    """Valida ``payload`` contra el contrato y devuelve la lista de violaciones.

    Lista vacía == conforme. No levanta: la política de enforcement la aplica
    :func:`enforce`.
    """
    schema = load_schema(contract)

    if not isinstance(payload, Mapping):
        return [f"payload debe ser un objeto, se recibio {type(payload).__name__}"]

    violations: list[str] = []

    for field in schema.get("required", []):
        if field not in payload:
            violations.append(f"falta el campo requerido '{field}'")

    properties: Mapping[str, Any] = schema.get("properties", {}) or {}
    for field, spec in properties.items():
        if field not in payload or not isinstance(spec, Mapping):
            continue
        value = payload[field]

        expected = spec.get("type")
        if expected is not None:
            allowed = [expected] if isinstance(expected, str) else list(expected)
            if not any(_matches_json_type(value, item) for item in allowed):
                violations.append(
                    f"campo '{field}': se esperaba tipo {'|'.join(allowed)}, "
                    f"se recibio {type(value).__name__}"
                )

        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            violations.append(
                f"campo '{field}': valor {value!r} fuera del enum permitido {enum}"
            )

    return violations


def to_payload(record: Any) -> Any:
    """Serializa un record (dataclass) al payload que se valida/persiste."""
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    return record


def enforce(contract: str, payload: Any, *, origin: str) -> None:
    """Aplica el contrato activo antes de persistir, según el modo de enforcement.

    Levanta :class:`ContractViolationError` en modo ``strict`` (default).
    """
    mode = get_mode()
    if mode == "off":
        return

    violations = validate_payload(contract, payload)
    if not violations:
        return

    if mode == "warn":
        logger.warning(
            "Contrato activo '%s' violado en '%s' (CANON §13), se persiste igual "
            "porque %s=warn: %s",
            contract,
            origin,
            ENV_VAR,
            "; ".join(violations),
        )
        return

    raise ContractViolationError(contract, origin, violations)


def enforce_record(contract: str, record: Any, *, origin: str) -> None:
    """Igual que :func:`enforce`, pero serializando el record antes de validar."""
    enforce(contract, to_payload(record), origin=origin)


def enforce_event(event_type: str, payload: Any, *, origin: str) -> None:
    """Aplica el contrato activo asociado a un ``event_type``, si lo hay.

    Los event_type que no mapean a un contrato activo pasan sin validar: el ledger de
    eventos es genérico y CANON §13 sólo exige contrato para los cinco de
    :data:`ACTIVE_CONTRACTS`.
    """
    contract = EVENT_CONTRACTS.get(event_type)
    if contract is None:
        return
    enforce(contract, payload, origin=origin)
