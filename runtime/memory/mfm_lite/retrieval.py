"""Retrieval estructural desde memoria multiescala."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from runtime.storage import StorageFacade
from runtime.memory.embeddings import (
    cosine_similarity,
    get_embedder,
    text_from_mapping,
)

# Centinela para distinguir "no me lo pasaron" de "me pasaron None" (None es un valor
# legítimo tanto para embedder como para un embedding degradado).
_UNSET: Any = object()

# Penalizaciones de scoring. Fuente normativa: canon/normative/
# MEMORY_COMPATIBILITY_POLICY_v1.md §5 ("Valores iniciales sugeridos").
#
# Penalty applied to cross-scenario memories in analogical mode (otro scenario_name).
_CROSS_SCENARIO_PENALTY = 0.5
# B30: penalización PROPIA y más suave para "mismo escenario, otra versión". El canon la
# prometía (`penalty_cross_version = 0.8`) pero no existía en el código: la versión
# distinta degradaba la memoria a cross-scenario, o sea que en modo estricto la
# DESCARTABA. Eje distinto del anterior, y NO es contaminación (canon §6: contaminación es
# memoria "de otro escenario"; §5.1 descarta solo por scenario_name).
_CROSS_VERSION_PENALTY = 0.8

# B28: tamaño del POOL de candidatos que se traen de storage para puntuar. Es una
# magnitud DISTINTA del top-k que se devuelve (`limit`).
#
# Antes el pool era `max(20, limit * 4)`: como storage ordena por `created_at DESC`
# (sqlite_store.py:954), el pool eran literalmente las ~20 memorias MÁS RECIENTES, así
# que una memoria vieja con mejor overlap NUNCA llegaba al scoring: la recencia decidía
# antes que la relevancia. Ahora se trae un pool amplio, se puntúa TODO el pool y recién
# ahí se corta el top-k por score.
#
# Trade-off de costo (por llamada a retrieve, pool = P):
#   - storage: 1 query, P filas leídas + P `json.loads` del structure_json;
#   - scoring: P Jaccard (O(tokens), barato);
#   - con RNFE_MEMORY_EMBEDDINGS activo: P `embed()` de structure + P cosenos. El embed de
#     la QUERY se calcula UNA sola vez por retrieve (antes se recalculaba por candidato).
# Por eso el pool es acotado y configurable, no "traer todo": crece lineal con P y con
# embeddings pesados (llama) P grande se paga caro.
_DEFAULT_CANDIDATE_POOL_SIZE = 200


def _embedding_weight() -> float:
    """Peso del coseno semántico al mezclar con Jaccard (default 0.5)."""
    try:
        w = float(os.environ.get("RNFE_MEMORY_EMBEDDINGS_WEIGHT", "0.5"))
    except (TypeError, ValueError):
        return 0.5
    return min(max(w, 0.0), 1.0)


def _resolve_candidate_pool_size(*, limit: int, override: int | None) -> int:
    """Pool de candidatos a puntuar. Nunca menor que el top-k pedido."""
    if override is not None:
        try:
            resolved = int(override)
        except (TypeError, ValueError):
            resolved = _DEFAULT_CANDIDATE_POOL_SIZE
    else:
        try:
            resolved = int(
                os.environ.get("RNFE_MEMORY_CANDIDATE_POOL", _DEFAULT_CANDIDATE_POOL_SIZE)
            )
        except (TypeError, ValueError):
            resolved = _DEFAULT_CANDIDATE_POOL_SIZE
    # El pool jamás puede ser menor que el top-k solicitado (si no, no se podría llenar).
    return max(resolved, limit, 1)


def _item_scenario_identity(meta: Dict[str, Any]) -> tuple[Any, Any]:
    """(scenario_name, scenario_version) de una memoria, desde su metadata.

    Fuente preferida: metadata["scenario_metadata"]; fallback: las claves planas de
    metadata (memorias viejas / escrituras directas). Un único lector para que el
    filtrado y el payload de salida no puedan divergir.
    """
    scenario_metadata = meta.get("scenario_metadata")
    if not isinstance(scenario_metadata, dict):
        scenario_metadata = {}
    name = scenario_metadata.get("scenario_name") or meta.get("scenario_name")
    version = scenario_metadata.get("scenario_version") or meta.get("scenario_version")
    return name, version


def summarize_retrieval_hits(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a compact, JSON-friendly RAG attestation from retrieval hits."""
    if not hits:
        return {
            "schema": "memory_rag_attestation.v1",
            "returned_count": 0,
            "retrieval_purity": None,
            "validation_status": "warn",
            "degradation_level": "no_memory",
            "trace_memory_ids": [],
        }
    first_attestation = hits[0].get("rag_attestation")
    if isinstance(first_attestation, dict):
        return dict(first_attestation)

    same = 0
    cross = 0
    trace_ids: list[str] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        if hit.get("memory_id") is not None:
            trace_ids.append(str(hit["memory_id"]))
        if hit.get("analogical_source"):
            cross += 1
        else:
            same += 1
    total = same + cross
    purity = (same / total) if total else None
    return {
        "schema": "memory_rag_attestation.v1",
        "returned_count": total,
        "returned_same_scenario_count": same,
        "returned_cross_scenario_count": cross,
        "retrieval_purity": round(purity, 4) if purity is not None else None,
        "validation_status": "warn" if cross else "pass",
        "degradation_level": "analogical_penalized" if cross else "strict_isolated",
        "trace_memory_ids": trace_ids,
    }


