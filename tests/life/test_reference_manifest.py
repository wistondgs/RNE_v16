"""Ola 5 — el manifest del régimen de referencia (§LXV, §CXI).

Un manifest existe para que una medición se pueda situar: «esto se midió
**aquí**». Las dos formas de que falle son opuestas y las dos son graves.

    callar un campo que no se pudo capturar   ⇒ invita a creer que es reproducible
    meter en el hash algo que varía por corrida ⇒ dos corridas del mismo régimen
                                                  no se pueden declarar iguales

Estas pruebas fijan las dos.
"""

from __future__ import annotations

from runtime.life import LifeKernelConfig, reference_manifest
from runtime.world import parameters


def _config(**kw):
    base = dict(
        run_id="manifest-test",
        organism_id="org-manifest",
        scenarios=("thermal_homeostasis",),
        block_size=8,
        max_steps=0,
        restore=False,
    )
    base.update(kw)
    return LifeKernelConfig(**base)


def test_estan_los_doce_campos_que_pide_la_seccion():
    """§LXV enumera doce. Faltar uno en silencio es la falla que importa."""
    man = reference_manifest.build(config=_config())
    for campo in reference_manifest.REQUIRED_FIELDS:
        assert campo in man, f"el manifest no lleva {campo!r}"
    assert "contract_violation" not in man


def test_lo_no_capturado_se_declara_dentro_de_los_datos():
    """Patrón B24 — «no medido» es un valor, no una ausencia.

    Sin HEAD, el manifest debe DECIR que no lo tiene. Un manifest al que le
    falta el HEAD y no lo dice es peor que ninguno: invita a tratar la corrida
    como reproducible cuando nadie sabe contra qué código se tomó.
    """
    man = reference_manifest.build(config=_config())
    no_capturados = set(reference_manifest.not_captured_fields(man))
    assert "head" in no_capturados
    assert man["head"]["status"] == "NOT_CAPTURED" and man["head"]["why"]

    # Y con HEAD deja de estarlo, sin tocar nada más.
    con_head = reference_manifest.build(config=_config(), head="abc1234")
    assert con_head["head"] == "abc1234"
    assert "head" not in set(reference_manifest.not_captured_fields(con_head))


def test_el_hash_identifica_el_regimen_no_la_corrida():
    """Dos corridas del mismo régimen ⇒ mismo hash; otro régimen ⇒ otro hash.

    Si el `run_id` entrara en el hash, «reproducible» sería indemostrable: cada
    corrida acuña el suyo. Si el `block_size` NO entrara, dos regímenes
    distintos se declararían el mismo — y con `block_size` gobernando cuándo se
    reconstruye el runner, eso sería exactamente el error que las olas 1 a 4
    pasaron reparando.
    """
    a = reference_manifest.build(config=_config(run_id="corrida-a"), head="h1")
    b = reference_manifest.build(config=_config(run_id="corrida-b"), head="h1")
    assert a["manifest_hash"] == b["manifest_hash"], (
        "el identificador de corrida contamina el hash del régimen"
    )

    otro = reference_manifest.build(config=_config(run_id="corrida-a", block_size=1), head="h1")
    assert otro["manifest_hash"] != a["manifest_hash"], (
        "cambiar block_size no cambió el hash: dos regímenes distintos con la misma huella"
    )

    # Y el HEAD sí cuenta: medir contra otro código es otro régimen.
    assert reference_manifest.build(config=_config(run_id="corrida-a"), head="h2")[
        "manifest_hash"
    ] != a["manifest_hash"]


def test_lleva_la_semantica_del_certificado():
    """`trajectory_reward` decide si C_t toca a V_t — la mezcla que originó todo.

    Dos mediciones tomadas con valores distintos no son comparables, así que el
    manifest tiene que decirlo o el régimen no está identificado.
    """
    man = reference_manifest.build(config=_config())
    sem = man["certificate_semantics"]
    assert sem["trajectory_reward"] == "none", "el default histórico cambió; revisar la prueba"
    assert sem["retention_signal"] == "ioc"
    assert reference_manifest.build(
        config=_config(trajectory_reward="previous_certificate")
    )["certificate_semantics"]["trajectory_reward"] == "previous_certificate"


def test_lleva_lambda_con_su_hash_y_su_registro():
    """Λ y el contrato de cada parámetro: el dominio vigente es parte del régimen.

    Una superficie de respuesta medida bajo `1 ≤ k` no se puede comparar con
    otra medida bajo `1 ≤ k ≤ 10`, aunque el valor de partida sea el mismo.
    """
    lam = parameters.bootstrap_state()
    man = reference_manifest.build(config=_config(), parameter_state=lam)
    ps = man["parameter_state"]
    assert ps["values"] == {k: lam[k] for k in sorted(lam)}
    assert ps["hash"] == parameters.state_hash(lam)
    assert set(ps["registry"]) == set(parameters.ADAPTIVE_PARAMETERS)
    assert ps["registry"]["memory_retrieval_limit"]["domain"] == [1, None], (
        "el dominio dejó de ser abierto sin que §XXXIII lo autorizara"
    )


def test_enumera_las_gates_puestas_y_no_las_apagadas():
    """Un régimen se define por lo que se desvía del default.

    Listar las 111 apagadas haría el manifest ilegible; no decir cuántas están
    puestas lo haría inútil. Se declara el conjunto encendido y su tamaño.
    """
    man = reference_manifest.build(config=_config())
    gates = man["feature_gates"]
    assert set(gates) == {"set", "count_set"}
    assert gates["count_set"] == len(gates["set"])
    assert all(k.startswith(("RNFE_", "AEON_")) for k in gates["set"])
