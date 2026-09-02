from __future__ import annotations
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode
from lab.genesis.provenance.risk import RiskAssessment
from lab.genesis.retention.epistemic import EpistemicStateRef, RetentionEpistemicView
from lab.genesis.retention.observation import RetentionObservationReceipt
from lab.genesis.retention.package import RetentionAuditPackage, RetentionSurface
from lab.genesis.retention.receipts import BaselineMeasurementReceipt
from lab.genesis.security.quarantine import QuarantineReceipt, QuarantineState

def build_case(tmp_path, baseline_score=0.90, observed_score=0.88, *, risk_target=None, risk_score=0.0, quarantine_target=None, quarantine_state=None):
    store=ContentAddressedArtifactStore(tmp_path); graph=ProvenanceGraph(); hashes={key:store.put({"surface":key}) for key in ("capability","cert","audit","verifier","metric","sampling")}
    baseline=BaselineMeasurementReceipt("baseline","m4","cap-1",hashes["audit"],hashes["verifier"],hashes["metric"],hashes["sampling"],baseline_score,10,(hashes["audit"],)); store.put(baseline.canonical_payload())
    hashes["baseline"]=baseline.receipt_hash
    kinds={"capability":NodeType.CAPABILITY,"cert":NodeType.DATASET,"audit":NodeType.AUDIT_DATASET,"baseline":NodeType.VERIFIER_RECEIPT,"verifier":NodeType.REPRESENTATION,"metric":NodeType.REPRESENTATION,"sampling":NodeType.REPRESENTATION}
    node_ids={}
    for key in hashes:
        node_id="n-"+key; node_ids[key]=node_id; graph.add_node(ProvenanceNode(node_id,"m4",kinds[key],hashes[key],"test",store.put({"metadata":key})))
    # An external evidence source makes inherited audit risk observable through M3.
    source_hash=store.put({"surface":"source-evidence"}); graph.add_node(ProvenanceNode("n-source","m4",NodeType.EVIDENCE,source_hash,"test",store.put({"metadata":"source"})))
    graph.add_edge(ProvenanceEdge("source-audit","m4","n-source","n-audit",EdgeType.GENERATED_FROM,EdgeClass.LINEAGE,1.0))
    mapping={RetentionSurface.CAPABILITY.value:node_ids["capability"],RetentionSurface.CERT_DATASET.value:node_ids["cert"],RetentionSurface.AUDIT_DATASET.value:node_ids["audit"],RetentionSurface.BASELINE.value:node_ids["baseline"],RetentionSurface.VERIFIER.value:node_ids["verifier"],RetentionSurface.METRIC.value:node_ids["metric"],RetentionSurface.SAMPLING.value:node_ids["sampling"]}
    package=RetentionAuditPackage("package","m4","cap-1",hashes["capability"],hashes["cert"],hashes["audit"],baseline.receipt_hash,hashes["verifier"],hashes["metric"],hashes["sampling"],None,0.05,0.5,0.5,mapping)
    observation=RetentionObservationReceipt("observation","m4",package.package_hash,"cap-1",hashes["audit"],hashes["verifier"],hashes["metric"],hashes["sampling"],observed_score,10,None,(store.put({"observation":"evidence"}),),{"future_metric_shape":{"tail":None}})
    assessments=()
    if risk_target:
        target="n-source" if risk_target=="inherited_audit" else node_ids[risk_target]
        evidence=store.put({"risk":risk_target}); assessments=(RiskAssessment("risk",target,"m4",risk_score,("poisoning",),(evidence,),"test"),)
    quarantines=()
    if quarantine_target:
        target_hash=hashes[quarantine_target]; evidence=store.put({"quarantine":quarantine_target})
        suspect=QuarantineReceipt.transition(receipt_id="q-suspect",schema_version="m4",target_hash=target_hash,previous_state=QuarantineState.NORMAL,new_state=QuarantineState.SUSPECT,reason_codes=("review",),evidence_hashes=(evidence,),producer="test")
        if quarantine_state is QuarantineState.SUSPECT:
            quarantines=(suspect,)
        elif quarantine_state is QuarantineState.QUARANTINED:
            quarantines=(suspect,QuarantineReceipt.transition(receipt_id="q",schema_version="m4",target_hash=target_hash,previous_state=QuarantineState.SUSPECT,new_state=quarantine_state,reason_codes=("review",),evidence_hashes=(evidence,),producer="test",previous_receipt_hash=suspect.receipt_hash))
        else:
            corroborated=QuarantineReceipt.transition(receipt_id="q-corroborated",schema_version="m4",target_hash=target_hash,previous_state=QuarantineState.SUSPECT,new_state=QuarantineState.CORROBORATED,reason_codes=("review",),evidence_hashes=(evidence,),producer="test",previous_receipt_hash=suspect.receipt_hash)
            quarantines=(suspect,corroborated,QuarantineReceipt.transition(receipt_id="q",schema_version="m4",target_hash=target_hash,previous_state=QuarantineState.CORROBORATED,new_state=quarantine_state,reason_codes=("review",),evidence_hashes=(evidence,),producer="test",previous_receipt_hash=corroborated.receipt_hash))
    state=EpistemicStateRef.from_records(graph,assessments,quarantines)
    view=RetentionEpistemicView.materialize(package,state,store,graph,assessments,quarantines)
    return locals()
