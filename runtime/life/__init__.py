"""Runtime de vida autonoma fuerte RNFE."""

from .checkpoints import CheckpointManager, LIFE_CHECKPOINT_KIND
from .contracts import (
    AutonomyDecision,
    EvolutionProposalV2,
    GoalState,
    LifeStepResult,
    RestoredIdentity,
    VitalSignsSnapshot,
)
from .goals import GoalManager
from .kernel import LifeKernel, LifeKernelConfig
from . import reference_manifest
from .persistence import OrganismPersistence
from .supervisor import AutonomySupervisor, AutonomySupervisorConfig
from .vitals import VitalSignsService

__all__ = [
    "AutonomyDecision",
    "AutonomySupervisor",
    "AutonomySupervisorConfig",
    "CheckpointManager",
    "EvolutionProposalV2",
    "GoalManager",
    "GoalState",
    "LifeKernel",
    "LifeKernelConfig",
    "LifeStepResult",
    "LIFE_CHECKPOINT_KIND",
    "OrganismPersistence",
    "reference_manifest",
    "RestoredIdentity",
    "VitalSignsService",
    "VitalSignsSnapshot",
]
