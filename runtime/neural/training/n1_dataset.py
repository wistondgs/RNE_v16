"""Construccion reproducible del dataset contrafactual N1.

No convierte ``family_delta_*`` historicos en causalidad.  Solo acepta pares
que comparten estado inicial/generador/semilla y difieren en la activacion de
una familia, con resultados persistidos del episodio.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


OUTCOME_FIELDS = ("reward", "closure", "certified", "continuity")


@dataclass(frozen=True, slots=True)
class CounterfactualSample:
    pair_id: str
    context_key: str
    scenario_generator: str
    seed: int
    family: str
    features: Mapping[str, float]
    utility_delta: float
    positive_utility: bool
    closure_delta: float
    certification_delta: float
    continuity_delta: float


@dataclass(frozen=True, slots=True)
class DatasetQualityReport:
    total_records: int
    valid_pairs: int
    unique_contexts: int
    generators: int
    families: tuple[str, ...]
    rejected_records: int

    def training_ready(
        self,
        *,
        min_pairs: int = 300,
        min_unique_contexts: int = 50,
        min_generators: int = 3,
    ) -> bool:
        return bool(
            self.valid_pairs >= min_pairs
            and self.unique_contexts >= min_unique_contexts
            and self.generators >= min_generators
            and len(self.families) >= 3
        )


class CounterfactualDatasetBuilder:
    def __init__(self, *, utility_weights: Mapping[str, float] | None = None):
        self.utility_weights = dict(
            utility_weights
            or {"reward": 0.40, "closure": 0.25, "certified": 0.20, "continuity": 0.15}
        )

    def build(
        self, records: Iterable[Mapping[str, Any]]
    ) -> tuple[list[CounterfactualSample], DatasetQualityReport]:
        raw_records = [dict(record) for record in records]
        groups: dict[tuple[str, str, int, str], dict[bool, Mapping[str, Any]]] = {}
        rejected = 0
        for record in raw_records:
            try:
                normalized = self._validate_record(record)
            except (KeyError, TypeError, ValueError):
                rejected += 1
                continue
            key = (
                normalized["context_key"],
                normalized["scenario_generator"],
                normalized["seed"],
                normalized["family"],
            )
            branch = bool(normalized["family_enabled"])
            if branch in groups.setdefault(key, {}):
                rejected += 1
                continue
            groups[key][branch] = normalized

        samples = []
        for key, branches in sorted(groups.items()):
            if set(branches) != {False, True}:
                rejected += len(branches)
                continue
            off, on = branches[False], branches[True]
            if (
                off["initial_state_hash"] != on["initial_state_hash"]
                or off["features"] != on["features"]
            ):
                rejected += 2
                continue
            deltas = {
                field: float(on[field]) - float(off[field])
                for field in OUTCOME_FIELDS
            }
            utility = sum(self.utility_weights[field] * deltas[field] for field in OUTCOME_FIELDS)
            pair_material = "|".join(str(item) for item in key)
            samples.append(
                CounterfactualSample(
                    pair_id=hashlib.sha256(pair_material.encode("utf-8")).hexdigest(),
                    context_key=key[0],
                    scenario_generator=key[1],
                    seed=key[2],
                    family=key[3],
                    features=dict(off["features"]),
                    utility_delta=utility,
                    positive_utility=utility > 0.0,
                    closure_delta=deltas["closure"],
                    certification_delta=deltas["certified"],
                    continuity_delta=deltas["continuity"],
                )
            )
        report = DatasetQualityReport(
            total_records=len(raw_records),
            valid_pairs=len(samples),
            unique_contexts=len({sample.context_key for sample in samples}),
            generators=len({sample.scenario_generator for sample in samples}),
            families=tuple(sorted({sample.family for sample in samples})),
            rejected_records=rejected,
        )
        return samples, report

    def split(
        self, samples: Iterable[CounterfactualSample]
    ) -> dict[str, list[CounterfactualSample]]:
        splits = {"train": [], "validation": [], "test": []}
        assignments: dict[tuple[str, int], str] = {}
        for sample in samples:
            group = (sample.scenario_generator, sample.seed)
            if group not in assignments:
                bucket = int(hashlib.sha256(f"{group[0]}|{group[1]}".encode()).hexdigest()[:8], 16) % 10
                assignments[group] = "train" if bucket < 7 else "validation" if bucket < 9 else "test"
            splits[assignments[group]].append(sample)
        return splits

    def _validate_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if any(str(key).startswith("family_delta_") for key in record):
            raise ValueError("heuristic_family_delta_is_not_a_causal_label")
        normalized = {
            "context_key": str(record["context_key"]),
            "scenario_generator": str(record["scenario_generator"]),
            "seed": int(record["seed"]),
            "family": str(record["family"]).upper(),
            "family_enabled": _strict_bool(record["family_enabled"]),
            "initial_state_hash": str(record["initial_state_hash"]),
            "features": {str(key): float(value) for key, value in dict(record["features"]).items()},
        }
        for field in OUTCOME_FIELDS:
            normalized[field] = float(record[field])
        if not all(
            normalized[field]
            for field in ("context_key", "scenario_generator", "family", "initial_state_hash")
        ):
            raise ValueError("n1_pair_identity_is_required")
        return normalized


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError("family_enabled_must_be_boolean")
