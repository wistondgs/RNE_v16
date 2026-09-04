"""Sealed M7 benchmark with a deliberately narrow learner-facing boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import random
from types import MappingProxyType
from typing import Any, Mapping

from lab.genesis.acquisition.contracts import ProgramSkillArtifact
from lab.genesis.acquisition.dsl import DSLSpecification, evaluate_expression, validate_program_skill
from lab.genesis.contracts.serialization import canonical_sha256, freeze


class TaskFamily(str, Enum):
    AFFINE = "AFFINE"
    ABS_AFFINE = "ABS_AFFINE"
    QUADRATIC_SIMPLE = "QUADRATIC_SIMPLE"


class DatasetSplit(str, Enum):
    TRAIN = "TRAIN"
    AUDIT = "AUDIT"
    HIDDEN = "HIDDEN"
    TRANSFER = "TRANSFER"

class CompositionWrapper(str, Enum):
    ADD_ONE = "ADD_ONE"
    NEGATE = "NEGATE"
    ABS = "ABS"


@dataclass(frozen=True, slots=True)
class Example:
    input_value: int
    output_value: int
    def canonical_payload(self) -> dict[str, int]: return {"input_value": self.input_value, "output_value": self.output_value}


@dataclass(frozen=True, slots=True)
class BenchmarkTaskDescriptor:
    task_id: str
    family: TaskFamily
    split_commitments: Mapping[str, str]
    descriptor_hash: str = field(init=False)
    def __post_init__(self) -> None:
        object.__setattr__(self, "family", TaskFamily(self.family)); values=freeze({str(k):str(v) for k,v in self.split_commitments.items()})
        if set(values)!={item.value for item in DatasetSplit} or len(set(values.values()))!=4 or any(len(v)!=64 for v in values.values()): raise ValueError("genesis_benchmark_split_commitments_invalid")
        object.__setattr__(self,"split_commitments",values);object.__setattr__(self,"descriptor_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"task_id":self.task_id,"family":self.family.value,"split_commitments":self.split_commitments}


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    schema_version: str
    dsl_hash: str
    generator_implementation_hash: str
    seed_commitment_hash: str
    tasks: tuple[BenchmarkTaskDescriptor, ...]
    manifest_hash: str = field(init=False)
    def __post_init__(self)->None:
        object.__setattr__(self,"tasks",tuple(sorted(self.tasks,key=lambda x:x.task_id)))
        if len({x.task_id for x in self.tasks})!=len(self.tasks) or len(self.tasks)<6: raise ValueError("genesis_benchmark_tasks_invalid")
        object.__setattr__(self,"manifest_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"schema_version":self.schema_version,"dsl_hash":self.dsl_hash,"generator_implementation_hash":self.generator_implementation_hash,"seed_commitment_hash":self.seed_commitment_hash,"tasks":tuple(x.canonical_payload() for x in self.tasks)}


@dataclass(frozen=True, slots=True)
class LearnerTrainingView:
    """The only data object passed into a synthesizer in M7-v1."""
    task_id: str
    training_examples: tuple[Example, ...]
    training_commitment_hash: str
    def __post_init__(self)->None: object.__setattr__(self,"training_examples",tuple(self.training_examples))


@dataclass(frozen=True, slots=True)
class SplitEvaluation:
    task_id: str; split: DatasetSplit; candidate_skill_hash: str; exact_pass: bool; total: int; correct: int; evaluation_context: str="DIRECT"; result_hash: str=field(init=False)
    def __post_init__(self)->None: object.__setattr__(self,"split",DatasetSplit(self.split));object.__setattr__(self,"result_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self)->dict[str,Any]: return {"task_id":self.task_id,"split":self.split.value,"candidate_skill_hash":self.candidate_skill_hash,"exact_pass":self.exact_pass,"total":self.total,"correct":self.correct,"evaluation_context":self.evaluation_context}


@dataclass(frozen=True, slots=True)
class _SealedTask:
    descriptor: BenchmarkTaskDescriptor; target_ast: Mapping[str,Any]; datasets: Mapping[DatasetSplit,tuple[Example,...]]
    def __post_init__(self)->None:
        object.__setattr__(self,"target_ast",freeze(self.target_ast))
        datasets={DatasetSplit(split):tuple(examples) for split,examples in self.datasets.items()}
        if set(datasets)!=set(DatasetSplit): raise ValueError("genesis_benchmark_datasets_invalid")
        object.__setattr__(self,"datasets",MappingProxyType(datasets))


class AuditAccess:
    """A one-shot handle only obtainable after an explicit candidate commitment."""
    def __init__(self, benchmark:"SealedCapabilityBenchmark", task_id:str, candidate:ProgramSkillArtifact)->None: self._benchmark=benchmark;self._task_id=task_id;self._candidate=candidate;self._used=False
    def evaluate_once(self)->SplitEvaluation:
        if self._used: raise ValueError("genesis_benchmark_audit_already_consumed")
        self._used=True; return self._benchmark._evaluate(self._task_id,DatasetSplit.AUDIT,self._candidate)


class SealedCapabilityBenchmark:
    def __init__(self, specification:DSLSpecification, tasks:tuple[_SealedTask,...], manifest:BenchmarkManifest)->None:
        self.specification=specification;self.manifest=manifest;self._tasks={x.descriptor.task_id:x for x in tasks}
        if not self.validate(): raise ValueError("genesis_benchmark_invalid")
    def learner_view(self,task_id:str)->LearnerTrainingView:
        task=self._tasks[task_id]; return LearnerTrainingView(task_id,task.datasets[DatasetSplit.TRAIN],task.descriptor.split_commitments[DatasetSplit.TRAIN.value])
    def commit_candidate(self,task_id:str,candidate:ProgramSkillArtifact)->AuditAccess:
        if task_id not in self._tasks or not validate_program_skill(candidate,self.specification): raise ValueError("genesis_benchmark_candidate_invalid")
        return AuditAccess(self,task_id,candidate)
    def evaluate_hidden(self,task_id:str,candidate:ProgramSkillArtifact)->SplitEvaluation: return self._evaluate(task_id,DatasetSplit.HIDDEN,candidate)
    def evaluate_transfer(self,task_id:str,candidate:ProgramSkillArtifact)->SplitEvaluation: return self._evaluate(task_id,DatasetSplit.TRANSFER,candidate)
    def evaluate_compositional(self,task_id:str,candidate:ProgramSkillArtifact,wrapper:CompositionWrapper)->SplitEvaluation:
        if not validate_program_skill(candidate,self.specification): raise ValueError("genesis_benchmark_candidate_invalid")
        transform={CompositionWrapper.ADD_ONE:lambda x:x+1,CompositionWrapper.NEGATE:lambda x:-x,CompositionWrapper.ABS:abs}[CompositionWrapper(wrapper)]
        examples=self._tasks[task_id].datasets[DatasetSplit.TRANSFER];correct=sum(transform(evaluate_expression(candidate.program_ast,x.input_value,self.specification))==transform(x.output_value) for x in examples)
        return SplitEvaluation(task_id,DatasetSplit.TRANSFER,candidate.skill_hash,correct==len(examples),len(examples),correct,f"COMPOSITION:{CompositionWrapper(wrapper).value}")
    def _evaluate(self,task_id:str,split:DatasetSplit,candidate:ProgramSkillArtifact)->SplitEvaluation:
        if not validate_program_skill(candidate,self.specification): raise ValueError("genesis_benchmark_candidate_invalid")
        examples=self._tasks[task_id].datasets[split];correct=sum(evaluate_expression(candidate.program_ast,x.input_value,self.specification)==x.output_value for x in examples)
        return SplitEvaluation(task_id,split,candidate.skill_hash,correct==len(examples),len(examples),correct)
    def validate(self)->bool:
        if not self.specification.validate() or self.manifest.dsl_hash!=self.specification.dsl_hash or set(self._tasks)!={x.task_id for x in self.manifest.tasks}: return False
        signatures=set()
        for descriptor in self.manifest.tasks:
            task=self._tasks[descriptor.task_id];seen=set()
            for split,examples in task.datasets.items():
                if {x.input_value for x in examples}&seen:return False
                seen|={x.input_value for x in examples}
                if canonical_sha256(tuple(x.canonical_payload() for x in examples))!=descriptor.split_commitments[split.value]:return False
                if any(evaluate_expression(task.target_ast,x.input_value,self.specification)!=x.output_value for x in examples):return False
            signature=tuple(evaluate_expression(task.target_ast,x,self.specification) for x in range(-12,13))
            if signature in signatures:return False
            signatures.add(signature)
        return True


def _node(op:str,*args:Mapping[str,Any],value:int|None=None)->dict[str,Any]:
    node={"op":op,"args":tuple(args)}
    if value is not None: node["value"]=value
    return node


def _target(family:TaskFamily,a:int,b:int,c:int=0)->Mapping[str,Any]:
    x=_node("X")
    affine=_node("ADD",_node("MUL_CONST",x,value=a),_node("CONST",value=b))
    if family is TaskFamily.AFFINE:return affine
    if family is TaskFamily.ABS_AFFINE:return _node("ADD",_node("ABS",affine),_node("CONST",value=c))
    return _node("ADD",_node("MUL_CONST",_node("SQUARE",x),value=a),_node("CONST",value=b))


def canonical_benchmark(specification:DSLSpecification, *, seed:int) -> SealedCapabilityBenchmark:
    """Build six deterministic, semantically nonduplicate sealed tasks."""
    rng=random.Random(seed);inputs={DatasetSplit.TRAIN:(-3,-2,-1,0,1,2,3),DatasetSplit.AUDIT:(-6,-5,4,5,6),DatasetSplit.HIDDEN:(-10,-8,-7,7,8,10),DatasetSplit.TRANSFER:(30,31,32,33,34)}
    tasks=[];seen=set()
    for family in TaskFamily:
        for index in range(2):
            while True:
                a=rng.choice((-2,-1,1,2));b=rng.choice(specification.allowed_constants);c=rng.choice((0,1,2))
                target=_target(family,a,b,c);signature=tuple(evaluate_expression(target,x,specification) for x in range(-12,13))
                if signature not in seen: seen.add(signature);break
            datasets={split:tuple(Example(x,evaluate_expression(target,x,specification)) for x in values) for split,values in inputs.items()}
            commitments={split.value:canonical_sha256(tuple(item.canonical_payload() for item in examples)) for split,examples in datasets.items()}
            descriptor=BenchmarkTaskDescriptor(f"{family.value.lower()}-{index}",family,commitments);tasks.append(_SealedTask(descriptor,freeze(target),datasets))
    manifest=BenchmarkManifest("genesis-m7-benchmark-v1",specification.dsl_hash,canonical_sha256({"implementation":"m7-benchmark-generator-v1"}),canonical_sha256({"seed":seed}),tuple(x.descriptor for x in tasks))
    return SealedCapabilityBenchmark(specification,tuple(tasks),manifest)
