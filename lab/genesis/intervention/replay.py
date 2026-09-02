from __future__ import annotations
from dataclasses import dataclass
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.events import EvidenceEvent
from lab.genesis.evidence.ledger import EvidenceLedger
from lab.genesis.evidence.seals import LedgerSeal
from lab.genesis.provenance.graph import ProvenanceGraph
from lab.genesis.provenance.nodes import NodeType, ProvenanceNode
from lab.genesis.provenance.edges import EdgeClass, EdgeType, ProvenanceEdge
from lab.genesis.intervention.kernel import KernelResult
@dataclass(frozen=True,slots=True)
class CausalExperimentReplay:
 status:str;reasons:tuple[str,...]
 @classmethod
 def verify(cls,result:KernelResult):
  reasons=[]
  for item,attr in ((result.manifest,"manifest_hash"),(result.root,"root_hash"),(result.cfi,"report_hash"),(result.summary,"summary_hash"),(result.trace,"trace_hash")):
   if getattr(item,attr)!=canonical_sha256(item.canonical_payload()):reasons.append(attr+"_invalid")
  for group,attr in ((result.receipts,"receipt_hash"),(result.delta_receipts,"receipt_hash"),(result.isolation_receipts,"receipt_hash"),(result.seals,"seal_hash"),(result.oracles,"receipt_hash"),(result.budgets,"receipt_hash")):
   for item in group:
    if getattr(item,attr)!=canonical_sha256(item.canonical_payload()):reasons.append(attr+"_invalid")
  if result.summary.attribution_eligible != (result.cfi.status.value=="PASS"):reasons.append("eligibility_invalid")
  return cls("FAIL" if reasons else "PASS",tuple(reasons))
@dataclass(frozen=True,slots=True)
class CausalEvidenceBundle:
 artifact_hashes:tuple[str,...];ledger_seal:LedgerSeal;graph:ProvenanceGraph;events:tuple[EvidenceEvent,...]
def evidence_bundle(store:ContentAddressedArtifactStore,result:KernelResult)->CausalEvidenceBundle:
 objects=(result.manifest.canonical_payload(),result.root.canonical_payload(),result.cfi.canonical_payload(),result.summary.canonical_payload(),result.trace.canonical_payload())+tuple(x.canonical_payload() for x in result.receipts)
 hashes=tuple(store.put(item) for item in objects);ledger=EvidenceLedger("m5-"+result.manifest.experiment_id,result.manifest.experiment_id);parent=None
 for index,digest in enumerate(hashes):
  event=EvidenceEvent("m5-event-"+str(index),"genesis.m5",result.manifest.experiment_id,"causal_experiment",digest,"0"*64,parent,index,"genesis.m5");ledger.append(event);parent=event.event_hash
 graph=ProvenanceGraph(); nodes=[]
 for index,digest in enumerate(hashes):
  node=ProvenanceNode("m5-node-"+str(index),"genesis.m5",NodeType.EVIDENCE,digest,"genesis.m5",store.put({"m5_metadata":index}));graph.add_node(node);nodes.append(node)
 for index in range(1,len(nodes)):graph.add_edge(ProvenanceEdge("m5-edge-"+str(index),"genesis.m5",nodes[index-1].node_id,nodes[index].node_id,EdgeType.DERIVED_FROM,EdgeClass.LINEAGE,1.0))
 return CausalEvidenceBundle(hashes,LedgerSeal.seal(ledger),graph,ledger.events)
