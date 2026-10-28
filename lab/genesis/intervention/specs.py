from __future__ import annotations
from dataclasses import dataclass,field
from enum import Enum
from typing import Mapping,Any
from lab.genesis.contracts.serialization import canonical_sha256,freeze
from lab.genesis.evidence.artifacts import is_artifact_hash
class ArmRole(str,Enum): CONTROL="CONTROL";TREATMENT="TREATMENT";PLACEBO="PLACEBO";ABLATION="ABLATION";CUSTOM="CUSTOM"
class RNGPolicy(str,Enum): COMMON_RANDOM_NUMBERS="COMMON_RANDOM_NUMBERS";ARM_DERIVED="ARM_DERIVED"
@dataclass(frozen=True,slots=True)
class ComputeBudgetSpec:
 logical_steps:int;max_candidate_calls:int;max_oracle_calls:int;max_tool_calls:int;max_tokens:int|None=None;memory_limit_bytes:int|None=None;matched_compute:bool=True;budget_hash:str=field(init=False)
 def __post_init__(self):
  if min(self.logical_steps,self.max_candidate_calls,self.max_oracle_calls,self.max_tool_calls)<0:raise ValueError("genesis_budget_negative")
  object.__setattr__(self,"budget_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"logical_steps":self.logical_steps,"max_candidate_calls":self.max_candidate_calls,"max_oracle_calls":self.max_oracle_calls,"max_tool_calls":self.max_tool_calls,"max_tokens":self.max_tokens,"memory_limit_bytes":self.memory_limit_bytes,"matched_compute":self.matched_compute}
@dataclass(frozen=True,slots=True)
class InterventionSpec:
 intervention_id:str;schema_version:str;intervention_type:str;target_paths:tuple[str,...];parameters_hash:str;expected_effect_class:str;spec_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"target_paths",tuple(self.target_paths));
 def __post_init__(self):
  object.__setattr__(self,"target_paths",tuple(self.target_paths))
  if not is_artifact_hash(self.parameters_hash):raise ValueError("genesis_intervention_parameters_invalid")
  object.__setattr__(self,"spec_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"intervention_id":self.intervention_id,"schema_version":self.schema_version,"intervention_type":self.intervention_type,"target_paths":self.target_paths,"parameters_hash":self.parameters_hash,"expected_effect_class":self.expected_effect_class}
@dataclass(frozen=True,slots=True)
class ArmSpec:
 arm_id:str;role:ArmRole;intervention_spec_hash:str;allowed_delta_paths:tuple[str,...];required_surfaces:tuple[str,...];budget_spec_hash:str;rng_mode:RNGPolicy;metadata_hash:str;arm_spec_hash:str=field(init=False)
 def __post_init__(self):
  object.__setattr__(self,"role",ArmRole(self.role));object.__setattr__(self,"rng_mode",RNGPolicy(self.rng_mode));object.__setattr__(self,"allowed_delta_paths",tuple(self.allowed_delta_paths));object.__setattr__(self,"required_surfaces",tuple(self.required_surfaces))
  if any(not is_artifact_hash(x) for x in (self.intervention_spec_hash,self.budget_spec_hash,self.metadata_hash)):raise ValueError("genesis_arm_hash_invalid")
  object.__setattr__(self,"arm_spec_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"arm_id":self.arm_id,"role":self.role.value,"intervention_spec_hash":self.intervention_spec_hash,"allowed_delta_paths":self.allowed_delta_paths,"required_surfaces":self.required_surfaces,"budget_spec_hash":self.budget_spec_hash,"rng_mode":self.rng_mode.value,"metadata_hash":self.metadata_hash}
@dataclass(frozen=True,slots=True)
class CausalExperimentManifest:
 experiment_id:str;schema_version:str;claim_hash:str;root_snapshot_hash:str;cfi_policy_hash:str;arm_specs:tuple[ArmSpec,...];budget_spec_hash:str;rng_policy:RNGPolicy;master_seed:int;oracle_spec_hash:str;evaluator_version:str;required_surfaces:tuple[str,...];manifest_hash:str=field(init=False)
 def __post_init__(self):
  object.__setattr__(self,"arm_specs",tuple(self.arm_specs));object.__setattr__(self,"rng_policy",RNGPolicy(self.rng_policy));object.__setattr__(self,"required_surfaces",tuple(self.required_surfaces))
  if any(not is_artifact_hash(x) for x in (self.claim_hash,self.root_snapshot_hash,self.cfi_policy_hash,self.budget_spec_hash,self.oracle_spec_hash)):raise ValueError("genesis_manifest_hash_invalid")
  object.__setattr__(self,"manifest_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {"experiment_id":self.experiment_id,"schema_version":self.schema_version,"claim_hash":self.claim_hash,"root_snapshot_hash":self.root_snapshot_hash,"cfi_policy_hash":self.cfi_policy_hash,"arm_specs":tuple(x.canonical_payload() for x in self.arm_specs),"budget_spec_hash":self.budget_spec_hash,"rng_policy":self.rng_policy.value,"master_seed":self.master_seed,"oracle_spec_hash":self.oracle_spec_hash,"evaluator_version":self.evaluator_version,"required_surfaces":self.required_surfaces}
