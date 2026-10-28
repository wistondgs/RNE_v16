from __future__ import annotations
from dataclasses import FrozenInstanceError
import pytest
from lab.genesis.retention.package import RetentionAuditPackage
from tests.genesis._retention_helpers import build_case

def test_package_binds_content_addressed_audit_dataset_and_hides_payload(tmp_path):
    case=build_case(tmp_path)
    assert not case["package"].validate_bindings(case["store"],case["graph"])
    assert "surface" not in str(case["package"].canonical_payload())
    with pytest.raises(FrozenInstanceError): case["package"].epsilon_i=1 # type: ignore[misc]
    with pytest.raises(ValueError): RetentionAuditPackage("x","m4","c","a"*64,"b"*64,"c"*64,"d"*64,"e"*64,"f"*64,"0"*64,None,-1,0,0,{})
