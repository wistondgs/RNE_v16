"""Manifest reproducible del punto de partida (§LXV, §CXI).

§LXIV lo condiciona: *«una vez cerrados H-046, R-012, parameter ownership y
transactionality, construí por primera vez un régimen de referencia. No
antes.»* Los cuatro están cerrados; esto es lo que los convierte en un punto
de partida citable.

El manifest no es documentación: es el objeto que permite decir «esta medición
se tomó **aquí**». Sin él, repetir las mediciones contaminadas (§LXVI) sería
comparar dos regímenes que nadie sabe si eran el mismo.

**Disciplina de honestidad (patrón B24).** Un campo que no se pudo capturar no
se omite ni se rellena con un plausible: se declara `NOT_CAPTURED` con el
motivo, **dentro de los datos**, legible por máquina. Un manifest al que le
falta el HEAD y no lo dice es peor que no tener manifest, porque invita a creer
que la corrida es reproducible.

**Sin timestamps dentro del hash** (§XLII): el `manifest_hash` identifica el
*régimen*, no el momento. Dos corridas del mismo régimen en días distintos
deben producir el mismo hash, o «reproducible» no significa nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import fields as dataclass_fields
from typing import Any, Dict, Iterable, Mapping

from runtime.world import parameters

REFERENCE_MANIFEST_SCHEMA = "reference-manifest-v1"

# Campos del manifest que §LXV exige. La lista es el contrato: si uno falta,
# `build` lo declara ausente en vez de devolver un manifest silenciosamente corto.
REQUIRED_FIELDS = (
    "head",
    "config",
    "scenario",
    "seed",
    "disturbance_family",
    "disturbance_seed",
    "agent",
    "feature_gates",
    "parameter_state",
    "certificate_semantics",
    "artifact_manifest",
    "runtime_version",
)

# Todo lo que el árbol lee del entorno. Barrido completo, no muestreo:
#   grep -rhoE '"(RNFE|AEON)_[A-Z0-9_]+"' --include='*.py' .
# Se enumeran para poder declarar cuáles estaban PUESTAS, que es lo que
# distingue un régimen de otro. Las no puestas se reportan como tales: «no
# aparece en el manifest» y «estaba apagada» no son lo mismo.
_GATE_PREFIXES = ("RNFE_", "AEON_")


def _not_captured(why: str) -> Dict[str, str]:
    """El único valor legítimo para algo que no se midió."""
    return {"status": "NOT_CAPTURED", "why": why}


def _env_gates() -> Dict[str, Any]:
    """Las gates efectivamente puestas en el proceso, y el conteo de las que no.

    No se listan las 111 apagadas: se declara cuántas hay y cuáles están
    encendidas. Un régimen de referencia se define por lo que se desvía del
    default, y el default es «ninguna».
    """
    puestas = {
        k: v
        for k, v in sorted(os.environ.items())
        if k.startswith(_GATE_PREFIXES)
    }
    return {"set": puestas, "count_set": len(puestas)}


def _config_payload(config: Any) -> Dict[str, Any]:
    """Config₀ entera y serializable. Distinta de Λ_t, que es del organismo."""
    try:
        campos = [f.name for f in dataclass_fields(config)]
    except TypeError:
        return _not_captured("config no es una dataclass")
    out: Dict[str, Any] = {}
    for nombre in sorted(campos):
        valor = getattr(config, nombre, None)
        if isinstance(valor, (str, int, float, bool, type(None))):
            out[nombre] = valor
        elif isinstance(valor, (list, tuple)):
            out[nombre] = list(valor)
        elif isinstance(valor, Mapping):
            out[nombre] = dict(valor)
        else:
            out[nombre] = repr(valor)
    return out


def _certificate_semantics(config: Any) -> Dict[str, Any]:
    """Qué significa un certificado EN ESTE régimen.

    `trajectory_reward` es el campo que decide si el certificado anterior entra
    en la recompensa del trayecto, y por tanto si `C_t` toca a `V_t` — la mezcla
    que motivó todo el trabajo. Va en el manifest porque una medición tomada con
    `"previous_certificate"` y otra con `"none"` no son comparables.
    """
    return {
        "trajectory_reward": getattr(config, "trajectory_reward", None),
        "retention_signal": getattr(config, "retention_signal", None),
        "closure_profile": getattr(config, "closure_profile", None),
        "note": (
            "trajectory_reward decide si C_{t-1} entra en la recompensa del "
            "trayecto; con 'none' (default) el certificado no toca la viabilidad"
        ),
    }


def _runtime_version() -> Dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }


def build(
    *,
    config: Any,
    head: str | None = None,
    parameter_state: Mapping[str, Any] | None = None,
    artifact_manifest: Any = None,
    agent: Any = None,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Los doce campos de §LXV, con lo no capturado declarado como tal.

    `head` se recibe en vez de resolverse: el runtime no debe invocar git, y un
    HEAD inventado es peor que uno ausente. Quien corra el experimento lo pasa.
    """
    lam = dict(parameter_state or {})
    manifest: Dict[str, Any] = {
        "schema_version": REFERENCE_MANIFEST_SCHEMA,
        "head": head or _not_captured("no lo pasó quien construyó el manifest"),
        "config": _config_payload(config),
        "scenario": list(getattr(config, "scenarios", ()) or ()),
        # El kernel no tiene una semilla global: la única que gobierna la
        # trayectoria observable es la de disturbance. Declararlo es más útil
        # que inventar un campo `seed` que nadie consume.
        "seed": _not_captured(
            "el kernel no expone una semilla global; la única que gobierna la "
            "trayectoria es disturbance_seed, declarada aparte"
        ),
        "disturbance_family": getattr(config, "disturbance_family", None),
        "disturbance_seed": getattr(config, "disturbance_seed", None),
        "agent": agent if agent is not None else _not_captured(
            "no se pasó descriptor de agente"
        ),
        "feature_gates": _env_gates(),
        "parameter_state": {
            "values": {k: lam[k] for k in sorted(lam)},
            "hash": parameters.state_hash(lam) if lam else None,
            "registry": {
                n: parameters.contract(n).to_payload()
                for n in parameters.ADAPTIVE_PARAMETERS
            },
        },
        "certificate_semantics": _certificate_semantics(config),
        "artifact_manifest": artifact_manifest if artifact_manifest is not None
        else _not_captured("no se pasó manifest de artefactos/modelos"),
        "runtime_version": _runtime_version(),
    }
    if extra:
        manifest["extra"] = dict(extra)

    faltantes = [f for f in REQUIRED_FIELDS if f not in manifest]
    if faltantes:                                  # no debería pasar; si pasa, se dice
        manifest["contract_violation"] = {"missing_fields": faltantes}
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    """Huella del RÉGIMEN, no de la corrida.

    Se excluyen los campos que varían entre dos corridas del mismo régimen:
    identificadores acuñados por proceso y la ruta del intérprete. Si el hash
    cambiara por eso, «dos corridas del mismo régimen» sería indemostrable.
    """
    volatil = {"manifest_hash", "run_id", "organism_id"}
    reducido = {k: v for k, v in manifest.items() if k not in volatil}
    cfg = reducido.get("config")
    if isinstance(cfg, Mapping):
        reducido["config"] = {
            k: v for k, v in cfg.items() if k not in ("run_id", "organism_id")
        }
    rv = reducido.get("runtime_version")
    if isinstance(rv, Mapping):
        reducido["runtime_version"] = {
            k: v for k, v in rv.items() if k != "executable"
        }
    canonico = json.dumps(reducido, sort_keys=True, default=repr)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:16]


def not_captured_fields(manifest: Mapping[str, Any]) -> Iterable[str]:
    """Qué NO se midió, para que un informe no pueda callarlo por descuido."""
    for nombre, valor in sorted(manifest.items()):
        if isinstance(valor, Mapping) and valor.get("status") == "NOT_CAPTURED":
            yield nombre
