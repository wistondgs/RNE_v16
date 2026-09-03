from __future__ import annotations
from dataclasses import dataclass,field
from itertools import combinations
from enum import Enum
from lab.genesis.contracts.serialization import canonical_sha256
from .descriptor import *
class IntegrityStatus(str,Enum):PASS="PASS";FAIL="FAIL";INCOMPLETE="INCOMPLETE"
class IndependenceStatus(str,Enum):VERIFIED_INDEPENDENT="VERIFIED_INDEPENDENT";DEPENDENT="DEPENDENT";UNKNOWN="UNKNOWN"
class FederationVerdict(str,Enum):PASS="PASS";FAIL="FAIL";INCONCLUSIVE="INCONCLUSIVE";CONFLICT="CONFLICT";ERROR="ERROR"
@dataclass(frozen=True,slots=True)
class VerifierIntegrityReceipt:
 receipt_id:str;verifier_descriptor_hash:str;expected_implementation_hash:str;observed_implementation_hash:str;dependency_manifest_hash:str;reliability_profile_hash:str;status:IntegrityStatus;reason_codes:tuple[str,...];receipt_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"status",IntegrityStatus(self.status));object.__setattr__(self,"reason_codes",tuple(self.reason_codes));object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"receipt_id":self.receipt_id,"verifier_descriptor_hash":self.verifier_descriptor_hash,"expected_implementation_hash":self.expected_implementation_hash,"observed_implementation_hash":self.observed_implementation_hash,"dependency_manifest_hash":self.dependency_manifest_hash,"reliability_profile_hash":self.reliability_profile_hash,"status":self.status.value,"reason_codes":self.reason_codes}
@dataclass(frozen=True,slots=True)
class FederatedVerificationRequirement:
 requirement_id:str;obligation_id:str;accepted_authorities:tuple[AuthorityClass,...];accepted_verifier_kinds:tuple[VerifierKind,...];min_qualifying_passes:int;min_independent_passes:int;sovereign_required:bool;requires_cfi_pass:bool=False;requirement_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"accepted_authorities",tuple(AuthorityClass(x) for x in self.accepted_authorities));object.__setattr__(self,"accepted_verifier_kinds",tuple(VerifierKind(x) for x in self.accepted_verifier_kinds));object.__setattr__(self,"requirement_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"requirement_id":self.requirement_id,"obligation_id":self.obligation_id,"accepted_authorities":tuple(x.value for x in self.accepted_authorities),"accepted_verifier_kinds":tuple(x.value for x in self.accepted_verifier_kinds),"min_qualifying_passes":self.min_qualifying_passes,"min_independent_passes":self.min_independent_passes,"sovereign_required":self.sovereign_required,"requires_cfi_pass":self.requires_cfi_pass}
class VerifierRegistry:
 def __init__(self):self.items={}
 def register(self,d):
  k=(d.verifier_id,d.verifier_version);old=self.items.get(k)
  if old and old.descriptor_hash!=d.descriptor_hash:raise ValueError("genesis_verifier_duplicate_conflict")
  self.items[k]=d
 def compatible(self,req):return tuple(sorted((d for d in self.items.values() if d.authority_class in req.accepted_authorities and d.verifier_kind in req.accepted_verifier_kinds),key=lambda x:x.descriptor_hash))
class VerifierDependencyGraph:
 def __init__(self,complete=True):self.complete=complete;self.nodes={};self.edges=set()
 def add(self,d):
  for other in self.nodes.values():
   if other.implementation_identity_hash==d.implementation_identity_hash:self.edges.add(tuple(sorted((other.descriptor_hash,d.descriptor_hash))))
  self.nodes[d.descriptor_hash]=d
 @property
 def graph_hash(self):return canonical_sha256({"nodes":sorted(self.nodes),"edges":sorted(self.edges),"complete":self.complete})
 def independence(self,a,b):return IndependenceStatus.DEPENDENT if tuple(sorted((a.descriptor_hash,b.descriptor_hash))) in self.edges else (IndependenceStatus.VERIFIED_INDEPENDENT if self.complete else IndependenceStatus.UNKNOWN)
def independent_pass_basis(evidence,graph,k):
 """Canonical non-greedy basis shared by federation adjudication callers."""
 passes=tuple(sorted((x for x in evidence if x[2]=="PASS"),key=lambda x:x[0].descriptor_hash))
 if k==0:return ()
 for group in combinations(passes,k):
  if all(graph.independence(a[0],b[0]) is IndependenceStatus.VERIFIED_INDEPENDENT for a,b in combinations(group,2)):return group
 return ()
def independent_conflict_basis(evidence,graph):
 valid=[x for x in evidence if x[1].status is IntegrityStatus.PASS]
 for a,b in combinations(sorted(valid,key=lambda x:x[0].descriptor_hash),2):
  if {a[2],b[2]}=={"PASS","FAIL"} and graph.independence(a[0],b[0]) is IndependenceStatus.VERIFIED_INDEPENDENT:return (a,b)
 return ()
def adjudicate(req,evidence,graph,cfi_pass=True):
 """Evidence=(descriptor, integrity, status). No counting rule or majority exists."""
 if req.requires_cfi_pass and not cfi_pass:return FederationVerdict.INCONCLUSIVE
 valid=[x for x in evidence if x[1].status is IntegrityStatus.PASS and x[0].authority_class in req.accepted_authorities and x[0].verifier_kind in req.accepted_verifier_kinds]
 sovereign=[x for x in valid if x[0].sovereignty is VerifierSovereignty.SOVEREIGN]
 pool=sovereign if req.sovereign_required else valid
 if not pool:return FederationVerdict.INCONCLUSIVE
 outcomes={x[2] for x in pool}
 if "FAIL" in outcomes and "PASS" in outcomes:
  return FederationVerdict.CONFLICT if independent_conflict_basis(pool,graph) else FederationVerdict.INCONCLUSIVE
 if "FAIL" in outcomes:return FederationVerdict.FAIL
 if "UNKNOWN" in outcomes:return FederationVerdict.INCONCLUSIVE
 passes=[x for x in pool if x[2]=="PASS"]
 if len(passes)<req.min_qualifying_passes:return FederationVerdict.INCONCLUSIVE
 return FederationVerdict.PASS if len(independent_pass_basis(passes,graph,req.min_independent_passes))>=req.min_independent_passes else FederationVerdict.INCONCLUSIVE
