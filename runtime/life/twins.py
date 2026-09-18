"""Gemelos causales: dos organismos que empiezan siendo el mismo (§P1, ola 6).

Una intervención `do(U)` sólo significa algo si lo que se compara después
difiere **por la intervención y por nada más**. Eso exige demostrar, antes de
intervenir, que los dos puntos de partida son el mismo:

    X₀ᴬ = X₀ᴮ

**Demostrado, no supuesto.** El harness calcula la huella del punto de partida
completo de cada gemelo y **se niega a continuar si difieren**. Es la lección
que Terrario ya había pagado (`7208ebe`): un organismo con tensores que son
nodos de grafo no se puede `deepcopy`, y construir cada gemelo de cero bajo la
misma configuración es además la opción más fuerte — porque entonces la
identidad se comprueba en vez de heredarse.

## Qué entra en la huella, y por qué

Todo lo longitudinal que el kernel posee, que es exactamente lo que las olas 1
a 6 le fueron dando: el organismo, su linaje, Λ, el mundo, el lazo ρₜ y el
estado neural. Si algo de eso viviera fuera del kernel, dos gemelos con la misma
huella podrían no ser el mismo organismo — y esa fue la situación real hasta
ayer, con el mundo reiniciándose cada bloque.

## Igualdad SALVO renombrado de identificadores acuñados

Dos gemelos son dos ejecuciones: comparten estado y no comparten identidad de
corrida. Medido sobre dos gemelos construidos igual, **todas** las diferencias
resultaron ser identificadores acuñados por proceso —`lin-<uuid>`,
`life-<uuid>`, `episode-<uuid>`— repartidos por dentro de los payloads: 267
campos distintos en el estado neural y **ni uno solo** de fisiología real.

Borrarlos sería demasiado: dejaría de verse que dos campos apuntan a la misma
entidad, y dos organismos distintos podrían parecer el mismo. Así que no se
borran, **se canonizan**: cada identificador acuñado se sustituye por su ordinal
de aparición, de forma consistente en todo el payload. Dos payloads son iguales
si lo son salvo un renombrado coherente de esos identificadores — que es
exactamente lo que significa «el mismo organismo en otra corrida».

Tampoco entran los timestamps (§XLII).

## Observar no debe mutar

Terrario lo midió y costó tres resultados: percibir una sonda avanzaba el estado
recurrente y el contador de pasos, así que examinar contaminaba lo examinado y el
ORDEN de los exámenes pasaba a formar parte del resultado. Aquí la huella se
calcula **sólo con lecturas de payloads ya exportados**; no invoca al organismo
ni al mundo.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

TWIN_IDENTITY_SCHEMA = "twin-identity-v1"

#: Claves que NO definen el punto de partida: identifican la corrida, no al ser.
#:
#: Es una REGLA, no una lista cerrada. La lista cerrada ya falló: llevaba
#: `run_id` y el estado neural guarda el suyo como `dynamic_chain.last_run_id`,
#: así que dos gemelos idénticos salían divergentes por un nombre de campo. Un
#: campo que termina en `run_id` identifica una ejecución por construcción de su
#: nombre; lo mismo con las marcas de tiempo.
_VOLATILE_SUFFIXES = ("run_id", "timestamp", "created_at", "updated_at", "_at")


def _is_volatile(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return any(key == s or key.endswith(s) for s in _VOLATILE_SUFFIXES)


class TwinsDiverged(AssertionError):
    """Dos supuestos gemelos no empiezan iguales. No se interviene a ciegas."""


#: Un identificador acuñado: un prefijo legible y una tirada de al menos ocho
#: hexadecimales. Cubre `lin-…`, `life-…`, `episode-…`, `org-…`, `mod-…`,
#: `rb-…` y `state-0-org-…` sin enumerarlos, que envejecería mal.
_MINTED = re.compile(r"^(.*?)([0-9a-f]{8}[0-9a-f-]*)$")


def _canonical(value: Any, minted: Optional[Dict[str, str]] = None) -> Any:
    """Estructura comparable: sin volátiles, ordenada, con los ids canonizados.

    `minted` acumula el renombrado y se comparte por toda la estructura, así que
    el mismo identificador recibe el mismo ordinal dondequiera que aparezca. Eso
    es lo que conserva «estos dos campos apuntan a la misma entidad».
    """
    if minted is None:
        minted = {}
    if isinstance(value, Mapping):
        return {
            k: _canonical(v, minted)
            for k, v in sorted(value.items())
            if not _is_volatile(k)
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(v, minted) for v in value]
    if isinstance(value, float):
        # Un float que sólo difiere en el último bit no es otro organismo; que la
        # huella diga que sí volvería el harness inservible en la práctica.
        return round(value, 9)
    if isinstance(value, str):
        coincidencia = _MINTED.match(value)
        if coincidencia:
            prefijo = coincidencia.group(1)
            if value not in minted:
                minted[value] = f"{prefijo}#{len(minted)}"
            return minted[value]
    return value


def identity_components(kernel: Any) -> Dict[str, Any]:
    """Las seis piezas del punto de partida, cada una con su huella propia.

    Se devuelven por separado, no sólo agregadas: cuando dos gemelos difieren,
    lo útil no es saber QUE difieren sino EN QUÉ. Un harness que sólo entrega un
    hash obliga a reconstruir a mano dónde se rompió la igualdad.
    """
    estado = getattr(kernel, "organism_state", None)
    linaje = getattr(kernel, "lineage", None)
    piezas: Dict[str, Any] = {
        "organism": estado.to_dict() if hasattr(estado, "to_dict") else None,
        "lineage": linaje.to_dict() if hasattr(linaje, "to_dict") else None,
        "parameters": getattr(kernel, "_parameter_state", None),
        "world": getattr(kernel, "_world_state", None),
        "autoevolution": getattr(kernel, "_autoevolution_state", None),
        "neural": getattr(kernel, "_neural_state", None),
    }
    # UN solo mapa de renombrado para las seis piezas: si cada una tuviera el
    # suyo, dos referencias al mismo linaje desde `organism` y desde `lineage`
    # podrían recibir ordinales distintos y la huella diría que difieren.
    minted: Dict[str, str] = {}
    return {nombre: _canonical(valor, minted) for nombre, valor in piezas.items()}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=repr).encode("utf-8")
    ).hexdigest()[:16]


def identity_hash(kernel: Any) -> str:
    """Huella del punto de partida completo. Determinista y sin volátiles."""
    return _digest(identity_components(kernel))


def component_hashes(kernel: Any) -> Dict[str, str]:
    """Huella pieza a pieza, para localizar una divergencia en vez de sólo verla."""
    return {n: _digest(v) for n, v in identity_components(kernel).items()}


@dataclass(frozen=True)
class OriginCheck:
    """El veredicto de `X₀ᴬ = X₀ᴮ`, con el detalle que hace falta para actuar."""

    schema_version: str
    identical: bool
    hash_a: str
    hash_b: str
    diverging: tuple[str, ...]
    components_a: Dict[str, str]
    components_b: Dict[str, str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identical": self.identical,
            "hash_a": self.hash_a,
            "hash_b": self.hash_b,
            "diverging": list(self.diverging),
            "components_a": dict(self.components_a),
            "components_b": dict(self.components_b),
        }


def compare_origin(a: Any, b: Any) -> OriginCheck:
    """Compara sin lanzar. Útil para medir cuánto divergen dos configuraciones."""
    ca, cb = component_hashes(a), component_hashes(b)
    divergentes = tuple(sorted(n for n in ca if ca[n] != cb.get(n)))
    return OriginCheck(
        schema_version=TWIN_IDENTITY_SCHEMA,
        identical=not divergentes,
        hash_a=identity_hash(a),
        hash_b=identity_hash(b),
        diverging=divergentes,
        components_a=ca,
        components_b=cb,
    )


def assert_same_origin(a: Any, b: Any) -> OriginCheck:
    """`X₀ᴬ = X₀ᴮ` o se niega a continuar.

    Negarse es el punto. Intervenir sobre dos organismos que no empiezan iguales
    produce una diferencia que nadie puede atribuir, y el resultado se ve igual
    de convincente que uno válido.
    """
    veredicto = compare_origin(a, b)
    if not veredicto.identical:
        detalle = ", ".join(
            f"{n}: {veredicto.components_a[n]} ≠ {veredicto.components_b.get(n)}"
            for n in veredicto.diverging
        )
        raise TwinsDiverged(
            f"los gemelos NO comparten punto de partida "
            f"({veredicto.hash_a} ≠ {veredicto.hash_b}); difieren en → {detalle}"
        )
    return veredicto


def intervene(
    kernel: Any, values: Mapping[str, Any], *, reason: str = "do(U)"
) -> Dict[str, Any]:
    """`do(U = u')` sobre Λ, por la única autoridad de materialización.

    Pasa por `apply_parameter_intent` y no por asignación directa: así la
    intervención queda en el ledger con su procedencia y sus hashes de Λ, y una
    campaña puede reconstruir después qué se intervino y cuándo. Una `do(U)`
    que no deja rastro es indistinguible de una deriva.

    Se aplica sobre el runner del gemelo —que es quien consume Λ— y el kernel lo
    recoge al cerrar el paso, igual que cualquier otra fuente.
    """
    runner = getattr(kernel, "_runner", None)
    if runner is None:
        raise RuntimeError("twin_has_no_runner: interviene tras el primer paso")
    return runner.apply_parameter_intent(dict(values), source="experiment", reason=reason)
