from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import canonical_json
from .contracts import ContractError, PublicAction


class SealAccessError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class PublicGroundTruthSeal:
    scenario_id: str
    commitment: str
    schema_version: str = "ea1-ground-truth-seal-v1"

    def to_payload(self) -> dict[str, str]:
        return {"scenario_id": self.scenario_id, "commitment": self.commitment, "schema_version": self.schema_version}


class _AccessToken:
    __slots__ = ("_identity", "purpose")
    def __init__(self, identity: object, purpose: str) -> None:
        self._identity = identity
        self.purpose = purpose


class SealedGroundTruth:
    """Private bundle. Only its public seal is passed to experimental arms."""

    def __init__(self, scenario_id: str, hidden: Mapping[str, Any], nonce: bytes | None = None) -> None:
        self.__identity = object()
        self.__hidden = dict(hidden)
        self.__nonce = nonce or secrets.token_bytes(32)
        if len(self.__nonce) != 32:
            raise ContractError("ground_truth_nonce_must_be_256_bits")
        material = canonical_json(self.__hidden).encode() + b"\x00" + self.__nonce
        self.public = PublicGroundTruthSeal(scenario_id, hashlib.sha256(material).hexdigest())

    def evaluator_token(self) -> _AccessToken:
        return _AccessToken(self.__identity, "evaluator")

    def oracle_token(self) -> _AccessToken:
        return _AccessToken(self.__identity, "oracle")

    def open(self, token: object, *, purpose: str) -> Mapping[str, Any]:
        if not isinstance(token, _AccessToken) or token._identity is not self.__identity or token.purpose != purpose:
            raise SealAccessError("ground_truth_access_denied")
        return dict(self.__hidden)

    def verify(self, hidden: Mapping[str, Any], nonce: bytes) -> bool:
        material = canonical_json(hidden).encode() + b"\x00" + nonce
        return secrets.compare_digest(self.public.commitment, hashlib.sha256(material).hexdigest())


class OracleService:
    def __init__(self, bundle: SealedGroundTruth, token: object) -> None:
        self._bundle = bundle
        self._token = token

    def choose(self, actions: tuple[PublicAction, ...]) -> PublicAction:
        hidden = self._bundle.open(self._token, purpose="oracle")
        preferred = str(hidden["oracle_action_id"])
        try:
            return next(action for action in actions if action.action_id == preferred)
        except StopIteration as exc:
            raise ContractError("oracle_action_not_publicly_available") from exc
