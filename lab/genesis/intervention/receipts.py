from __future__ import annotations
from dataclasses import dataclass,field
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.causal.cfi import CFIStatus
@dataclass(frozen=True,slots=True)
class DecisionSeal:
 seal_id:str;schema_version:str;experiment_id:str;arm_id:str;candidate_output_hash:str;arm_preoracle_state_hash:str;oracle_unopened:bool;decision_payload_hash:str;seal_hash:str=field(init=False)
 def __post_init__(self):
  if not self.oracle_unopened:raise ValueError("genesis_oracle_already_open")
  object.__setattr__(self,"seal_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"seal_id":self.seal_id,"schema_version":self.schema_version,"experiment_id":self.experiment_id,"arm_id":self.arm_id,"candidate_output_hash":self.candidate_output_hash,"arm_preoracle_state_hash":self.arm_preoracle_state_hash,"oracle_unopened":self.oracle_unopened,"decision_payload_hash":self.decision_payload_hash}
@dataclass(frozen=True,slots=True)
class OracleReceipt:
 receipt_id:str;schema_version:str;experiment_id:str;arm_id:str;decision_seal_hash:str;oracle_spec_hash:str;evaluator_version:str;outcome_hash:str;score:float;opened_after_seal:bool;receipt_hash:str=field(init=False)
 def __post_init__(self):
  if not self.opened_after_seal:raise ValueError("genesis_oracle_before_seal")
  object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"receipt_id":self.receipt_id,"schema_version":self.schema_version,"experiment_id":self.experiment_id,"arm_id":self.arm_id,"decision_seal_hash":self.decision_seal_hash,"oracle_spec_hash":self.oracle_spec_hash,"evaluator_version":self.evaluator_version,"outcome_hash":self.outcome_hash,"score":self.score,"opened_after_seal":self.opened_after_seal}
@dataclass(frozen=True,slots=True)
class BudgetReceipt:
 arm_id:str;budget_hash:str;logical_steps:int;candidate_calls:int;oracle_calls:int;tool_calls:int;status:str;receipt_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"arm_id":self.arm_id,"budget_hash":self.budget_hash,"logical_steps":self.logical_steps,"candidate_calls":self.candidate_calls,"oracle_calls":self.oracle_calls,"tool_calls":self.tool_calls,"status":self.status}
@dataclass(frozen=True,slots=True)
class ArmExecutionReceipt:
 experiment_id:str;arm_id:str;arm_spec_hash:str;root_snapshot_hash:str;allowed_delta_receipt_hash:str;isolation_receipt_hash:str;decision_seal_hash:str;oracle_receipt_hash:str;budget_receipt_hash:str;pre_state_hash:str;post_state_hash:str;cfi_status:CFIStatus;score:float;receipt_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"cfi_status",CFIStatus(self.cfi_status));object.__setattr__(self,"receipt_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"experiment_id":self.experiment_id,"arm_id":self.arm_id,"arm_spec_hash":self.arm_spec_hash,"root_snapshot_hash":self.root_snapshot_hash,"allowed_delta_receipt_hash":self.allowed_delta_receipt_hash,"isolation_receipt_hash":self.isolation_receipt_hash,"decision_seal_hash":self.decision_seal_hash,"oracle_receipt_hash":self.oracle_receipt_hash,"budget_receipt_hash":self.budget_receipt_hash,"pre_state_hash":self.pre_state_hash,"post_state_hash":self.post_state_hash,"cfi_status":self.cfi_status.value,"score":self.score}
@dataclass(frozen=True,slots=True)
class ExecutionTrace:
 experiment_id:str;executed_arm_order:tuple[str,...];trace_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"executed_arm_order",tuple(self.executed_arm_order));object.__setattr__(self,"trace_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"experiment_id":self.experiment_id,"executed_arm_order":self.executed_arm_order}
