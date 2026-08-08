from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from runtime.symbolic.mci import (
    Justification,
    MCIRuntime,
    NeuralHypothesis,
    TransitionCompiler,
    TransitionEvidence,
    thermal_spec,
)


ROOT = Path(__file__).parents[2]
SOURCE_SHA256 = {
    "runtime/symbolic/schemas.py": "bf6b50b73d9759fa91fbd204c48f53e5dc0e2f8aa66e0626c4b066bc71100d6a",
    "runtime/symbolic/mci/__init__.py": "389614cf2013c7e16b4385a586b77273e17760c9b9be340c6a0ed2e0fc7651fb",
    "runtime/symbolic/mci/conditions.py": "39a8585e2882d6d41b4be3d2d3718e0f1c5b266e7aef529f23c58cd2cc2d041e",
    "runtime/symbolic/mci/contracts.py": "6bd40fe4647ce6bc19d36108084b2f9514a1766eefeff96ffd3016fb5e1f610a",
    "runtime/symbolic/mci/compiler.py": "259c40fa8a122a55abe5e8f9e863b6cfa944c3ce42243e90bbb26e1d7b5dd777",
    "runtime/symbolic/mci/specs.py": "26463a6e2f8d8ddde448eb1ae234efb93eabd3ff3622bcd579491ec98728b31e",
    "runtime/symbolic/mci/causal_learning.py": "0f2ec475ffcaaa74384acbcefe8bbba022b6d32605d5522ac7ef786b8401c329",
    "runtime/symbolic/mci/hypothesis_ledger.py": "68bba7040f9a615504e89e143a1ee503f94ccf192cfb6ad3915af4fc3049d89f",
    "runtime/symbolic/mci/hypothesis_mapping.py": "ef88e79565f6cc65b07301331e26ee94efa51f8cae671b5790ba2c2a0a408d63",
    "runtime/symbolic/mci/provider_protocol.py": "e403227e5cdfce7859d13f355d51c6c04a26a3c1d6def90c23e3a7f3f946ef23",
    "runtime/symbolic/mci/jtms.py": "c900ddbbd2aee5aaed2305e1a355aa1701e1b628fbcc7e28d33987cd3c4ab1e9",
    "runtime/symbolic/mci/planner.py": "3b3baf359a282fced2e92619ce99db8b97bb4343b854537178d8a7fd8bcfdc0b",
    "runtime/symbolic/mci/regime_detector.py": "b7b7c9a1ea55e12b12e213141eef84af4e9ed168b8acdc003a3aadd1d1eabf1c",
    "runtime/symbolic/mci/self_model.py": "c9fedea64c55720655ec0a5ec97f4789cf7fe752073e02ab39f48ce4e3945186",
    "runtime/symbolic/mci/runtime.py": "956879652bb6323edb78a92accde8e5617057b2cb0c3604077b365829897be82",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_production_files_remain_byte_identical_to_source():
    assert {path: _sha256(ROOT / path) for path in SOURCE_SHA256} == SOURCE_SHA256


def test_transition_evidence_identity_is_stable_and_content_addressed():
    state = {"temperature": 0.8, "cooling_active": False, "alarm": False}
    observed = {"temperature": 0.7, "cooling_active": True, "alarm": False}
    predicted = {"temperature": 0.73, "cooling_active": True, "alarm": False}
    first = TransitionEvidence(
        state, "activate_cooling", 0.0, observed, predicted,
        replay_unit_id="compat/evidence", logical_time=2,
    )
    replay = TransitionEvidence(
        state, "activate_cooling", 0.0, observed, predicted,
        replay_unit_id="compat/evidence", logical_time=2,
    )
    changed = TransitionEvidence(
        state, "activate_cooling", 0.0, {**observed, "temperature": 0.69}, predicted,
        replay_unit_id="compat/evidence", logical_time=2,
    )

    assert replay.evidence_id == first.evidence_id
    assert changed.evidence_id != first.evidence_id


def test_core_imports_and_executes_when_runtime_neural_is_blocked():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('runtime.neural'):
            raise ImportError('runtime.neural blocked by compatibility gate')
        return None
sys.meta_path.insert(0, Block())
from runtime.symbolic.mci import TransitionCompiler, thermal_spec
assert TransitionCompiler(thermal_spec()).execute(
    {'temperature': .8, 'cooling_active': False, 'alarm': False},
    action='activate_cooling', external_input=0.0,
)['temperature'] < .8
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_excluded_subsystems_and_historical_wiring_are_absent():
    excluded = (
        "boundary_detector.py", "rollout_engine.py", "safety_contracts.py",
        "overlay_translator.py", "known_mappings.py", "scales.py",
        "structural_morphism.py", "transfer_ledger.py", "transfer_package.py",
    )
    assert not any((ROOT / "runtime/symbolic/mci" / name).exists() for name in excluded)
    scenario_source = (ROOT / "runtime/world/scenario_runner.py").read_text()
    assert "runtime.symbolic.mci" not in scenario_source
    assert "MCIRuntime" not in scenario_source


def test_mci_has_no_factual_authority_or_experience_dependency():
    source = "\n".join(path.read_text() for path in (ROOT / "runtime/symbolic/mci").glob("*.py"))
    forbidden = (
        "runtime.neural", "ExperienceRecord", "ExperienceStore", "MemoryRecord",
        "CanonicalOutcomeAuthority", "_issue_canonical_outcome_authority",
        "write_canonical_experience", "organism.life_transition.committed",
    )
    assert all(token not in source for token in forbidden)
    ea1_source = "\n".join(path.read_text() for path in (ROOT / "runtime/experiments/ea1").glob("*.py"))
    assert "observe_outcome(" not in ea1_source


def _restore_jtms(runtime: MCIRuntime, snapshot: dict[str, object]) -> None:
    beliefs = snapshot["beliefs"]
    justifications = snapshot["justifications"]
    assert isinstance(beliefs, list) and isinstance(justifications, list)
    for item in beliefs:
        assert isinstance(item, dict) and item["status"] == "IN"
        runtime.ledger.add_belief(
            belief_id=str(item["belief_id"]), proposition=str(item["proposition"]),
            confidence=float(item["confidence"]), logical_time=int(item["logical_time"]),
        )
    for item in justifications:
        assert isinstance(item, dict)
        runtime.ledger.justify(
            Justification(
                justification_id=str(item["justification_id"]),
                antecedent_ids=tuple(item["antecedent_ids"]),
                consequence_id=str(item["consequence_id"]), kind=str(item["kind"]),
            )
        )


def test_snapshot_reload_preserves_effective_model_ledgers_and_planner_use():
    base = thermal_spec()
    learned_effect = float(base.parameters["cooling_effect"]) * 1.5
    runtime = MCIRuntime(base)
    state = {"temperature": 0.8, "cooling_active": False, "alarm": False}
    promoted = None
    for episode in range(16):
        predicted = TransitionCompiler(runtime.learner.active_spec).execute(
            state, action="activate_cooling", external_input=0.0
        )
        observed = {**predicted, "temperature": state["temperature"] - learned_effect}
        promoted = runtime.learner.observe(
            TransitionEvidence(
                state, "activate_cooling", 0.0, observed, predicted,
                replay_unit_id=f"compat/{episode}", logical_time=episode * 2 + 2,
            )
        ) or promoted
    assert promoted is not None and runtime.learner.active_overlay is not None

    hypothesis = NeuralHypothesis(
        hypothesis_id="compatibility-hypothesis", kind="parameter",
        target_id="cooling_effect", expression=None, proposed_value=learned_effect,
        confidence=0.8, evidence_refs=(), provider="compatibility-test",
        model_ref="historical-core", logical_time=40,
    )
    assert runtime.learner.hypothesis_ledger.submit(hypothesis)
    runtime.propose(state=state, external_input=0.0, logical_time=41, regime="compat")

    overlay_snapshot = runtime.learner.active_overlay.to_dict()
    hypothesis_snapshot = runtime.learner.hypothesis_ledger.snapshot()
    jtms_snapshot = runtime.ledger.snapshot()
    before_plan = runtime.evaluate_plan_sequence(
        state, actions=("activate_cooling",), external_input=0.0
    )

    restored = MCIRuntime(base)
    restored.restore_overlay(overlay_snapshot)
    restored.restore_hypothesis_ledger(hypothesis_snapshot)
    _restore_jtms(restored, jtms_snapshot)

    assert restored.learner.active_spec.sha256 == runtime.learner.active_spec.sha256
    assert restored.learner.active_overlay == runtime.learner.active_overlay
    assert restored.learner.hypothesis_ledger.snapshot() == hypothesis_snapshot
    assert restored.ledger.snapshot() == jtms_snapshot
    after_plan = restored.evaluate_plan_sequence(
        state, actions=("activate_cooling",), external_input=0.0
    )
    baseline_plan = MCIRuntime(base).evaluate_plan_sequence(
        state, actions=("activate_cooling",), external_input=0.0
    )
    assert after_plan == before_plan
    assert after_plan.projected_states != baseline_plan.projected_states
