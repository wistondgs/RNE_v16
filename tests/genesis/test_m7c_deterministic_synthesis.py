"""M7-C bounded deterministic TRAIN-only program synthesis gates."""
from __future__ import annotations

import inspect

from lab.genesis.acquisition.benchmark import Example, LearnerTrainingView, canonical_benchmark
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest, CANDIDATE_RANKING_RULE, CapabilityManifest, HUMAN_INTERVENTION_POLICY, PROMOTION_RULE
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer
from lab.genesis.contracts.serialization import canonical_sha256

def h(value:str)->str:return canonical_sha256({"m7c":value})
def spec()->DSLSpecification:return DSLSpecification("m7","genesis-m7-dsl-v1",(-2,-1,0,1,2,3),5,12,10000)
def campaign(specification:DSLSpecification,budget:int)->AcquisitionCampaignManifest:
    g0=CapabilityManifest("g0","m7",())
    return AcquisitionCampaignManifest("campaign","m7",h("snapshot"),g0.manifest_hash,specification.dsl_hash,h("synth"),{key:h(key) for key in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},h("generator"),{key:h("seed"+key) for key in ("TRAIN","AUDIT","HIDDEN","TRANSFER")},{"max_candidates":budget},5,12,specification.allowed_constants,tuple(x.value for x in specification.operators),CANDIDATE_RANKING_RULE,PROMOTION_RULE,h("cfi"),h("resource"),30,HUMAN_INTERVENTION_POLICY,(h("obligation"),))

def test_synthesis_is_repeatable_and_only_accepts_a_training_view() -> None:
    definition=spec();benchmark=canonical_benchmark(definition,seed=17);view=benchmark.learner_view("affine-0");runner=DeterministicProgramSynthesizer();first=runner.synthesize(campaign=campaign(definition,256),specification=definition,training=view);second=runner.synthesize(campaign=campaign(definition,256),specification=definition,training=view)
    assert first.receipt.synthesis_hash==second.receipt.synthesis_hash and first.selected_skill.skill_hash==second.selected_skill.skill_hash and first.training_error==0
    assert tuple(inspect.signature(runner.synthesize).parameters)==("campaign","specification","training")

def test_mdl_prefers_identity_for_identity_training_data() -> None:
    definition=spec();view=LearnerTrainingView("identity",tuple(Example(x,x) for x in (-2,-1,0,1,2)),h("train"))
    outcome=DeterministicProgramSynthesizer().synthesize(campaign=campaign(definition,64),specification=definition,training=view)
    assert outcome.training_error==0 and outcome.selected_skill.program_ast["op"]=="X" and outcome.receipt.candidates_examined<=64

def test_budget_exhaustion_is_explicit_and_never_promotes_a_partial_fit() -> None:
    definition=spec();view=canonical_benchmark(definition,seed=17).learner_view("affine-0")
    outcome=DeterministicProgramSynthesizer().synthesize(campaign=campaign(definition,1),specification=definition,training=view)
    assert outcome.selected_skill is None and outcome.receipt.selected_skill_hash is None and outcome.receipt.termination.value=="BUDGET_EXHAUSTED"
