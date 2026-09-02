"""Read-only capture adapters for CFI-v0."""

from .code import capture_code
from .dependencies import capture_dependencies
from .environment import capture_environment
from .rng import capture_rng, restore_rng, verify_equivalence

__all__ = ["capture_code", "capture_dependencies", "capture_environment", "capture_rng", "restore_rng", "verify_equivalence"]
