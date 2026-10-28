"""Condensador micro/meso/macro para MFM_lite."""

from __future__ import annotations

from typing import Any, Dict, Iterable


class MFMCondenser:
    # Claves del contexto que NO deben guardarse en memoria: son ellas mismas memorias
    # recuperadas / trazas, y anidarlas hace que cada memoria contenga las anteriores →
    # crecimiento EXPONENCIAL del payload (episode.closed llegó a 677 MB, doblando por episodio).
    _RECURSIVE_CONTEXT_KEYS = (
        "retrieved_memory",
        "memory_hits",
        "memory_rag_attestation",
        "overlay_directives",
        "inherited_rules",
        "belief_state",
    )

    def _prune_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pruned = dict(context or {})
        for key in self._RECURSIVE_CONTEXT_KEYS:
            pruned.pop(key, None)
        return pruned

    def micro(self, *, episode_result: Dict[str, Any], certificate) -> Dict[str, Any]:
        episode = episode_result.get("episode", {})
        result = {
            "episode_id": episode.get("episode_id"),
            "result": episode.get("result", {}),
            # Contexto PODADO: firma de situación (observación, fórmula, intervención) sin
            # las memorias recuperadas — evita la recursión que reventaba el payload.
            "context": self._prune_context(episode.get("context", {})),
            "ioc_proxy": certificate.ioc_proxy,
            "continuity_score": certificate.continuity_score,
        }
        scenario_metadata = episode.get("scenario_metadata")
        if scenario_metadata:
            result["scenario_metadata"] = scenario_metadata
        return result

    def meso(self, *, episode_result: Dict[str, Any], certificate) -> Dict[str, Any]:
        episode = episode_result.get("episode", {})
        result = episode.get("result", {})
        context = episode.get("context", {})
        pattern_key = f"{context.get('formula','NA')}"
        scenario_metadata = episode.get("scenario_metadata")

        # B25: la variable del mundo NO se hardcodea. Se resuelve desde
        # scenario_metadata.main_variable (default "temperature"), igual que
        # continuity_guard.py:32, certificate_builder.py:67 y coherence_obstruction.py:113.
        # Antes se emitía siempre updated_world["temperature"], asi que en escenarios cuya
        # variable principal es otra (resource_management -> "stock_level") el meso guardaba
        # "temperature": None: perdia la variable real Y metia un token "None" en el
        # structure_json que ensucia el Jaccard de retrieval (_jaccard no filtra None).
        meta = scenario_metadata if isinstance(scenario_metadata, dict) else {}
        main_var = meta.get("main_variable") or "temperature"
        updated_world = result.get("updated_world") or {}
        main_value = updated_world.get(main_var)

        meso_result = {
            "pattern_key": pattern_key,
            "reasoning_sequence": result.get("reasoning_sequence", []),
            "relation_kind": result.get("relation_kind"),
            # Convención ya establecida en el repo (certificate_builder.py:100-101):
            # el par (nombre de variable, valor) viaja junto, para que una memoria de otra
            # variable no sea comparable en silencio con esta.
            "world_main_variable": main_var,
            "world_main_variable_value": main_value,
            "ioc_proxy": certificate.ioc_proxy,
        }
        # Compat ADITIVA: se conserva la clave literal cuando la variable principal ES
        # "temperature" (mismo back-compat que certificate_builder.py:99 con
        # "world_temperature"). Deja byte-idéntico el payload de los escenarios térmicos
        # (los dominantes) y no rompe artifacts/memorias ya persistidas.
        #
        # NO ES REMOVIBLE HOY: `runtime/world/min_cognitive_episode.py:99` lee esta clave
        # por nombre (`top.get("temperature") is not None`) de una memoria RECUPERADA para
        # decidir la intervención (`activate_cooling`). Ese camino nunca setea
        # `scenario_metadata`, así que `main_var` cae al default "temperature" y la clave se
        # emite — el consumidor sigue funcionando **gracias a este shim**. Sacarlo rompe en
        # silencio la selección de intervención del episodio mínimo.
        # Para poder retirarla hay que migrar ANTES ese consumidor a
        # `world_main_variable_value` (backlog B70). Hay un test que custodia esto.
        if main_var == "temperature":
            meso_result["temperature"] = main_value

        if scenario_metadata:
            meso_result["scenario_metadata"] = scenario_metadata
        return meso_result

    def macro(
        self,
        *,
        pattern_key: str,
        records: Iterable[Dict[str, Any]],
        mean_ioc: float,
        std_ioc: float,
    ) -> Dict[str, Any]:
        return {
            "pattern_key": pattern_key,
            "support_count": len(list(records)),
            "mean_ioc": mean_ioc,
            "std_ioc": std_ioc,
        }
