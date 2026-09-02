import pytest
from tests.genesis.test_verifier_federation import d,req
from lab.genesis.verifiers import VerifierRegistry
def test_registry_deterministic_and_conflict_rejected():
 r=VerifierRegistry();a=d("a","x");r.register(a);assert r.compatible(req())==(a,)
 with pytest.raises(ValueError):r.register(d("a","different"))
