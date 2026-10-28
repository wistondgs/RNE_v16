from __future__ import annotations
import pytest
from lab.genesis.retention.receipts import RetentionVerdict
from lab.genesis.retention.rule_a_star import RuleAStar
from lab.genesis.security.quarantine import QuarantineState
from tests.genesis._retention_helpers import build_case

@pytest.mark.parametrize("target",["audit","baseline","verifier","metric","sampling"])
def test_poisoned_critical_surfaces_are_inconclusive_even_when_numeric_result_varies(tmp_path,target):
    false_regression=build_case(tmp_path/(target+"-low"),.90,.72,risk_target=target,risk_score=.8)
    false_retention=build_case(tmp_path/(target+"-high"),.90,.89,risk_target=target,risk_score=.8)
    for case in (false_regression,false_retention):
        result=RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"])
        assert result.decision.verdict is RetentionVerdict.INCONCLUSIVE and result.reverification_request

def test_quarantine_and_risk_are_separate_gates(tmp_path):
    quarantined=build_case(tmp_path/"quarantine",risk_target="audit",risk_score=.1,quarantine_target="audit",quarantine_state=QuarantineState.QUARANTINED)
    rehabilitated_high=build_case(tmp_path/"rehab",risk_target="audit",risk_score=.8,quarantine_target="audit",quarantine_state=QuarantineState.REHABILITATED)
    for case in (quarantined,rehabilitated_high): assert RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"]).decision.verdict is RetentionVerdict.INCONCLUSIVE
