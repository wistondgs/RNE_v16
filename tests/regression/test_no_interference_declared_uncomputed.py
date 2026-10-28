"""B24: `no_interference` está DECLARADO como campo no computado, y nadie lo consume.

Estado verificado:

- Se escribe siempre `True`, sin lógica ninguna, en los 4 sitios de escritura
  (`runtime/memory/mfm_lite/episode_store.py:41,67,94`,
   `runtime/organism/experience.py:221`) más el default de la facade.
- La columna es NOT NULL (`sqlite_store.py:186`, `postgres/schema.sql:127`), así
  que migrar a nullable es caro.
- **Nadie lo lee para decidir nada.** Los backends solo lo persisten y lo
  devuelven en el round-trip.
- El canon lo nombra como desiderátum ("no interferencia",
  `canon/experimental/RNFE_blueprint_matematico_latex.md:649`; "no-interferencia",
  `canon/provisional/ROADMAP_RNFE_v2.md:201`) pero **no lo define
  operativamente**, y nada en `canon/normative/` fija un criterio computable.

Decisión fijada acá: NO se inventa una lógica para que "parezca" computado. Se
documenta inequívocamente como no computado y estos tests son el tripwire:

1. si aparece un CONSUMIDOR (alguien que lo lea para decidir), el test falla y
   obliga a revisar la decisión (o computarlo de verdad, o retirar la columna);
2. si se borra la advertencia de los sitios de escritura, el test falla.
"""

import ast
from pathlib import Path

_RUNTIME = Path("runtime")

# Sitios donde el campo PUEDE aparecer, y por qué.
_WRITE_SITES = {
    "runtime/memory/mfm_lite/episode_store.py",   # escritura (default de schema)
    "runtime/organism/experience.py",             # escritura (default de schema)
    "runtime/storage/facade.py",                  # firma + construcción del record
    "runtime/storage/records.py",                 # definición del campo
}
# Persistencia pura: serializan/deserializan la columna, no la interpretan.
_PERSISTENCE_SITES = {
    "runtime/storage/backends/sqlite_store.py",
    "runtime/storage/backends/postgres_store.py",
}
_ALLOWED = _WRITE_SITES | _PERSISTENCE_SITES


def _py_files():
    return sorted(p for p in _RUNTIME.rglob("*.py") if "__pycache__" not in p.parts)


def _mentions(path: Path) -> bool:
    return "no_interference" in path.read_text(encoding="utf-8")


def test_no_hay_sitios_nuevos_que_toquen_no_interference():
    """Si un módulo nuevo lo toca, hay que decidir: computarlo o retirarlo."""
    touching = {p.as_posix() for p in _py_files() if _mentions(p)}
    unexpected = touching - _ALLOWED
    assert not unexpected, (
        "módulos nuevos tocan `no_interference`, un campo NO COMPUTADO (B24): "
        f"{sorted(unexpected)}. Antes de usarlo hay que computarlo de verdad."
    )
    # Y los sitios conocidos siguen siendo los que creemos.
    assert _WRITE_SITES <= touching


def _field_reads(tree: ast.AST) -> list[int]:
    """Líneas donde se LEE el valor del campo: `x.no_interference` o `x["no_interference"]`.

    Escribirlo como keyword de una llamada (`no_interference=True`), declararlo
    como campo del dataclass o nombrarlo como parámetro NO son lecturas: no
    consumen el valor. Cualquier lectura sí lo consume, sin importar dónde
    aparezca (condición, comprensión, argumento, return...).
    """
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "no_interference"
            and isinstance(node.ctx, ast.Load)
        ):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "no_interference"
        ):
            lines.append(node.lineno)
    return lines


def test_nadie_consume_no_interference_para_decidir():
    """El corazón de B24: CERO consumidores en runtime/.

    Único permiso: los dos backends, que serializan/deserializan la columna sin
    interpretarla. Cualquier otra lectura del valor es tratarlo como evidencia,
    y el valor no es evidencia de nada: es un `True` constante.
    """
    consumers = []
    for path in _py_files():
        posix = path.as_posix()
        if posix in _PERSISTENCE_SITES or not _mentions(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consumers += [f"{posix}:{line}" for line in _field_reads(tree)]

    assert not consumers, (
        "alguien está CONSUMIENDO `no_interference` como si fuera evidencia, pero es "
        f"un campo NO COMPUTADO (siempre True por default de schema): {consumers}. "
        "O se computa de verdad, o no se usa."
    )


def test_el_tripwire_de_consumidores_realmente_dispara():
    """Un tripwire que no puede fallar es otra mentira. Prueba de mutación."""
    consumidor_if = ast.parse("def f(m):\n    if m.no_interference:\n        return 1\n")
    consumidor_filtro = ast.parse("def f(ms):\n    return [m for m in ms if m.no_interference]\n")
    consumidor_dict = ast.parse("def f(d):\n    return d['no_interference']\n")
    escritura = ast.parse("def f():\n    write(no_interference=True)\n")
    declaracion = ast.parse("class R:\n    no_interference: bool = True\n")

    assert _field_reads(consumidor_if) == [2]
    assert _field_reads(consumidor_filtro) == [2]
    assert _field_reads(consumidor_dict) == [2]
    assert _field_reads(escritura) == []      # escribirlo no es consumirlo
    assert _field_reads(declaracion) == []    # declararlo tampoco


def test_los_sitios_de_escritura_declaran_que_no_esta_computado():
    """La advertencia tiene que estar donde se escribe la mentira."""
    for posix in sorted(_WRITE_SITES):
        source = Path(posix).read_text(encoding="utf-8")
        assert "B24" in source, f"{posix} no declara B24"
        lowered = source.lower()
        assert "no computado" in lowered, f"{posix} no declara que el campo NO está computado"
        assert "no confiar" in lowered, f"{posix} no advierte que no hay que confiar en el valor"


def test_el_campo_sigue_siendo_not_null_en_los_dos_backends():
    """Fija por qué la salida honesta es documentar y no migrar a nullable."""
    sqlite = Path("runtime/storage/backends/sqlite_store.py").read_text(encoding="utf-8")
    postgres = Path("runtime/storage/backends/postgres/schema.sql").read_text(encoding="utf-8")
    assert "no_interference INTEGER NOT NULL" in sqlite
    assert "no_interference BOOLEAN NOT NULL" in postgres


def test_el_valor_persistido_es_el_default_de_schema_no_una_medicion():
    """Lo único que se puede afirmar del campo: que es el default, no evidencia."""
    from runtime.storage.records import MemoryRecord

    record = MemoryRecord(
        memory_id="m1", run_id="r1", episode_id="e1", scale="micro", structure_json={},
    )
    # El default existe y es True — y eso es exactamente todo lo que significa.
    assert record.no_interference is True
    # La advertencia vive en el docstring/comentarios del módulo del record.
    source = Path("runtime/storage/records.py").read_text(encoding="utf-8")
    assert "NO CONFIAR EN ESTE VALOR" in source
