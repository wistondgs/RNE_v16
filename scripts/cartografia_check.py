#!/usr/bin/env python
"""G1 — la cartografía es una caché invalidable, no unas notas que envejecen solas.

Portado del que Wis construyó en Terrario, con una adición que un fallo propio
obligó a hacer (R-015): **este mapa cita ficheros de más de un árbol.**

El fallo que este gate previene es de ORDEN, no de ignorancia: construir sobre
código que no se ha leído. Aquí costó una afirmación falsa repetida durante
horas — «en RNFE nada aprende» — que salió de un barrido correcto con el alcance
equivocado. El comando cubría `runtime/neural/` entero; RNFE son tres árboles y
el entrenamiento estaba en el que no miré.

Un documento no puede decir por sí solo si sigue siendo cierto. Un hash sí. Este
comprobador recalcula el sha256 de cada fichero que la cartografía cita y lo
compara con el que tenía cuando se escribió esa sección. Si difiere, la sección
queda STALE y no se construye sobre ella hasta releerla.

La lista de ficheros por sección NO se mantiene a mano: se deriva del propio
documento, que ya cita `fichero:línea` en todas partes. Un manifiesto mantenido
aparte se desincroniza del texto que describe, que es el fallo que este gate
existe para impedir.

**Citas de otro árbol.** Un hecho central de esta cartografía —que el único
entrenamiento con provenance vive en v16 y no aquí— cita ficheros que no existen
en este repositorio. Se escriben con prefijo:

    runtime/world/parameters.py          este árbol
    v16:runtime/neural/training/n4_ranking.py     el árbol vecino
    v15:runtime/...                               el viejo

Vigilar el árbol vecino es lo que convierte «lo miré» en algo que caduca. Sin
esto, la sección que corrige R-015 envejecería en silencio: exactamente el fallo
que la originó.

    python scripts/cartografia_check.py            comprueba; sale != 0 si hay algo obsoleto
    python scripts/cartografia_check.py --write    regenera el manifiesto tras releer
    python scripts/cartografia_check.py --section "III"   limita el alcance
    python scripts/cartografia_check.py --tarea parametros
                                        filtra la lista de lectura con el registro negativo

Con `--tarea`, el gate deja de ser sólo una alarma y pasa a devolver una lista de
lectura ya filtrada: qué envejeció, menos lo que ya se aprendió que no sirve para
esa clase de tarea. Un gate que nombra cuarenta ficheros es un gate que se ignora.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registro_negativo import BYTES_POR_TOKEN, veredicto  # noqa: E402

SCHEMA = "genesis.docs.cartography-manifest/v1"
CARTOGRAPHY = PROJECT_ROOT / "docs" / "CARTOGRAFIA_GENESIS_01.md"
MANIFEST = PROJECT_ROOT / "docs" / "CARTOGRAFIA_MANIFIESTO.json"

#: Los otros árboles de RNFE. Se declaran aquí porque una afirmación sobre
#: «RNFE» que sólo barre uno es falsa, y eso ya pasó. Un árbol ausente no se
#: inventa: sus citas se reportan como INACCESIBLE, que es distinto de ABSENT.
TREES: dict[str, Path] = {
    "v16": Path("/home/wis/Desarrollo/RNE_v16"),
    "v15": Path("/home/wis/dev/rnfe.v15"),
}

#: Sólo se vigilan rutas del árbol real, con prefijo opcional de árbol vecino.
#: Un fichero citado que no existe se reporta aparte: puede ser una cita
#: equivocada o un fichero borrado, y ambas invalidan la sección igual que un
#: hash movido.
REFERENCE = re.compile(
    r"\b((?:v16:|v15:)?"
    r"(?:runtime|tests|scripts|lab|engines|contracts|canon|docs)/[\w./-]+"
    r"\.(?:py|yaml|yml|json|md))"
)


#: `fichero:línea` dentro de un enlace markdown, con o sin prefijo de árbol.
#: El hash vigila el fichero; esto vigila la CITA. Son fallos distintos: una
#: línea se pudre cuando el símbolo se desplaza, y si el fichero no cambió
#: desde que se regeneró el manifiesto la sección sigue verde apuntando a otra
#: cosa. En el árbol de Terrario esta comprobación encontró seis a la primera.
CITATION = re.compile(
    r"\((((?:v16:|v15:)?"
    r"(?:runtime|tests|scripts|lab|engines|contracts|canon|docs)/[\w./-]+"
    r"\.(?:py|yaml|yml|json|md)):(\d+))\)"
)


def rotten_citations() -> dict[str, list[str]]:
    """Citas `fichero:línea` que no resuelven, por sección.

    No comprueba que la línea diga lo que la prosa afirma --eso no es
    decidible-- sino que exista y no esté en blanco.
    """
    text = CARTOGRAPHY.read_text(encoding="utf-8")
    found: dict[str, list[str]] = {}
    for title, body in sections(text).items():
        bad: list[str] = []
        for _, reference, number in CITATION.findall(body):
            path, reason = resolve(reference)
            if path is None:
                bad.append(f"{reference}:{number} — {reason}")
                continue
            if not path.is_file():
                bad.append(f"{reference}:{number} — el fichero no existe")
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            index = int(number)
            if index < 1 or index > len(lines):
                bad.append(f"{reference}:{number} — fuera de rango ({len(lines)} líneas)")
            elif not lines[index - 1].strip():
                bad.append(f"{reference}:{number} — línea en blanco")
        if bad:
            found[title] = sorted(set(bad))
    return found


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def resolve(reference: str) -> tuple[Path | None, str]:
    """Una cita → (camino absoluto, motivo si no se puede resolver)."""
    if ":" in reference:
        prefix, relative = reference.split(":", 1)
        root = TREES.get(prefix)
        if root is None:
            return None, f"árbol desconocido: {prefix!r}"
        if not root.is_dir():
            return None, f"árbol inaccesible: {root}"
        return root / relative, ""
    return PROJECT_ROOT / reference, ""


def sections(text: str) -> dict[str, str]:
    """El documento partido por sus encabezados de primer nivel."""
    found: dict[str, str] = {}
    current = "(preámbulo)"
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("# "):
            found[current] = "\n".join(body)
            current = line[2:].strip()
            body = []
        else:
            body.append(line)
    found[current] = "\n".join(body)
    return found


#: Los dos ficheros que se describen a sí mismos. El documento nombra a su
#: manifiesto al explicar cómo caduca, y el manifiesto lo reescribe este gate en
#: cada `--write`: vigilarlo lo dejaría obsoleto siempre, que es una alarma que
#: nadie puede apagar y por tanto una alarma que se ignora.
#: Terrario lo evita no vigilando `docs/` en absoluto; aquí sí se vigila, porque
#: el canon normativo de Genesis vive en el árbol y merece caducar.
SELF = {
    "docs/CARTOGRAFIA_MANIFIESTO.json",
    "docs/CARTOGRAFIA_GENESIS_01.md",
}


def referenced(body: str) -> set[str]:
    """Las rutas que una sección cita, sin el sufijo `:línea`."""
    return {m.rstrip("/") for m in REFERENCE.findall(body)} - SELF


def head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def unwatched() -> tuple[str, ...]:
    """Secciones que no citan una sola ruta: el gate no puede invalidarlas.

    Portado del árbol de Terrario, donde doce de cuarenta y cuatro estaban en
    esa situación y las dos comprobadas salieron desfasadas. No es un fallo:
    es la frontera de este comprobador, dicha en cada corrida.
    """
    text = CARTOGRAPHY.read_text(encoding="utf-8")
    return tuple(title for title, body in sections(text).items()
                 if title != "(preámbulo)" and not referenced(body))


def survey() -> dict[str, dict[str, str]]:
    """Estado actual: por sección, el hash de cada fichero que cita."""
    text = CARTOGRAPHY.read_text(encoding="utf-8")
    state: dict[str, dict[str, str]] = {}
    for title, body in sections(text).items():
        paths = referenced(body)
        if not paths:
            continue
        hashes: dict[str, str] = {}
        for reference in sorted(paths):
            path, problema = resolve(reference)
            if path is None:
                hashes[reference] = "INACCESIBLE"
            else:
                hashes[reference] = file_sha256(path) if path.is_file() else "ABSENT"
        state[title] = hashes
    return state


def write_manifest() -> int:
    state = survey()
    MANIFEST.write_text(json.dumps({
        "schema_version": SCHEMA,
        "document": "docs/CARTOGRAFIA_GENESIS_01.md",
        "written_at": date.today().isoformat(),
        "head": head(),
        "trees": {name: str(root) for name, root in TREES.items()},
        "sections": {title: {"files": files} for title, files in state.items()},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    covered = sum(len(files) for files in state.values())
    ajenos = sum(1 for files in state.values() for r in files if ":" in r)
    print(f"manifiesto escrito: {len(state)} secciones, {covered} ficheros vigilados "
          f"({ajenos} de otro árbol)")
    return 0


def check(only: str | None, tarea: str | None = None) -> int:
    if not MANIFEST.is_file():
        print(f"no hay manifiesto: {MANIFEST.relative_to(PROJECT_ROOT)}")
        print("ejecuta --write tras leer el código que la cartografía describe")
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = {title: entry["files"] for title, entry in manifest["sections"].items()}
    current = survey()

    # G1 dice qué envejeció; el registro negativo dice qué de eso no vale la pena
    # abrir para ESTA clase de tarea. Unidos, lo que sale no es «lee estas
    # secciones» sino una lista de lectura ya filtrada.
    stale: dict[str, list[str]] = {}
    descartes: list[tuple[str, str, int]] = []
    for title, files in current.items():
        if only and only.lower() not in title.lower():
            continue
        was = recorded.get(title)
        if was is None:
            stale[title] = ["sección nueva, sin hashes registrados"]
            continue
        reasons = []
        for reference, digest in sorted(files.items()):
            before = was.get(reference)
            if before is None:
                motivo = f"cita nueva: {reference}"
            elif digest == "INACCESIBLE":
                motivo = f"árbol no montado: {reference}"
            elif digest == "ABSENT":
                motivo = f"ya no existe: {reference}"
            elif digest != before:
                motivo = f"cambió: {reference}"
            else:
                continue
            if tarea and ":" not in reference:
                descartado, porque, bytes_ = veredicto(reference, tarea)
                if descartado:
                    descartes.append((reference, porque, bytes_))
                    reasons.append(f"{motivo}  —  DESCARTADO: {porque}")
                    continue
            reasons.append(motivo)
        for reference in sorted(set(was) - set(files)):
            reasons.append(f"dejó de citarse: {reference}")
        if reasons:
            stale[title] = reasons

    ciegas = unwatched()
    if ciegas and not only:
        print(f"SIN VIGILANCIA — {len(ciegas)} sección(es) no citan ninguna ruta.\n")
        for title in ciegas:
            print(f"      {title}")
        print()

    podridas = {t: v for t, v in rotten_citations().items()
                if not only or only.lower() in t.lower()}

    scope = f" (sección ~ {only!r})" if only else ""
    if podridas:
        print(f"CITAS ROTAS{scope} — {len(podridas)} sección(es):\n")
        for title, reasons in podridas.items():
            print(f"  {title}")
            for reason in reasons:
                print(f"      {reason}")
            print()
        if not stale:
            print("G1: los hashes están al día; lo que falla son las citas de línea.")
            return 1
    if not stale:
        vigilados = sum(len(f) for t, f in current.items()
                        if not only or only.lower() in t.lower())
        print(f"cartografía al día{scope}: {vigilados} ficheros vigilados")
        return 0

    print(f"CARTOGRAFÍA OBSOLETA{scope} — {len(stale)} sección(es):\n")
    for title, reasons in stale.items():
        print(f"  {title}")
        for reason in reasons:
            print(f"      {reason}")
        print()
    if descartes:
        evitados = sum(b for _, _, b in descartes) // BYTES_POR_TOKEN
        unicos = {ruta for ruta, _, _ in descartes}
        print(f"  {len(unicos)} fichero(s) descartado(s) para «{tarea}»: "
              f"hasta ~{evitados} tokens que no hace falta releer.")
        print("  Si alguno resulta que sí hacía falta:")
        print(f"      python scripts/registro_negativo.py falso-descarte <ruta> {tarea}\n")
    print("G1: léelas antes de construir sobre ellas, reescríbelas y corre --write.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="regenera el manifiesto (sólo tras releer el código)")
    parser.add_argument("--section", default=None,
                        help="limita la comprobación a las secciones que contengan este texto")
    parser.add_argument("--tarea", default=None,
                        help="clase de tarea; filtra la lista de lectura con el registro negativo")
    args = parser.parse_args()
    return write_manifest() if args.write else check(args.section, args.tarea)


if __name__ == "__main__":
    raise SystemExit(main())
