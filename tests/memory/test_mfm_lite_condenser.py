"""B25: el condensador meso no hardcodea la variable del mundo.

Resuelve scenario_metadata.main_variable (default "temperature") y lee
updated_world[main_var], igual que continuity_guard / certificate_builder /
coherence_obstruction.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.memory.mfm_lite.condenser import MFMCondenser


@dataclass
class _Cert:
    ioc_proxy: float = 0.9
    continuity_score: float = 0.8


def _episode_result(*, main_variable: str | None, updated_world: dict) -> dict:
    scenario_metadata = None
    if main_variable is not None:
        scenario_metadata = {
            "scenario_name": "any_scenario",
            "scenario_version": "1.0",
            "main_variable": main_variable,
        }
    episode = {
        "episode_id": "ep-1",
        "result": {
            "reasoning_sequence": ["observe", "infer"],
            "relation_kind": "causal",
            "updated_world": updated_world,
        },
        "context": {"formula": "F1"},
    }
    if scenario_metadata:
        episode["scenario_metadata"] = scenario_metadata
    return {"episode": episode}


class TestMesoMainVariable:
    def test_meso_uses_scenario_main_variable_not_temperature(self):
        """resource_management: main_variable=stock_level -> guarda el stock, no None."""
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable="stock_level",
                updated_world={"stock_level": 42.0, "temperature": 0.99},
            ),
            certificate=_Cert(),
        )
        assert meso["world_main_variable"] == "stock_level"
        assert meso["world_main_variable_value"] == 42.0
        # No debe emitir la clave literal "temperature" para un escenario no-térmico:
        # antes emitia "temperature": None (dato muerto + token "None" en el Jaccard).
        assert "temperature" not in meso

    def test_meso_grid_thermal_main_variable(self):
        """grid_thermal: main_variable=global_temp_mean (no es "temperature")."""
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable="global_temp_mean",
                updated_world={"global_temp_mean": 0.71},
            ),
            certificate=_Cert(),
        )
        assert meso["world_main_variable"] == "global_temp_mean"
        assert meso["world_main_variable_value"] == 0.71

    def test_legacy_temperature_key_is_NOT_removable_a_live_consumer_reads_it(self):
        """TRIPWIRE — no saques la clave legacy `temperature`: hay un consumidor VIVO.

        `runtime/world/min_cognitive_episode.py:99` hace `top.get("temperature") is not None`
        sobre una memoria RECUPERADA y con eso decide la intervención (`activate_cooling`).
        Ese camino nunca setea `scenario_metadata`, así que `main_var` cae al default
        "temperature" y la clave se emite: **el consumidor funciona GRACIAS a este shim**, no
        porque nadie lea la clave.

        Si este test falla porque sacaste la clave: migrá ANTES ese consumidor a
        `world_main_variable_value` (backlog B70). Sacarla sin migrar rompe **en silencio** la
        selección de intervención del episodio mínimo.
        """
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable=None,  # como el camino de min_cognitive_episode: sin metadata
                updated_world={"temperature": 0.88},
            ),
            certificate=_Cert(),
        )
        # La clave exacta que min_cognitive_episode.py:99 lee por nombre.
        assert meso["temperature"] == 0.88
        # Y la forma nueva convive con ella (aditiva, no reemplazo).
        assert meso["world_main_variable"] == "temperature"
        assert meso["world_main_variable_value"] == 0.88

    def test_meso_defaults_to_temperature_and_keeps_backcompat_key(self):
        """Sin scenario_metadata -> default "temperature" + clave legacy aditiva."""
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable=None,
                updated_world={"temperature": 0.88},
            ),
            certificate=_Cert(),
        )
        assert meso["world_main_variable"] == "temperature"
        assert meso["world_main_variable_value"] == 0.88
        # Compat aditiva: el payload térmico conserva la clave histórica.
        assert meso["temperature"] == 0.88

    def test_meso_thermal_scenario_keeps_both_keys(self):
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable="temperature",
                updated_world={"temperature": 0.93},
            ),
            certificate=_Cert(),
        )
        assert meso["temperature"] == 0.93
        assert meso["world_main_variable_value"] == 0.93

    def test_meso_missing_variable_in_world_is_none_not_crash(self):
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable="stock_level",
                updated_world={},
            ),
            certificate=_Cert(),
        )
        assert meso["world_main_variable"] == "stock_level"
        assert meso["world_main_variable_value"] is None

    def test_meso_preserves_pattern_key_contract(self):
        """promotion_gate/promotion leen meso["pattern_key"]: no se toca."""
        condenser = MFMCondenser()
        meso = condenser.meso(
            episode_result=_episode_result(
                main_variable="stock_level", updated_world={"stock_level": 1.0}
            ),
            certificate=_Cert(),
        )
        assert meso["pattern_key"] == "F1"
        assert meso["ioc_proxy"] == 0.9
        assert meso["reasoning_sequence"] == ["observe", "infer"]
        assert meso["relation_kind"] == "causal"
