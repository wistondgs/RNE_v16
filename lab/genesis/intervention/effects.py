from __future__ import annotations
from dataclasses import dataclass,field
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.causal.cfi import CFIStatus
from lab.genesis.intervention.receipts import ArmExecutionReceipt
@dataclass(frozen=True,slots=True)
class CausalEffectSummary:
 experiment_id:str;arm_receipt_hashes:tuple[str,...];effects:tuple[tuple[str,float],...];cfi_report_hash:str;attribution_eligible:bool;summary_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"arm_receipt_hashes",tuple(self.arm_receipt_hashes));object.__setattr__(self,"effects",tuple(sorted(self.effects)));object.__setattr__(self,"summary_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"experiment_id":self.experiment_id,"arm_receipt_hashes":self.arm_receipt_hashes,"effects":self.effects,"cfi_report_hash":self.cfi_report_hash,"attribution_eligible":self.attribution_eligible}
def summarize(experiment_id,receipts,cfi):
 by={x.arm_id:x for x in receipts};control=by.get("control"); effects=[]
 if control:
  for name in ("treatment","placebo","ablation"):
   if name in by:effects.append((name+"_effect",by[name].score-control.score))
 return CausalEffectSummary(experiment_id,tuple(x.receipt_hash for x in sorted(receipts,key=lambda x:x.arm_id)),tuple(effects),cfi.report_hash,cfi.status is CFIStatus.PASS)
