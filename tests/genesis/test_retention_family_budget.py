from __future__ import annotations
from lab.genesis.retention.family import RetentionFamilyEvaluator, RetentionFamilyPolicy
from lab.genesis.retention.receipts import RetentionVerdict
from lab.genesis.retention.rule_a_star import RuleAStar
from tests.genesis._retention_helpers import build_case

def test_family_budget_and_inconclusive_member_block_pass(tmp_path):
    a=build_case(tmp_path/"a",.90,.88); b=build_case(tmp_path/"b",.90,.86); poisoned=build_case(tmp_path/"p",.90,.88,risk_target="audit",risk_score=.8)
    da=RuleAStar.evaluate(a["package"],a["baseline"],a["observation"],a["state"],a["view"]).decision
    db=RuleAStar.evaluate(b["package"],b["baseline"],b["observation"],b["state"],b["view"]).decision
    dp=RuleAStar.evaluate(poisoned["package"],poisoned["baseline"],poisoned["observation"],poisoned["state"],poisoned["view"]).decision
    policy=RetentionFamilyPolicy("family","m4",("a","b"),.04)
    assert RetentionFamilyEvaluator.evaluate(policy,{"a":(da,.5),"b":(db,.5)}).verdict is RetentionVerdict.PASS
    tight=RetentionFamilyPolicy("family","m4",("a","b"),.02)
    assert RetentionFamilyEvaluator.evaluate(tight,{"a":(da,.5),"b":(db,.5)}).verdict is RetentionVerdict.REGRESSION
    assert RetentionFamilyEvaluator.evaluate(policy,{"a":(da,.5),"b":(dp,.5)}).verdict is RetentionVerdict.INCONCLUSIVE
