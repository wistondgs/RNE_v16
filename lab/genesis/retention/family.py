"""Conservative aggregate retention policy; inconclusive members are never omitted."""
from __future__ import annotations
from dataclasses import dataclass, field
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.retention.receipts import RetentionDecisionReceipt, RetentionVerdict

@dataclass(frozen=True, slots=True)
class RetentionFamilyPolicy:
    family_id:str; schema_version:str; required_capability_ids:tuple[str,...]; epsilon_family_total:float; policy_hash:str=field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"required_capability_ids",tuple(self.required_capability_ids))
        if self.epsilon_family_total<0: raise ValueError("genesis_family_epsilon_invalid")
        object.__setattr__(self,"policy_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,object]: return {"family_id":self.family_id,"schema_version":self.schema_version,"required_capability_ids":self.required_capability_ids,"epsilon_family_total":self.epsilon_family_total}

@dataclass(frozen=True, slots=True)
class RetentionFamilyDecision:
    family_id:str; policy_hash:str; verdict:RetentionVerdict; total_regression:float; member_decision_hashes:tuple[str,...]; decision_hash:str=field(init=False)
    def __post_init__(self)->None: object.__setattr__(self,"verdict",RetentionVerdict(self.verdict)); object.__setattr__(self,"member_decision_hashes",tuple(self.member_decision_hashes)); object.__setattr__(self,"decision_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,object]: return {"family_id":self.family_id,"policy_hash":self.policy_hash,"verdict":self.verdict.value,"total_regression":self.total_regression,"member_decision_hashes":self.member_decision_hashes}

class RetentionFamilyEvaluator:
    @staticmethod
    def evaluate(policy:RetentionFamilyPolicy, members:dict[str,tuple[RetentionDecisionReceipt,float]])->RetentionFamilyDecision:
        if set(members)!=set(policy.required_capability_ids): verdict=RetentionVerdict.ERROR; total=0.0
        else:
            decisions=[members[key][0] for key in policy.required_capability_ids]; total=sum(members[key][1]*members[key][0].regression_value for key in policy.required_capability_ids)
            if any(item.verdict is RetentionVerdict.ERROR for item in decisions): verdict=RetentionVerdict.ERROR
            elif any(item.verdict is RetentionVerdict.INCONCLUSIVE for item in decisions): verdict=RetentionVerdict.INCONCLUSIVE
            elif any(item.verdict is RetentionVerdict.REGRESSION for item in decisions) or total>policy.epsilon_family_total: verdict=RetentionVerdict.REGRESSION
            else: verdict=RetentionVerdict.PASS
        return RetentionFamilyDecision(policy.family_id,policy.policy_hash,verdict,total,tuple(members[key][0].decision_hash for key in sorted(members)))
