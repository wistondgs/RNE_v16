"""Characterize the M5 kernel before adding M7 capability interventions."""

from __future__ import annotations

import pytest

from lab.genesis.causal.fork import SyntheticForkableStateAdapter
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.intervention.kernel import GenericInterventionKernel
from lab.genesis.intervention.oracle import SyntheticOracle
from lab.genesis.intervention.specs import (
    ArmRole,
    ArmSpec,
    CausalExperimentManifest,
    ComputeBudgetSpec,
    InterventionSpec,
    RNGPolicy,
)


def h(value: object) -> str:
    return canonical_sha256({"m7e2-characterization": value})


def test_current_m5_kernel_cannot_execute_a_program_skill_installation() -> None:
    adapter = SyntheticForkableStateAdapter()
    root = adapter.capture_root(
        {
            "capabilities": {"operator": "IDENTITY", "installed_skill_hashes": ()},
            "inputs": (-2, -1, 0, 1, 2),
        }
    )
    budget = ComputeBudgetSpec(10, 1, 1, 0)
    control = InterventionSpec("control", "m7e2", "none", (), h("control"), "none")
    install = InterventionSpec(
        "treatment",
        "m7e2",
        "install_program_skill",
        ("capabilities.installed_skill_hashes",),
        h("install"),
        "install",
    )
    manifest = CausalExperimentManifest(
        "m7e2-characterization",
        "m7e2",
        h("claim"),
        root.root_hash,
        h("cfi"),
        (
            ArmSpec("control", ArmRole.CONTROL, control.spec_hash, (), (), budget.budget_hash, RNGPolicy.ARM_DERIVED, h("control-arm")),
            ArmSpec("treatment", ArmRole.TREATMENT, install.spec_hash, ("capabilities.installed_skill_hashes",), (), budget.budget_hash, RNGPolicy.ARM_DERIVED, h("treatment-arm")),
        ),
        budget.budget_hash,
        RNGPolicy.ARM_DERIVED,
        7,
        h("oracle"),
        "synthetic-v1",
        (),
    )

    with pytest.raises(ValueError, match="intervention_unregistered"):
        GenericInterventionKernel().run(
            manifest,
            root,
            (control, install),
            budget,
            adapter,
            SyntheticOracle(manifest.oracle_spec_hash),
        )
