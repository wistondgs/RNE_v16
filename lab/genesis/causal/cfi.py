from __future__ import annotations
from dataclasses import dataclass,field
from enum import Enum
from lab.genesis.contracts.serialization import canonical_sha256
class CFIStatus(str,Enum): PASS="PASS";FAIL="FAIL";INCOMPLETE="INCOMPLETE"
@dataclass(frozen=True,slots=True)
class CFIReport:
 experiment_id:str; required_surfaces:tuple[str,...]; unknown_surfaces:tuple[str,...]; violations:tuple[str,...]; rng_policy:str; arm_receipt_hashes:tuple[str,...]; status:CFIStatus; report_hash:str=field(init=False)
 def __post_init__(self): object.__setattr__(self,"required_surfaces",tuple(self.required_surfaces));object.__setattr__(self,"unknown_surfaces",tuple(self.unknown_surfaces));object.__setattr__(self,"violations",tuple(self.violations));object.__setattr__(self,"arm_receipt_hashes",tuple(self.arm_receipt_hashes));object.__setattr__(self,"status",CFIStatus(self.status));object.__setattr__(self,"report_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self): return {"experiment_id":self.experiment_id,"required_surfaces":self.required_surfaces,"unknown_surfaces":self.unknown_surfaces,"violations":self.violations,"rng_policy":self.rng_policy,"arm_receipt_hashes":self.arm_receipt_hashes,"status":self.status.value}
