from __future__ import annotations
import pytest
from lab.genesis.retention.epistemic import EpistemicStateRef, RetentionEpistemicView
from lab.genesis.retention.replay import RetentionReplay
from lab.genesis.retention.rule_a_star import RuleAStar
from lab.genesis.retention.receipts import RetentionVerdict
from lab.genesis.provenance.risk import RiskAssessment
from tests.genesis._retention_helpers import build_case

def test_historical_decision_replays_at_t0_and_new_state_changes_new_decision(tmp_path):
    old=build_case(tmp_path/"old")
    old_result=RuleAStar.evaluate(old["package"],old["baseline"],old["observation"],old["state"],old["view"])
    replay=RetentionReplay.verify(old["store"],old["graph"],old["package"],old["baseline"],old["observation"],old["state"],old["view"],old_result.decision)
    assert replay.verdict is RetentionVerdict.PASS
    evidence=old["store"].put({"late":"risk"}); late=RiskAssessment("late","n-source","m4",.8,("late",),(evidence,),"test")
    state1=EpistemicStateRef.from_records(old["graph"],(late,),())
    view1=RetentionEpistemicView.materialize(old["package"],state1,old["store"],old["graph"],(late,),())
    assert RuleAStar.evaluate(old["package"],old["baseline"],old["observation"],state1,view1).decision.verdict is RetentionVerdict.INCONCLUSIVE

@pytest.mark.parametrize("field,value",[("epsilon_i",.9),("weight_i",.9),("sigma_max",.1),("cert_dataset_hash","0"*64),("audit_dataset_hash","0"*64),("baseline_receipt_hash","0"*64),("verifier_spec_hash","0"*64),("metric_spec_hash","0"*64),("sampling_policy_hash","0"*64),("capability_artifact_hash","0"*64),("provenance_node_ids",{})])
def test_package_and_decision_tampering_fail_replay(tmp_path,field,value):
    case=build_case(tmp_path); result=RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"])
    object.__setattr__(case["package"],field,value)
    replay=RetentionReplay.verify(case["store"],case["graph"],case["package"],case["baseline"],case["observation"],case["state"],case["view"],result.decision)
    assert replay.verdict is RetentionVerdict.ERROR

@pytest.mark.parametrize("object_name,field,value",[("baseline","score",.1),("observation","observed_score",.1),("state","schema_version","tampered"),("risk","producer","tampered"),("decision","verdict",RetentionVerdict.REGRESSION),("request","reason_codes",("tampered",))])
def test_receipt_tampering_is_detected(tmp_path,object_name,field,value):
    case=build_case(tmp_path,risk_target="audit",risk_score=.8)
    result=RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"])
    target={"baseline":case["baseline"],"observation":case["observation"],"state":case["state"],"risk":case["assessments"][0],"decision":result.decision,"request":result.reverification_request}[object_name]
    object.__setattr__(target,field,value)
    replay=RetentionReplay.verify(case["store"],case["graph"],case["package"],case["baseline"],case["observation"],case["state"],case["view"],result.decision,result.reverification_request,case["assessments"],case["quarantines"])
    assert replay.verdict is RetentionVerdict.ERROR

def test_audit_payload_never_appears_in_retention_receipts(tmp_path):
    case=build_case(tmp_path); result=RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"])
    secret="sensitive audit examples"; assert secret not in str(case["package"].canonical_payload()); assert secret not in str(result.decision.canonical_payload())
