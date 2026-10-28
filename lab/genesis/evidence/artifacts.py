"""Write-once, content-addressed evidence artifacts for Genesis experiments."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from lab.genesis.contracts.serialization import canonical_json_bytes


def is_artifact_hash(value: str) -> bool:
    """Return whether *value* is the only accepted on-disk object identifier."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class ContentAddressedArtifactStore:
    """A filesystem store whose object identity is strict canonical JSON SHA-256.

    The normal API intentionally has no update or delete operation.  Filesystem
    access is not treated as trusted: ``verify`` re-hashes the stored bytes.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_hash: str) -> Path:
        if not is_artifact_hash(artifact_hash):
            raise ValueError("genesis_artifact_hash_invalid")
        # The format check above makes both path components data-only.
        return self.objects / artifact_hash[:2] / artifact_hash

    def put(self, payload: Any) -> str:
        data = canonical_json_bytes(payload)
        artifact_hash = hashlib.sha256(data).hexdigest()
        destination = self._path(artifact_hash)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != data:
                raise RuntimeError("genesis_artifact_hash_content_conflict")
            return artifact_hash

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".genesis-object-", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # link is atomic and, unlike os.replace, never overwrites an
                # already present object in a concurrent writer race.
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != data:
                    raise RuntimeError("genesis_artifact_hash_content_conflict")
            return artifact_hash
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def get_bytes(self, artifact_hash: str) -> bytes:
        return self._path(artifact_hash).read_bytes()

    def get(self, artifact_hash: str) -> Any:
        """Load only JSON produced by :meth:`put`; never deserialize code."""
        return json.loads(self.get_bytes(artifact_hash).decode("utf-8"))

    def exists(self, artifact_hash: str) -> bool:
        try:
            return self._path(artifact_hash).is_file()
        except ValueError:
            return False

    def verify(self, artifact_hash: str) -> bool:
        try:
            data = self.get_bytes(artifact_hash)
        except (OSError, ValueError):
            return False
        return hashlib.sha256(data).hexdigest() == artifact_hash
