from __future__ import annotations
from lab.genesis.retention.package import RetentionSurface
from tests.genesis._retention_helpers import build_case

def test_epistemic_state_is_frozen_and_inherited_risk_reaches_audit_dataset(tmp_path):
    case=build_case(tmp_path,risk_target="inherited_audit",risk_score=.8)
    audit=case["view"].for_surface(RetentionSurface.AUDIT_DATASET)
    assert audit.risk_score==.8 and audit.risk_assessment_hash==case["assessments"][0].assessment_hash
    assert case["state"].state_hash!=case["state"].provenance_graph_hash
