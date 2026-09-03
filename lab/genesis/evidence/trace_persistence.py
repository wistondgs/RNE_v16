"""Validate-first persistence and fresh-object replay for sealed M6 traces."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping

from lab.genesis.causal.cfi import CFIReport
from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import VerifierReceipt
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256
from lab.genesis.contracts.verification import VerificationObligation, VerificationPlan
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode
from lab.genesis.verifiers.adjudication import (
    RequirementAdjudicationReceipt, validate_requirement_adjudication,
)
from lab.genesis.verifiers.descriptor import VerifierDescriptor
from lab.genesis.verifiers.evidence import (
    ExecutionRecordMaterial, RequirementEvidenceBundle,
    validate_requirement_evidence_bundle,
)
from lab.genesis.verifiers.execution import (
    ExecutionSubjectBinding, PlannedExecutionRequest, VerifierExecutionRecord,
    validate_execution_record,
)
from lab.genesis.verifiers.federation import (
    FederatedVerificationRequirement, VerifierDependencyGraph,
    VerifierIntegrityReceipt, VerifierRegistry,
)
from lab.genesis.verifiers.plan import (
    FederationPlan, RequirementRoutingResult, SelectedVerifierBinding,
)
from lab.genesis.verifiers.references import (
    QualifiedReferenceBinding, ReferenceDescriptor, ReferenceQualificationPolicy,
    ReferenceQualificationReceipt, ReferenceRegistry,
)
from lab.genesis.verifiers.reliability import VerifierReliabilityProfile
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCampaignReceipt, ReliabilityCaseResult,
)
from lab.genesis.verifiers.router import VerifierRouter, validate_federation_plan

from .artifacts import ContentAddressedArtifactStore
from .events import EvidenceEvent
from .ledger import EvidenceLedger
from .seals import LedgerSeal
from .trace_closure import (
    TRACE_SCHEMA_VERSION, TraceArtifactGroup, TraceClosureManifest,
    derive_trace_id, verify_trace_closure,
)


ROLE_ORDER = (
    "typed_claim", "verification_plan", "federated_requirement",
    "verifier_descriptor", "verifier_dependency_graph", "reliability_campaign",
    "reliability_profile", "integrity_receipt", "reference_descriptor",
    "reference_qualification_policy", "reference_qualification_receipt",
    "qualified_reference_binding", "cfi_report", "federation_plan",
    "selected_verifier_binding", "execution_subject_binding",
    "planned_execution_request", "verifier_receipt", "verifier_execution_record",
    "requirement_evidence_bundle", "requirement_adjudication_receipt",
    "provenance_metadata", "provenance_node", "provenance_edge",
)
ROLE_RANK = {role: index for index, role in enumerate(ROLE_ORDER)}


@dataclass(frozen=True, slots=True)
class PersistedTrace:
    trace_id: str
    closure_hash: str
    closure: TraceClosureManifest


@dataclass(frozen=True, slots=True)
class TraceReplay:
    admitted: bool
    reasons: tuple[str, ...]
    closure_hash: str
    adjudication: RequirementAdjudicationReceipt | None = None
    graph: ProvenanceGraph | None = None


@dataclass(frozen=True, slots=True)
class _StagedTrace:
    closure: TraceClosureManifest
    events: tuple[EvidenceEvent, ...]
    seal: LedgerSeal
    graph: ProvenanceGraph
    payloads: Mapping[str, Any]
    artifact_commit_order: tuple[str, ...]


class _Catalog:
    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.groups: dict[str, set[str]] = {}

    def add(self, role: str, item: Any, expected_hash: str | None = None) -> str:
        raw_payload = item.canonical_payload() if hasattr(item, "canonical_payload") else item
        # Stage exactly what ``ContentAddressedArtifactStore.get`` will later
        # return; never accidentally validate against live nested dataclasses.
        payload = json.loads(canonical_json_bytes(raw_payload).decode("utf-8"))
        artifact_hash = canonical_sha256(payload)
        if expected_hash is not None and artifact_hash != expected_hash:
            raise ValueError(f"genesis_trace_artifact_identity_mismatch:{role}")
        previous = self.payloads.setdefault(artifact_hash, payload)
        if canonical_sha256(previous) != artifact_hash:
            raise ValueError("genesis_trace_artifact_payload_conflict")
        self.groups.setdefault(role, set()).add(artifact_hash)
        return artifact_hash

    def groups_as_contracts(self) -> tuple[TraceArtifactGroup, ...]:
        return tuple(TraceArtifactGroup(role, tuple(hashes))
                     for role, hashes in sorted(self.groups.items()))

    def order(self) -> tuple[str, ...]:
        roles_by_hash: dict[str, set[str]] = {}
        for role, hashes in self.groups.items():
            for artifact_hash in hashes:
                roles_by_hash.setdefault(artifact_hash, set()).add(role)
        return tuple(sorted(
            self.payloads,
            key=lambda artifact_hash: (
                min(ROLE_RANK.get(role, len(ROLE_ORDER)) for role in roles_by_hash[artifact_hash]),
                artifact_hash,
            ),
        ))


def _dependency_graph_payload(graph: VerifierDependencyGraph) -> dict[str, object]:
    return {"nodes": sorted(graph.nodes), "edges": sorted(graph.edges), "complete": graph.complete}


def _validate_input(*, router: VerifierRouter, federation_plan: FederationPlan,
                    subject: ExecutionSubjectBinding,
                    records: Iterable[ExecutionRecordMaterial],
                    bundle: RequirementEvidenceBundle,
                    adjudication: RequirementAdjudicationReceipt) -> tuple[ExecutionRecordMaterial, ...]:
    records = tuple(records)
    if not validate_federation_plan(federation_plan, router):
        raise ValueError("genesis_trace_federation_plan_invalid")
    if not subject.validate() or not all(binding.validate() for binding in federation_plan.selected_bindings):
        raise ValueError("genesis_trace_binding_or_subject_invalid")
    bindings = {item.binding_hash: item for item in federation_plan.selected_bindings}
    for material in records:
        binding = bindings.get(material.record.selected_verifier_binding_hash)
        if binding is None or not validate_execution_record(
            material.record, receipt=material.receipt, subject=subject,
            request=material.request, binding=binding, descriptor=material.descriptor,
            qualified_reference_binding=material.qualified_reference_binding,
        ):
            raise ValueError("genesis_trace_execution_record_invalid")
    if not validate_requirement_evidence_bundle(
        bundle, router=router, federation_plan=federation_plan, subject=subject, records=records,
    ):
        raise ValueError("genesis_trace_bundle_invalid")
    if not validate_requirement_adjudication(
        adjudication, router=router, federation_plan=federation_plan,
        bundle=bundle, subject=subject, records=records,
    ):
        raise ValueError("genesis_trace_adjudication_invalid")
    return records


def _add_historical_catalog(catalog: _Catalog, *, router: VerifierRouter,
                            federation_plan: FederationPlan,
                            subject: ExecutionSubjectBinding,
                            records: tuple[ExecutionRecordMaterial, ...],
                            bundle: RequirementEvidenceBundle,
                            adjudication: RequirementAdjudicationReceipt) -> None:
    catalog.add("typed_claim", router.claim, router.claim.claim_hash)
    catalog.add("verification_plan", router.verification_plan, router.verification_plan.plan_hash)
    for item in router.requirements:
        catalog.add("federated_requirement", item, item.requirement_hash)
    descriptors = tuple(sorted(router.registry.items.values(), key=lambda item: item.descriptor_hash))
    for item in descriptors:
        catalog.add("verifier_descriptor", item, item.descriptor_hash)
    catalog.add("verifier_dependency_graph", _dependency_graph_payload(router.graph), federation_plan.dependency_graph_hash)
    for item in router.campaigns:
        catalog.add("reliability_campaign", item, item.campaign_hash)
    for item in router.profiles:
        catalog.add("reliability_profile", item, item.profile_hash)
    for item in router.integrities:
        catalog.add("integrity_receipt", item, item.receipt_hash)
    if router.reference_registry is not None:
        for item in router.reference_registry.descriptors():
            catalog.add("reference_descriptor", item, item.descriptor_hash)
    for item in router.qualification_policies:
        catalog.add("reference_qualification_policy", item, item.policy_hash)
    for item in router.qualification_receipts:
        catalog.add("reference_qualification_receipt", item, item.receipt_hash)
    for item in router.ref_bindings:
        catalog.add("qualified_reference_binding", item, item.binding_hash)
    for item in router.cfi_reports:
        catalog.add("cfi_report", item, item.report_hash)
    catalog.add("federation_plan", federation_plan, federation_plan.plan_hash)
    for item in federation_plan.selected_bindings:
        catalog.add("selected_verifier_binding", item, item.binding_hash)
    catalog.add("execution_subject_binding", subject, subject.subject_hash)
    for material in records:
        catalog.add("planned_execution_request", material.request, material.request.request_hash)
        catalog.add("verifier_receipt", material.receipt, material.receipt.receipt_hash)
        catalog.add("verifier_execution_record", material.record, material.record.record_hash)
        catalog.add("verifier_descriptor", material.descriptor, material.descriptor.descriptor_hash)
        if material.qualified_reference_binding is not None:
            catalog.add("qualified_reference_binding", material.qualified_reference_binding,
                        material.qualified_reference_binding.binding_hash)
    catalog.add("requirement_evidence_bundle", bundle, bundle.bundle_hash)
    catalog.add("requirement_adjudication_receipt", adjudication, adjudication.receipt_hash)


def _build_provenance(catalog: _Catalog, trace_id: str) -> tuple[ProvenanceGraph, tuple[str, ...], tuple[str, ...]]:
    graph = ProvenanceGraph()
    base_hashes = catalog.order()
    node_by_hash: dict[str, ProvenanceNode] = {}
    roles_by_hash: dict[str, tuple[str, ...]] = {}
    for role, hashes in catalog.groups.items():
        for artifact_hash in hashes:
            roles_by_hash[artifact_hash] = tuple(sorted((*roles_by_hash.get(artifact_hash, ()), role)))
    for artifact_hash in base_hashes:
        metadata_hash = catalog.add("provenance_metadata", {
            "trace_id": trace_id, "artifact_hash": artifact_hash,
            "roles": roles_by_hash[artifact_hash],
        })
        node = ProvenanceNode(
            f"m6b4-node-{artifact_hash}", TRACE_SCHEMA_VERSION, NodeType.EVIDENCE,
            artifact_hash, "genesis.m6b4", metadata_hash,
        )
        catalog.add("provenance_node", node, node.node_hash)
        graph.add_node(node)
        node_by_hash[artifact_hash] = node
    dependencies = {
        "verification_plan": ("typed_claim",),
        "federated_requirement": ("typed_claim", "verification_plan"),
        "verifier_dependency_graph": ("verifier_descriptor",),
        "reliability_profile": ("reliability_campaign",),
        "integrity_receipt": ("verifier_descriptor", "reliability_profile"),
        "federation_plan": ("typed_claim", "verification_plan", "federated_requirement",
                              "verifier_descriptor", "verifier_dependency_graph",
                              "reliability_profile", "integrity_receipt", "cfi_report"),
        "selected_verifier_binding": ("federation_plan", "verifier_descriptor", "integrity_receipt", "reliability_profile"),
        "execution_subject_binding": ("typed_claim",),
        "planned_execution_request": ("federation_plan", "selected_verifier_binding", "execution_subject_binding"),
        "verifier_execution_record": ("planned_execution_request", "verifier_receipt", "verifier_descriptor", "execution_subject_binding"),
        "requirement_evidence_bundle": ("federation_plan", "execution_subject_binding", "verifier_execution_record"),
        "requirement_adjudication_receipt": ("federation_plan", "execution_subject_binding", "requirement_evidence_bundle", "verifier_execution_record"),
    }
    edges: set[tuple[str, str, EdgeType, EdgeClass]] = set()
    for target_role, source_roles in dependencies.items():
        for target_hash in catalog.groups.get(target_role, ()):
            for source_role in source_roles:
                for source_hash in catalog.groups.get(source_role, ()):
                    if source_hash != target_hash:
                        edges.add((source_hash, target_hash, EdgeType.DERIVED_FROM, EdgeClass.LINEAGE))
    for source_hash in catalog.groups.get("verifier_execution_record", ()):
        for target_hash in catalog.groups.get("requirement_adjudication_receipt", ()):
            edges.add((source_hash, target_hash, EdgeType.SUPPORTED_BY, EdgeClass.RELATIONAL))
    edge_hashes: list[str] = []
    for source_hash, target_hash, edge_type, edge_class in sorted(
        edges, key=lambda item: (item[0], item[1], item[2].value, item[3].value),
    ):
        edge = ProvenanceEdge(
            f"m6b4-edge-{canonical_sha256((trace_id, source_hash, target_hash, edge_type.value, edge_class.value))}",
            TRACE_SCHEMA_VERSION, node_by_hash[source_hash].node_id, node_by_hash[target_hash].node_id,
            edge_type, edge_class, 1.0,
        )
        catalog.add("provenance_edge", edge, edge.edge_hash)
        graph.add_edge(edge)
        edge_hashes.append(edge.edge_hash)
    return graph, tuple(sorted(node.node_hash for node in node_by_hash.values())), tuple(sorted(edge_hashes))


def stage_m6_trace(*, router: VerifierRouter, federation_plan: FederationPlan,
                   subject: ExecutionSubjectBinding, records: Iterable[ExecutionRecordMaterial],
                   bundle: RequirementEvidenceBundle,
                   adjudication: RequirementAdjudicationReceipt,
                   historical_artifacts: Mapping[str, Iterable[Any]] | None = None) -> _StagedTrace:
    records = _validate_input(router=router, federation_plan=federation_plan, subject=subject,
                             records=records, bundle=bundle, adjudication=adjudication)
    trace_id = derive_trace_id(
        schema_version=TRACE_SCHEMA_VERSION, federation_plan_hash=federation_plan.plan_hash,
        requirement_hash=bundle.requirement_hash, execution_subject_hash=subject.subject_hash,
        evidence_bundle_hash=bundle.bundle_hash, adjudication_receipt_hash=adjudication.receipt_hash,
    )
    catalog = _Catalog()
    _add_historical_catalog(catalog, router=router, federation_plan=federation_plan,
                            subject=subject, records=records, bundle=bundle, adjudication=adjudication)
    for role, items in (historical_artifacts or {}).items():
        for item in items:
            catalog.add(role, item)
    graph, node_hashes, edge_hashes = _build_provenance(catalog, trace_id)
    artifact_order = catalog.order()
    ledger = EvidenceLedger(f"genesis-m6b4:{trace_id}", trace_id)
    events: list[EvidenceEvent] = []
    for sequence, artifact_hash in enumerate(artifact_order):
        event = EvidenceEvent(
            f"m6b4-event-{trace_id}-{sequence}", TRACE_SCHEMA_VERSION, trace_id,
            "m6_artifact", artifact_hash, adjudication.receipt_hash,
            ledger.head_hash, sequence, "genesis.m6b4",
        )
        ledger.append(event)
        events.append(event)
    seal = LedgerSeal.seal(ledger, TRACE_SCHEMA_VERSION)
    closure = TraceClosureManifest(
        schema_version=TRACE_SCHEMA_VERSION, trace_id=trace_id,
        federation_plan_hash=federation_plan.plan_hash, requirement_hash=bundle.requirement_hash,
        execution_subject_hash=subject.subject_hash, evidence_bundle_hash=bundle.bundle_hash,
        adjudication_receipt_hash=adjudication.receipt_hash,
        artifact_groups=catalog.groups_as_contracts(),
        ordered_ledger_event_artifact_hashes=artifact_order,
        ordered_ledger_event_hashes=tuple(event.event_hash for event in events),
        ledger_head_hash=ledger.head_hash, ledger_event_count=len(events),
        ledger_seal_artifact_hash=seal.seal_hash,
        provenance_node_artifact_hashes=node_hashes,
        provenance_edge_artifact_hashes=edge_hashes,
    )
    payloads = dict(catalog.payloads)
    for event in events:
        payloads[event.event_hash] = event.canonical_payload()
    payloads[seal.seal_hash] = seal.canonical_payload()
    return _StagedTrace(closure, tuple(events), seal, graph, payloads, artifact_order)


def persist_m6_trace(store: ContentAddressedArtifactStore, **kwargs: Any) -> PersistedTrace:
    """Validate and stage everything before the first durable CAS write."""
    staged = stage_m6_trace(**kwargs)
    for artifact_hash in staged.artifact_commit_order:
        if store.put(staged.payloads[artifact_hash]) != artifact_hash:
            raise RuntimeError("genesis_trace_cas_identity_mismatch")
    for event in staged.events:
        if store.put(event.canonical_payload()) != event.event_hash:
            raise RuntimeError("genesis_trace_event_cas_identity_mismatch")
    if store.put(staged.seal.canonical_payload()) != staged.seal.seal_hash:
        raise RuntimeError("genesis_trace_seal_cas_identity_mismatch")
    if store.put(staged.closure.canonical_payload()) != staged.closure.closure_hash:
        raise RuntimeError("genesis_trace_closure_cas_identity_mismatch")
    return PersistedTrace(staged.closure.trace_id, staged.closure.closure_hash, staged.closure)


def _restore_claim(payload: Mapping[str, Any]) -> TypedClaim:
    return TypedClaim(**payload)


def _restore_verification_plan(payload: Mapping[str, Any]) -> VerificationPlan:
    return VerificationPlan(
        payload["plan_id"], payload["claim_hash"],
        tuple(VerificationObligation(**item) for item in payload["obligations"]),
        payload["budget"], payload["verifier_versions"],
    )


def _restore_federation_plan(payload: Mapping[str, Any]) -> FederationPlan:
    results = tuple(RequirementRoutingResult(**{
        key: value for key, value in item.items() if key != "result_hash"
    }) for item in payload["routing_results"])
    bindings = tuple(SelectedVerifierBinding(**{
        key: value for key, value in item.items() if key != "binding_hash"
    }) for item in payload["selected_bindings"])
    return FederationPlan(
        payload["schema_version"], payload["claim_hash"], payload["verification_plan_hash"],
        tuple(payload["requirement_hashes"]), results, bindings,
        payload["dependency_graph_hash"], tuple(payload["reliability_profile_hashes"]),
        tuple(payload["integrity_receipt_hashes"]),
        tuple(payload["qualified_reference_binding_hashes"]), tuple(payload["cfi_report_hashes"]),
        payload["selection_policy_hash"],
    )


def _restore_campaign(payload: Mapping[str, Any]) -> ReliabilityCampaignReceipt:
    values = dict(payload)
    values["case_results"] = tuple(ReliabilityCaseResult(**item) for item in values["case_results"])
    return ReliabilityCampaignReceipt(**values)


def _group_payloads(closure: TraceClosureManifest, payloads: Mapping[str, Any], role: str) -> tuple[Any, ...]:
    group = next((item for item in closure.artifact_groups if item.role == role), None)
    return () if group is None else tuple(payloads[item] for item in group.artifact_hashes)


def _restore_router(closure: TraceClosureManifest, payloads: Mapping[str, Any]) -> tuple[VerifierRouter, FederationPlan, ExecutionSubjectBinding, tuple[ExecutionRecordMaterial, ...], RequirementEvidenceBundle, RequirementAdjudicationReceipt]:
    claim = _restore_claim(_group_payloads(closure, payloads, "typed_claim")[0])
    verification_plan = _restore_verification_plan(_group_payloads(closure, payloads, "verification_plan")[0])
    requirements = tuple(FederatedVerificationRequirement(**item) for item in _group_payloads(closure, payloads, "federated_requirement"))
    descriptors = tuple(VerifierDescriptor(**item) for item in _group_payloads(closure, payloads, "verifier_descriptor"))
    registry = VerifierRegistry()
    for descriptor in descriptors:
        registry.register(descriptor)
    graph_payload = _group_payloads(closure, payloads, "verifier_dependency_graph")[0]
    graph = VerifierDependencyGraph(complete=bool(graph_payload["complete"]))
    for descriptor in descriptors:
        graph.add(descriptor)
    if set(graph_payload["nodes"]) != set(graph.nodes):
        raise ValueError("genesis_trace_graph_nodes_invalid")
    edges = {tuple(item) for item in graph_payload["edges"]}
    if any(len(edge) != 2 or not set(edge) <= set(graph.nodes) for edge in edges):
        raise ValueError("genesis_trace_graph_edges_invalid")
    graph.edges = edges
    if canonical_sha256(_dependency_graph_payload(graph)) != _group_payloads(closure, payloads, "federation_plan")[0]["dependency_graph_hash"]:
        raise ValueError("genesis_trace_graph_hash_invalid")
    campaigns = tuple(_restore_campaign(item) for item in _group_payloads(closure, payloads, "reliability_campaign"))
    profiles = tuple(VerifierReliabilityProfile(**item) for item in _group_payloads(closure, payloads, "reliability_profile"))
    integrities = tuple(VerifierIntegrityReceipt(**item) for item in _group_payloads(closure, payloads, "integrity_receipt"))
    reference_descriptors = tuple(ReferenceDescriptor(**item) for item in _group_payloads(closure, payloads, "reference_descriptor"))
    reference_registry = None
    if reference_descriptors:
        reference_registry = ReferenceRegistry()
        for descriptor in reference_descriptors:
            reference_registry.register(descriptor)
    policies = tuple(ReferenceQualificationPolicy(**item) for item in _group_payloads(closure, payloads, "reference_qualification_policy"))
    qualification_receipts = tuple(ReferenceQualificationReceipt(**item) for item in _group_payloads(closure, payloads, "reference_qualification_receipt"))
    reference_bindings = tuple(QualifiedReferenceBinding(**item) for item in _group_payloads(closure, payloads, "qualified_reference_binding"))
    cfi_reports = tuple(CFIReport(**item) for item in _group_payloads(closure, payloads, "cfi_report"))
    router = VerifierRouter(
        claim=claim, verification_plan=verification_plan, requirements=requirements,
        registry=registry, dependency_graph=graph, reliability_profiles=profiles,
        campaign_receipts=campaigns, integrity_receipts=integrities,
        qualified_reference_bindings=reference_bindings, reference_registry=reference_registry,
        qualification_receipts=qualification_receipts, qualification_policies=policies,
        cfi_reports=cfi_reports,
    )
    federation_plan = _restore_federation_plan(_group_payloads(closure, payloads, "federation_plan")[0])
    subject = ExecutionSubjectBinding(**_group_payloads(closure, payloads, "execution_subject_binding")[0])
    requests = tuple(PlannedExecutionRequest(**item) for item in _group_payloads(closure, payloads, "planned_execution_request"))
    receipts = tuple(VerifierReceipt(**item) for item in _group_payloads(closure, payloads, "verifier_receipt"))
    records = tuple(VerifierExecutionRecord(**item) for item in _group_payloads(closure, payloads, "verifier_execution_record"))
    descriptors_by_hash = {item.descriptor_hash: item for item in descriptors}
    requests_by_binding = {item.selected_verifier_binding_hash: item for item in requests}
    receipts_by_hash = {item.receipt_hash: item for item in receipts}
    references_by_hash = {item.binding_hash: item for item in reference_bindings}
    materials = tuple(sorted((ExecutionRecordMaterial(
        record, receipts_by_hash[record.verifier_receipt_hash],
        requests_by_binding[record.selected_verifier_binding_hash],
        descriptors_by_hash[record.descriptor_hash],
        references_by_hash.get(record.qualified_reference_binding_hash),
    ) for record in records), key=lambda item: item.record.record_hash))
    bundle = RequirementEvidenceBundle(**_group_payloads(closure, payloads, "requirement_evidence_bundle")[0])
    adjudication = RequirementAdjudicationReceipt(**_group_payloads(closure, payloads, "requirement_adjudication_receipt")[0])
    return router, federation_plan, subject, materials, bundle, adjudication


def _restore_graph(closure: TraceClosureManifest, payloads: Mapping[str, Any]) -> ProvenanceGraph:
    graph = ProvenanceGraph()
    for artifact_hash in closure.provenance_node_artifact_hashes:
        graph.add_node(ProvenanceNode(**payloads[artifact_hash]))
    for artifact_hash in closure.provenance_edge_artifact_hashes:
        graph.add_edge(ProvenanceEdge(**payloads[artifact_hash]))
    return graph


def replay_m6_trace(store: ContentAddressedArtifactStore, trace_closure_hash: str) -> TraceReplay:
    """Replay only from a durable closure root and a fresh store instance."""
    reasons: list[str] = []
    if not store.verify(trace_closure_hash):
        return TraceReplay(False, ("closure_artifact_invalid",), trace_closure_hash)
    try:
        closure = TraceClosureManifest.from_payload(store.get(trace_closure_hash))
    except (KeyError, TypeError, ValueError):
        return TraceReplay(False, ("closure_payload_invalid",), trace_closure_hash)
    if closure.closure_hash != trace_closure_hash:
        return TraceReplay(False, ("closure_root_mismatch",), trace_closure_hash)
    payloads: dict[str, Any] = {}
    for artifact_hash in closure.referenced_artifact_hashes():
        if not store.verify(artifact_hash):
            reasons.append(f"artifact_invalid:{artifact_hash}")
            continue
        try:
            payloads[artifact_hash] = store.get(artifact_hash)
        except (OSError, ValueError):
            reasons.append(f"artifact_unreadable:{artifact_hash}")
    try:
        events = tuple(EvidenceEvent(**payloads[item]) for item in closure.ordered_ledger_event_hashes)
        seal = LedgerSeal(**payloads[closure.ledger_seal_artifact_hash])
    except (KeyError, TypeError, ValueError):
        reasons.append("ledger_transcript_unreadable")
        return TraceReplay(False, tuple(reasons), trace_closure_hash)
    reasons.extend(verify_trace_closure(
        closure, artifact_payloads=payloads, events=events, seal=seal,
        expected_closure_hash=trace_closure_hash,
    ))
    if reasons:
        return TraceReplay(False, tuple(reasons), trace_closure_hash)
    try:
        router, plan, subject, materials, bundle, adjudication = _restore_router(closure, payloads)
        _validate_input(router=router, federation_plan=plan, subject=subject,
                        records=materials, bundle=bundle, adjudication=adjudication)
        graph = _restore_graph(closure, payloads)
        if graph.verify():
            raise ValueError("genesis_trace_provenance_invalid")
    except (KeyError, TypeError, ValueError) as error:
        return TraceReplay(False, (str(error),), trace_closure_hash)
    return TraceReplay(True, (), trace_closure_hash, adjudication, graph)
