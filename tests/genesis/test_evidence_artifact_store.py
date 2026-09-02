from __future__ import annotations

import pytest

from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore


def test_content_addressed_store_is_idempotent_and_detects_corruption(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    artifact_hash = store.put({"z": [2, 1], "a": "evidence"})

    assert store.put({"a": "evidence", "z": [2, 1]}) == artifact_hash
    assert store.get(artifact_hash) == {"a": "evidence", "z": [2, 1]}
    assert store.verify(artifact_hash)

    store._path(artifact_hash).write_bytes(b'{"replacement":true}')
    assert not store.verify(artifact_hash)
    with pytest.raises(RuntimeError, match="content_conflict"):
        store.put({"z": [2, 1], "a": "evidence"})


def test_store_rejects_path_traversal_and_invalid_hashes(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    for invalid in ("../objects", "A" * 64, "a" * 63, "a" * 64 + "/x"):
        assert not store.exists(invalid)
        with pytest.raises(ValueError):
            store.get(invalid)
