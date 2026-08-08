from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import Arm, ExperimentProposal, PublicAction
from .canonical import digest
from .sealing import OracleService


class ControlPolicy(Protocol):
    arm: Arm
    def select(self, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> ExperimentProposal | None: ...


@dataclass(slots=True)
class PassiveControl:
    arm: Arm = Arm.C0_PASSIVE
    def select(self, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> None:
        return None


@dataclass(slots=True)
class GreedyControl:
    arm: Arm = Arm.C1_GREEDY
    def select(self, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> ExperimentProposal | None:
        return max(proposals, key=lambda p: (p.immediate_reward, p.proposal_id), default=None)


class RandomMatchedCostControl:
    arm = Arm.C2_RANDOM
    def __init__(self, seed: int, substrate_tag: str) -> None:
        if substrate_tag not in {"MCI", "A11"}:
            raise ValueError("c2_substrate_tag_must_be_MCI_or_A11")
        self.seed, self.substrate_tag, self.draw_index = seed, substrate_tag, 0

    def select(self, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> ExperimentProposal | None:
        if not proposals:
            return None
        candidates = sorted(proposals, key=lambda p: p.proposal_id)
        # Counter-based public stream: replay depends only on seed and draw index.
        counter = int(digest({"arm_seed": self.seed, "draw_index": self.draw_index}), 16)
        chosen = candidates[counter % len(candidates)]
        self.draw_index += 1
        return chosen


class OracleControl:
    arm = Arm.C5_ORACLE
    def __init__(self, oracle: OracleService) -> None:
        self._oracle = oracle

    def select(self, proposals: tuple[ExperimentProposal, ...], actions: tuple[PublicAction, ...]) -> ExperimentProposal | None:
        action = self._oracle.choose(actions)
        return next((proposal for proposal in proposals if proposal.action_id == action.action_id), None)
