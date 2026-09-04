"""Declarative M7 capability transitions executed inside the M5 kernel.

This module deliberately does *not* fork state, calculate causal effects,
open an oracle, or issue a CFI report.  Those responsibilities remain in
``GenericInterventionKernel``.  It only gives that kernel a closed, auditable
way to install or remove a previously sealed M7 program skill in an arm-local
state and to evaluate the safe integer DSL.

Keeping the runtime narrow is important: M7 causal attribution is evidence
about the effect of a concrete capability, not a second causal engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from lab.genesis.acquisition.benchmark import SealedCapabilityBenchmark
from lab.genesis.acquisition.contracts import CapabilityManifest, ProgramSkillArtifact
from lab.genesis.acquisition.dsl import DSLSpecification, evaluate_expression, validate_program_skill
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.intervention.specs import InterventionSpec


class CapabilityOperation(str, Enum):
    """The only state mutations C1/C2/C3 are permitted to request."""

    NONE = "NONE"
    INSTALL = "INSTALL"
    REMOVE = "REMOVE"


def capability_intervention_type(operation: CapabilityOperation) -> str:
    """Map a declared transition to a trusted M5 intervention registry key."""

    return {
        CapabilityOperation.NONE: "none",
        CapabilityOperation.INSTALL: "capability_install",
        CapabilityOperation.REMOVE: "capability_remove",
    }[CapabilityOperation(operation)]


def _canonical_hashes(values: Sequence[str], reason: str) -> tuple[str, ...]:
    result = tuple(sorted(str(value) for value in values))
    if len(result) != len(set(result)) or any(len(value) != 64 for value in result):
        raise ValueError(reason)
    return result


@dataclass(frozen=True, slots=True)
class CapabilityStateAction:
    """A concrete, re-derivable capability transition for exactly one M5 arm.

    ``post_manifest`` is explicit even for an ablation.  This lets the action
    prove exact set subtraction instead of treating an empty capability set as
    a magic condition.  We do not overload promotion lineage for removal: a
    removal is an experimental arm state, not a new promoted organism state.
    """

    action_id: str
    schema_version: str
    operation: CapabilityOperation
    pre_manifest: CapabilityManifest
    post_manifest: CapabilityManifest
    skill_hash: str | None = None
    action_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.action_id or not self.schema_version:
            raise ValueError("genesis_capability_action_identity_invalid")
        operation = CapabilityOperation(self.operation)
        object.__setattr__(self, "operation", operation)
        if not self.pre_manifest.validate() or not self.post_manifest.validate():
            raise ValueError("genesis_capability_action_manifest_invalid")
        before = set(self.pre_manifest.skill_hashes)
        after = set(self.post_manifest.skill_hashes)
        if operation is CapabilityOperation.NONE:
            if self.skill_hash is not None or before != after:
                raise ValueError("genesis_capability_action_none_invalid")
        elif operation is CapabilityOperation.INSTALL:
            if not self.skill_hash or self.skill_hash in before or after != before | {self.skill_hash}:
                raise ValueError("genesis_capability_action_install_invalid")
        elif operation is CapabilityOperation.REMOVE:
            if not self.skill_hash or self.skill_hash not in before or after != before - {self.skill_hash}:
                raise ValueError("genesis_capability_action_remove_invalid")
        object.__setattr__(self, "action_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "schema_version": self.schema_version,
            "operation": self.operation.value,
            "pre_manifest_hash": self.pre_manifest.manifest_hash,
            "post_manifest_hash": self.post_manifest.manifest_hash,
            "pre_skill_hashes": self.pre_manifest.skill_hashes,
            "post_skill_hashes": self.post_manifest.skill_hashes,
            "skill_hash": self.skill_hash,
        }

    def validate(self) -> bool:
        try:
            return CapabilityStateAction(
                self.action_id,
                self.schema_version,
                self.operation,
                self.pre_manifest,
                self.post_manifest,
                self.skill_hash,
            ).action_hash == self.action_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        manifests_by_hash: Mapping[str, CapabilityManifest],
    ) -> "CapabilityStateAction":
        values = dict(payload)
        pre = manifests_by_hash.get(values.pop("pre_manifest_hash"))
        post = manifests_by_hash.get(values.pop("post_manifest_hash"))
        values.pop("pre_skill_hashes", None)
        values.pop("post_skill_hashes", None)
        if pre is None or post is None:
            raise ValueError("genesis_capability_action_manifest_unavailable")
        return cls(pre_manifest=pre, post_manifest=post, **values)

@dataclass(frozen=True, slots=True)
class CapabilityExecutionBinding:
    """Bind a M6 candidate identity to the exact executable M5 arm state.

    A no-capability arm has an explicit identity rather than masquerading as a
    program skill.  This avoids the subtle but serious error of certifying a
    synthetic ``zero`` skill as though it had been installed in G0.
    """

    schema_version: str
    arm_id: str
    root_instance_id: str
    root_snapshot_hash: str
    manifest: CapabilityManifest
    active_skill: ProgramSkillArtifact | None
    execution_identity_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not self.schema_version
            or not self.arm_id
            or not self.root_instance_id
            or len(self.root_snapshot_hash) != 64
            or not self.manifest.validate()
        ):
            raise ValueError("genesis_capability_execution_binding_invalid")
        if self.active_skill is None:
            if self.manifest.skill_hashes:
                raise ValueError("genesis_capability_execution_binding_missing_active_skill")
        elif (
            not self.active_skill.validate()
            or self.active_skill.skill_hash not in self.manifest.skill_hashes
            or self.manifest.skill_hashes != (self.active_skill.skill_hash,)
        ):
            raise ValueError("genesis_capability_execution_binding_skill_invalid")
        object.__setattr__(self, "execution_identity_hash", canonical_sha256(self.canonical_payload()))

    @property
    def active_skill_hash(self) -> str | None:
        return None if self.active_skill is None else self.active_skill.skill_hash

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "arm_id": self.arm_id,
            "root_instance_id": self.root_instance_id,
            "root_snapshot_hash": self.root_snapshot_hash,
            "manifest_hash": self.manifest.manifest_hash,
            "manifest_skill_hashes": self.manifest.skill_hashes,
            "active_skill_hash": self.active_skill_hash,
            "execution_mode": "DSL_SKILL" if self.active_skill is not None else "NO_CAPABILITY",
        }

    def validate(self) -> bool:
        try:
            return CapabilityExecutionBinding(
                self.schema_version,
                self.arm_id,
                self.root_instance_id,
                self.root_snapshot_hash,
                self.manifest,
                self.active_skill,
            ).execution_identity_hash == self.execution_identity_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        manifest: CapabilityManifest,
        active_skill: ProgramSkillArtifact | None,
    ) -> "CapabilityExecutionBinding":
        values = dict(payload)
        values.pop("manifest_hash", None)
        values.pop("manifest_skill_hashes", None)
        values.pop("active_skill_hash", None)
        values.pop("execution_mode", None)
        return cls(
            manifest=manifest,
            active_skill=active_skill,
            **values,
        )

    def evaluate(self, value: int, specification: DSLSpecification) -> int:
        if not self.validate() or not specification.validate():
            raise ValueError("genesis_capability_execution_binding_invalid")
        if self.active_skill is None:
            return 0
        if not validate_program_skill(self.active_skill, specification):
            raise ValueError("genesis_capability_execution_binding_dsl_invalid")
        return evaluate_expression(self.active_skill.program_ast, value, specification)


def capability_root_state(
    *,
    manifest: CapabilityManifest,
    execution_skill_hash: str | None,
    inputs: Sequence[int],
    root_instance_id: str,
    historical_skill_hashes: Sequence[str] = (),
) -> dict[str, Any]:
    """Create the only M7 capability state passed to M5's root snapshot.

    The state contains immutable capability identities and raw integer inputs;
    it never contains the benchmark's target AST, labels, or oracle result.
    ``root_instance_id`` is a predeclared experimental-source identity.  It is
    neither a time nor a random nonce: committing it distinguishes a fresh C3
    source capture from a re-used C1 G0 snapshot even when their executable
    capability sets are intentionally identical.
    ``historical_skill_hashes`` records lineage knowledge for freshness checks
    in the evidence layer but intentionally does not restrict a normal G1
    root that has the installed skill.
    """

    if not manifest.validate() or not isinstance(root_instance_id, str) or not root_instance_id:
        raise ValueError("genesis_capability_root_manifest_invalid")
    installed = manifest.skill_hashes
    if execution_skill_hash is None:
        if installed:
            raise ValueError("genesis_capability_root_execution_missing")
    elif execution_skill_hash not in installed:
        raise ValueError("genesis_capability_root_execution_invalid")
    values = tuple(inputs)
    if not values or any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValueError("genesis_capability_root_inputs_invalid")
    return {
        "causal_root_instance_id": root_instance_id,
        "capabilities": {
            "manifest_hash": manifest.manifest_hash,
            "installed_skill_hashes": installed,
            "execution_skill_hash": execution_skill_hash,
            "historical_skill_hashes": _canonical_hashes(
                historical_skill_hashes, "genesis_capability_root_history_invalid"
            ),
        },
        "inputs": values,
    }


class CapabilityArmRuntime:
    """Trusted declarative executor supplied to the existing M5 kernel."""

    def __init__(
        self,
        *,
        specification: DSLSpecification,
        actions_by_spec_hash: Mapping[str, CapabilityStateAction],
        skills_by_hash: Mapping[str, ProgramSkillArtifact],
    ) -> None:
        if not specification.validate():
            raise ValueError("genesis_capability_runtime_dsl_invalid")
        self.specification = specification
        self.actions_by_spec_hash = dict(actions_by_spec_hash)
        self.skills_by_hash = dict(skills_by_hash)
        if not self.actions_by_spec_hash or any(
            not key or not action.validate() for key, action in self.actions_by_spec_hash.items()
        ):
            raise ValueError("genesis_capability_runtime_actions_invalid")
        if any(
            key != skill.skill_hash or not validate_program_skill(skill, specification)
            for key, skill in self.skills_by_hash.items()
        ):
            raise ValueError("genesis_capability_runtime_skills_invalid")
        for action in self.actions_by_spec_hash.values():
            if action.skill_hash is not None and action.skill_hash not in self.skills_by_hash:
                raise ValueError("genesis_capability_runtime_action_skill_unknown")

    def _capabilities(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        capabilities = state.get("capabilities")
        if not isinstance(capabilities, Mapping):
            raise ValueError("genesis_capability_runtime_state_invalid")
        return capabilities

    def _state_skill_set(self, state: Mapping[str, Any]) -> tuple[str, ...]:
        capabilities = self._capabilities(state)
        values = _canonical_hashes(
            capabilities.get("installed_skill_hashes", ()), "genesis_capability_runtime_installed_invalid"
        )
        active = capabilities.get("execution_skill_hash")
        if active is not None and active not in values:
            raise ValueError("genesis_capability_runtime_active_invalid")
        return values

    def apply(self, state: dict[str, Any], intervention: InterventionSpec) -> dict[str, Any]:
        """Apply a declared action and reject every unbound state transition."""

        action = self.actions_by_spec_hash.get(intervention.spec_hash)
        if action is None:
            raise ValueError("genesis_capability_runtime_intervention_unbound")
        if (
            intervention.intervention_type != capability_intervention_type(action.operation)
            or intervention.parameters_hash != action.action_hash
        ):
            raise ValueError("genesis_capability_runtime_intervention_mismatch")
        capabilities = self._capabilities(state)
        if (
            capabilities.get("manifest_hash") != action.pre_manifest.manifest_hash
            or self._state_skill_set(state) != action.pre_manifest.skill_hashes
        ):
            raise ValueError("genesis_capability_runtime_prestate_mismatch")
        active = capabilities.get("execution_skill_hash")
        if action.operation is CapabilityOperation.INSTALL:
            active = action.skill_hash
        elif action.operation is CapabilityOperation.REMOVE:
            if active != action.skill_hash:
                raise ValueError("genesis_capability_runtime_ablation_not_operational")
            active = None
        state["capabilities"] = {
            "manifest_hash": action.post_manifest.manifest_hash,
            "installed_skill_hashes": action.post_manifest.skill_hashes,
            "execution_skill_hash": active,
            "historical_skill_hashes": tuple(capabilities.get("historical_skill_hashes", ())),
        }
        return state

    def inputs(self, root: Any, state: Mapping[str, Any]) -> tuple[int, ...]:
        values = tuple(state.get("inputs", ()))
        if not values or any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("genesis_capability_runtime_inputs_invalid")
        return values

    def execute(self, state: Mapping[str, Any], inputs: Sequence[int]) -> tuple[int, ...]:
        """Run one installed sealed program, or the predeclared null baseline."""

        self._state_skill_set(state)
        active = self._capabilities(state).get("execution_skill_hash")
        if active is None:
            return tuple(0 for _ in inputs)
        skill = self.skills_by_hash.get(active)
        if skill is None or not validate_program_skill(skill, self.specification):
            raise ValueError("genesis_capability_runtime_execution_skill_invalid")
        return tuple(evaluate_expression(skill.program_ast, value, self.specification) for value in inputs)


class CapabilityMeasurementOracle:
    """Evaluator-only exact oracle for a fixed benchmark task and input vector."""

    evaluator_version = "genesis-m7-capability-measurement-oracle-v1"

    def __init__(self, *, benchmark: SealedCapabilityBenchmark, task_id: str, inputs: Sequence[int]) -> None:
        if not benchmark.validate() or task_id not in benchmark._tasks:
            raise ValueError("genesis_capability_oracle_benchmark_invalid")
        values = tuple(inputs)
        if not values or any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("genesis_capability_oracle_inputs_invalid")
        self._benchmark = benchmark
        self._task_id = task_id
        self._inputs = values
        self.oracle_spec_hash = canonical_sha256(
            {
                "schema_version": self.evaluator_version,
                "benchmark_manifest_hash": benchmark.manifest.manifest_hash,
                "task_id": task_id,
                "inputs_hash": canonical_sha256(values),
            }
        )

    def evaluate(self, outputs: Sequence[int], inputs: Sequence[int]) -> tuple[float, str]:
        if tuple(inputs) != self._inputs:
            raise ValueError("genesis_capability_oracle_input_binding_invalid")
        output_values = tuple(outputs)
        if len(output_values) != len(self._inputs):
            raise ValueError("genesis_capability_oracle_outputs_invalid")
        target = self._benchmark._tasks[self._task_id].target_ast
        expected = tuple(evaluate_expression(target, value, self._benchmark.specification) for value in self._inputs)
        exact = output_values == expected
        return (
            1.0 if exact else 0.0,
            canonical_sha256(
                {
                    "inputs": self._inputs,
                    "outputs": output_values,
                    "expected": expected,
                    "exact": exact,
                }
            ),
        )
