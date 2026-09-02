"""Stable execution-binding helpers shared by Genesis verifiers."""

from __future__ import annotations

from typing import Any, Mapping

from lab.genesis.contracts.serialization import canonical_sha256


def canonical_execution_context_hash(
    claim_hash: str,
    candidate_identity_hash: str,
    context: Mapping[str, Any],
) -> str:
    """Seal the execution context without depending on a claim object identity.

    This is intentionally byte-for-byte compatible with the M6A-1 helper.
    Protocol fields are supplied separately; every other context field remains
    part of the seal, including verifier-specific property/reference bindings.
    """

    protocol_keys = {
        "claim",
        "claim_hash",
        "candidate_identity_hash",
        "context_hash",
    }
    payload = {
        "claim_hash": claim_hash,
        "candidate_identity_hash": candidate_identity_hash,
        **{
            str(key): value
            for key, value in context.items()
            if str(key) not in protocol_keys
        },
    }
    return canonical_sha256(payload)
