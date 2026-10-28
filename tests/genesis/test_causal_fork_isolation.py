from tests.genesis._m5_helpers import run
def test_root_sealed_before_independent_arms():
 result,adapter=run();assert adapter.trace[0:2]==["ROOT_CAPTURE","ROOT_SEAL"];assert all(adapter.trace.index("ROOT_SEAL")<adapter.trace.index(x) for x in adapter.trace if x.startswith("ARM_"));assert result.cfi.status.value=="PASS"
