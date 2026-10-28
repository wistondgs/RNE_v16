from __future__ import annotations
from lab.genesis.retention.receipts import RetentionVerdict
from lab.genesis.retention.rule_a_star import RuleAStar
from tests.genesis._retention_helpers import build_case

def test_high_inherited_risk_emits_reverification_not_rollback(tmp_path):
    case=build_case(tmp_path,risk_target="inherited_audit",risk_score=.8)
    result=RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"])
    assert result.decision.verdict is RetentionVerdict.INCONCLUSIVE
    assert result.reverification_request and result.reverification_request.trigger_risk_score==.8
    assert not hasattr(result,"rollback")
