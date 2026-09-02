"""CFI receipts for allowed deltas and post-arm isolation."""
from __future__ import annotations
from dataclasses import dataclass, field
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.causal.fork import RootSnapshot

@dataclass(frozen=True,slots=True)
class AllowedDeltaReceipt:
 arm_id:str; root_hash:str; arm_preexecution_hash:str; allowed_paths:tuple[str,...]; observed_paths:tuple[str,...]; undeclared_paths:tuple[str,...]; status:str; receipt_hash:str=field(init=False)
 def __post_init__(self): object.__setattr__(self,"allowed_paths",tuple(self.allowed_paths));object.__setattr__(self,"observed_paths",tuple(self.observed_paths));object.__setattr__(self,"undeclared_paths",tuple(self.undeclared_paths));object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self): return {"arm_id":self.arm_id,"root_hash":self.root_hash,"arm_preexecution_hash":self.arm_preexecution_hash,"allowed_paths":self.allowed_paths,"observed_paths":self.observed_paths,"undeclared_paths":self.undeclared_paths,"status":self.status}

@dataclass(frozen=True,slots=True)
class ArmIsolationReceipt:
 arm_id:str; root_hash_before:str; root_hash_after:str; arm_hash_before:str; arm_hash_after:str; forbidden_shared_writes:tuple[str,...]; mutable_alias_status:str; namespace_hash:str; status:str; receipt_hash:str=field(init=False)
 def __post_init__(self): object.__setattr__(self,"forbidden_shared_writes",tuple(self.forbidden_shared_writes));object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self): return {"arm_id":self.arm_id,"root_hash_before":self.root_hash_before,"root_hash_after":self.root_hash_after,"arm_hash_before":self.arm_hash_before,"arm_hash_after":self.arm_hash_after,"forbidden_shared_writes":self.forbidden_shared_writes,"mutable_alias_status":self.mutable_alias_status,"namespace_hash":self.namespace_hash,"status":self.status}
