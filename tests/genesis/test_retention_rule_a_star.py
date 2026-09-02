from __future__ import annotations
from lab.genesis.retention.receipts import RetentionVerdict
from lab.genesis.retention.rule_a_star import RuleAStar
from tests.genesis._retention_helpers import build_case

def test_clean_retention_and_real_regression(tmp_path):
    clean=build_case(tmp_path/"clean",.90,.88); regression=build_case(tmp_path/"regression",.90,.72)
    assert RuleAStar.evaluate(clean["package"],clean["baseline"],clean["observation"],clean["state"],clean["view"]).decision.verdict is RetentionVerdict.PASS
    assert RuleAStar.evaluate(regression["package"],regression["baseline"],regression["observation"],regression["state"],regression["view"]).decision.verdict is RetentionVerdict.REGRESSION

def test_observation_reference_mismatch_is_error(tmp_path):
    case=build_case(tmp_path); object.__setattr__(case["observation"],"audit_dataset_hash","0"*64)
    assert RuleAStar.evaluate(case["package"],case["baseline"],case["observation"],case["state"],case["view"]).decision.verdict is RetentionVerdict.ERROR
