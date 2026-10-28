"""Familias de perturbación declaradas — qué le hace el mundo al organismo.

Hasta aquí la perturbación era una función escrita a mano en el kernel de vida:
espiga cada 7 pasos, y entre espigas un ciclo de tres valores. Cuatro valores
distintos, período 21, determinista y sin ruido. Por la ley de Ashby eso fija
la variedad reguladora requerida en 4: **una tabla de cuatro entradas regula
ese mundo perfectamente**, que es justo lo que el canon excluye como «ejecutar
una política preprogramada».

Este módulo no cambia esa perturbación: la vuelve **declarable**. La familia
pasa a ser un dato con nombre, semilla y variedad declarada, de modo que:

  - se puede variar sin tocar el runtime — es el defecto que hacía que el mundo
    de Genesis no se pudiera mover, porque estaba escrito a mano;
  - se puede **ablacionar**: `constant` es el control degenerado y `legacy` es
    el brazo que reproduce byte a byte lo que había;
  - viaja en la traza, así que el observador sabe a qué se enfrentó el
    organismo en vez de tener que deducirlo del código de esa versión.

`legacy` es el default y reproduce exactamente `LifeKernel._perturbation`. Sin
declarar familia, el comportamiento es idéntico al anterior.

La variedad declarada es el número de valores distintos que la familia puede
emitir, o `None` cuando es continua. El observador la necesita para decir si un
resultado de regulación significa algo: contra variedad 1 no significa nada.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Dict, Mapping


__all__ = [
    "DisturbanceFamily",
    "FAMILIES",
    "resolve",
    "describe",
]


def _unit_noise(seed: int, step: int) -> float:
    """Ruido reproducible en [0, 1) — determinista en (semilla, paso).

    Se deriva por hash y no por un RNG con estado: dos corridas con la misma
    semilla dan la misma secuencia aunque se salten pasos o se reanuden desde
    un checkpoint, que es la propiedad que un experimento reanudable necesita.
    """
    digest = hashlib.blake2b(f"{seed}:{step}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


@dataclass(frozen=True)
class DisturbanceFamily:
    """Una familia de perturbación: cómo varía la entrada externa con el paso.

    Attributes:
        name: Identificador estable; es lo que viaja en la traza.
        fn: (paso, semilla) -> entrada externa.
        variety: Valores distintos que puede emitir, o None si es continua.
        stationary: False si la distribución cambia con el tiempo.
        description: Qué le exige al regulador. En una frase.
    """

    name: str
    fn: Callable[[int, int], float]
    variety: int | None
    stationary: bool
    description: str

    def at(self, step: int, *, seed: int = 0) -> float:
        return float(self.fn(int(step), int(seed)))

    def to_dict(self) -> Dict[str, object]:
        return {
            "family": self.name,
            "declared_variety": self.variety,
            "stationary": self.stationary,
            "description": self.description,
        }


# ── Las familias ─────────────────────────────────────────────────────────────

def _legacy(step: int, seed: int) -> float:
    """La de siempre: espiga 0.14 cada 7 pasos, y {0.04, 0.05, 0.06} entre medias."""
    if step % 7 == 6:
        return 0.14
    return 0.04 + 0.01 * float(step % 3)


def _constant(step: int, seed: int) -> float:
    """Control degenerado. Variedad 1: nada que regular, y sirve para probarlo."""
    return 0.04


def _ramp(step: int, seed: int) -> float:
    """Deriva monótona. La respuesta correcta de ayer deja de serlo hoy."""
    return min(0.30, 0.02 + 0.0008 * float(step))


def _regime_step(step: int, seed: int) -> float:
    """Un solo cambio de régimen, a mitad. Es la forma canónica de «recuperación»."""
    return 0.04 if step < 500 else 0.16


def _pulse(step: int, seed: int) -> float:
    """Espigas aisladas en pasos irregulares: exige distinguir transitorio de régimen."""
    return 0.22 if _unit_noise(seed, step) < 0.06 else 0.04


def _random_walk(step: int, seed: int) -> float:
    """Paseo acotado y no estacionario. Ninguna tabla finita lo cubre.

    COSTE DECLARADO: O(paso) por llamada, porque un paseo es la suma de sus
    incrementos y no hay atajo que conserve la reproducibilidad fuera de orden.
    Una corrida de N pasos cuesta O(N²): a 1.200 pasos son ~720 mil iteraciones
    triviales, despreciable; a 100 mil pasos, no. No se memoiza a propósito —
    un caché de módulo introduce estado compartido y rompe la garantía de que
    dos procesos con la misma semilla vean la misma secuencia. Si hace falta
    una corrida larga, la salida correcta es precalcular la serie y pasarla,
    no esconder estado aquí.
    """
    value = 0.08
    for t in range(step + 1):
        value += (_unit_noise(seed, t) - 0.5) * 0.012
        value = max(0.01, min(0.30, value))
    return value


def _switching(step: int, seed: int) -> float:
    """Dos regímenes que se alternan en momentos impredecibles.

    Exige detectar el cambio, no memorizar el calendario: el organismo no puede
    saber cuándo llega, sólo que llegó.
    """
    block = step // 40
    return 0.05 if _unit_noise(seed, block) < 0.5 else 0.18


FAMILIES: Mapping[str, DisturbanceFamily] = {
    f.name: f
    for f in (
        DisturbanceFamily("legacy", _legacy, 4, True,
                          "Periódica de período 21 con cuatro valores. Una tabla la regula."),
        DisturbanceFamily("constant", _constant, 1, True,
                          "Control degenerado: variedad 1, no hay nada que regular."),
        DisturbanceFamily("ramp", _ramp, None, False,
                          "Deriva monótona: la respuesta correcta cambia con el tiempo."),
        DisturbanceFamily("regime_step", _regime_step, 2, False,
                          "Un cambio de régimen: mide recuperación tras perturbación."),
        DisturbanceFamily("pulse", _pulse, 2, True,
                          "Espigas irregulares: exige separar transitorio de régimen."),
        DisturbanceFamily("random_walk", _random_walk, None, False,
                          "Paseo acotado no estacionario: ninguna tabla finita lo cubre."),
        DisturbanceFamily("switching", _switching, 2, False,
                          "Regímenes que alternan sin aviso: exige detectar el cambio."),
    )
}


def resolve(name: str | None) -> DisturbanceFamily:
    """Devuelve la familia por nombre. `None` o vacío ⇒ `legacy`.

    Raises:
        KeyError: nombre desconocido. Falla en vez de caer a un default
            silencioso: una corrida que cree estar bajo `switching` y corre
            bajo `legacy` produce un resultado indistinguible y falso.
    """
    key = (name or "legacy").strip().lower()
    if key not in FAMILIES:
        raise KeyError(
            f"DISTURBANCE_FAMILY_UNKNOWN: {name!r}; conocidas: {sorted(FAMILIES)}"
        )
    return FAMILIES[key]


def describe(name: str | None, *, seed: int = 0, steps: int = 21) -> Dict[str, object]:
    """Ficha de la familia con una muestra medida — para la traza y el informe.

    `observed_distinct` es lo que la familia emitió de hecho en esa ventana, no
    lo que declara poder emitir. Cuando difieren, manda el medido: la ventana
    puede ser más corta que el período.
    """
    family = resolve(name)
    sample = [round(family.at(t, seed=seed), 6) for t in range(max(1, steps))]
    return {
        **family.to_dict(),
        "seed": seed,
        "sample_window": steps,
        "observed_distinct": len(set(sample)),
        "sample": sample[:21],
    }
