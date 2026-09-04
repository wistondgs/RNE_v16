"""Exact post-promotion M7 capability measurements (not causal attribution)."""
from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
from lab.genesis.acquisition.benchmark import CompositionWrapper,SealedCapabilityBenchmark,SplitEvaluation
from lab.genesis.acquisition.campaign import AcquisitionResult
from lab.genesis.contracts.serialization import canonical_sha256

@dataclass(frozen=True,slots=True)
class CapabilityMeasurementReceipt:
    schema_version:str;promotion_hash:str;hidden:SplitEvaluation;ood_transfer:SplitEvaluation;compositional:tuple[SplitEvaluation,...];verdict:str;receipt_hash:str=field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"compositional",tuple(self.compositional));expected="PASS" if self.hidden.exact_pass and self.ood_transfer.exact_pass and all(x.exact_pass for x in self.compositional) else "FAIL"
        if self.verdict!=expected:raise ValueError("genesis_capability_measurement_not_derived")
        object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]:return {"schema_version":self.schema_version,"promotion_hash":self.promotion_hash,"hidden":self.hidden.canonical_payload(),"ood_transfer":self.ood_transfer.canonical_payload(),"compositional":tuple(x.canonical_payload() for x in self.compositional),"verdict":self.verdict}
    def validate(self)->bool:return self.receipt_hash==canonical_sha256(self.canonical_payload())

def measure_promoted_capability(*,result:AcquisitionResult,benchmark:SealedCapabilityBenchmark,task_id:str)->CapabilityMeasurementReceipt:
    if result.g1_manifest is None or result.synthesis.selected_skill is None or result.promotion.status.value!="PROMOTED":raise ValueError("genesis_capability_not_promoted")
    skill=result.synthesis.selected_skill;hidden=benchmark.evaluate_hidden(task_id,skill);transfer=benchmark.evaluate_transfer(task_id,skill);composed=tuple(benchmark.evaluate_compositional(task_id,skill,wrapper) for wrapper in CompositionWrapper)
    verdict="PASS" if hidden.exact_pass and transfer.exact_pass and all(x.exact_pass for x in composed) else "FAIL"
    return CapabilityMeasurementReceipt("genesis-m7-capability-measurement-v1",result.promotion.promotion_hash,hidden,transfer,composed,verdict)
