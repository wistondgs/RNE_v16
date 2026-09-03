"""M6B4-B1/B2: durable closure persistence, recovery and fresh replay."""
from dataclasses import replace
import runpy

import pytest

from lab.genesis.evidence import (
    ContentAddressedArtifactStore, persist_m6_trace, replay_m6_trace, stage_m6_trace,
)
from lab.genesis.verifiers import (
    FederationVerdict, adjudicate_requirement, build_requirement_evidence_bundle,
)


source = runpy.run_path("tests/genesis/test_m6b2_evidence.py")


def valid_trace_material():
    router, plan, subject, records = source["material"]()
    bundle = build_requirement_evidence_bundle(
        router=router, federation_plan=plan, subject=subject,
        requirement_id="router-requirement", records=records,
    )
    adjudication = adjudicate_requirement(
        router=router, federation_plan=plan, subject=subject,
        records=records, bundle=bundle,
    )
    assert adjudication.verdict is FederationVerdict.PASS
    return dict(router=router, federation_plan=plan, subject=subject,
                records=records, bundle=bundle, adjudication=adjudication)


class CountingStore(ContentAddressedArtifactStore):
    def __init__(self, root, fail_on=None):
        super().__init__(root)
        self.put_calls = 0
        self.fail_on = fail_on

    def put(self, payload):
        self.put_calls += 1
        if self.fail_on == self.put_calls:
            raise OSError("injected durable-stage failure")
        return super().put(payload)


def role_hash(closure, role):
    return next(group.artifact_hashes[0] for group in closure.artifact_groups if group.role == role)


def test_validate_before_write_and_canonical_idempotent_persistence(tmp_path):
    material = valid_trace_material()
    store = CountingStore(tmp_path)
    false = replace(material["adjudication"], verdict=FederationVerdict.FAIL)
    with pytest.raises(ValueError, match="adjudication_invalid"):
        persist_m6_trace(store, **(material | {"adjudication": false}))
    assert store.put_calls == 0

    first = persist_m6_trace(store, **material)
    writes_after_first = store.put_calls
    second = persist_m6_trace(store, **material)
    assert first.trace_id == second.trace_id
    assert first.closure_hash == second.closure_hash
    assert store.put_calls > writes_after_first
    assert replay_m6_trace(ContentAddressedArtifactStore(tmp_path), first.closure_hash).admitted

