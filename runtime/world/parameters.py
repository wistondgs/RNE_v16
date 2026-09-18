"""Registro canónico del espacio de parámetros adaptativos (§XIII, §XIV).

El barrido de la noche encontró ~100 gates `RNFE_*`, 3 `AEON_*` y 24 campos de
`LifeKernelConfig`. **Eso no son 127 hiperparámetros adaptativos.** La mayoría
son compuertas de arquitectura, configuración de arranque o pura observabilidad,
y dejar que un agente de hiperparámetros los mueva «porque son parámetros» es
exactamente el fallo que este módulo existe para impedir.

Aquí sólo se declaran los parámetros que un lazo adaptativo puede proponer
mutar en caliente, con su contrato completo y legible por máquina. Hoy son
**dos**, y no se añade un tercero hasta demostrar su cadena causal (§XV).

El contrato no es narrativo: `validate` y `domain` los consume el materializador,
`apply_semantics` decide si un cambio necesita reconstruir, y `authority` dice
quién puede materializar frente a quién sólo puede proponer. La distinción
intención/mutación (§XII) se apoya en estos campos, no en `if` dispersos.

Medido antes de escribir esto (H-048): en el camino productivo la autoridad de
mutación efectiva ya era **1**; el defecto era que el default se reaplicaba en
cada reconstrucción del consumidor. Por eso el contrato distingue `default`
—que pertenece al bootstrap— de `Λ_t`, que pertenece al organismo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

# ── Taxonomía (§XIII) ────────────────────────────────────────────────────────
#
# Un parámetro pertenece a EXACTAMENTE una clase, y sólo una es adaptable en
# caliente por el lazo. Las demás existen para que nadie las confunda con ella.
FEATURE_GATE = "FEATURE_GATE"                      # enciende/apaga una capacidad
STATIC_CONFIG = "STATIC_CONFIG"                    # se fija al arrancar y no se mueve
RUNTIME_CONTROL = "RUNTIME_CONTROL"                # lo mueve el runtime, no un optimizador
ADAPTIVE_HYPERPARAMETER = "ADAPTIVE_HYPERPARAMETER"  # ← lo único que ρₜ puede proponer
HOMEOSTATIC_THRESHOLD = "HOMEOSTATIC_THRESHOLD"    # escala rápida, namespace aparte (§XXXIX)
RESOURCE_BUDGET = "RESOURCE_BUDGET"                # techo de recursos
EXPERIMENTAL_PARAMETER = "EXPERIMENTAL_PARAMETER"  # de laboratorio, no de vida
MODEL_PARAMETER = "MODEL_PARAMETER"                # pesos/arquitectura de un órgano
OBSERVABILITY_ONLY = "OBSERVABILITY_ONLY"          # no cambia conducta

PARAMETER_KINDS = (
    FEATURE_GATE, STATIC_CONFIG, RUNTIME_CONTROL, ADAPTIVE_HYPERPARAMETER,
    HOMEOSTATIC_THRESHOLD, RESOURCE_BUDGET, EXPERIMENTAL_PARAMETER,
    MODEL_PARAMETER, OBSERVABILITY_ONLY,
)

# Semántica de aplicación: qué hace falta para que un valor nuevo surta efecto.
HOT_APPLY = "HOT_APPLY"                    # el consumidor lo lee cada vez
REBUILD_REQUIRED = "REBUILD_REQUIRED"      # hay que reconstruir el consumidor
RESTART_REQUIRED = "RESTART_REQUIRED"      # hay que reiniciar el proceso
APPLY_SEMANTICS = (HOT_APPLY, REBUILD_REQUIRED, RESTART_REQUIRED)

PARAMETER_STATE_SCHEMA = "parameter-state-v1"


@dataclass(frozen=True)
class ParameterContract:
    """Todo lo que hay que saber de un parámetro para mutarlo con seguridad."""

    canonical_name: str
    kind: str
    value_type: str                      # integer | categorical | continuous | boolean | ordinal
    domain: Any                          # (lo, hi) para numéricos; tupla de valores para categóricos
    default: Any
    owner: str                           # de quién es el VALOR VIGENTE
    scope: str                           # quién lo consume
    apply_semantics: str
    may_propose: Tuple[str, ...]         # quién puede pedir un cambio (§XXXVII)
    authority: str                       # quién lo MATERIALIZA — uno solo (§CIV)
    persistence: str
    rollback_semantics: str
    coerce: Callable[[Any], Any]
    aliases: Tuple[str, ...] = ()
    depends_on: Tuple[str, ...] = ()     # parámetros condicionales (§XXXV)

    def validate(self, value: Any) -> Any:
        """Devuelve el valor coercido, o lanza. Nunca corrige en silencio."""
        coerced = self.coerce(value)
        if self.value_type == "categorical":
            if coerced not in self.domain:
                raise ValueError(
                    f"PARAMETER_OUT_OF_DOMAIN: {self.canonical_name}={value!r}; "
                    f"dominio: {list(self.domain)}"
                )
            return coerced
        lo, hi = self.domain
        if lo is not None and coerced < lo:
            raise ValueError(
                f"PARAMETER_OUT_OF_DOMAIN: {self.canonical_name}={value!r} < mínimo {lo}"
            )
        if hi is not None and coerced > hi:
            raise ValueError(
                f"PARAMETER_OUT_OF_DOMAIN: {self.canonical_name}={value!r} > máximo {hi}"
            )
        return coerced

    def to_payload(self) -> Dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "kind": self.kind,
            "value_type": self.value_type,
            "domain": list(self.domain) if isinstance(self.domain, tuple) else self.domain,
            "default": self.default,
            "owner": self.owner,
            "scope": self.scope,
            "apply_semantics": self.apply_semantics,
            "may_propose": list(self.may_propose),
            "authority": self.authority,
            "persistence": self.persistence,
            "rollback_semantics": self.rollback_semantics,
            "aliases": list(self.aliases),
            "depends_on": list(self.depends_on),
        }


def _normalise_filter_mode(value: Any) -> str:
    mode = str(value)
    return "cross_scenario_analogical" if mode == "analogical" else mode


# ── Los DOS parámetros adaptativos demostrados (§XV) ─────────────────────────
#
# No se añade ninguno más hasta demostrar su cadena causal hasta conducta o
# estado. El máximo de `memory_retrieval_limit` se deja en None a propósito:
# §XXXIII prohíbe inventar uno antes de caracterizar la capacidad real del
# subsistema de memoria y su coste.
_REGISTRY: Dict[str, ParameterContract] = {
    c.canonical_name: c
    for c in (
        ParameterContract(
            canonical_name="memory_retrieval_limit",
            kind=ADAPTIVE_HYPERPARAMETER,
            value_type="integer",
            domain=(1, None),                       # sin máximo: §XXXIII
            default=3,
            owner="organism",
            scope="scenario_runner",
            apply_semantics=HOT_APPLY,              # se lee en cada retrieve()
            may_propose=("autoevolution", "execution_tier", "ecology", "experiment"),
            authority="parameter_state",
            persistence="life_checkpoint:parameter_state",
            rollback_semantics="restore_previous_value",
            coerce=lambda v: int(v),
        ),
        ParameterContract(
            canonical_name="memory_filter_mode",
            kind=ADAPTIVE_HYPERPARAMETER,
            value_type="categorical",
            domain=("strict_same_scenario", "cross_scenario_analogical"),
            default="strict_same_scenario",
            owner="organism",
            scope="scenario_runner",
            apply_semantics=HOT_APPLY,
            may_propose=("autoevolution", "ecology", "experiment"),
            authority="parameter_state",
            persistence="life_checkpoint:parameter_state",
            rollback_semantics="restore_previous_value",
            coerce=_normalise_filter_mode,
            aliases=("analogical",),
        ),
    )
}

ADAPTIVE_PARAMETERS: Tuple[str, ...] = tuple(_REGISTRY)


def contract(name: str) -> ParameterContract:
    """Contrato de un parámetro. Nombre desconocido ⇒ error, no default silencioso."""
    key = _REGISTRY_ALIASES.get(name, name)
    if key not in _REGISTRY:
        raise KeyError(
            f"PARAMETER_UNKNOWN: {name!r}; adaptables declarados: {list(_REGISTRY)}"
        )
    return _REGISTRY[key]


_REGISTRY_ALIASES: Dict[str, str] = {
    alias: c.canonical_name for c in _REGISTRY.values() for alias in c.aliases
}


def bootstrap_state() -> Dict[str, Any]:
    """Λ₀ — los defaults. Sólo legítimos cuando NO existe estado previo (§CII)."""
    return {name: c.default for name, c in _REGISTRY.items()}


def validate_all(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Valida un conjunto ENTERO antes de aplicar nada (§XVIII).

    Devuelve los valores coercidos o lanza en el primero inválido. Quien llama
    debe aplicar sólo el resultado: así una propuesta multivariable no puede
    dejar la mitad escrita.
    """
    out: Dict[str, Any] = {}
    for name, value in values.items():
        out[contract(name).canonical_name] = contract(name).validate(value)
    return out


def state_payload(values: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": PARAMETER_STATE_SCHEMA,
        "values": {k: values[k] for k in sorted(values)},
    }


def state_from_payload(payload: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """`None`/`{}` ⇒ sin estado previo. Esquema desconocido ⇒ error, no silencio."""
    if not payload:
        return None
    schema = payload.get("schema_version")
    if schema != PARAMETER_STATE_SCHEMA:
        raise ValueError(f"PARAMETER_STATE_SCHEMA_UNKNOWN: {schema!r}")
    values = payload.get("values") or {}
    return validate_all({k: v for k, v in values.items() if k in _REGISTRY})
