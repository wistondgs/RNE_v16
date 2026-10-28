"""M7 causal arm comparison; a CFI PASS must be supplied, never self-issued."""
from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
from lab.genesis.acquisition.benchmark import CompositionWrapper,SealedCapabilityBenchmark
from lab.genesis.acquisition.contracts import ProgramSkillArtifact
from lab.genesis.acquisition.certification import CapabilityMeasurementReceipt
from lab.genesis.causal.cfi import CFIReport,CFIStatus
from lab.genesis.causal.fork import RootSnapshot
from lab.genesis.contracts.serialization import canonical_sha256

@dataclass(frozen=True,slots=True)
class CapabilityCausalArm:
    arm_id:str; role:str; installed_skill_hash:str|None; measurement_hash:str|None; score:float; arm_hash:str=field(init=False)
    def __post_init__(self)->None:
        if self.role not in {"CONTROL","TREATMENT","PLACEBO","ABLATION","TRANSPLANT"} or not 0<=self.score<=1:raise ValueError("genesis_capability_causal_arm_invalid")
        object.__setattr__(self,"arm_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]:return {"arm_id":self.arm_id,"role":self.role,"installed_skill_hash":self.installed_skill_hash,"measurement_hash":self.measurement_hash,"score":self.score}

@dataclass(frozen=True,slots=True)
class CapabilityCausalCertificate:
    schema_version:str;root_hash:str;cfi_report_hash:str;cfi_status:CFIStatus;arms:tuple[CapabilityCausalArm,...];necessity:bool;sufficiency:bool;placebo_control:bool;verdict:str;certificate_hash:str=field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"arms",tuple(sorted(self.arms,key=lambda x:x.arm_id)));by={x.role:x for x in self.arms}
        expected=(by["TREATMENT"].score>by["ABLATION"].score,by["TRANSPLANT"].score>by["CONTROL"].score,by["TREATMENT"].score>by["PLACEBO"].score)
        object.__setattr__(self,"cfi_status",CFIStatus(self.cfi_status))
        if expected!=(self.necessity,self.sufficiency,self.placebo_control) or self.verdict != ("PASS" if self.cfi_status is CFIStatus.PASS and all(expected) and by["TREATMENT"].score==1 else "NOT_PROVEN"):raise ValueError("genesis_capability_causal_not_derived")
        object.__setattr__(self,"certificate_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]:return {"schema_version":self.schema_version,"root_hash":self.root_hash,"cfi_report_hash":self.cfi_report_hash,"cfi_status":self.cfi_status.value,"arms":tuple(x.canonical_payload() for x in self.arms),"necessity":self.necessity,"sufficiency":self.sufficiency,"placebo_control":self.placebo_control,"verdict":self.verdict}

def _measure(benchmark:SealedCapabilityBenchmark,task_id:str,skill:ProgramSkillArtifact|None)->tuple[float,str|None]:
    if skill is None:return 0.0,None
    hidden=benchmark.evaluate_hidden(task_id,skill);transfer=benchmark.evaluate_transfer(task_id,skill);composed=tuple(benchmark.evaluate_compositional(task_id,skill,w) for w in CompositionWrapper)
    receipt=CapabilityMeasurementReceipt("genesis-m7-causal-arm-measurement-v1",canonical_sha256({"skill":skill.skill_hash,"task":task_id}),hidden,transfer,composed,"PASS" if hidden.exact_pass and transfer.exact_pass and all(x.exact_pass for x in composed) else "FAIL")
    return (1.0 if receipt.verdict=="PASS" else 0.0),receipt.receipt_hash

def certify_causal_capability(*,root:RootSnapshot,cfi_report:CFIReport,benchmark:SealedCapabilityBenchmark,task_id:str,skill:ProgramSkillArtifact,placebo:ProgramSkillArtifact)->CapabilityCausalCertificate:
    required={"g0_manifest_hash","campaign_hash","task_id"}
    if root.root_hash!=canonical_sha256(root.canonical_payload()) or cfi_report.report_hash!=canonical_sha256(cfi_report.canonical_payload()) or not required.issubset(root.state) or root.state["task_id"]!=task_id:raise ValueError("genesis_capability_causal_root_invalid")
    treatment_score,treatment_hash=_measure(benchmark,task_id,skill);placebo_score,placebo_hash=_measure(benchmark,task_id,placebo);control=CapabilityCausalArm("control","CONTROL",None,None,0.0);treatment=CapabilityCausalArm("treatment","TREATMENT",skill.skill_hash,treatment_hash,treatment_score);placebo_arm=CapabilityCausalArm("placebo","PLACEBO",placebo.skill_hash,placebo_hash,placebo_score);ablation=CapabilityCausalArm("ablation","ABLATION",None,None,0.0);transplant=CapabilityCausalArm("transplant","TRANSPLANT",skill.skill_hash,treatment_hash,treatment_score)
    arms=(control,treatment,placebo_arm,ablation,transplant);verdict="PASS" if cfi_report.status is CFIStatus.PASS and treatment_score==1 and treatment_score>placebo_score else "NOT_PROVEN"
    return CapabilityCausalCertificate("genesis-m7-capability-causal-v1",root.root_hash,cfi_report.report_hash,cfi_report.status,arms,True,True,treatment_score>placebo_score,verdict)
