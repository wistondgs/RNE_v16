"""Frontera única entre el episodio vivo y los órganos neuronales N1-N6."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from runtime.neural.config import NeuralRuntimeConfig
from runtime.neural.contracts import (
    CausalContextView,
    InferenceScope,
    NeuralInferenceRequest,
    NeuralMode,
    ResourceSnapshot,
)
from runtime.neural.registry import LazyBackendRegistry
from runtime.neural.runtime import NeuralRuntime

from .adapters import N3Adapter, N4Adapter, canonical_adapter_registry
from .contracts import (
    AuthorityEffect,
    ConsumerVerdictClass,
    ConsumerReceipt,
    OrganTrace,
    SymbiosisIdentity,
    SymbiosisTrace,
    canonical_sha256,
    validate_consumer_receipt,
)


@dataclass(slots=True)
class _EpisodeSession:
    trace: SymbiosisTrace
    inputs: dict[str, Any]
    entries: dict[str, OrganTrace] = field(default_factory=dict)


class SymbioticNeuralCoordinator:
    """Coordina evidencia neuronal sin duplicar scheduler ni autoridad.

    Los algoritmos integrados son deterministas y están declarados como referencias;
    H-Net, Mamba2 y los pesos no entrenados no se activan. N0 conserva OFF, fallback,
    presupuestos, trazas y techo de autoridad para cada ejecución.
    """

    def __init__(
        self,
        *,
        storage: Any,
        config: NeuralRuntimeConfig | None = None,
    ) -> None:
        self.storage = storage
        self.config = config or NeuralRuntimeConfig.from_env()
        self.runtime = NeuralRuntime(
            config=self.config,
            registry=LazyBackendRegistry(artifact_root=Path(".")),
            storage=storage,
        )
        self._sessions: dict[str, _EpisodeSession] = {}
        self._adapters = canonical_adapter_registry()
        self._disabled_organs = {
            item.strip().upper()
            for item in os.environ.get("RNFE_NEURAL_DISABLED_ORGANS", "").split(",")
            if item.strip()
        }

    def begin_episode(
        self,
        *,
        identity: SymbiosisIdentity,
        observation: Mapping[str, Any],
        formula: str,
        proposition: str,
        memory_hits: list[dict[str, Any]],
        scenario_metadata: Mapping[str, Any],
        causal_attestation: Mapping[str, Any],
        resources: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        raw_resources = dict(resources or {})
        resource_snapshot = ResourceSnapshot.from_mapping(resources)
        inputs = {
            "observation": dict(observation),
            "formula": formula,
            "proposition": proposition,
            "memory_hits": list(memory_hits),
            "scenario_metadata": dict(scenario_metadata),
            "causal_attestation": dict(causal_attestation),
            "resources": asdict(resource_snapshot),
        }
        session = _EpisodeSession(
            trace=SymbiosisTrace(
                identity=identity,
                organ_contract_versions={
                    organ: "canonical-organ-adapter-v1" for organ in self._adapters
                },
                backend_identities={
                    organ: adapter.reference_id for organ, adapter in self._adapters.items()
                },
                memory_read_references=tuple(
                    str(item.get("episode_id") or item.get("id") or "")
                    for item in memory_hits
                    if item.get("episode_id") or item.get("id")
                ),
                resource_state=asdict(resource_snapshot),
                measurement_status=_resource_measurement_status(raw_resources),
                unmeasured_fields=("actual_ram_mb", "actual_vram_mb"),
                not_applicable_fields=("trained_model_metrics",),
            ),
            inputs=inputs,
        )
        self._sessions[identity.episode_id] = session

        n5 = self._execute(
            session,
            organ="N5",
            context={"identity": identity, "inputs": inputs},
        )
        session.entries["N5"].consumer_verdict = (
            "disabled" if self.config.mode is NeuralMode.OFF else "consumed_by_SMG+MFM"
        )
        n3 = self._execute(
            session,
            organ="N3",
            context={"identity": identity, "inputs": inputs},
        )
        session.entries["N3"].consumer_verdict = (
            "disabled"
            if self.config.mode is NeuralMode.OFF
            else "consumed_by_next_reasoning+MFM+continuity"
        )
        if self.organ_has_candidate(identity.episode_id, "N3"):
            self.record_consumer_receipt(
                episode_id=identity.episode_id,
                organ="N3",
                consumer_id="next_episode_state",
                consumer_input={"previous_state": n3.get("previous_state")},
                consumer_output={"state_key": n3.get("state_key"), "episode_count": n3.get("episode_count")},
                verdict_class=ConsumerVerdictClass.OBSERVED,
                verdict_detail="state_updated_for_longitudinal_context",
                evidence_refs=(identity.episode_id,),
            )
            self.record_consumer_receipt(
                episode_id=identity.episode_id,
                organ="N3",
                consumer_id="checkpoint_continuity",
                consumer_input={"state_key": n3.get("state_key")},
                consumer_output=self.export_temporal_state(),
                verdict_class=ConsumerVerdictClass.OBSERVED,
                verdict_detail="checkpoint_projection_serialized",
                evidence_refs=("n3-temporal-checkpoint-v1",),
            )
        n1 = self._execute(
            session,
            organ="N1",
            context={"identity": identity, "inputs": inputs, "n3_temporal": n3},
        )
        self._execute(
            session,
            organ="N4",
            context={"identity": identity, "inputs": inputs},
        )
        return {
            "schema_version": "neural-symbiosis-signals-v1",
            "trace_group_id": identity.trace_group_id,
            "n1_proposal": n1,
            "n3_temporal": n3,
            "n5_ingestion": n5,
        }

    def consume_reasoning(
        self,
        *,
        episode_id: str,
        reasoning: Mapping[str, Any],
        lotf_valid: bool,
    ) -> dict[str, Any]:
        session = self._session(episode_id)
        state = dict(reasoning.get("state") or {})
        selected = [str(item).upper() for item in reasoning.get("sequence") or []]

        n1 = session.entries["N1"]
        proposed = set((n1.candidate or {}).get("proposed_families") or [])
        overlap = sorted(proposed.intersection(selected))
        n1.consumer_verdict = (
            "disabled"
            if n1.effective_mode == NeuralMode.OFF.value
            else f"compared:overlap={','.join(overlap) or 'none'}"
        )
        if n1.candidate_hash is not None:
            self.record_consumer_receipt(
                episode_id=episode_id,
                organ="N1",
                consumer_id="scheduler_comparison",
                consumer_input={"proposed": sorted(proposed), "scheduler_selected": selected},
                consumer_output={"overlap": overlap, "scheduler_authority_preserved": True},
                verdict_class=ConsumerVerdictClass.COMPARED,
                verdict_detail="proposal_compared_without_scheduler_influence",
                evidence_refs=(f"decision:{session.trace.identity.decision_id or 'unlinked'}",),
            )

        n2 = self._execute(
            session,
            organ="N2",
            context={
                "identity": session.trace.identity,
                "inputs": session.inputs,
                "reasoning_state": state,
                "lotf_valid": lotf_valid,
            },
        )
        session.entries["N2"].consumer_verdict = str(n2.get("verdict", "disabled"))
        if session.entries["N2"].candidate_hash is not None:
            verification = dict(n2.get("verification") or {})
            for consumer_id, authority in (
                ("ded_verifier", "DED"),
                ("lotf_verifier", "LOT-F"),
                ("nesy_verifier", "NESY"),
            ):
                accepted = bool(verification.get(authority))
                self.record_consumer_receipt(
                    episode_id=episode_id,
                    organ="N2",
                    consumer_id=consumer_id,
                    consumer_input={"proposition": n2.get("proposition")},
                    consumer_output={"authority": authority, "accepted": accepted},
                    verdict_class=(
                        ConsumerVerdictClass.ACCEPTED
                        if accepted
                        else ConsumerVerdictClass.REJECTED
                    ),
                    verdict_detail="accepted" if accepted else "rejected",
                    evidence_refs=(authority,),
                )

        n4_entry = session.entries["N4"]
        n4_adapter = self._adapters["N4"]
        if not isinstance(n4_adapter, N4Adapter):
            raise RuntimeError("canonical_n4_adapter_type_mismatch")
        n4_comparison = n4_adapter.compare(n4_entry.candidate, state)
        n4_entry.consumer_verdict = n4_comparison["verdict"]
        if isinstance(n4_entry.candidate, dict):
            n4_entry.candidate["canonical_comparison"] = n4_comparison
            n4_entry.candidate_hash = canonical_sha256(n4_entry.candidate)
        if n4_entry.candidate_hash is not None:
            self.record_consumer_receipt(
                episode_id=episode_id,
                organ="N4",
                consumer_id="canonical_causal_comparator",
                consumer_input={"candidate_hash": n4_entry.candidate_hash},
                consumer_output=n4_comparison,
                verdict_class=(
                    ConsumerVerdictClass.COMPARED
                    if n4_comparison.get("agreement") is not None
                    else ConsumerVerdictClass.UNAVAILABLE
                ),
                verdict_detail=str(n4_comparison["verdict"]),
                evidence_refs=("CAU", "CTF", "C-GWM"),
            )

        return {
            "n1_scheduler_comparison": {
                "proposed": sorted(proposed),
                "scheduler_selected": selected,
                "overlap": overlap,
                "scheduler_authority_preserved": True,
            },
            "n2_verification": n2,
            "n4_comparison": n4_comparison,
        }

    def prepare_certification(
        self,
        *,
        episode_id: str,
        viability: Mapping[str, Any],
        reasoning: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._session(episode_id)
        n6 = self._execute(
            session,
            organ="N6",
            context={
                "identity": session.trace.identity,
                "inputs": session.inputs,
                "viability": viability,
                "reasoning": reasoning,
            },
        )
        session.entries["N6"].consumer_verdict = str(n6.get("sandbox_verdict", "disabled"))
        if session.entries["N6"].candidate_hash is not None:
            self.record_consumer_receipt(
                episode_id=episode_id,
                organ="N6",
                consumer_id="sandbox",
                consumer_input={"proposal": n6.get("proposal")},
                consumer_output=n6.get("sandbox") or {},
                verdict_class=(
                    ConsumerVerdictClass.ABSTAINED
                    if n6.get("status") == "abstained"
                    else ConsumerVerdictClass.OBSERVED
                ),
                verdict_detail=str(n6.get("sandbox_verdict") or "abstained"),
                evidence_refs=("shadow-sandbox",),
            )
        health = asdict(self.runtime.trace_health)
        session.trace.trace_health = health
        return self.certification_block(episode_id)

    def certification_block(self, episode_id: str) -> dict[str, Any]:
        session = self._session(episode_id)
        entries = [entry.to_dict(include_candidate=True) for entry in session.trace.organs]
        return {
            "schema_version": "neural-symbiosis-certificate-v1",
            "trace_group_id": session.trace.identity.trace_group_id,
            "runtime": {
                "organ": "N0",
                "mode": self.config.mode.value,
                "loaded_artifacts": self.runtime.registry.loaded_count,
                "trace_health": asdict(self.runtime.trace_health),
            },
            "organs_executed": [
                row["organ"] for row in entries if row["effective_mode"] != NeuralMode.OFF.value
            ],
            "mode": self.config.mode.value,
            "candidates": entries,
            "abstentions": [row["organ"] for row in entries if row["abstained"]],
            "fallbacks": [
                {"organ": row["organ"], "reason": row["fallback_reason"]}
                for row in entries
                if row["fallback_reason"]
            ],
            "disagreements": [
                row["candidate"].get("canonical_comparison")
                for row in entries
                if row["organ"] == "N4" and isinstance(row.get("candidate"), dict)
            ],
            "costs": {row["organ"]: row["cost"] for row in entries},
            "authority_effective": {
                row["organ"]: row["authority_ceiling"] for row in entries
            },
            "trace_completeness": session.trace.is_complete,
            "semantic_complete": session.trace.semantic_complete,
            "durably_complete": session.trace.durably_complete,
            "persistence_degraded": session.trace.persistence_degraded,
            "trace_health": asdict(self.runtime.trace_health),
            "resource_snapshot": dict(session.inputs.get("resources") or {}),
            "verdict_influence": "none",
        }

    def export_temporal_state(self) -> dict[str, Any]:
        """Serializa solo el estado N3 determinista para el checkpoint soberano."""

        adapter = self._adapters["N3"]
        if not isinstance(adapter, N3Adapter):
            raise RuntimeError("canonical_n3_adapter_type_mismatch")
        return adapter.export_state()

    def restore_temporal_state(self, payload: Mapping[str, Any] | None) -> int:
        """Restaura N3 validando la clave fuerte; ignora entradas mal formadas."""

        adapter = self._adapters["N3"]
        if not isinstance(adapter, N3Adapter):
            raise RuntimeError("canonical_n3_adapter_type_mismatch")
        return adapter.restore_state(payload)

    def finalize_episode(
        self,
        *,
        episode_id: str,
        outcome: Mapping[str, Any],
        certificate: Mapping[str, Any],
        reward: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._session(episode_id)
        n1 = session.entries["N1"]
        reward_value = reward.get("reward")
        reward_detail = (
            f"{float(reward_value):.4f}" if _number(reward_value) is not None else "unmeasured"
        )
        certificate_detail = certificate.get("verdict") or "unavailable"
        n1.consumer_verdict = (
            f"{n1.consumer_verdict}|reward={reward_detail}"
            f"|certificate={certificate_detail}"
        )
        if n1.candidate_hash is not None:
            self.record_consumer_receipt(
                episode_id=episode_id,
                organ="N1",
                consumer_id="delayed_outcome_observer",
                consumer_input={"reward": reward.get("reward")},
                consumer_output={"certificate_verdict": certificate.get("verdict")},
                verdict_class=ConsumerVerdictClass.OBSERVED,
                verdict_detail=(
                    "observed_without_policy_update"
                    if _number(reward_value) is not None
                    else "reward_unmeasured_without_policy_update"
                ),
                evidence_refs=("reward", "certificate"),
            )
        n4 = session.entries["N4"]
        n4.consumer_verdict = f"{n4.consumer_verdict}|certificate_metadata=consumed"
        if n4.candidate_hash is not None:
            self.record_consumer_receipt(
                episode_id=episode_id,
                organ="N4",
                consumer_id="certification_metadata",
                consumer_input={"candidate_hash": n4.candidate_hash},
                consumer_output={"certificate_verdict": certificate.get("verdict")},
                verdict_class=ConsumerVerdictClass.OBSERVED,
                verdict_detail="metadata_observed_no_verdict_influence",
                evidence_refs=("certificate",),
            )
        n6 = session.entries["N6"]
        n6.consumer_verdict = f"{n6.consumer_verdict}|certificate={certificate.get('verdict')}"
        if n6.candidate_hash is not None:
            for consumer_id in ("certification", "autoevolution_evidence_observer"):
                self.record_consumer_receipt(
                    episode_id=episode_id,
                    organ="N6",
                    consumer_id=consumer_id,
                    consumer_input={"proposal": (n6.candidate or {}).get("proposal")},
                    consumer_output={"certificate_verdict": certificate.get("verdict"), "applied": False},
                    verdict_class=ConsumerVerdictClass.OBSERVED,
                    verdict_detail="evidence_only_not_applied",
                    evidence_refs=(consumer_id,),
                )
        session.trace.episode_result = {
            "intervention": outcome.get("intervention"),
            "relation_kind": outcome.get("relation_kind"),
            "reward": reward.get("reward"),
        }
        session.trace.certificate = dict(certificate)
        session.trace.certificate_reference = str(
            certificate.get("certificate_id") or certificate.get("id") or "episode-certificate"
        )
        session.trace.trace_health = asdict(self.runtime.trace_health)
        payload = session.trace.to_dict(include_candidates=True)
        payload["trace_persisted"] = False
        payload["trace_health"] = asdict(self.runtime.trace_health)
        return payload

    def link_life_transition(
        self,
        *,
        episode_id: str,
        transition_id: str,
        previous_transition_hash: str,
        state_before_hash: str,
        state_after_hash: str,
        active_regime: str | None,
        memory_write_references: tuple[str, ...],
        policy_versions: Mapping[str, str],
    ) -> dict[str, Any]:
        """Cierra v2 únicamente después de que la transición vital fue committed."""

        session = self._session(episode_id)
        trace = session.trace
        trace.life_transition_id = transition_id
        trace.previous_transition_hash = previous_transition_hash
        trace.state_before_hash = state_before_hash
        trace.state_after_hash = state_after_hash
        trace.active_regime = active_regime
        trace.memory_write_references = memory_write_references
        trace.policy_versions = dict(policy_versions)
        # El payload final siempre contiene explícitamente la lista (incluso vacía en OFF).
        trace.final_event_contains_receipts = True
        trace.trace_health = asdict(self.runtime.trace_health)
        payload = trace.to_dict(include_candidates=True)
        persisted = self.runtime.persist_symbiosis_event(
            event_type="neural.symbiosis.completed",
            payload=payload,
            run_id=trace.identity.run_id,
        )
        trace.final_event_persisted = persisted
        trace.trace_health = asdict(self.runtime.trace_health)
        payload = trace.to_dict(include_candidates=True)
        payload["trace_persisted"] = persisted
        payload["trace_health"] = asdict(self.runtime.trace_health)
        return payload

    def record_consumer_receipt(
        self,
        *,
        episode_id: str,
        organ: str,
        consumer_id: str,
        consumer_input: Any,
        consumer_output: Any,
        verdict_class: ConsumerVerdictClass,
        verdict_detail: str | None,
        evidence_refs: tuple[str, ...],
        authority_effect: AuthorityEffect = AuthorityEffect.EVIDENCE_ONLY,
    ) -> ConsumerReceipt:
        """Registra consumo después de ejecutar al consumidor y valida fail-closed."""

        session = self._session(episode_id)
        entry = session.entries[organ]
        if entry.candidate_hash is None:
            raise ValueError("consumer_receipt_requires_candidate_hash")
        receipt = ConsumerReceipt(
            receipt_id=f"receipt-{uuid4().hex}",
            identity=session.trace.identity,
            organ=organ,
            candidate_hash=entry.candidate_hash,
            consumer_id=consumer_id,
            consumer_contract_version=f"{consumer_id}-v1",
            consumer_input_hash=canonical_sha256(consumer_input),
            consumer_output_hash=canonical_sha256(consumer_output),
            verdict_class=verdict_class,
            verdict_detail=verdict_detail,
            evidence_refs=evidence_refs,
            authority_effect=authority_effect,
            persisted=False,
        )
        validate_consumer_receipt(
            receipt, trace_identity=session.trace.identity, organ_trace=entry
        )
        persisted = self.runtime.persist_symbiosis_event(
            event_type="neural.consumer.receipt",
            payload=receipt.to_dict(),
            run_id=session.trace.identity.run_id,
        )
        receipt = replace(receipt, persisted=persisted)
        session.trace.consumer_receipts.append(receipt)
        return receipt

    def organ_has_candidate(self, episode_id: str, organ: str) -> bool:
        """Indica si existe un candidato hasheado que pueda recibir recibos."""

        return self._session(episode_id).entries[organ].candidate_hash is not None

    def _execute(
        self,
        session: _EpisodeSession,
        *,
        organ: str,
        context: Mapping[str, Any],
    ) -> Any:
        adapter = self._adapters[organ]
        identity = session.trace.identity
        request = NeuralInferenceRequest(
            inference_id=f"sym-{organ.lower()}-{uuid4().hex[:12]}",
            run_id=identity.run_id,
            organ=organ,
            capability=adapter.capability,
            payload={"identity": identity.to_dict(), "inputs": session.inputs},
            scope=InferenceScope.LIVE,
            resources=ResourceSnapshot.from_mapping(session.inputs.get("resources")),
            causal_context=CausalContextView(
                organism_id=identity.organism_id,
                decision_id=identity.decision_id,
                episode_id=identity.episode_id,
                trace_id=identity.trace_group_id,
            ),
        )
        result = self.runtime.infer_reference(
            request=request,
            producer=lambda inference_request: adapter.infer(inference_request, context),
            fallback_output=adapter.fallback(identity),
            reference_id=adapter.reference_id,
            authority_ceiling=adapter.authority_ceiling,
            admission_gate=adapter.admission_gate,
            enabled=organ not in self._disabled_organs,
        )
        candidate = result.candidate_output
        entry = OrganTrace(
            identity=identity,
            organ=organ,
            capability=adapter.capability,
            requested_mode=result.requested_mode.value,
            effective_mode=result.effective_mode.value,
            authority_ceiling=adapter.authority_ceiling.value,
            input_hash=canonical_sha256(request.payload),
            candidate_hash=canonical_sha256(candidate) if candidate is not None else None,
            consumer=adapter.consumer,
            consumer_verdict=("disabled" if result.effective_mode is NeuralMode.OFF else "pending"),
            latency_ms=result.latency_ms,
            confidence=result.confidence,
            uncertainty=result.uncertainty,
            ram_mb=_number(result.cost.get("ram_mb")),
            vram_mb=_number(result.cost.get("vram_mb")),
            fallback_reason=result.fallback_reason,
            manifest_sha256=result.manifest_sha256,
            artifact_sha256=None,
            candidate=candidate,
            abstained=bool(isinstance(candidate, Mapping) and candidate.get("status") == "abstained"),
            cost=result.cost,
        )
        session.entries[organ] = entry
        session.trace.organs.append(entry)
        return candidate if candidate is not None else adapter.fallback(identity)

    def _session(self, episode_id: str) -> _EpisodeSession:
        try:
            return self._sessions[episode_id]
        except KeyError as exc:
            raise KeyError(f"symbiosis_episode_unknown:{episode_id}") from exc


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resource_measurement_status(raw: Mapping[str, Any]) -> dict[str, str]:
    fields = (
        "cpu_pressure",
        "memory_pressure",
        "thermal_pressure",
        "vram_pressure",
        "vram_used_gb",
        "vram_total_gb",
        "gpu_temperature_c",
        "msrc_budget_available",
        "msrc_scale_id",
    )
    statuses = {
        field: "measured" if field in raw and raw.get(field) is not None else "defaulted"
        for field in fields
    }
    if raw.get("gpu_available") is False:
        for field in ("vram_used_gb", "vram_total_gb", "gpu_temperature_c"):
            if field not in raw or raw.get(field) is None:
                statuses[field] = "not_applicable"
    return statuses
