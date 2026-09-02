from tests.genesis._m5_helpers import experiment
from lab.genesis.intervention.kernel import GenericInterventionKernel
def test_undeclared_delta_fails_cfi():
 a,r,s,b,m,o=experiment();object.__setattr__(m.arm_specs[1],"allowed_delta_paths",());result=GenericInterventionKernel().run(m,r,s,b,a,o);assert result.cfi.status.value=="FAIL"
