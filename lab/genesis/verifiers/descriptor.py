from __future__ import annotations
import hashlib
from dataclasses import dataclass,field
from enum import Enum
from pathlib import Path
from lab.genesis.contracts.serialization import canonical_sha256
class VerifierKind(str,Enum): FORMAL_KERNEL="FORMAL_KERNEL";EXACT_EXECUTABLE="EXACT_EXECUTABLE";PROPERTY="PROPERTY";DIFFERENTIAL="DIFFERENTIAL";STATISTICAL="STATISTICAL";HEURISTIC="HEURISTIC";LEARNED="LEARNED"
class VerifierSovereignty(str,Enum): SOVEREIGN="SOVEREIGN";SUPPORTING="SUPPORTING";NON_SOVEREIGN="NON_SOVEREIGN"
class AuthorityClass(str,Enum): KERNEL="KERNEL";EXACT="EXACT";PROPERTY="PROPERTY";DIFFERENTIAL="DIFFERENTIAL";STATISTICAL="STATISTICAL";HEURISTIC="HEURISTIC"
@dataclass(frozen=True,slots=True)
class VerifierImplementationIdentity:
 module_relative_path:str;symbol_name:str;module_content_hash:str;declared_version:str;identity_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"identity_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"module_relative_path":self.module_relative_path,"symbol_name":self.symbol_name,"module_content_hash":self.module_content_hash,"declared_version":self.declared_version}
 @classmethod
 def capture(cls,path,symbol,version):
  p=Path(path);return cls(p.as_posix(),symbol,hashlib.sha256(p.read_bytes()).hexdigest(),version)
@dataclass(frozen=True,slots=True)
class VerifierDescriptor:
 verifier_id:str;schema_version:str;verifier_version:str;verifier_kind:VerifierKind;authority_class:AuthorityClass;sovereignty:VerifierSovereignty;supported_claim_types:tuple[str,...];supported_obligation_kinds:tuple[str,...];implementation_identity_hash:str;dependency_manifest_hash:str;cost_class:str;deterministic:bool;descriptor_hash:str=field(init=False)
 def __post_init__(self):
  object.__setattr__(self,"verifier_kind",VerifierKind(self.verifier_kind));object.__setattr__(self,"authority_class",AuthorityClass(self.authority_class));object.__setattr__(self,"sovereignty",VerifierSovereignty(self.sovereignty));object.__setattr__(self,"supported_claim_types",tuple(self.supported_claim_types));object.__setattr__(self,"supported_obligation_kinds",tuple(self.supported_obligation_kinds))
  if self.verifier_kind in {VerifierKind.HEURISTIC,VerifierKind.LEARNED} and self.sovereignty is not VerifierSovereignty.NON_SOVEREIGN:raise ValueError("genesis_learned_not_sovereign")
  object.__setattr__(self,"descriptor_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {k:getattr(self,k).value if hasattr(getattr(self,k),'value') else getattr(self,k) for k in ("verifier_id","schema_version","verifier_version","verifier_kind","authority_class","sovereignty","supported_claim_types","supported_obligation_kinds","implementation_identity_hash","dependency_manifest_hash","cost_class","deterministic")}
