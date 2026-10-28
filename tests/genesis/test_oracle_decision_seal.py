import pytest
from tests.genesis._m5_helpers import experiment
from lab.genesis.intervention.oracle import OracleGate
def test_oracle_requires_valid_preoracle_seal_and_secret_is_not_visible():
 a,r,s,b,m,o=experiment();assert "target" not in str(r.canonical_payload())
 with pytest.raises(Exception):OracleGate().open(None,o,(),())
