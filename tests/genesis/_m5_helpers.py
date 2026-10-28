from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.causal.fork import SyntheticForkableStateAdapter
from lab.genesis.intervention.specs import *
from lab.genesis.intervention.kernel import GenericInterventionKernel
from lab.genesis.intervention.oracle import SyntheticOracle
def h(x):return canonical_sha256({"x":x})
def experiment(required=(),budget_override=None):
 adapter=SyntheticForkableStateAdapter({x:"UNKNOWN" for x in required});root=adapter.capture_root({"capabilities":{"operator":"IDENTITY"},"inputs":tuple(range(-10,11))});budget=ComputeBudgetSpec(10,1,1,0)
 specs=(InterventionSpec("control","m5","none",(),h("p0"),"none"),InterventionSpec("treatment","m5","increment_operator",("capabilities.operator",),h("p1"),"increment"),InterventionSpec("placebo","m5","placebo_marker",("capabilities.placebo_marker",),h("p2"),"inert"))
 arms=(ArmSpec("control",ArmRole.CONTROL,specs[0].spec_hash,(),required,budget.budget_hash,RNGPolicy.ARM_DERIVED,h("m0")),ArmSpec("treatment",ArmRole.TREATMENT,specs[1].spec_hash,("capabilities.operator",),required,budget_override or budget.budget_hash,RNGPolicy.ARM_DERIVED,h("m1")),ArmSpec("placebo",ArmRole.PLACEBO,specs[2].spec_hash,("capabilities.placebo_marker",),required,budget.budget_hash,RNGPolicy.ARM_DERIVED,h("m2")))
 manifest=CausalExperimentManifest("exp","m5",h("claim"),root.root_hash,h("cfi"),arms,budget.budget_hash,RNGPolicy.ARM_DERIVED,7,h("oracle"),"synthetic",required)
 return adapter,root,specs,budget,manifest,SyntheticOracle(manifest.oracle_spec_hash)
def run(required=(),order=None,budget_override=None):
 a,r,s,b,m,o=experiment(required,budget_override);return GenericInterventionKernel().run(m,r,s,b,a,o,order),a
