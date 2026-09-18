#!/usr/bin/env python
"""Memoriza qué NO sirve leer, y cuenta si eso ahorra algo de verdad.

Un mapa que registra qué es relevante ayuda una vez. Un registro que recuerda
qué resultó **irrelevante** ayuda cada vez que la misma clase de tarea vuelve,
porque los callejones sin salida son más numerosos que los caminos y se repiten
más. `observer/probes.py` son stubs con `NotImplementedError`; abrirlo para
entender qué se escribe en la traza es gasto puro, y se vuelve a pagar en cada
sesión que no lo recuerde.

Esto prueba **un solo mecanismo** y lo mide. Sin medición sería exactamente la
clase de cosa plausible-pero-no-verificada que este proyecto lleva dos días
encontrando: un sistema para evitar lecturas desperdiciadas cuyo propio ahorro
nadie comprobó.

El contador lleva los dos lados. Lo ahorrado son los bytes que no se abrieron.
El costo son los **falsos descartes**: las veces que el registro dijo «no sirve»
y el fichero hacía falta. Un contador que sólo sume lo primero sube siempre y no
dice nada.

    python scripts/registro_negativo.py marcar <ruta> <tarea> "<motivo>"
    python scripts/registro_negativo.py consultar <ruta> <tarea>
    python scripts/registro_negativo.py falso-descarte <ruta> <tarea>
    python scripts/registro_negativo.py informe
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Base propia. `.terrario/terrario.db` es la del laboratorio y está vigilada
#: por la suite: cambiarla falla la sesión entera. Además son dos cosas que no
#: tienen por qué versionarse juntas.
DB = PROJECT_ROOT / ".cartografia" / "mapa.db"

#: Los tokens no se cuentan: se acotan. Cuatro bytes por token es la
#: aproximación de andar por casa, y el tamaño del fichero supone que se habría
#: leído entero — cuando en la práctica muchas lecturas son rebanadas. Por eso
#: lo que sale es una COTA SUPERIOR del ahorro, no una estimación centrada.
#: Leerlo como estimación inflaría el beneficio justo en la dirección que le
#: conviene al propio registro.
BYTES_POR_TOKEN = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS irrelevante (
    ruta TEXT NOT NULL, tarea TEXT NOT NULL, motivo TEXT NOT NULL,
    bytes INTEGER NOT NULL, anotado_en TEXT NOT NULL,
    PRIMARY KEY (ruta, tarea)
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    en TEXT NOT NULL,
    clase TEXT NOT NULL CHECK (clase IN ('CONSULTA','DESCARTE','FALSO_DESCARTE','ANOTACION')),
    ruta TEXT, tarea TEXT, bytes INTEGER NOT NULL DEFAULT 0
);
"""


def conectar() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(DB)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(SCHEMA)
    return conexion


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tamano(ruta: str) -> int:
    camino = PROJECT_ROOT / ruta
    return camino.stat().st_size if camino.is_file() else 0


def _evento(conexion, clase: str, ruta: str | None, tarea: str | None, bytes_: int = 0) -> None:
    conexion.execute(
        "INSERT INTO eventos (en, clase, ruta, tarea, bytes) VALUES (?,?,?,?,?)",
        (ahora(), clase, ruta, tarea, bytes_))


def marcar(ruta: str, tarea: str, motivo: str) -> int:
    """Este fichero se abrió para esta clase de tarea y no sirvió."""
    with conectar() as conexion:
        bytes_ = _tamano(ruta)
        conexion.execute(
            "INSERT OR REPLACE INTO irrelevante (ruta,tarea,motivo,bytes,anotado_en) "
            "VALUES (?,?,?,?,?)", (ruta, tarea, motivo, bytes_, ahora()))
        _evento(conexion, "ANOTACION", ruta, tarea, bytes_)
    print(f"anotado: {ruta} no sirve para «{tarea}» ({bytes_} bytes) — {motivo}")
    return 0