class MemoryRetrieval:
    def __init__(self, *, storage: StorageFacade):
        self.storage = storage

    def retrieve(
        self,
        *,
        run_id: str,
        query: Dict[str, Any],
        scales: list[str] | None = None,
        limit: int = 5,
        scenario_name: str | None = None,
        scenario_version: str | None = None,
        scenario_filter_mode: str = "strict_same_scenario",
        candidate_pool_size: int | None = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve memory records scored by structural overlap.

        Args:
            run_id: Run ID to scope retrieval.
            query: Query dict for overlap scoring.
            scales: Memory scales to search.
            limit: Top-k a DEVOLVER (después de puntuar el pool completo).
            scenario_name: Filter memories by scenario name.
            scenario_version: Version de escenario de la query. Una memoria del MISMO
                escenario con OTRA version no se descarta: se conserva penalizada
                (penalty_cross_version).
            scenario_filter_mode: 'strict_same_scenario' discards cross-scenario
                memories. 'cross_scenario_analogical' (alias 'analogical') keeps
                them with a penalty.
            candidate_pool_size: Cuántos candidatos traer de storage para puntuar
                (default _DEFAULT_CANDIDATE_POOL_SIZE / env RNFE_MEMORY_CANDIDATE_POOL).
                Es independiente de `limit`: sin esto el ranking lo decidía la recencia.

        Returns:
            List of scored memory dicts with retrieval_metrics.
        """
        # Normalize alias
        if scenario_filter_mode == "analogical":
            scenario_filter_mode = "cross_scenario_analogical"
        # B28: el pool (cuántos candidatos compiten) se separa del top-k (cuántos se
        # devuelven). El TTL ya se aplica en storage ANTES del limit (P6), así que las
        # filas expiradas no consumen presupuesto de pool: eso se respeta tal cual.
        pool_size = _resolve_candidate_pool_size(
            limit=limit, override=candidate_pool_size
        )
        candidates = self.storage.retrieve_memory_records(
            run_id=run_id,
            scales=scales or ["macro", "meso", "micro"],
            limit=pool_size,
        )

        # El embedding de la query se calcula UNA vez por retrieve, no una vez por
        # candidato: con el pool ampliado eso serían 2*P embeds por llamada.
        embedder = get_embedder()
        query_embedding = (
            embedder.embed(text_from_mapping(query)) if embedder is not None else None
        )

        candidate_same_scenario_count = 0
        candidate_cross_scenario_count = 0
        candidate_cross_version_count = 0
        filtered_cross_scenario_count = 0
        penalty_applied = False
        version_penalty_applied = False

        scored = []
        for item in candidates:
            structure = item.structure_json or {}
            meta = item.metadata or {}
            score = self._score(
                query=query,
                structure=structure,
                embedder=embedder,
                query_embedding=query_embedding,
            )

            # Scenario filtering
            is_cross_scenario = False
            is_cross_version = False
            if scenario_name is not None:
                item_scenario, item_version = _item_scenario_identity(meta)
                # B30: DOS ejes distintos, no uno.
                #
                # (a) OTRO ESCENARIO (scenario_name distinto) -> contaminación
                #     (canon MEMORY_COMPATIBILITY_POLICY_v1 §6). En estricto se DESCARTA;
                #     en analógico se penaliza fuerte (0.5) y se marca analogical_source.
                #     SIN CAMBIOS respecto del comportamiento previo.
                #
                # (b) MISMO ESCENARIO, OTRA VERSION -> NO es contaminación: es la misma
                #     identidad causal con otra config. Antes se lo degradaba al bucket
                #     cross-scenario, así que en estricto se DESCARTABA. El canon dice lo
                #     contrario: §5.1 descarta solo `scenario_name != query.scenario_name`,
                #     §2.1 pide misma versión "preferiblemente", y §100-103 promete un
                #     `penalty_cross_version = 0.8` propio y más suave. Se conserva
                #     penalizado, en AMBOS modos, y NO se marca analogical_source (esa
                #     bandera significa procedencia cross-escenario y alimenta
                #     pollution_detected / transfer_assessment / belief_state).
                if item_scenario != scenario_name:
                    candidate_cross_scenario_count += 1
                    is_cross_scenario = True
                    if scenario_filter_mode == "strict_same_scenario":
                        filtered_cross_scenario_count += 1
                        continue  # Discard cross-scenario memory
                    # Analogical mode: penalize but keep
                    score *= _CROSS_SCENARIO_PENALTY
                    penalty_applied = True
                else:
                    candidate_same_scenario_count += 1
                    if scenario_version is not None and item_version != scenario_version:
                        candidate_cross_version_count += 1
                        is_cross_version = True
                        score *= _CROSS_VERSION_PENALTY
                        version_penalty_applied = True

            scored.append((score, item, is_cross_scenario, is_cross_version))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for score, item, is_cross, is_cross_ver in scored[:limit]:
            meta = item.metadata or {}
            item_scenario, item_version = _item_scenario_identity(meta)
            entry: Dict[str, Any] = {
                "memory_id": item.memory_id,
                "scale": item.scale,
                "score": score,
                "structure": item.structure_json,
                "ioc_proxy": item.ioc_proxy,
                "support_count": item.support_count,
                "scenario_name": item_scenario,
                "scenario_version": item_version,
                "certificate_id": item.certificate_id,
            }
            if is_cross:
                entry["analogical_source"] = True
            if is_cross_ver:
                # Bandera PROPIA: mismo escenario, otra versión. Deliberadamente NO es
                # analogical_source (eso significaría "vino de otro escenario" y dispararía
                # pollution_detected en reality/service.py:401-408).
                entry["cross_version_source"] = True
            out.append(entry)

        returned_same_scenario_count = sum(1 for entry in out if not entry.get("analogical_source"))
        returned_cross_scenario_count = sum(1 for entry in out if entry.get("analogical_source"))
        returned_cross_version_count = sum(1 for entry in out if entry.get("cross_version_source"))
        returned_count = len(out)
        retrieval_purity = (
            returned_same_scenario_count / returned_count
            if returned_count
            else None
        )
        if scenario_name is None:
            validation_status = "pass"
            degradation_level = "unfiltered"
        elif returned_count == 0:
            validation_status = "warn"
            degradation_level = "no_memory"
        elif scenario_filter_mode == "strict_same_scenario" and returned_cross_scenario_count:
            validation_status = "fail"
            degradation_level = "strict_policy_violation"
        elif returned_cross_scenario_count:
            validation_status = "warn"
            degradation_level = "analogical_penalized"
        elif returned_cross_version_count:
            # B30: mismo escenario, otra versión. NO es violación de la policy estricta
            # (canon §5.1 descarta por scenario_name, no por versión) => "pass". Pero se
            # reporta como degradación propia para que la mezcla de versiones sea visible
            # y no se confunda con un retrieval limpio.
            validation_status = "pass"
            degradation_level = "cross_version_penalized"
        else:
            validation_status = "pass"
            degradation_level = "strict_isolated"

        # Attach retrieval metrics to each result for observability
        retrieval_metrics = {
            "retrieved_same_scenario_count": returned_same_scenario_count,
            "retrieved_cross_scenario_count": returned_cross_scenario_count,
            "candidate_same_scenario_count": candidate_same_scenario_count,
            "candidate_cross_scenario_count": candidate_cross_scenario_count,
            "filtered_cross_scenario_count": filtered_cross_scenario_count,
            "scenario_filter_mode": scenario_filter_mode,
            "cross_scenario_penalty_applied": penalty_applied,
            "retrieval_purity": retrieval_purity,
            # B30: el eje versión se reporta SEPARADO del eje escenario. Una memoria del
            # mismo escenario con otra versión NO suma a los contadores cross-scenario ni a
            # cross_scenario_penalty_applied (de los que cuelga pollution_detected).
            "candidate_cross_version_count": candidate_cross_version_count,
            "retrieved_cross_version_count": returned_cross_version_count,
            "cross_version_penalty_applied": version_penalty_applied,
            # B28: observabilidad del pool. `candidate_pool_scored` == `candidate_pool_size`
            # significa que el pool se saturó: puede haber memorias relevantes que no
            # llegaron a competir (subir RNFE_MEMORY_CANDIDATE_POOL).
            "candidate_pool_size": pool_size,
            "candidate_pool_scored": len(candidates),
        }
        rag_attestation = {
            "schema": "memory_rag_attestation.v1",
            "scenario_filter_mode": scenario_filter_mode,
            "query_scenario": scenario_name,
            "query_scenario_version": scenario_version,
            "returned_count": returned_count,
            "returned_same_scenario_count": returned_same_scenario_count,
            "returned_cross_scenario_count": returned_cross_scenario_count,
            "candidate_same_scenario_count": candidate_same_scenario_count,
            "candidate_cross_scenario_count": candidate_cross_scenario_count,
            "filtered_cross_scenario_count": filtered_cross_scenario_count,
            "cross_scenario_penalty_applied": penalty_applied,
            "candidate_cross_version_count": candidate_cross_version_count,
            "returned_cross_version_count": returned_cross_version_count,
            "cross_version_penalty_applied": version_penalty_applied,
            "retrieval_purity": round(retrieval_purity, 4) if retrieval_purity is not None else None,
            "validation_status": validation_status,
            "degradation_level": degradation_level,
            "trace_memory_ids": [str(entry["memory_id"]) for entry in out],
        }
        for entry in out:
            entry["retrieval_metrics"] = retrieval_metrics
            entry["rag_attestation"] = rag_attestation

        return out

    def _score(
        self,
        *,
        query: Dict[str, Any],
        structure: Dict[str, Any],
        embedder: Any = _UNSET,
        query_embedding: Any = _UNSET,
    ) -> float:
        jaccard = self._jaccard(query=query, structure=structure)
        # RNFE_MEMORY_EMBEDDINGS off (default) -> get_embedder() None -> Jaccard puro
        # (byte-idéntico). hashed/llama -> mezcla coseno semántico.
        # embedder/query_embedding se pueden precomputar por llamada a retrieve (B28) para
        # no re-embeber la query por cada candidato del pool; sin ellos, se resuelven acá
        # (comportamiento standalone idéntico al previo).
        if embedder is _UNSET:
            embedder = get_embedder()
        if embedder is None:
            return jaccard
        if query_embedding is _UNSET:
            query_embedding = embedder.embed(text_from_mapping(query))
        cos = cosine_similarity(
            query_embedding,
            embedder.embed(text_from_mapping(structure)),
        )
        if cos <= 0.0:
            # Embedding no disponible/degradado (p.ej. llama sin GGUF): cae a Jaccard.
            return jaccard
        weight = _embedding_weight()
        return float((1.0 - weight) * jaccard + weight * cos)

    @staticmethod
    def _jaccard(*, query: Dict[str, Any], structure: Dict[str, Any]) -> float:
        query_tokens = {str(v) for v in query.values() if v is not None}
        if not query_tokens:
            return 0.0
        structure_tokens = set()
        for value in structure.values():
            if isinstance(value, list):
                structure_tokens.update(str(item) for item in value)
            else:
                structure_tokens.add(str(value))
        if not structure_tokens:
            return 0.0
        overlap = len(query_tokens & structure_tokens) / len(query_tokens | structure_tokens)
        return float(overlap)
