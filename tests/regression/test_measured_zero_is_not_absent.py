"""Un cero MEDIDO no es un valor ausente.

En Python `0.0 or D` vale `D`, así que el modismo `x or D` —que parece
sustituir el ausente por un default— sustituye también el cero. Y el cero es
la medición más informativa que hay: significa que la cantidad se midió y dio
nada.

Se encontraron diez sitios vivos con el patrón sobre cantidades medidas. Seis
mentían en dirección favorable: un margen de viabilidad de 0.0 —el organismo en
el borde— se leía como margen máximo; una pureza de memoria de 0.0 se leía como
pureza perfecta, y `min_memory_purity` es un invariante constitucional DURO; un
score de morfismo de 0.0 se leía como 1.0 y abría la puerta causal de la
herencia de reglas justo en el caso que debe cerrar.

Este fichero fija el comportamiento corregido y deja una alarma para que el
patrón no vuelva: ya volvió una vez, entre `data_loader` y `core_inference`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Sitios reparados. Cada entrada es (fichero, cantidad medida) y existe para
#: que el barrido de abajo falle con un nombre concreto y no con un número.
SITIOS_REPARADOS = (
    ("runtime/reasoning/families/core_inference.py", "fuerza de la arista causal"),
    ("runtime/world/scenario_runner.py", "margen de viabilidad previo"),
    ("runtime/conjunction/service.py", "pureza de memoria y calidad cognitiva"),
    ("runtime/organism/ecology.py", "score de morfismo en la puerta de herencia"),
    ("runtime/neural/integration/adapters.py", "incertidumbre temporal"),
    ("runtime/certification/coherence_obstruction.py", "pérdida de información del transporte"),
    ("runtime/core/data/data_loader.py", "semilla del split"),
)

#: `x or <no-cero>` sobre una cantidad. Se excluye `or 0`/`or 0.0` porque ahí el
#: default coincide con el cero y el modismo es inocuo, y se excluyen las
#: guardas legítimas contra división por cero (`len(...) or 1`, `sum(...) or 1`).
PATRON = re.compile(r"\bor\s+(?:0*[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)\b")
GUARDA_DIVISION = re.compile(r"\b(?:len|sum|max|min|count|int)\s*\([^)]*\)\s*or\s+[0-9]")


def _lineas_con_patron(rel: str) -> list[tuple[int, str]]:
    texto = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    fuera = []
    for n, linea in enumerate(texto.splitlines(), 1):
        limpia = linea.split("#", 1)[0]
        if not PATRON.search(limpia):
            continue
        if GUARDA_DIVISION.search(limpia):
            continue
        fuera.append((n, linea.strip()))
    return fuera


@pytest.mark.parametrize("rel,cantidad", SITIOS_REPARADOS)
def test_el_sitio_reparado_no_vuelve_al_patron(rel: str, cantidad: str) -> None:
    """Alarma: si el modismo reaparece en un fichero ya reparado, falla con nombre."""
    reincidencias = _lineas_con_patron(rel)
    assert not reincidencias, (
        f"MEASURED_ZERO_COERCED: reaparece `x or <default>` en {rel} "
        f"({cantidad}); un cero medido volvería a leerse como ausente.\n"
        + "\n".join(f"  l.{n}: {t}" for n, t in reincidencias)
    )


def test_el_cero_medido_sobrevive_en_la_puerta_causal_de_la_ecologia() -> None:
    """Un morfismo de score 0.0 NO puede leerse como transferencia segura."""
    fuente = (REPO / "runtime/organism/ecology.py").read_text(encoding="utf-8")
    assert 'getattr(morphism, "overall_score", None)' in fuente, (
        "la puerta causal debe pedir el score con default None y decidir "
        "explícitamente, no con `or 1.0`"
    )


def test_la_pureza_de_memoria_cero_llega_al_invariante() -> None:
    """`min_memory_purity` es invariante duro: un 0.0 medido debe llegarle."""
    from runtime.conjunction.service import _or_default

    assert _or_default(0.0, 1.0) == 0.0, "el cero medido se está sustituyendo"
    assert _or_default(None, 1.0) == 1.0, "el ausente debe tomar el default"
    assert _or_default(0.4, 1.0) == 0.4


def test_la_semilla_cero_es_una_semilla() -> None:
    """La semilla 0 es válida; convertirla en 42 rompe la reproducibilidad."""
    # Se miran sólo las líneas de código: los comentarios citan el modismo
    # viejo a propósito, para que quien lea el fichero sepa qué se arregló.
    codigo = "\n".join(
        l.split("#", 1)[0]
        for l in (REPO / "runtime/core/data/data_loader.py").read_text(encoding="utf-8").splitlines()
    )
    assert "seed or 42" not in codigo
    assert "42 if seed is None else int(seed)" in codigo


def test_num_de_core_inference_ya_cubre_el_ausente() -> None:
    """La razón por la que el `or` sobraba allí: `_num` ya sustituye el ausente.

    Si esto cambiara, los sitios reparados en `core_inference` dejarían de estar
    protegidos y habría que volver a una guarda explícita.
    """
    from runtime.reasoning.families.core_inference import _num

    assert _num(None, 1.0) == 1.0
    assert _num("no numérico", 1.0) == 1.0
    assert _num(0.0, 1.0) == 0.0, "un cero medido debe pasar tal cual"
