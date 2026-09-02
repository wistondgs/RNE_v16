from tests.genesis._m5_helpers import experiment
from lab.genesis.intervention.kernel import GenericInterventionKernel
class DefectiveAdapter:
 def __init__(self,base):self.base=base;self.required_surfaces=base.required_surfaces;self.trace=base.trace
 def __getattr__(self,x):return getattr(self.base,x)
 def fork(self,root,arm):
  state=self.base.fork(root,arm)
  if arm=="treatment":object.__setattr__(root,"state",{"capabilities":{"operator":"CORRUPT"},"inputs":tuple(range(-10,11))})
  return state
def test_root_shared_write_is_detected():
 a,r,s,b,m,o=experiment();result=GenericInterventionKernel().run(m,r,s,b,DefectiveAdapter(a),o);assert result.cfi.status.value=="FAIL" and not result.summary.attribution_eligible