def veredicto(ruta: str, tarea: str) -> tuple[bool, str, int]:
    """Consulta sin imprimir, para que otro gate la use.

    Devuelve (descartado, motivo, bytes) y **registra el evento**. Que lo
    registre importa: el ahorro sólo es medible donde ocurre, y ocurre cuando
    otro paso del trabajo decide no abrir algo. Una consulta que no se cuenta es
    un ahorro que no existe para el contador.
    """
    with conectar() as conexion:
        _evento(conexion, "CONSULTA", ruta, tarea)
        fila = conexion.execute(
            "SELECT motivo, bytes FROM irrelevante WHERE ruta=? AND tarea=?",
            (ruta, tarea)).fetchone()
        if fila is None:
            return False, "", 0
        _evento(conexion, "DESCARTE", ruta, tarea, fila["bytes"])
        return True, fila["motivo"], fila["bytes"]


def consultar(ruta: str, tarea: str) -> int:
    """¿Vale la pena abrirlo? Sale 1 si el registro dice que no."""
    descartado, motivo, bytes_ = veredicto(ruta, tarea)
    if not descartado:
        print(f"ábrelo: sin registro para «{tarea}»")
        return 0
    print(f"NO lo abras: {motivo}  (hasta ~{bytes_ // BYTES_POR_TOKEN} tokens)")
    return 1


def falso_descarte(ruta: str, tarea: str) -> int:
    """El registro dijo que no servía y hacía falta. Esto es el costo."""
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT bytes FROM irrelevante WHERE ruta=? AND tarea=?",
            (ruta, tarea)).fetchone()
        if fila is None:
            print(f"no había descarte de {ruta} para «{tarea}»; nada que corregir")
            return 1
        conexion.execute("DELETE FROM irrelevante WHERE ruta=? AND tarea=?", (ruta, tarea))
        _evento(conexion, "FALSO_DESCARTE", ruta, tarea, fila["bytes"])
    print(f"falso descarte anotado y registro retirado: {ruta} / «{tarea}»")
    return 0


def informe() -> int:
    with conectar() as conexion:
        def cuenta(clase: str) -> tuple[int, int]:
            fila = conexion.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM eventos WHERE clase=?",
                (clase,)).fetchone()
            return fila["n"], fila["b"]

        consultas, _ = cuenta("CONSULTA")
        descartes, bytes_evitados = cuenta("DESCARTE")
        falsos, bytes_falsos = cuenta("FALSO_DESCARTE")
        anotaciones, _ = cuenta("ANOTACION")
        vivos = conexion.execute("SELECT COUNT(*) n FROM irrelevante").fetchone()["n"]

    evitados = bytes_evitados // BYTES_POR_TOKEN
    # El costo de un falso descarte no es sólo releer el fichero: es haber
    # trabajado sin él. Contarlo como su tamaño es el suelo del costo, no el
    # costo, y se dice aquí para que nadie lea el neto como si fuera exacto.
    coste = bytes_falsos // BYTES_POR_TOKEN

    print("REGISTRO NEGATIVO")
    print(f"  anotaciones vivas          {vivos}")
    print(f"  consultas                  {consultas}")
    print(f"  descartes                  {descartes}")
    print(f"  falsos descartes           {falsos}")
    print()
    print(f"  tokens evitados (cota sup) {evitados:>8}")
    print(f"  coste de falsos (cota inf) {coste:>8}")
    print(f"  neto (mejor caso)          {evitados - coste:>8}")
    if consultas:
        print(f"  tasa de acierto            {descartes / consultas:.0%}")
    if descartes and not falsos:
        print("\n  Sin falsos descartes todavía: el neto es el mejor caso, no el caso.")
    if not consultas:
        print("\n  Sin consultas todavía: nada que medir. El registro sólo ahorra al releerse.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("marcar"); p.add_argument("ruta"); p.add_argument("tarea"); p.add_argument("motivo")
    p = sub.add_parser("consultar"); p.add_argument("ruta"); p.add_argument("tarea")
    p = sub.add_parser("falso-descarte"); p.add_argument("ruta"); p.add_argument("tarea")
    sub.add_parser("informe")
    args = parser.parse_args()

    if args.orden == "marcar":
        return marcar(args.ruta, args.tarea, args.motivo)
    if args.orden == "consultar":
        return consultar(args.ruta, args.tarea)
    if args.orden == "falso-descarte":
        return falso_descarte(args.ruta, args.tarea)
    return informe()


if __name__ == "__main__":
    raise SystemExit(main())
