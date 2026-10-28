"""Operational conjunction service.

This service is the coordination brain requested by the "conjunction +
compensations" design: it does not replace the organism runtime, it governs
which route may act and records why.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, Iterable

from runtime.memory.mfm_lite.retrieval import MemoryRetrieval, summarize_retrieval_hits
from runtime.storage.records import utc_now_iso
from runtime.world.registry import get_scenario

from .compensations import CompensationMatrix
from .contracts import (
    AgentPolicy,
    AutonomyPolicy,
    CausalAssumption,
    CompensationAction,
    CompensationStatus,
    ComputeTier,
    ConfidenceState,
    EvidenceItem,
    FinalDecision,
    OperationalConjunctionResult,
    OperationalConstraints,
    OperationContext,
    TaskType,
    ValidationFinding,
    ValidationStatus,
)
from .router import ComputeRouter
from .validators import OperationalValidatorStack


def _or_default(value: Any, default: float) -> float:
    """Sustituye el AUSENTE por el default; nunca el cero medido.

    `x or D` parece hacer esto y no lo hace: en Python `0.0` es falsy, así que
    una medición de cero —la más informativa que hay, porque significa que la
    cantidad se midió y dio nada— se reemplaza por el default. Sobre una pureza
    de memoria o un margen de viabilidad, eso invierte el sentido justo en el
    borde, que es donde importa.
    """
    return float(default) if value is None else float(value)


class OperationalConjunctionLayer:
    """Coordinate evidence, causality, compute, validators, and compensations."""

    def __init__(self, *, storage=None):
        self.storage = storage
        self.router = ComputeRouter()
        self.validators = OperationalValidatorStack()
        self.compensations = CompensationMatrix()

    def evaluate(self, context: OperationContext) -> OperationalConjunctionResult:
        route = self.router.route(context)
        findings = self.validators.validate(context=context, route=route)
        actions = self.compensations.compensate(context=context, findings=findings)
        context, actions, compensation_trace = self._execute_compensations(
            context=context,
            actions=actions,
        )
        if actions:
            route = self.router.route(context)
            findings = self.validators.validate(context=context, route=route)
            followup_actions = self.compensations.compensate(
                context=context,
                findings=findings,
            )
            actions = self._merge_compensation_actions(
                executed_actions=actions,
                followup_actions=followup_actions,
            )
        validation_status = self._validation_status(findings)
        compensation_status = self._compensation_status(actions, validation_status)
        confidence_state = self._confidence_state(context=context, findings=findings)
        final_decision = self._final_decision(
            context=context,
            findings=findings,
            compensation_status=compensation_status,
        )
        permissions = {
            "requested_action": context.requested_action,
            "is_critical": context.is_critical_action(),
            "agent_role": context.agent_policy.role if context.agent_policy else None,
            "agent_policy_allows": (
                context.agent_policy.allows(context.requested_action)
                if context.agent_policy else not context.is_critical_action()
            ),
            "autonomy_policy": (
                context.autonomy_policy.to_dict() if context.autonomy_policy else None
            ),
            "automatic_execution_allowed": final_decision in {
                "allow",
                "allow_with_compensation",
                "degrade",
                "observe",
            },
        }
        trace = (
            *route.trace,
            {
                "stage": "validation",
                "status": validation_status,
                "findings": [item.to_dict() for item in findings],
            },
            {
                "stage": "compensation",
                "status": compensation_status,
                "actions": [item.to_dict() for item in actions],
            },
            *compensation_trace,
            {
                "stage": "final_decision",
                "decision": final_decision,
                "confidence_state": confidence_state,
            },
        )
        result = OperationalConjunctionResult(
            operation_id=context.operation_id,
            selected_compute_tier=route.selected_compute_tier,
            selected_reasoning_path=route.selected_reasoning_path,
            validation_status=validation_status,
            compensation_status=compensation_status,
            confidence_state=confidence_state,
            execution_permissions=permissions,
            final_decision=final_decision,
            validation_findings=findings,
            compensations=actions,
            trace=trace,
            context_summary=self._context_summary(context),
        )
        self._persist_result(context=context, result=result)
        return result

    def evaluate_life_cycle(
        self,
        *,
        run_id: str,
        scenario: str,
        decision: Any,
        vitals: Any,
        goals: Iterable[Any],
        step_index: int,
        external_input: float | None,
        allow_external_reasoner: bool = False,
        max_compute_tier: ComputeTier = "tier_2_specialized",
        autonomy_policy: str = "bounded",
        resource_snapshot: Dict[str, Any] | None = None,
    ) -> OperationalConjunctionResult:
        context = self._build_life_context(
            run_id=run_id,
            scenario=scenario,
            decision=decision,
            vitals=vitals,
            goals=goals,
            step_index=step_index,
            external_input=external_input,
            allow_external_reasoner=allow_external_reasoner,
            max_compute_tier=max_compute_tier,
            autonomy_policy=autonomy_policy,
            resource_snapshot=resource_snapshot,
        )
        return self.evaluate(context)

    def _build_life_context(
        self,
        *,
        run_id: str,
        scenario: str,
        decision: Any,
        vitals: Any,
        goals: Iterable[Any],
        step_index: int,
        external_input: float | None,
        allow_external_reasoner: bool,
        max_compute_tier: ComputeTier,
        autonomy_policy: str,
        resource_snapshot: Dict[str, Any] | None = None,
    ) -> OperationContext:
        action = str(getattr(decision, "action", "act"))
        task_type = self._task_type(action)
        required = ["vital_signs", "causal_signature"]
        if action == "self_modify":
            required.extend(["healthy_checkpoint", "validated_plan", "rollback_plan"])
        elif action == "consult_external":
            required.extend(["validated_plan"])
        elif action == "rollback":
            required.append("healthy_checkpoint")

        evidence = self._life_evidence(
            run_id=run_id,
            scenario=scenario,
            vitals=vitals,
            goals=goals,
            action=action,
            step_index=step_index,
            external_input=external_input,
            decision=decision,
        )
        causal = self._causal_assumptions(scenario=scenario, evidence=evidence)
        resource_pressure = float(getattr(vitals, "resource_pressure", 0.0) or 0.0)
        raw_risk = float(getattr(vitals, "risk_score", 0.0) or 0.0)
        if int(getattr(vitals, "episode_count", 0) or 0) <= 0 and action == "act":
            raw_risk = min(raw_risk, 0.50)
        constraints = OperationalConstraints(
            max_compute_tier=(
                "tier_0_deterministic" if resource_pressure >= 0.90 else max_compute_tier
            ),
            allow_external=bool(allow_external_reasoner),
            resource_pressure_limit=0.85,
            permitted_actions=self._permitted_actions(allow_external_reasoner),
        )
        resolved_autonomy = AutonomyPolicy.resolve(
            requested_mode=autonomy_policy,
            risk_score=raw_risk,
            resource_pressure=resource_pressure,
            # Sin `or 1.0`. `min_memory_purity` es un invariante constitucional
            # DURO: una pureza medida de 0.0 debe disparar violación y cuarentena.
            # El `or` la leía como pureza perfecta y el invariante no se enteraba.
            memory_purity=_or_default(getattr(vitals, "memory_purity", None), 1.0),
            agent_policy_present=True,
            operational_conjunction_enabled=True,
            resource_pressure_limit=0.85,
        )
        agent_policy = AgentPolicy(
            role="life_kernel",
            allowed_actions=self._permitted_actions(allow_external_reasoner),
            prohibited_actions=() if allow_external_reasoner else ("consult_external",),
            budget_units=1.0,
            max_steps=0 if resolved_autonomy.active_mode == "governed_unbounded" else 1,
            requires_plan_for_critical=True,
            rollback_required_for_critical=True,
        )
        complexity = self._complexity_for(action=action, goals=goals)
        uncertainty = self._uncertainty(vitals=vitals, evidence=evidence)
        directives = getattr(decision, "directives", {}) or {}
        snap = resource_snapshot or {}
        gpu_available = bool(snap.get("gpu_available"))
        return OperationContext.create(
            run_id=run_id,
            user_intent="maintain_autonomous_life_cycle",
            task_type=task_type,
            requested_action=action,
            scenario=scenario,
            required_evidence=required,
            available_evidence=evidence,
            causal_assumptions=causal,
            constraints=constraints,
            agent_policy=agent_policy,
            autonomy_policy=resolved_autonomy,
            risk_score=raw_risk,
            complexity_score=complexity,
            resource_pressure=resource_pressure,
            uncertainty_score=uncertainty,
            gpu_available=gpu_available,
            vram_pressure=float(snap.get("vram_pressure", 0.0) or 0.0),
            vram_headroom=float(snap.get("vram_headroom", 0.0) or 0.0),
            gpu_acceleration=float(snap.get("gpu_acceleration", 0.0) or 0.0),
            metadata={
                "step_index": step_index,
                "external_input": external_input,
                "decision_id": getattr(decision, "decision_id", None),
                "decision_reason": getattr(decision, "reason", None),
                "requested_tool": directives.get("requested_tool"),
                "agent_step_count": int(directives.get("agent_step_count", 0) or 0),
                "human_approved": bool(directives.get("human_approved")),
                "autonomy_policy": resolved_autonomy.to_dict(),
            },
        )

    def _life_evidence(
        self,
        *,
        run_id: str,
        scenario: str,
        vitals: Any,
        goals: Iterable[Any],
        action: str,
        step_index: int,
        external_input: float | None,
        decision: Any,
    ) -> tuple[EvidenceItem, ...]:
        evidence: list[EvidenceItem] = [
            EvidenceItem.create(
                kind="vital_signs",
                source="life.vitals",
                confidence=0.90,
                payload=vitals.to_dict() if hasattr(vitals, "to_dict") else {},
                canonical=True,
            )
        ]
        try:
            signature = get_scenario(scenario).causal_signature
            evidence.append(
                EvidenceItem.create(
                    kind="causal_signature",
                    source="world.registry",
                    confidence=self._signature_confidence(signature),
                    payload={
                        "scenario": signature.scenario_name,
                        "main_variable": signature.main_variable,
                        "edge_count": len(signature.causal_edges),
                        "intervention_count": len(signature.intervention_effects),
                    },
                    canonical=True,
                )
            )
        except Exception as exc:
            evidence.append(
                EvidenceItem.create(
                    kind="conflict",
                    source="world.registry",
                    confidence=0.10,
                    payload={"conflict": True, "error": f"{type(exc).__name__}: {exc}"},
                )
            )

        memory_hits = self._retrieve_life_memory(
            run_id=run_id,
            scenario=scenario,
            action=action,
            external_input=external_input,
        )
        if memory_hits:
            top = memory_hits[0]
            evidence.append(
                EvidenceItem.create(
                    kind="memory_rag",
                    source="memory.mfm_lite",
                    confidence=float(top.get("score", 0.0) or 0.0),
                    payload={"hit_count": len(memory_hits), "top": top},
                )
            )

        checkpoint = self._latest_checkpoint(run_id=run_id)
        if checkpoint is not None:
            evidence.append(
                EvidenceItem.create(
                    kind="healthy_checkpoint",
                    source="life.checkpoint",
                    confidence=0.80 if checkpoint.get("healthy") else 0.45,
                    payload=checkpoint,
                    canonical=bool(checkpoint.get("healthy")),
                )
            )
            evidence.append(
                EvidenceItem.create(
                    kind="rollback_plan",
                    source="life.checkpoint",
                    confidence=0.75,
                    payload={
                        "plan": "restore_latest_healthy_checkpoint",
                        "checkpoint_artifact_id": checkpoint.get("artifact_id"),
                    },
                    canonical=True,
                )
            )

        directives = getattr(decision, "directives", {}) or {}
        if directives.get("validated_plan") is True:
            evidence.append(
                EvidenceItem.create(
                    kind="validated_plan",
                    source="autonomy_supervisor",
                    confidence=0.75,
                    payload={"step_index": step_index, "action": action},
                    canonical=True,
                )
            )
        if directives.get("human_approved") is True:
            evidence.append(
                EvidenceItem.create(
                    kind="human_approval",
                    source="autonomy_supervisor",
                    confidence=0.95,
                    payload={"step_index": step_index, "action": action},
                    canonical=True,
                )
            )
        return tuple(evidence)

    def _execute_compensations(
        self,
        *,
        context: OperationContext,
        actions: tuple[CompensationAction, ...],
    ) -> tuple[OperationContext, tuple[CompensationAction, ...], tuple[Dict[str, Any], ...]]:
        if not actions:
            return context, actions, ()

        current = context
        executed: list[CompensationAction] = []
        trace: list[Dict[str, Any]] = []
        for action in actions:
            current, action, entry = self._execute_compensation(
                context=current,
                action=action,
            )
            executed.append(action)
            trace.append(entry)
            self._persist_compensation_execution(context=current, action=action, entry=entry)
        return current, tuple(executed), tuple(trace)

    def _execute_compensation(
        self,
        *,
        context: OperationContext,
        action: CompensationAction,
    ) -> tuple[OperationContext, CompensationAction, Dict[str, Any]]:
        directive = dict(action.directive)
        evidence_before = context.evidence_kinds()
        metadata = dict(context.metadata)
        status = action.status

        if action.code == "expand_retrieval":
            missing_kind = str(directive.get("finding_details", {}).get("missing_kind") or "")
            recovered = self._recover_evidence(context=context, kind=missing_kind)
            if recovered:
                context = self._with_evidence(context=context, evidence=recovered)
                status = "applied"
                directive["recovered_evidence_kinds"] = [item.kind for item in recovered]
            directive["executed"] = True
            directive["execution"] = "recovered_evidence" if recovered else "no_recovery_available"

        elif action.code == "resource_conservation":
            metadata.update(
                {
                    "context_reduced": True,
                    "cache_preferred": True,
                    "large_models_avoided": True,
                }
            )
            context = replace(context, metadata=metadata)
            directive["executed"] = True
            directive["execution"] = "resource_conservation_mode_enabled"

        elif action.code in {"degrade_compute_tier", "degrade_to_local"}:
            max_tier = "tier_1_local_light"
            if action.code == "degrade_compute_tier":
                max_tier = context.constraints.max_compute_tier
            context = replace(
                context,
                constraints=replace(
                    context.constraints,
                    max_compute_tier=max_tier,
                    allow_external=False,
                ),
                metadata={**metadata, "external_reasoner_disabled": True},
            )
            directive["executed"] = True
            directive["execution"] = "compute_policy_degraded"

        elif action.code == "require_rollback_plan":
            recovered = self._recover_evidence(context=context, kind="rollback_plan")
            if recovered:
                context = self._with_evidence(context=context, evidence=recovered)
                status = "applied"
                directive["recovered_evidence_kinds"] = [item.kind for item in recovered]
            directive["executed"] = True
            directive["execution"] = "checkpoint_lookup_performed"

        elif action.code == "require_plan_validation":
            plan_evidence = EvidenceItem.create(
                kind="execution_plan",
                source="operational_conjunction",
                confidence=0.55,
                payload={
                    "requested_action": context.requested_action,
                    "requires_validation": True,
                    "created_from_compensation": True,
                },
            )
            context = self._with_evidence(context=context, evidence=(plan_evidence,))
            directive["created_evidence_kind"] = "execution_plan"
            directive["executed"] = True
            directive["execution"] = "draft_plan_created_requires_validation"

        elif action.code == "downgrade_causal_claim":
            context = replace(
                context,
                metadata={**metadata, "causal_claim_downgraded_to_hypothesis": True},
            )
            directive["executed"] = True
            directive["execution"] = "causal_claim_marked_hypothesis"

        elif action.code == "mark_conflict":
            context = replace(
                context,
                metadata={**metadata, "conflicting_evidence_isolated": True},
            )
            directive["executed"] = True
            directive["execution"] = "conflict_isolated"

        elif action.code == "require_human_approval":
            recovered = self._recover_evidence(context=context, kind="human_approval")
            if recovered:
                context = self._with_evidence(context=context, evidence=recovered)
                status = "applied"
                directive["recovered_evidence_kinds"] = [item.kind for item in recovered]
            directive["executed"] = True
            directive["execution"] = "human_approval_checked"

        elif action.code == "stop_agent":
            context = replace(
                context,
                metadata={
                    **metadata,
                    "agent_stopped": True,
                    "stop_reason": directive.get("stop_condition", action.reason),
                },
            )
            directive["executed"] = True
            directive["execution"] = "agent_stop_condition_applied"

        elif action.code == "degrade_autonomy_scope":
            context = replace(
                context,
                metadata={
                    **metadata,
                    "autonomy_degraded": True,
                    "autonomy_degradation_reason": directive.get("finding_details", {}).get(
                        "degradation_reason",
                        action.reason,
                    ),
                },
            )
            directive["executed"] = True
            directive["execution"] = "autonomy_scope_degraded_to_bounded"

        else:
            context = replace(context, metadata={**metadata, "scope_reduced": True})
            directive["executed"] = True
            directive["execution"] = "scope_reduction_applied"

        evidence_after = context.evidence_kinds()
        executed_action = replace(action, status=status, directive=directive)
        return (
            context,
            executed_action,
            {
                "stage": "compensation.execution",
                "action": action.code,
                "status": status,
                "execution": directive.get("execution"),
                "added_evidence_kinds": sorted(evidence_after - evidence_before),
            },
        )

    def _recover_evidence(
        self,
        *,
        context: OperationContext,
        kind: str,
    ) -> tuple[EvidenceItem, ...]:
        if not kind or context.has_evidence(kind):
            return ()
        if kind == "memory_rag":
            hits = self._retrieve_verified_memory(context=context)
            if not hits:
                return ()
            top = hits[0]
            attestation = top.get("rag_attestation") if isinstance(top, dict) else None
            return (
                EvidenceItem.create(
                    kind="memory_rag",
                    source="memory.hybrid_verified",
                    confidence=float(top.get("score", 0.0) or 0.0),
                    payload={
                        "hit_count": len(hits),
                        "top": top,
                        "rag_attestation": attestation,
                        "retrieval_strategy": [
                            "exact_event_search",
                            "structural_overlap",
                            "canonical_source_priority",
                        ],
                    },
                    canonical=bool(top.get("canonical")),
                ),
            )
        if kind == "causal_signature" and context.scenario:
            try:
                signature = get_scenario(context.scenario).causal_signature
            except Exception:
                return ()
            return (
                EvidenceItem.create(
                    kind="causal_signature",
                    source="world.registry",
                    confidence=self._signature_confidence(signature),
                    payload={
                        "scenario": signature.scenario_name,
                        "main_variable": signature.main_variable,
                        "edge_count": len(signature.causal_edges),
                        "intervention_count": len(signature.intervention_effects),
                    },
                    canonical=True,
                ),
            )
        if kind in {"healthy_checkpoint", "rollback_plan"} and context.run_id:
            checkpoint = self._latest_checkpoint(run_id=context.run_id)
            if not checkpoint:
                return ()
            out = []
            if kind == "healthy_checkpoint" and checkpoint.get("healthy"):
                out.append(
                    EvidenceItem.create(
                        kind="healthy_checkpoint",
                        source="life.checkpoint",
                        confidence=0.80,
                        payload=checkpoint,
                        canonical=True,
                    )
                )
            if kind == "rollback_plan":
                out.append(
                    EvidenceItem.create(
                        kind="rollback_plan",
                        source="life.checkpoint",
                        confidence=0.75 if checkpoint.get("healthy") else 0.40,
                        payload={
                            "plan": "restore_latest_healthy_checkpoint",
                            "checkpoint_artifact_id": checkpoint.get("artifact_id"),
                            "healthy": checkpoint.get("healthy"),
                        },
                        canonical=bool(checkpoint.get("healthy")),
                    )
                )
            return tuple(out)
        if kind == "human_approval" and context.metadata.get("human_approved") is True:
            return (
                EvidenceItem.create(
                    kind="human_approval",
                    source="operation.metadata",
                    confidence=0.95,
                    payload={"approved": True},
                    canonical=True,
                ),
            )
        return ()

    def _retrieve_verified_memory(self, *, context: OperationContext) -> list[Dict[str, Any]]:
        if self.storage is None or not context.run_id:
            return []
        query = {
            "scenario": context.scenario,
            "action": context.requested_action,
            **{
                key: value for key, value in context.metadata.items()
                if key in {"external_input", "decision_reason"}
            },
        }
        exact_hits = self._exact_event_search(context=context, query=query)
        structural_hits = self._retrieve_life_memory(
            run_id=context.run_id,
            scenario=context.scenario or "",
            action=context.requested_action,
            external_input=context.metadata.get("external_input"),
        )
        hits = [
            *exact_hits,
            *[
                {
                    **item,
                    "strategy": "structural_overlap",
                    "canonical": False,
                }
                for item in structural_hits
            ],
        ]
        hits.sort(key=lambda item: (bool(item.get("canonical")), float(item.get("score", 0.0))), reverse=True)
        selected = hits[:5]
        attestation = summarize_retrieval_hits(selected)
        for hit in selected:
            hit.setdefault("rag_attestation", attestation)
        return selected

    def _exact_event_search(
        self,
        *,
        context: OperationContext,
        query: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        if self.storage is None:
            return []
        terms = {
            str(value).lower()
            for value in query.values()
            if value not in {None, ""}
        }
        if not terms:
            return []
        try:
            events = self.storage.list_events(run_id=context.run_id, limit=100)
        except Exception:
            return []
        hits: list[Dict[str, Any]] = []
        for event in events:
            payload = json.dumps(event.payload or {}, ensure_ascii=True, sort_keys=True).lower()
            matched = sorted(term for term in terms if term in payload)
            if not matched:
                continue
            hits.append(
                {
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "source": event.source,
                    "score": round(len(matched) / len(terms), 4),
                    "matched_terms": matched,
                    "strategy": "exact_event_search",
                    "canonical": event.source in {"life_kernel", "operational_conjunction"},
                }
            )
        return hits

    @staticmethod
    def _with_evidence(
        *,
        context: OperationContext,
        evidence: tuple[EvidenceItem, ...],
    ) -> OperationContext:
        existing_ids = {item.evidence_id for item in context.available_evidence}
        existing_kinds = context.evidence_kinds()
        additions = [
            item for item in evidence
            if item.evidence_id not in existing_ids and item.kind not in existing_kinds
        ]
        if not additions:
            return context
        return replace(context, available_evidence=(*context.available_evidence, *additions))

    @staticmethod
    def _merge_compensation_actions(
        *,
        executed_actions: tuple[CompensationAction, ...],
        followup_actions: tuple[CompensationAction, ...],
    ) -> tuple[CompensationAction, ...]:
        merged: dict[tuple[str, str], CompensationAction] = {}
        for action in executed_actions:
            key = (action.code, str(action.directive.get("finding_code", "")))
            merged[key] = action
        for action in followup_actions:
            key = (action.code, str(action.directive.get("finding_code", "")))
            previous = merged.get(key)
            if previous is None:
                merged[key] = action
                continue
            merged[key] = replace(
                previous,
                status="blocked" if action.status == "blocked" else previous.status,
                reason=action.reason,
                directive={**previous.directive, **action.directive},
            )
        return tuple(merged.values())

    def _retrieve_life_memory(
        self,
        *,
        run_id: str,
        scenario: str,
        action: str,
        external_input: float | None,
    ) -> list[Dict[str, Any]]:
        if self.storage is None:
            return []
        try:
            return MemoryRetrieval(storage=self.storage).retrieve(
                run_id=run_id,
                query={
                    "scenario": scenario,
                    "action": action,
                    "external_input_band": "high" if (external_input or 0.0) >= 0.10 else "normal",
                },
                limit=3,
                scenario_name=scenario,
                scenario_filter_mode="strict_same_scenario",
            )
        except Exception:
            return []

    def _latest_checkpoint(self, *, run_id: str) -> Dict[str, Any] | None:
        if self.storage is None:
            return None
        try:
            from runtime.core.checkpoint_kinds import LIFE_CHECKPOINT_KIND

            artifacts = self.storage.list_artifacts(
                run_id=run_id,
                kind=LIFE_CHECKPOINT_KIND,
                limit=1,
            )
        except Exception:
            return None
        if not artifacts:
            return None
        artifact = artifacts[0]
        return {
            "artifact_id": artifact.artifact_id,
            "healthy": bool((artifact.metadata or {}).get("healthy")),
            "created_at": artifact.created_at,
        }

    def _causal_assumptions(
        self,
        *,
        scenario: str,
        evidence: tuple[EvidenceItem, ...],
    ) -> tuple[CausalAssumption, ...]:
        try:
            signature = get_scenario(scenario).causal_signature
        except Exception:
            return (
                CausalAssumption(
                    name="scenario_causal_signature",
                    statement="scenario must expose causal support",
                    supported=False,
                    strength=0.0,
                ),
            )
        evidence_ids = tuple(
            item.evidence_id for item in evidence if item.kind == "causal_signature"
        )
        strength = self._signature_confidence(signature)
        return (
            CausalAssumption(
                name="scenario_causal_graph",
                statement="interventions are evaluated against scenario causal signature",
                supported=bool(signature.causal_edges and signature.intervention_effects),
                strength=strength,
                support_evidence_ids=evidence_ids,
            ),
        )

    @staticmethod
    def _signature_confidence(signature: Any) -> float:
        edges = list(getattr(signature, "causal_edges", ()) or ())
        if not edges:
            return 0.0
        return round(sum(float(getattr(edge, "strength", 0.0)) for edge in edges) / len(edges), 4)

    @staticmethod
    def _task_type(action: str) -> TaskType:
        if action == "self_modify":
            return "self_modification"
        if action == "consult_external":
            return "external_consultation"
        if action in {"rollback", "quarantine", "shutdown", "sleep"}:
            return "maintenance"
        if action in {"act", "explore"}:
            return "life_cycle"
        return "agent_action"

    @staticmethod
    def _permitted_actions(allow_external_reasoner: bool) -> tuple[str, ...]:
        base = (
            "act",
            "observe",
            "explore",
            "sleep",
            "self_modify",
            "rollback",
            "quarantine",
            "shutdown",
        )
        if allow_external_reasoner:
            return (*base, "consult_external")
        return base

    @staticmethod
    def _complexity_for(*, action: str, goals: Iterable[Any]) -> float:
        if action in {"self_modify", "rollback", "consult_external"}:
            return 0.80
        if action == "explore":
            return 0.55
        active_goals = [goal for goal in goals if getattr(goal, "status", "active") == "active"]
        return min(0.65, 0.20 + 0.05 * len(active_goals))

    @staticmethod
    def _uncertainty(*, vitals: Any, evidence: tuple[EvidenceItem, ...]) -> float:
        cognitive_quality = _or_default(getattr(vitals, "cognitive_quality", None), 0.5)
        memory_bonus = 0.20 if any(item.kind == "memory_rag" for item in evidence) else 0.0
        conflict_penalty = 0.35 if any(item.kind == "conflict" for item in evidence) else 0.0
        return max(0.0, min(1.0, 1.0 - cognitive_quality - memory_bonus + conflict_penalty))

    @staticmethod
    def _validation_status(findings: tuple[ValidationFinding, ...]) -> ValidationStatus:
        if any(item.status == "fail" for item in findings):
            return "fail"
        if any(item.status == "warn" for item in findings):
            return "warn"
        return "pass"

    @staticmethod
    def _compensation_status(
        actions: tuple[Any, ...],
        validation_status: ValidationStatus,
    ) -> CompensationStatus:
        if any(item.status == "blocked" for item in actions):
            return "blocked"
        if actions:
            return "required" if validation_status == "fail" else "applied"
        return "none"

    @staticmethod
    def _confidence_state(
        *,
        context: OperationContext,
        findings: tuple[ValidationFinding, ...],
    ) -> ConfidenceState:
        if any(item.code == "contradictory_evidence" for item in findings):
            return "conflicted"
        if context.uncertainty_score >= 0.70 or any(item.status == "fail" for item in findings):
            return "low"
        if context.uncertainty_score >= 0.40 or any(item.status == "warn" for item in findings):
            return "medium"
        return "high"

    @staticmethod
    def _final_decision(
        *,
        context: OperationContext,
        findings: tuple[ValidationFinding, ...],
        compensation_status: CompensationStatus,
    ) -> FinalDecision:
        if compensation_status == "blocked":
            return "block"
        if any(item.status == "fail" for item in findings):
            return "block" if context.is_critical_action() else "degrade"
        if compensation_status == "applied":
            return "allow_with_compensation"
        if any(item.status == "warn" for item in findings):
            return "allow_with_compensation"
        return "allow"

    @staticmethod
    def _context_summary(context: OperationContext) -> Dict[str, Any]:
        return {
            "run_id": context.run_id,
            "task_type": context.task_type,
            "requested_action": context.requested_action,
            "scenario": context.scenario,
            "required_evidence": list(context.required_evidence),
            "available_evidence_kinds": sorted(context.evidence_kinds()),
            "risk_score": context.risk_score,
            "complexity_score": context.complexity_score,
            "resource_pressure": context.resource_pressure,
            "uncertainty_score": context.uncertainty_score,
            "autonomy_policy": (
                context.autonomy_policy.to_dict() if context.autonomy_policy else None
            ),
        }

    def _persist_compensation_execution(
        self,
        *,
        context: OperationContext,
        action: CompensationAction,
        entry: Dict[str, Any],
    ) -> None:
        if self.storage is None:
            return
        try:
            self.storage.append_event(
                event_type="operational.compensation.executed",
                run_id=context.run_id,
                source="operational_conjunction",
                payload={
                    "timestamp": utc_now_iso(),
                    "operation_id": context.operation_id,
                    "action": action.to_dict(),
                    "trace": dict(entry),
                },
            )
        except Exception:
            return

    def _persist_result(
        self,
        *,
        context: OperationContext,
        result: OperationalConjunctionResult,
    ) -> None:
        if self.storage is None:
            return
        try:
            self.storage.append_event(
                event_type="operational.conjunction.evaluated",
                run_id=context.run_id,
                source="operational_conjunction",
                payload={
                    "timestamp": utc_now_iso(),
                    "context": context.to_dict(),
                    "result": result.to_dict(),
                },
            )
        except Exception:
            return
