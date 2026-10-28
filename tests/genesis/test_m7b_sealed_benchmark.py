"""M7-B benchmark isolation and sealing gates."""
from __future__ import annotations

import pytest

from lab.genesis.acquisition.benchmark import DatasetSplit, Example, canonical_benchmark
from lab.genesis.acquisition.contracts import ProgramSkillArtifact
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.contracts.serialization import canonical_sha256


def h(label: str) -> str: return canonical_sha256({"m7b-benchmark": label})

def spec() -> DSLSpecification:
    return DSLSpecification("genesis-m7-dsl-spec-v1", "genesis-m7-dsl-v1", (-2,-1,0,1,2,3), 5, 12, 10000)

def candidate() -> ProgramSkillArtifact:
    return ProgramSkillArtifact("genesis-m7-program-skill-v1", "FINITE_INTEGER_FUNCTION", "genesis-m7-dsl-v1", {"kind":"integer"}, {"kind":"integer"}, {"op":"X","args":()}, {"node_count":1,"ast_depth":1}, ("X",), h("campaign"), (h("train"),))

def test_canonical_campaign_has_six_nonduplicate_tasks_and_disjoint_splits() -> None:
    first=canonical_benchmark(spec(),seed=17);second=canonical_benchmark(spec(),seed=17)
    assert first.manifest.manifest_hash==second.manifest.manifest_hash
    assert len(first.manifest.tasks)==6 and {item.family.value for item in first.manifest.tasks}=={"AFFINE","ABS_AFFINE","QUADRATIC_SIMPLE"}
    assert first.validate()
    for task in first._tasks.values():
        inputs=[{example.input_value for example in task.datasets[split]} for split in DatasetSplit]
        assert all(left.isdisjoint(right) for index,left in enumerate(inputs) for right in inputs[index+1:])

def test_learner_boundary_exposes_train_only_and_audit_is_one_shot_after_commitment() -> None:
    benchmark=canonical_benchmark(spec(),seed=17);view=benchmark.learner_view("affine-0")
    assert view.training_examples and not hasattr(view,"target_ast") and not hasattr(view,"audit_examples") and not hasattr(view,"hidden_examples") and not hasattr(view,"transfer_examples")
    assert not hasattr(benchmark,"evaluate_audit")
    access=benchmark.commit_candidate("affine-0",candidate())
    result=access.evaluate_once()
    assert result.split is DatasetSplit.AUDIT and result.total>0
    with pytest.raises(ValueError,match="already_consumed"): access.evaluate_once()

def test_hidden_and_transfer_are_evaluator_only_results_and_dataset_tamper_fails_closed() -> None:
    benchmark=canonical_benchmark(spec(),seed=17);skill=candidate()
    assert benchmark.evaluate_hidden("affine-0",skill).split is DatasetSplit.HIDDEN
    assert benchmark.evaluate_transfer("affine-0",skill).split is DatasetSplit.TRANSFER
    task=benchmark._tasks["affine-0"]
    with pytest.raises(TypeError): task.datasets[DatasetSplit.TRAIN]=(Example(-3,999),)  # type: ignore[index]
    object.__setattr__(task,"datasets",{**task.datasets,DatasetSplit.TRAIN:(Example(-3,999),)})
    assert not benchmark.validate()
