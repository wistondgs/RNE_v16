import pytest
from tests.genesis._m5_helpers import run,experiment,h
from lab.genesis.intervention.kernel import GenericInterventionKernel
from lab.genesis.intervention.replay import CausalExperimentReplay
@pytest.mark.parametrize("object_name,field,value",[("manifest","master_seed",9),("root","state",{}),("seal","candidate_output_hash","0"*64),("oracle","score",.5),("budget","logical_steps",99),("receipt","score",.5),("trace","executed_arm_order",("x",)),("cfi","violations",("tamper",)),("summary","effects",(("x",1.),))])
def test_tampering_fails_replay(object_name,field,value):
 result,_=run();target={"manifest":result.manifest,"root":result.root,"seal":result.seals[0],"oracle":result.oracles[0],"budget":result.budgets[0],"receipt":result.receipts[0],"trace":result.trace,"cfi":result.cfi,"summary":result.summary}[object_name];object.__setattr__(target,field,value);assert CausalExperimentReplay.verify(result).status=="FAIL"
def test_unknown_and_budget_mismatch_block_attribution():
 incomplete,_=run(required=("cache",));assert incomplete.cfi.status.value=="INCOMPLETE" and not incomplete.summary.attribution_eligible
 a,r,s,b,m,o=experiment(budget_override=h("different"));failed=GenericInterventionKernel().run(m,r,s,b,a,o);assert failed.cfi.status.value=="FAIL" and not failed.summary.attribution_eligible
