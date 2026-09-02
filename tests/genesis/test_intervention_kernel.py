from tests.genesis._m5_helpers import run
def test_synthetic_control_treatment_placebo_effects():
 result,_=run();scores={x.arm_id:x.score for x in result.receipts};effects=dict(result.summary.effects);assert scores=={"control":0.0,"treatment":1.0,"placebo":0.0};assert effects["treatment_effect"]==1 and effects["placebo_effect"]==0 and result.summary.attribution_eligible
