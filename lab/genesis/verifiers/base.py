"""Verifier protocol."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import VerifierReceipt


class Verifier(Protocol):
    verifier_id: str
    verifier_version: str

    def verify(self, claim: TypedClaim, candidate: Any, context: Mapping[str, Any]) -> VerifierReceipt:
        ...
