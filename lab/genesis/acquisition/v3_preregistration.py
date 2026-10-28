"""M7-H3A: materialized V3 preregistration and recoverable-run contracts.

This module deliberately contains no acquisition entry point.  Its job is to
make a V3 experiment completely addressable before H3B is allowed to execute
one of its canonical slots.  In particular, a launcher receives a sealed
predeclaration, never caller-selected scientific hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ast
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from lab.genesis.acquisition.contracts import CapabilityManifest
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256, freeze


_HASH_LENGTH = 64
_COMMIT_LENGTH = 40
_SCHEMA = "genesis-m7-h3-v3-preregistration-v1"
_SOURCE_CLOSURE_VERSION = "EXECUTION_SOURCE_CLOSURE-v1"
_CANONICAL_TASKS = (
    "abs_affine-0", "abs_affine-1", "affine-0", "affine-1",
    "quadratic_simple-0", "quadratic_simple-1",
)
_V2_NONCONFIRMATORY = "TECHNICALLY_VALID_BUT_NONCONFIRMATORY"
_V2_RUNTIME_BOUND = "V2_PREDECLARATION_RUNTIME_BOUND"


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or len(value) != _HASH_LENGTH or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(reason)


def _require_commit(value: str, reason: str) -> None:
    if not isinstance(value, str) or len(value) != _COMMIT_LENGTH or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(reason)


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("genesis_h3_relative_path_invalid")
    return value


def _hashes(values: Iterable[str], reason: str) -> tuple[str, ...]:
    result = tuple(sorted(str(item) for item in values))
    if len(set(result)) != len(result):
        raise ValueError(reason)
    for item in result:
        _require_hash(item, reason)
    return result


def _mapping(values: Mapping[str, str], reason: str) -> Mapping[str, str]:
    result = {str(key): str(value) for key, value in values.items()}
    if tuple(result) != tuple(sorted(result)):
        result = dict(sorted(result.items()))
    if not result:
        raise ValueError(reason)
    for key, value in result.items():
        if not key:
            raise ValueError(reason)
        _require_hash(value, reason)
    return freeze(result)


@dataclass(frozen=True, slots=True)
class ExecutionSourceBlobV3:
    path: str
    blob_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path))
        _require_commit(self.blob_hash, "genesis_h3_source_blob_invalid")

    def canonical_payload(self) -> dict[str, str]:
        return {"path": self.path, "blob_hash": self.blob_hash}


@dataclass(frozen=True, slots=True)
class ExecutionSourceManifestV3:
    """Concrete tracked source identity, rooted in ``C_IMPL`` rather than a label."""

    schema_version: str
    repository_identity: str
    implementation_commit: str
    entrypoint_paths: tuple[str, ...]
    source_blobs: tuple[ExecutionSourceBlobV3, ...]
    closure_version: str = _SOURCE_CLOSURE_VERSION
    dynamic_dependency_paths: tuple[str, ...] = ()
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        entries = tuple(sorted({_relative_path(item) for item in self.entrypoint_paths}))
        blobs = tuple(sorted(self.source_blobs, key=lambda item: item.path))
        dynamic = tuple(sorted({_relative_path(item) for item in self.dynamic_dependency_paths}))
        if (
            self.schema_version != "genesis-m7-h3-execution-source-manifest-v1"
            or self.closure_version != _SOURCE_CLOSURE_VERSION
            or not self.repository_identity
            or not entries
            or not blobs
            or len({item.path for item in blobs}) != len(blobs)
            or not set(entries).issubset({item.path for item in blobs})
            or not set(dynamic).issubset({item.path for item in blobs})
        ):
            raise ValueError("genesis_h3_source_manifest_invalid")
        _require_commit(self.implementation_commit, "genesis_h3_source_commit_invalid")
        object.__setattr__(self, "entrypoint_paths", entries)
        object.__setattr__(self, "source_blobs", blobs)
        object.__setattr__(self, "dynamic_dependency_paths", dynamic)
        object.__setattr__(self, "manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository_identity": self.repository_identity,
            "implementation_commit": self.implementation_commit,
            "closure_version": self.closure_version,
            "entrypoint_paths": self.entrypoint_paths,
            "dynamic_dependency_paths": self.dynamic_dependency_paths,
            "source_blobs": tuple(item.canonical_payload() for item in self.source_blobs),
        }

    def validate(self) -> bool:
        try:
            return ExecutionSourceManifestV3.from_payload(self.canonical_payload()).manifest_hash == self.manifest_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ExecutionSourceManifestV3":
        values = dict(payload)
        values["entrypoint_paths"] = tuple(values["entrypoint_paths"])
        values["dynamic_dependency_paths"] = tuple(values.get("dynamic_dependency_paths", ()))
        values["source_blobs"] = tuple(ExecutionSourceBlobV3(**item) for item in values["source_blobs"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class EnvironmentManifestV3:
    """Stable, comparable environment identity; it excludes host-local noise."""

    schema_version: str
    python_implementation: str
    python_version: str
    platform_system: str
    platform_machine: str
    dependency_source_hashes: Mapping[str, str]
    packages: tuple[tuple[str, str], ...]
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        package_rows = tuple(sorted((str(name).lower(), str(version)) for name, version in self.packages))
        if (
            self.schema_version != "genesis-m7-h3-environment-manifest-v1"
            or not self.python_implementation
            or not self.python_version
            or not self.platform_system
            or not self.platform_machine
            or not package_rows
            or len({name for name, _ in package_rows}) != len(package_rows)
            or any(not name or not version for name, version in package_rows)
        ):
            raise ValueError("genesis_h3_environment_manifest_invalid")
        object.__setattr__(self, "dependency_source_hashes", _mapping(
            self.dependency_source_hashes, "genesis_h3_environment_dependency_invalid",
        ))
        object.__setattr__(self, "packages", package_rows)
        object.__setattr__(self, "manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "platform_system": self.platform_system,
            "platform_machine": self.platform_machine,
            "dependency_source_hashes": self.dependency_source_hashes,
            "packages": self.packages,
        }

    def validate(self) -> bool:
        try:
            return EnvironmentManifestV3(**self.canonical_payload()).manifest_hash == self.manifest_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "EnvironmentManifestV3":
        values = dict(payload)
        values["packages"] = tuple(tuple(item) for item in values["packages"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class PriorExperimentExposureV3:
    """A disclosed V2 exposure that is explicitly ineligible for V3 aggregation."""

    schema_version: str
    prior_battery_hash: str
    prior_campaign_id: str
    prior_campaign_status: str
    admissibility: str
    excluded_from_v3_aggregate: bool
    reason: str
    excluded_artifact_hashes: tuple[str, ...]
    exposure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != "genesis-m7-h3-prior-exposure-v1"
            or self.prior_campaign_id != "m7h2-confirmatory-abs_affine-0"
            or self.admissibility != _V2_NONCONFIRMATORY
            or self.reason != _V2_RUNTIME_BOUND
            or self.excluded_from_v3_aggregate is not True
            or not self.prior_campaign_status
        ):
            raise ValueError("genesis_h3_prior_exposure_invalid")
        _require_hash(self.prior_battery_hash, "genesis_h3_prior_exposure_battery_invalid")
        object.__setattr__(self, "excluded_artifact_hashes", _hashes(
            self.excluded_artifact_hashes, "genesis_h3_prior_exposure_artifacts_invalid",
        ))
        if not self.excluded_artifact_hashes:
            raise ValueError("genesis_h3_prior_exposure_artifacts_missing")
        object.__setattr__(self, "exposure_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prior_battery_hash": self.prior_battery_hash,
            "prior_campaign_id": self.prior_campaign_id,
            "prior_campaign_status": self.prior_campaign_status,
            "admissibility": self.admissibility,
            "excluded_from_v3_aggregate": self.excluded_from_v3_aggregate,
            "reason": self.reason,
            "excluded_artifact_hashes": self.excluded_artifact_hashes,
        }

    def validate(self) -> bool:
        try:
            return PriorExperimentExposureV3(**self.canonical_payload()).exposure_hash == self.exposure_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PriorExperimentExposureV3":
        values = dict(payload)
        values["excluded_artifact_hashes"] = tuple(values["excluded_artifact_hashes"])
        return cls(**values)


class V3RunState(str, Enum):
    PLANNED = "PLANNED"
    STARTED = "STARTED"
    SEARCH_TERMINAL = "SEARCH_TERMINAL"
    CANDIDATE_COMMITTED = "CANDIDATE_COMMITTED"
    AUDIT_TERMINAL = "AUDIT_TERMINAL"
    PROMOTED = "PROMOTED"
    POST_PROMOTION_EVIDENCE = "POST_PROMOTION_EVIDENCE"
    CAMPAIGN_TERMINAL = "CAMPAIGN_TERMINAL"


class V3RecoveryAction(str, Enum):
    START = "START"
    RESTART_DETERMINISTIC_SEARCH = "RESTART_DETERMINISTIC_SEARCH"
    CONTINUE_WITH_COMMITTED_CANDIDATE = "CONTINUE_WITH_COMMITTED_CANDIDATE"
    REUSE_DURABLE_AUDIT = "REUSE_DURABLE_AUDIT"
    CONTINUE_POST_PROMOTION = "CONTINUE_POST_PROMOTION"
    COMPLETE_TERMINAL_EVIDENCE = "COMPLETE_TERMINAL_EVIDENCE"
    SKIP_TERMINAL_CAMPAIGN = "SKIP_TERMINAL_CAMPAIGN"


@dataclass(frozen=True, slots=True)
class RecoveryPolicyV3:
    schema_version: str
    state_order: tuple[str, ...]
    require_same_source_manifest: bool
    require_same_environment_manifest: bool
    audit_reconsumption_allowed: bool
    terminal_retry_allowed: bool
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        states = tuple(V3RunState(item).value for item in self.state_order)
        if (
            self.schema_version != "genesis-m7-h3-recovery-policy-v1"
            or states != tuple(item.value for item in V3RunState)
            or self.require_same_source_manifest is not True
            or self.require_same_environment_manifest is not True
            or self.audit_reconsumption_allowed is not False
            or self.terminal_retry_allowed is not False
        ):
            raise ValueError("genesis_h3_recovery_policy_invalid")
        object.__setattr__(self, "state_order", states)
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_order": self.state_order,
            "require_same_source_manifest": self.require_same_source_manifest,
            "require_same_environment_manifest": self.require_same_environment_manifest,
            "audit_reconsumption_allowed": self.audit_reconsumption_allowed,
            "terminal_retry_allowed": self.terminal_retry_allowed,
        }

    def validate(self) -> bool:
        try:
            return RecoveryPolicyV3(**self.canonical_payload()).policy_hash == self.policy_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def frozen(cls) -> "RecoveryPolicyV3":
        return cls(
            "genesis-m7-h3-recovery-policy-v1", tuple(item.value for item in V3RunState),
            True, True, False, False,
        )


@dataclass(frozen=True, slots=True)
class V3CampaignBinding:
    task_id: str
    campaign_id: str
    g0_snapshot_hash: str
    baseline_manifest_hash: str
    split_commitment_hashes: Mapping[str, str]
    split_seed_commitment_hashes: Mapping[str, str]
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.task_id not in _CANONICAL_TASKS or self.campaign_id != f"m7h3-confirmatory-{self.task_id}":
            raise ValueError("genesis_h3_campaign_identity_invalid")
        _require_hash(self.g0_snapshot_hash, "genesis_h3_campaign_g0_invalid")
        _require_hash(self.baseline_manifest_hash, "genesis_h3_campaign_baseline_invalid")
        splits = _mapping(self.split_commitment_hashes, "genesis_h3_campaign_split_invalid")
        seeds = _mapping(self.split_seed_commitment_hashes, "genesis_h3_campaign_seed_invalid")
        expected = {"TRAIN", "AUDIT", "HIDDEN", "TRANSFER"}
        if set(splits) != expected or set(seeds) != expected:
            raise ValueError("genesis_h3_campaign_split_invalid")
        object.__setattr__(self, "split_commitment_hashes", splits)
        object.__setattr__(self, "split_seed_commitment_hashes", seeds)
        object.__setattr__(self, "binding_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "campaign_id": self.campaign_id,
            "g0_snapshot_hash": self.g0_snapshot_hash,
            "baseline_manifest_hash": self.baseline_manifest_hash,
            "split_commitment_hashes": self.split_commitment_hashes,
            "split_seed_commitment_hashes": self.split_seed_commitment_hashes,
        }

    def validate(self) -> bool:
        try:
            return V3CampaignBinding(**self.canonical_payload()).binding_hash == self.binding_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V3CampaignBinding":
        return cls(**dict(payload))


@dataclass(frozen=True, slots=True)
class V3BatteryManifest:
    """The new battery identity; V2's historical hash cannot be substituted."""

    schema_version: str
    benchmark_manifest_hash: str
    dsl_hash: str
    search_semantics_id: str
    search_implementation_hash: str
    frontier_policy_hash: str
    acceptance_policy_hash: str
    target_frontier_audit_hash: str
    resource_estimate_hash: str
    c_star: int
    resource_policy_hash: str
    audit_policy_hash: str
    compositional_protocol_hash: str
    causal_protocol_hash: str
    m6_verification_policy_hash: str
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    recovery_policy_hash: str
    predecessor_v2_battery_hash: str
    prior_exposure_hash: str
    campaign_bindings: tuple[V3CampaignBinding, ...]
    execution_order: tuple[str, ...]
    battery_manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        bindings = tuple(sorted(self.campaign_bindings, key=lambda item: item.task_id))
        order = tuple(self.execution_order)
        if (
            self.schema_version != "genesis-m7-h3-confirmatory-battery-v3"
            or self.search_semantics_id != "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2"
            or self.c_star != 7
            or order != _CANONICAL_TASKS
            or tuple(item.task_id for item in bindings) != _CANONICAL_TASKS
            or not all(item.validate() for item in bindings)
            or len({item.campaign_id for item in bindings}) != len(bindings)
        ):
            raise ValueError("genesis_h3_battery_identity_invalid")
        for value in (
            self.benchmark_manifest_hash, self.dsl_hash, self.search_implementation_hash,
            self.frontier_policy_hash, self.acceptance_policy_hash, self.target_frontier_audit_hash,
            self.resource_estimate_hash, self.resource_policy_hash, self.audit_policy_hash,
            self.compositional_protocol_hash, self.causal_protocol_hash, self.m6_verification_policy_hash,
            self.execution_source_manifest_hash, self.environment_manifest_hash, self.recovery_policy_hash,
            self.predecessor_v2_battery_hash, self.prior_exposure_hash,
        ):
            _require_hash(value, "genesis_h3_battery_hash_invalid")
        object.__setattr__(self, "campaign_bindings", bindings)
        object.__setattr__(self, "execution_order", order)
        object.__setattr__(self, "battery_manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "dsl_hash": self.dsl_hash,
            "search_semantics_id": self.search_semantics_id,
            "search_implementation_hash": self.search_implementation_hash,
            "frontier_policy_hash": self.frontier_policy_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "target_frontier_audit_hash": self.target_frontier_audit_hash,
            "resource_estimate_hash": self.resource_estimate_hash,
            "c_star": self.c_star,
            "resource_policy_hash": self.resource_policy_hash,
            "audit_policy_hash": self.audit_policy_hash,
            "compositional_protocol_hash": self.compositional_protocol_hash,
            "causal_protocol_hash": self.causal_protocol_hash,
            "m6_verification_policy_hash": self.m6_verification_policy_hash,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "recovery_policy_hash": self.recovery_policy_hash,
            "predecessor_v2_battery_hash": self.predecessor_v2_battery_hash,
            "prior_exposure_hash": self.prior_exposure_hash,
            "campaign_bindings": tuple(item.canonical_payload() for item in self.campaign_bindings),
            "execution_order": self.execution_order,
        }

    def validate(self) -> bool:
        try:
            return V3BatteryManifest.from_payload(self.canonical_payload()).battery_manifest_hash == self.battery_manifest_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V3BatteryManifest":
        values = dict(payload)
        values["campaign_bindings"] = tuple(V3CampaignBinding.from_payload(item) for item in values["campaign_bindings"])
        values["execution_order"] = tuple(values["execution_order"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class GEIConfirmatoryPredeclarationV3:
    """The sole scientific object which an H3B launcher may load."""

    schema_version: str
    implementation_commit: str
    execution_source: ExecutionSourceManifestV3
    environment: EnvironmentManifestV3
    recovery_policy: RecoveryPolicyV3
    prior_exposure: PriorExperimentExposureV3
    battery: V3BatteryManifest
    predeclaration_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA
            or not self.execution_source.validate()
            or not self.environment.validate()
            or not self.recovery_policy.validate()
            or not self.prior_exposure.validate()
            or not self.battery.validate()
        ):
            raise ValueError("genesis_h3_predeclaration_invalid")
        _require_commit(self.implementation_commit, "genesis_h3_predeclaration_commit_invalid")
        if (
            self.implementation_commit != self.execution_source.implementation_commit
            or self.battery.execution_source_manifest_hash != self.execution_source.manifest_hash
            or self.battery.environment_manifest_hash != self.environment.manifest_hash
            or self.battery.recovery_policy_hash != self.recovery_policy.policy_hash
            or self.battery.prior_exposure_hash != self.prior_exposure.exposure_hash
            or self.battery.predecessor_v2_battery_hash != self.prior_exposure.prior_battery_hash
            or self.battery.battery_manifest_hash == self.prior_exposure.prior_battery_hash
        ):
            raise ValueError("genesis_h3_predeclaration_binding_invalid")
        object.__setattr__(self, "predeclaration_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "implementation_commit": self.implementation_commit,
            "execution_source": self.execution_source.canonical_payload(),
            "environment": self.environment.canonical_payload(),
            "recovery_policy": self.recovery_policy.canonical_payload(),
            "prior_exposure": self.prior_exposure.canonical_payload(),
            "battery": self.battery.canonical_payload(),
        }

    def validate(self) -> bool:
        try:
            return GEIConfirmatoryPredeclarationV3.from_payload(self.canonical_payload()).predeclaration_hash == self.predeclaration_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GEIConfirmatoryPredeclarationV3":
        values = dict(payload)
        values["execution_source"] = ExecutionSourceManifestV3.from_payload(values["execution_source"])
        values["environment"] = EnvironmentManifestV3.from_payload(values["environment"])
        values["recovery_policy"] = RecoveryPolicyV3(**values["recovery_policy"])
        values["prior_exposure"] = PriorExperimentExposureV3.from_payload(values["prior_exposure"])
        values["battery"] = V3BatteryManifest.from_payload(values["battery"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class V3ScientificDomain:
    """The fixed H2 scientific domain copied without importing V2 execution evidence."""

    benchmark_manifest_hash: str
    dsl_hash: str
    search_implementation_hash: str
    frontier_policy_hash: str
    acceptance_policy_hash: str
    target_frontier_audit_hash: str
    resource_estimate_hash: str
    audit_policy_hash: str
    compositional_protocol_hash: str
    causal_protocol_hash: str
    m6_verification_policy_hash: str
    v2_task_plans: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for value in (
            self.benchmark_manifest_hash, self.dsl_hash, self.search_implementation_hash,
            self.frontier_policy_hash, self.acceptance_policy_hash, self.target_frontier_audit_hash,
            self.resource_estimate_hash, self.audit_policy_hash, self.compositional_protocol_hash,
            self.causal_protocol_hash, self.m6_verification_policy_hash,
        ):
            _require_hash(value, "genesis_h3_scientific_domain_hash_invalid")
        plans = tuple(sorted((dict(item) for item in self.v2_task_plans), key=lambda item: str(item.get("task_id", ""))))
        if tuple(item.get("task_id") for item in plans) != _CANONICAL_TASKS:
            raise ValueError("genesis_h3_scientific_domain_tasks_invalid")
        for item in plans:
            if item.get("campaign_id") != f"m7h2-confirmatory-{item['task_id']}":
                raise ValueError("genesis_h3_scientific_domain_v2_identity_invalid")
            commitments = item.get("split_commitment_hashes")
            if not isinstance(commitments, Mapping):
                raise ValueError("genesis_h3_scientific_domain_splits_invalid")
            _mapping(commitments, "genesis_h3_scientific_domain_splits_invalid")
            if set(commitments) != {"TRAIN", "AUDIT", "HIDDEN", "TRANSFER"}:
                raise ValueError("genesis_h3_scientific_domain_splits_invalid")
        object.__setattr__(self, "v2_task_plans", plans)

    @classmethod
    def from_v2_launch_payload(cls, payload: Mapping[str, Any]) -> "V3ScientificDomain":
        """Extract only fixed domain facts from the preserved V2 launch record."""

        try:
            audit = dict(payload["h2a_audit"])
            estimate = dict(payload["h2a_estimate"])
            frontier = dict(payload["h2a_frontier"])
            policy = dict(payload["h2a_policy"])
            battery = dict(payload["h2a_battery"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("genesis_h3_scientific_domain_payload_invalid") from error
        # Each historical subobject is self-hashed here.  The R0 audit remains
        # the authority that classifies V2's own preregistration defect.
        if (
            canonical_sha256(audit) != battery.get("target_frontier_audit_hash")
            or canonical_sha256(estimate) != frontier.get("resource_estimate_hash")
            or canonical_sha256(frontier) != policy.get("complete_frontier_policy_hash")
            or canonical_sha256(policy) != battery.get("acceptance_policy_hash")
        ):
            raise ValueError("genesis_h3_scientific_domain_link_invalid")
        return cls(
            battery["canonical_benchmark_manifest_hash"], battery["dsl_hash"],
            battery["synthesizer_implementation_hash"], canonical_sha256(frontier),
            canonical_sha256(policy), canonical_sha256(audit), canonical_sha256(estimate),
            battery["audit_policy_hash"], battery["compositional_protocol_hash"],
            battery["causal_protocol_hash"], battery["m6_verification_policy_hash"],
            tuple(battery["task_plans"]),
        )


def materialize_v3_predeclaration(
    *, implementation_commit: str, execution_source: ExecutionSourceManifestV3,
    environment: EnvironmentManifestV3, domain: V3ScientificDomain,
    prior_exposure: PriorExperimentExposureV3,
) -> GEIConfirmatoryPredeclarationV3:
    """Derive the one V3 battery from committed source/environment and fixed domain facts."""

    if (
        not execution_source.validate() or not environment.validate() or not prior_exposure.validate()
        or implementation_commit != execution_source.implementation_commit
    ):
        raise ValueError("genesis_h3_materialization_input_invalid")
    bindings: list[V3CampaignBinding] = []
    for plan in domain.v2_task_plans:
        task_id = str(plan["task_id"])
        baseline = CapabilityManifest(
            f"m7h3-confirmatory-{task_id}-g0", "genesis-m7-confirmatory-g0-v3", (),
        )
        bindings.append(V3CampaignBinding(
            task_id, f"m7h3-confirmatory-{task_id}",
            canonical_sha256({"m7_h3_g0": baseline.manifest_hash, "task_id": task_id}),
            baseline.manifest_hash, plan["split_commitment_hashes"],
            {
                split: canonical_sha256({
                    "schema": "genesis-m7-h3-split-seed-v1", "task_id": task_id,
                    "split": split, "benchmark_manifest_hash": domain.benchmark_manifest_hash,
                })
                for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")
            },
        ))
    recovery = RecoveryPolicyV3.frozen()
    resource_policy_hash = canonical_sha256({
        "frontier_policy_hash": domain.frontier_policy_hash,
        "resource_estimate_hash": domain.resource_estimate_hash,
        "c_star": 7,
    })
    battery = V3BatteryManifest(
        "genesis-m7-h3-confirmatory-battery-v3", domain.benchmark_manifest_hash, domain.dsl_hash,
        "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2", domain.search_implementation_hash,
        domain.frontier_policy_hash, domain.acceptance_policy_hash, domain.target_frontier_audit_hash,
        domain.resource_estimate_hash, 7, resource_policy_hash, domain.audit_policy_hash,
        domain.compositional_protocol_hash, domain.causal_protocol_hash, domain.m6_verification_policy_hash,
        execution_source.manifest_hash, environment.manifest_hash, recovery.policy_hash,
        prior_exposure.prior_battery_hash, prior_exposure.exposure_hash, tuple(bindings), _CANONICAL_TASKS,
    )
    return GEIConfirmatoryPredeclarationV3(
        _SCHEMA, implementation_commit, execution_source, environment, recovery, prior_exposure, battery,
    )


@dataclass(frozen=True, slots=True)
class V3ExecutionLaunchReceipt:
    """Operational launch receipt derived entirely from the sealed object."""

    schema_version: str
    predeclaration_hash: str
    battery_manifest_hash: str
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    recovery_policy_hash: str
    execution_order: tuple[str, ...]
    authorization_commit: str
    sealed_predeclaration_path: str
    sealed_predeclaration_blob_hash: str
    artifact_root_identity: str
    launcher_implementation_hash: str
    launch_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != "genesis-m7-h3-execution-launch-v1"
            or tuple(self.execution_order) != _CANONICAL_TASKS
            or not self.artifact_root_identity
        ):
            raise ValueError("genesis_h3_launch_invalid")
        for value in (
            self.predeclaration_hash, self.battery_manifest_hash, self.execution_source_manifest_hash,
            self.environment_manifest_hash, self.recovery_policy_hash, self.launcher_implementation_hash,
        ):
            _require_hash(value, "genesis_h3_launch_hash_invalid")
        _require_commit(self.authorization_commit, "genesis_h3_launch_authorization_commit_invalid")
        _require_commit(self.sealed_predeclaration_blob_hash, "genesis_h3_launch_predeclaration_blob_invalid")
        object.__setattr__(self, "sealed_predeclaration_path", _relative_path(self.sealed_predeclaration_path))
        object.__setattr__(self, "execution_order", tuple(self.execution_order))
        object.__setattr__(self, "launch_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "predeclaration_hash": self.predeclaration_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "recovery_policy_hash": self.recovery_policy_hash,
            "execution_order": self.execution_order,
            "authorization_commit": self.authorization_commit,
            "sealed_predeclaration_path": self.sealed_predeclaration_path,
            "sealed_predeclaration_blob_hash": self.sealed_predeclaration_blob_hash,
            "artifact_root_identity": self.artifact_root_identity,
            "launcher_implementation_hash": self.launcher_implementation_hash,
        }


def prepare_v3_launch(*, predeclaration: GEIConfirmatoryPredeclarationV3, artifact_root_identity: str,
                      authorization_commit: str, sealed_predeclaration_path: str,
                      sealed_predeclaration_blob_hash: str) -> V3ExecutionLaunchReceipt:
    """Create no experiment state; derive a launch only from a sealed predeclaration."""

    if not predeclaration.validate():
        raise ValueError("genesis_h3_launch_predeclaration_invalid")
    return V3ExecutionLaunchReceipt(
        "genesis-m7-h3-execution-launch-v1", predeclaration.predeclaration_hash,
        predeclaration.battery.battery_manifest_hash, predeclaration.execution_source.manifest_hash,
        predeclaration.environment.manifest_hash, predeclaration.recovery_policy.policy_hash,
        predeclaration.battery.execution_order, authorization_commit, sealed_predeclaration_path,
        sealed_predeclaration_blob_hash, artifact_root_identity,
        canonical_sha256({"implementation": "genesis-m7-h3-launcher-v1", "loads": _SCHEMA}),
    )


def validate_v3_launch_environment(*, predeclaration: GEIConfirmatoryPredeclarationV3,
                                   observed: EnvironmentManifestV3) -> bool:
    """Reject environment drift before a launcher can create campaign state."""

    return (
        predeclaration.validate()
        and observed.validate()
        and observed.manifest_hash == predeclaration.environment.manifest_hash
    )


def load_sealed_predeclaration(path: str | Path, *, expected_hash: str) -> GEIConfirmatoryPredeclarationV3:
    """Load one canonical JSON preregistration; free scientific inputs do not exist."""

    _require_hash(expected_hash, "genesis_h3_loader_expected_hash_invalid")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        predeclaration = GEIConfirmatoryPredeclarationV3.from_payload(payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("genesis_h3_loader_payload_invalid") from error
    if not predeclaration.validate() or predeclaration.predeclaration_hash != expected_hash:
        raise ValueError("genesis_h3_loader_hash_mismatch")
    return predeclaration


def verify_sealed_predeclaration_provenance(
    *, predeclaration: GEIConfirmatoryPredeclarationV3, repo: str | Path,
    authorization_commit: str, sealed_predeclaration_path: str,
    git_dir: str | Path | None = None,
) -> str:
    """Verify the external C_SEAL authorization without a circular Git hash.

    The returned Git blob hash is operational provenance for the launch receipt.
    The sealed JSON itself commits only ``C_IMPL``.  This deliberately keeps the
    predeclaration content independent from the commit which stores it.
    """

    if not predeclaration.validate():
        raise ValueError("genesis_h3_seal_predeclaration_invalid")
    _require_commit(authorization_commit, "genesis_h3_seal_authorization_commit_invalid")
    relative = _relative_path(sealed_predeclaration_path)
    root = Path(repo)
    try:
        if not _git_ok(root, ["merge-base", "--is-ancestor", predeclaration.implementation_commit,
                              authorization_commit], git_dir=git_dir):
            raise ValueError("genesis_h3_seal_not_descendant_of_implementation")
        committed = subprocess.run(
            _git_command(root, ["show", f"{authorization_commit}:{relative}"], git_dir=git_dir),
            capture_output=True, check=False,
        )
        if committed.returncode:
            raise ValueError("genesis_h3_seal_predeclaration_missing")
        local = (root / relative).read_bytes()
        if committed.stdout != local or canonical_sha256(json.loads(local)) != predeclaration.predeclaration_hash:
            raise ValueError("genesis_h3_seal_predeclaration_blob_mismatch")
        blob_hash = _git(root, ["rev-parse", f"{authorization_commit}:{relative}"], git_dir=git_dir)
        if not verify_execution_source_manifest(
            manifest=predeclaration.execution_source, repo=root,
            authorization_commit=authorization_commit, git_dir=git_dir,
        ):
            raise ValueError("genesis_h3_seal_execution_source_mismatch")
        return blob_hash
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and str(error).startswith("genesis_h3_seal_"):
            raise
        raise ValueError("genesis_h3_seal_provenance_invalid") from error


def reject_prior_v2_evidence(*, predeclaration: GEIConfirmatoryPredeclarationV3, campaign_id: str, artifact_hashes: Iterable[str]) -> None:
    """Reject V2 identity laundering even where task outputs happen to coincide."""

    if campaign_id.startswith("m7h2-confirmatory-") or campaign_id == predeclaration.prior_exposure.prior_campaign_id:
        raise ValueError("genesis_h3_v2_campaign_reuse_rejected")
    artifacts = set(str(item) for item in artifact_hashes)
    if artifacts & set(predeclaration.prior_exposure.excluded_artifact_hashes):
        raise ValueError("genesis_h3_v2_evidence_reuse_rejected")


@dataclass(frozen=True, slots=True)
class V3RunLedgerEvent:
    schema_version: str
    battery_manifest_hash: str
    campaign_id: str
    launch_hash: str
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    sequence: int
    state: V3RunState
    previous_event_hash: str | None
    artifact_hashes: tuple[str, ...]
    terminal_status: str | None = None
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", V3RunState(self.state))
        if (
            self.schema_version != "genesis-m7-h3-run-ledger-event-v1"
            or not self.campaign_id
            or not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ValueError("genesis_h3_ledger_event_invalid")
        for value in (self.battery_manifest_hash, self.launch_hash, self.execution_source_manifest_hash, self.environment_manifest_hash):
            _require_hash(value, "genesis_h3_ledger_event_hash_invalid")
        if self.previous_event_hash is not None:
            _require_hash(self.previous_event_hash, "genesis_h3_ledger_previous_invalid")
        artifacts = _hashes(self.artifact_hashes, "genesis_h3_ledger_artifacts_invalid")
        if self.state is V3RunState.CAMPAIGN_TERMINAL and self.terminal_status not in {"SUPPORTED", "FAIL", "NOT_PROVEN"}:
            raise ValueError("genesis_h3_ledger_terminal_invalid")
        if self.state is not V3RunState.CAMPAIGN_TERMINAL and self.terminal_status is not None:
            raise ValueError("genesis_h3_ledger_terminal_invalid")
        object.__setattr__(self, "artifact_hashes", artifacts)
        object.__setattr__(self, "event_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "battery_manifest_hash": self.battery_manifest_hash,
            "campaign_id": self.campaign_id,
            "launch_hash": self.launch_hash,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "sequence": self.sequence,
            "state": self.state.value,
            "previous_event_hash": self.previous_event_hash,
            "artifact_hashes": self.artifact_hashes,
            "terminal_status": self.terminal_status,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V3RunLedgerEvent":
        values = dict(payload)
        values["artifact_hashes"] = tuple(values["artifact_hashes"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class RecoveryReceiptV3:
    schema_version: str
    battery_manifest_hash: str
    campaign_id: str
    original_launch_hash: str
    recovery_launch_hash: str
    last_event_hash: str | None
    last_state: V3RunState
    irreversible_artifact_hashes: tuple[str, ...]
    allowed_action: V3RecoveryAction
    execution_source_manifest_hash: str
    environment_manifest_hash: str
    reason: str
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != "genesis-m7-h3-recovery-receipt-v1" or not self.campaign_id or not self.reason:
            raise ValueError("genesis_h3_recovery_receipt_invalid")
        for value in (
            self.battery_manifest_hash, self.original_launch_hash, self.recovery_launch_hash,
            self.execution_source_manifest_hash, self.environment_manifest_hash,
        ):
            _require_hash(value, "genesis_h3_recovery_receipt_hash_invalid")
        if self.last_event_hash is not None:
            _require_hash(self.last_event_hash, "genesis_h3_recovery_receipt_last_event_invalid")
        object.__setattr__(self, "last_state", V3RunState(self.last_state))
        object.__setattr__(self, "allowed_action", V3RecoveryAction(self.allowed_action))
        object.__setattr__(self, "irreversible_artifact_hashes", _hashes(
            self.irreversible_artifact_hashes, "genesis_h3_recovery_receipt_artifacts_invalid",
        ))
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "battery_manifest_hash": self.battery_manifest_hash,
            "campaign_id": self.campaign_id,
            "original_launch_hash": self.original_launch_hash,
            "recovery_launch_hash": self.recovery_launch_hash,
            "last_event_hash": self.last_event_hash,
            "last_state": self.last_state.value,
            "irreversible_artifact_hashes": self.irreversible_artifact_hashes,
            "allowed_action": self.allowed_action.value,
            "execution_source_manifest_hash": self.execution_source_manifest_hash,
            "environment_manifest_hash": self.environment_manifest_hash,
            "reason": self.reason,
        }


_ALLOWED_TRANSITIONS = {
    None: V3RunState.PLANNED,
    V3RunState.PLANNED: V3RunState.STARTED,
    V3RunState.STARTED: V3RunState.SEARCH_TERMINAL,
    V3RunState.SEARCH_TERMINAL: V3RunState.CANDIDATE_COMMITTED,
    V3RunState.CANDIDATE_COMMITTED: V3RunState.AUDIT_TERMINAL,
    V3RunState.AUDIT_TERMINAL: V3RunState.PROMOTED,
    V3RunState.PROMOTED: V3RunState.POST_PROMOTION_EVIDENCE,
    V3RunState.POST_PROMOTION_EVIDENCE: V3RunState.CAMPAIGN_TERMINAL,
}


class V3RunLedger:
    """Append-only, campaign-local ledger for a predeclared recovery state machine."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _directory(self, campaign_id: str) -> Path:
        if not campaign_id or "/" in campaign_id or "\\" in campaign_id:
            raise ValueError("genesis_h3_ledger_campaign_path_invalid")
        return self.root / campaign_id

    def read(self, campaign_id: str) -> tuple[V3RunLedgerEvent, ...]:
        directory = self._directory(campaign_id)
        if not directory.exists():
            return ()
        events: list[V3RunLedgerEvent] = []
        for path in sorted(directory.glob("*.event.json")):
            try:
                event = V3RunLedgerEvent.from_payload(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError("genesis_h3_ledger_read_invalid") from error
            if path.name != f"{event.sequence:08d}-{event.event_hash}.event.json":
                raise ValueError("genesis_h3_ledger_filename_invalid")
            events.append(event)
        previous: str | None = None
        state: V3RunState | None = None
        for sequence, event in enumerate(events):
            if (
                event.sequence != sequence
                or event.previous_event_hash != previous
                or _ALLOWED_TRANSITIONS.get(state) is not event.state
            ):
                raise ValueError("genesis_h3_ledger_chain_invalid")
            previous, state = event.event_hash, event.state
        return tuple(events)

    def append(self, event: V3RunLedgerEvent) -> V3RunLedgerEvent:
        events = self.read(event.campaign_id)
        if events and events[-1].event_hash == event.event_hash:
            return event
        previous = events[-1].event_hash if events else None
        state = events[-1].state if events else None
        if (
            event.sequence != len(events)
            or event.previous_event_hash != previous
            or _ALLOWED_TRANSITIONS.get(state) is not event.state
        ):
            raise ValueError("genesis_h3_ledger_transition_invalid")
        directory = self._directory(event.campaign_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{event.sequence:08d}-{event.event_hash}.event.json"
        data = canonical_json_bytes(event.canonical_payload())
        if destination.exists():
            if destination.read_bytes() != data:
                raise ValueError("genesis_h3_ledger_event_conflict")
            return event
        temporary = directory / f".{event.event_hash}.{uuid4().hex}.pending"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                # A concurrent publisher won the create-only race.  Its
                # payload may only be accepted when it is byte-identical.
                if destination.read_bytes() != data:
                    raise ValueError("genesis_h3_ledger_event_conflict")
            return event
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _validate_recovery_events(*, predeclaration: GEIConfirmatoryPredeclarationV3,
                              launch: V3ExecutionLaunchReceipt, campaign_id: str,
                              events: Sequence[V3RunLedgerEvent]) -> tuple[V3RunLedgerEvent, ...]:
    """Reject a syntactically valid journal from a different V3 identity."""

    items = tuple(events)
    previous: str | None = None
    state: V3RunState | None = None
    for sequence, item in enumerate(items):
        if (
            item.campaign_id != campaign_id
            or item.battery_manifest_hash != predeclaration.battery.battery_manifest_hash
            or item.launch_hash != launch.launch_hash
            or item.execution_source_manifest_hash != predeclaration.execution_source.manifest_hash
            or item.environment_manifest_hash != predeclaration.environment.manifest_hash
            or item.sequence != sequence
            or item.previous_event_hash != previous
            or _ALLOWED_TRANSITIONS.get(state) is not item.state
        ):
            raise ValueError("genesis_h3_recovery_event_binding_invalid")
        previous, state = item.event_hash, item.state
    return items


def recovery_receipt(*, predeclaration: GEIConfirmatoryPredeclarationV3, launch: V3ExecutionLaunchReceipt,
                     events: Sequence[V3RunLedgerEvent], campaign_id: str, reason: str) -> RecoveryReceiptV3:
    """Derive a continuation action; it never permits a scientific retry."""

    if (
        not predeclaration.validate()
        or launch.predeclaration_hash != predeclaration.predeclaration_hash
        or launch.battery_manifest_hash != predeclaration.battery.battery_manifest_hash
        or launch.execution_source_manifest_hash != predeclaration.execution_source.manifest_hash
        or launch.environment_manifest_hash != predeclaration.environment.manifest_hash
        or campaign_id not in {item.campaign_id for item in predeclaration.battery.campaign_bindings}
    ):
        raise ValueError("genesis_h3_recovery_binding_invalid")
    items = _validate_recovery_events(
        predeclaration=predeclaration, launch=launch, campaign_id=campaign_id, events=events,
    )
    last = items[-1] if items else None
    state = V3RunState.PLANNED if last is None else last.state
    action = {
        V3RunState.PLANNED: V3RecoveryAction.START,
        V3RunState.STARTED: V3RecoveryAction.RESTART_DETERMINISTIC_SEARCH,
        V3RunState.SEARCH_TERMINAL: V3RecoveryAction.CONTINUE_WITH_COMMITTED_CANDIDATE,
        V3RunState.CANDIDATE_COMMITTED: V3RecoveryAction.CONTINUE_WITH_COMMITTED_CANDIDATE,
        V3RunState.AUDIT_TERMINAL: V3RecoveryAction.REUSE_DURABLE_AUDIT,
        V3RunState.PROMOTED: V3RecoveryAction.CONTINUE_POST_PROMOTION,
        V3RunState.POST_PROMOTION_EVIDENCE: V3RecoveryAction.COMPLETE_TERMINAL_EVIDENCE,
        V3RunState.CAMPAIGN_TERMINAL: V3RecoveryAction.SKIP_TERMINAL_CAMPAIGN,
    }[state]
    artifacts = () if last is None else last.artifact_hashes
    return RecoveryReceiptV3(
        "genesis-m7-h3-recovery-receipt-v1", predeclaration.battery.battery_manifest_hash,
        campaign_id, launch.launch_hash, launch.launch_hash, None if last is None else last.event_hash,
        state, artifacts, action, predeclaration.execution_source.manifest_hash,
        predeclaration.environment.manifest_hash, reason,
    )


def capture_environment_manifest(*, dependency_sources: Mapping[str, Path]) -> EnvironmentManifestV3:
    """Capture comparable package facts without hostname, PID, time or absolute paths."""

    try:
        from importlib.metadata import distributions
        packages = tuple(sorted(
            (str(dist.metadata["Name"]).lower(), str(dist.version))
            for dist in distributions() if dist.metadata.get("Name")
        ))
    except Exception as error:  # pragma: no cover - environment discovery failure is explicit.
        raise ValueError("genesis_h3_environment_packages_unavailable") from error
    source_hashes: dict[str, str] = {}
    for relative, source in dependency_sources.items():
        source_hashes[_relative_path(relative)] = canonical_sha256({"bytes": Path(source).read_bytes().hex()})
    return EnvironmentManifestV3(
        "genesis-m7-h3-environment-manifest-v1", sys.implementation.name,
        platform.python_version(), platform.system(), platform.machine(), source_hashes, packages,
    )


def _module_to_path(root: Path, module: str) -> Path | None:
    relative = Path(*module.split("."))
    candidate = root / f"{relative}.py"
    if candidate.is_file():
        return candidate
    package = root / relative / "__init__.py"
    return package if package.is_file() else None


def _package_initializers(root: Path, relative: str) -> tuple[str, ...]:
    """Return package initializers Python executes before loading ``relative``."""

    path = PurePosixPath(relative)
    directories = path.parts[:-1]
    result: list[str] = []
    for index in range(1, len(directories) + 1):
        initializer = PurePosixPath(*directories[:index], "__init__.py").as_posix()
        if (root / initializer).is_file():
            result.append(initializer)
    return tuple(result)


def _relative_import_module(relative: str, node: ast.ImportFrom) -> str | None:
    """Resolve a local relative import without consulting the live interpreter."""

    if not node.level:
        return node.module
    package = list(PurePosixPath(relative).parts[:-1])
    # ``from .x`` remains in the current package; each additional dot climbs.
    climb = node.level - 1
    if climb > len(package):
        return None
    base = package[:len(package) - climb]
    return ".".join((*base, *(node.module or "").split("."))).strip(".")


def discover_execution_source_paths(repo: str | Path, *, entrypoints: Sequence[str]) -> tuple[str, ...]:
    """Derive the statically reachable repository-owned Python closure.

    This includes package initializers because Python executes them before a
    submodule.  A closure which omitted ``acquisition/__init__.py`` would be
    unsound: importing one V3 submodule executes its public package surface.
    """

    root = Path(repo)
    pending = [_relative_path(item) for item in entrypoints]
    discovered: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in discovered:
            continue
        path = root / relative
        if not path.is_file():
            raise ValueError("genesis_h3_source_entrypoint_missing")
        discovered.add(relative)
        pending.extend(_package_initializers(root, relative))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.ImportFrom):
                module = _relative_import_module(relative, node)
                if module is not None and not module.startswith("lab.genesis"):
                    module = None
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("lab.genesis"):
                        candidate = _module_to_path(root, alias.name)
                        if candidate is not None:
                            pending.append(candidate.relative_to(root).as_posix())
            if module:
                candidate = _module_to_path(root, module)
                if candidate is not None:
                    pending.append(candidate.relative_to(root).as_posix())
    return tuple(sorted(discovered))


def audit_dynamic_local_dependencies(repo: str | Path, *, source_paths: Sequence[str]) -> tuple[str, ...]:
    """Audit dynamic imports in the sealed surface.

    Literal repository-local imports are returned as explicit dependencies.
    A computed module name at an import primitive is deliberately a blocker:
    allowing it would make the source surface runtime-bound again.
    """

    root = Path(repo)
    dynamic: set[str] = set()
    for relative in source_paths:
        path = root / _relative_path(relative)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            dynamic_primitive = (
                isinstance(function, ast.Name) and function.id == "__import__"
            ) or (
                isinstance(function, ast.Attribute) and function.attr == "import_module"
            )
            if not dynamic_primitive:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                raise ValueError("genesis_h3_dynamic_import_reachability_unknown")
            module = node.args[0].value
            if module.startswith("lab.genesis"):
                dependency = _module_to_path(root, module)
                if dependency is None:
                    raise ValueError("genesis_h3_dynamic_import_local_missing")
                dynamic.add(dependency.relative_to(root).as_posix())
    return tuple(sorted(dynamic))


def validate_runtime_import_witness(*, manifest: ExecutionSourceManifestV3,
                                    runtime_local_paths: Iterable[str]) -> None:
    """Make an observed local import outside the sealed surface fatal.

    Parent and child runners contribute normalized repository-relative paths to
    the same witness.  The witness is a backstop for static closure, never an
    authority that can enlarge a predeclaration after launch.
    """

    if not manifest.validate():
        raise ValueError("genesis_h3_runtime_witness_manifest_invalid")
    observed = {_relative_path(item) for item in runtime_local_paths}
    sealed = {item.path for item in manifest.source_blobs}
    omitted = tuple(sorted(observed - sealed))
    if omitted:
        raise ValueError(f"genesis_h3_source_closure_incomplete:{','.join(omitted)}")


def _git_command(repo: Path, args: Sequence[str], *, git_dir: str | Path | None = None) -> list[str]:
    command = ["git"]
    if git_dir is not None:
        command.append(f"--git-dir={git_dir}")
        command.append(f"--work-tree={repo}")
    else:
        command.extend(["-C", str(repo)])
    return command + list(args)


def _git(repo: Path, args: Sequence[str], *, git_dir: str | Path | None = None) -> str:
    completed = subprocess.run(_git_command(repo, args, git_dir=git_dir), text=True, capture_output=True, check=False)
    if completed.returncode:
        raise ValueError(f"genesis_h3_git_invalid:{completed.stderr.strip()}")
    return completed.stdout.strip()


def _git_ok(repo: Path, args: Sequence[str], *, git_dir: str | Path | None = None) -> bool:
    return subprocess.run(_git_command(repo, args, git_dir=git_dir), text=True, capture_output=True, check=False).returncode == 0


def execution_source_manifest_from_git(*, repo: str | Path, implementation_commit: str,
                                       entrypoints: Sequence[str], git_dir: str | Path | None = None) -> ExecutionSourceManifestV3:
    """Materialize source blobs from immutable Git objects at ``C_IMPL``."""

    _require_commit(implementation_commit, "genesis_h3_source_commit_invalid")
    root = Path(repo)
    paths = discover_execution_source_paths(root, entrypoints=entrypoints)
    dynamic = audit_dynamic_local_dependencies(root, source_paths=paths)
    blobs = tuple(ExecutionSourceBlobV3(path, _git(root, ["rev-parse", f"{implementation_commit}:{path}"], git_dir=git_dir)) for path in paths)
    return ExecutionSourceManifestV3(
        "genesis-m7-h3-execution-source-manifest-v1", "RNFE_V16_GENESIS",
        implementation_commit, tuple(entrypoints), blobs,
        dynamic_dependency_paths=dynamic,
    )


def verify_execution_source_manifest(*, manifest: ExecutionSourceManifestV3, repo: str | Path,
                                     authorization_commit: str, git_dir: str | Path | None = None) -> bool:
    """Require blobs to be identical at C_IMPL and C_SEAL, and unmodified locally."""

    if not manifest.validate():
        return False
    try:
        _require_commit(authorization_commit, "genesis_h3_authorization_commit_invalid")
        root = Path(repo)
        for item in manifest.source_blobs:
            if (
                _git(root, ["rev-parse", f"{manifest.implementation_commit}:{item.path}"], git_dir=git_dir) != item.blob_hash
                or _git(root, ["rev-parse", f"{authorization_commit}:{item.path}"], git_dir=git_dir) != item.blob_hash
            ):
                return False
        paths = [item.path for item in manifest.source_blobs]
        return (
            _git_ok(root, ["diff", "--quiet", manifest.implementation_commit, authorization_commit, "--", *paths], git_dir=git_dir)
            and _git_ok(root, ["diff", "--quiet", "--", *paths], git_dir=git_dir)
            and _git_ok(root, ["diff", "--cached", "--quiet", "--", *paths], git_dir=git_dir)
        )
    except (OSError, ValueError):
        return False
