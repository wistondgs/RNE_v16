"""H2B1 noncanonical end-to-end fixture.

This deliberately shares no campaign ID, AUDIT root or CAS root with the
predeclared battery.  It proves that downstream M5/M6 consumers receive a V2
source receipt rather than a synthetic V1 receipt.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lab.genesis.acquisition.audit import DurableAuditClaimRegistry
from lab.genesis.acquisition.battery import predeclare_confirmatory_battery
from lab.genesis.acquisition.benchmark import TaskBenchmarkBinding, canonical_benchmark
from lab.genesis.acquisition.campaign import PriorInsufficiencyReceipt
from lab.genesis.acquisition.causal_experiments import materialize_causal_capability_attribution
from lab.genesis.acquisition.causal_replay import persist_causal_capability_attribution
from lab.genesis.acquisition.complete_frontier import (
    audit_target_class_frontier,
    complete_frontier_acceptance_policy_v2,
    complete_frontier_search_policy_v2,
    estimate_complete_frontier_resources,
    predeclare_complete_frontier_battery_v2,
)
from lab.genesis.acquisition.composition import (
    compositional_transfer_protocol_commitment,
    confirmatory_compositional_transfer_protocol,
)
from lab.genesis.acquisition.confirmation import confirmatory_policy
from lab.genesis.acquisition.contracts import PromotionStatus
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.ranked_synthesis import ranked_search_policy
from lab.genesis.acquisition.v2_campaign import (
    V2AcquisitionResult,
    V2ConfirmatoryCampaignManifest,
    V2GEICampaignAttestation,
    V2SynthesisOutcome,
    _placebo_for_v2,
    _promotion,
    _skill_from_v2_outcome,
    _v2_commitment,
    materialize_v2_compositional_transfer_evidence,
    materialize_v2_capability_arm_evidence,
    materialize_v2_promoted_skill_evidence,
    replay_v2_causal_capability_attribution,
    validate_v2_candidate_commitment,
)
from lab.genesis.acquisition.v2_execution import (
    V2ExecutionBinding,
    replay_v2_fixture_execution,
    run_v2_fixture_execution,
)
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.trace_persistence import replay_m6_trace


def h(value: object) -> str:
    return canonical_sha256({"m7h2b1-fixture": value})


def h2a_inputs():
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000,
    )
    benchmark = canonical_benchmark(specification, seed=17)
    v1 = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("audit"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    protocol = confirmatory_compositional_transfer_protocol(policy=v1, evaluation_policy_hash=h("composition"))
    v1_battery = predeclare_confirmatory_battery(
        policy=v1, protocol=protocol, benchmark=benchmark,
        code_snapshot_hash=h("v1-code"), environment_commitment_hash=h("v1-env"),
    )
    audit = audit_target_class_frontier(benchmark)
    estimate = estimate_complete_frontier_resources(audit=audit, specification=specification, benchmark=benchmark)
    frontier = complete_frontier_search_policy_v2(
        audit=audit, estimate=estimate, specification=specification, benchmark=benchmark,
    )
    policy = complete_frontier_acceptance_policy_v2(
        benchmark=benchmark, audit=audit, frontier_policy=frontier, estimate=estimate,
        predecessor_v1_policy=v1, predecessor_v1_battery=v1_battery,
    )
    battery = predeclare_complete_frontier_battery_v2(
        acceptance_policy=policy, frontier_policy=frontier, estimate=estimate, audit=audit,
        benchmark=benchmark, predecessor_v1_policy=v1, predecessor_v1_battery=v1_battery,
        code_snapshot_hash=h("v2-code"), environment_commitment_hash=h("v2-env"),
    )
    return benchmark, policy, battery, frontier


class H2B1V2EndToEndFixtureTest(unittest.TestCase):
    def test_noncanonical_fixture_keeps_v2_receipt_through_downstream_gates(self) -> None:
        benchmark, policy, battery, frontier = h2a_inputs()
        task_id = "affine-0"
        plan = battery.plan_for(task_id)
        campaign = V2ConfirmatoryCampaignManifest(
            "genesis-m7-v2-confirmatory-campaign-h2b1-fixture", "fixture-v2-affine-0", task_id,
            h("fixture-g0"), plan.baseline.manifest_hash, benchmark.manifest.manifest_hash,
            benchmark.specification.dsl_hash, plan.split_commitment_hashes,
            plan.split_seed_commitment_hashes, policy.policy_hash, battery.battery_manifest_hash,
            frontier.policy_hash, battery.target_frontier_audit_hash, battery.causal_protocol_hash,
            frontier.synthesizer_implementation_hash, frontier.search_semantics_id,
            4, benchmark.specification.max_ast_depth, 4, 10_000, 10_000, 30, 1024,
            "no_interactive_corrective_selection-v1",
        )
        binding = TaskBenchmarkBinding(
            "genesis-m7-v2-fixture-task-binding-h2b1", campaign.campaign_hash,
            benchmark.manifest.manifest_hash, task_id, plan.split_commitment_hashes,
        )
        engine = ranked_search_policy(
            specification=benchmark.specification, policy_id="m7h2b1-fixture-engine",
            max_ast_nodes=4, max_ast_depth=benchmark.specification.max_ast_depth,
            max_raw_ast_evaluations=10_000, max_distinct_behaviors=10_000,
            wall_time_limit_seconds=30,
        )
        execution = V2ExecutionBinding(
            "genesis-m7-v2-execution-binding-h2b1-fixture", campaign.campaign_id, task_id,
            campaign.campaign_hash, binding.binding_hash, policy.policy_hash,
            battery.battery_manifest_hash, frontier.policy_hash, engine, benchmark.specification.dsl_hash,
            frontier.search_semantics_id, "genesis-m7-rank-canonical-enumerative-synthesizer-v2",
            frontier.synthesizer_implementation_hash, 4, benchmark.specification.max_ast_depth, 4,
            10_000, 10_000, 30, 1024, "H2B1_NONCANONICAL_FIXTURE",
        )
        training = benchmark.learner_view(task_id)
        outcome = run_v2_fixture_execution(
            binding=execution, specification=benchmark.specification, training=training,
            test_v1_synthesis_tripwire=True,
        )
        self.assertIsNotNone(outcome.selected_candidate)
        self.assertEqual(outcome.receipt.schema_version, "genesis-m7-v2-synthesis-execution-receipt-h2b0")
        candidate = _skill_from_v2_outcome(campaign=campaign, benchmark=benchmark, outcome=outcome)
        assert candidate is not None
        commitment = _v2_commitment(campaign=campaign, training=training, outcome=outcome, candidate=candidate)
        self.assertTrue(validate_v2_candidate_commitment(
            commitment=commitment, campaign=campaign, training=training, outcome=outcome, candidate=candidate,
        ))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            durable = DurableAuditClaimRegistry(root / "fixture-audit", policy=policy).evaluate(
                campaign=campaign, task_binding=binding, commitment=commitment,
                evaluate_once=lambda: benchmark.commit_candidate(task_id, candidate).evaluate_once(),
            )
            promotion, successor = _promotion(
                campaign=campaign, baseline=plan.baseline, commitment=commitment,
                receipt_hash=outcome.receipt.receipt_hash, candidate=candidate, audit=durable.audit,
            )
            self.assertIs(promotion.status, PromotionStatus.PROMOTED)
            assert successor is not None
            result = V2AcquisitionResult(
                prior=PriorInsufficiencyReceipt(
                    "genesis-m7-v2-fixture-prior", campaign.campaign_hash, task_id,
                    plan.baseline.manifest_hash, None, 0, len(training.training_examples), "PASS", "fixture",
                ),
                synthesis=V2SynthesisOutcome(outcome.receipt, candidate), execution=outcome,
                commitment=commitment, audit=durable.audit, promotion=promotion, g1_manifest=successor,
                task_benchmark_binding=binding, durable_audit=durable, execution_binding=execution,
            )
            store = ContentAddressedArtifactStore(root / "fixture-cas")
            hidden = materialize_v2_promoted_skill_evidence(
                campaign=campaign, baseline=plan.baseline, benchmark=benchmark, task_id=task_id,
                binding=binding, execution_binding=execution, result=result, split="HIDDEN",
            )
            transfer = materialize_v2_promoted_skill_evidence(
                campaign=campaign, baseline=plan.baseline, benchmark=benchmark, task_id=task_id,
                binding=binding, execution_binding=execution, result=result, split="TRANSFER",
            )
            protocol = confirmatory_compositional_transfer_protocol(policy=policy, evaluation_policy_hash=h("v2-composition"))
            composition = materialize_v2_compositional_transfer_evidence(
                policy=policy, protocol=protocol, campaign=campaign, baseline=plan.baseline,
                benchmark=benchmark, task_id=task_id, binding=binding, execution_binding=execution, result=result,
            )
            placebo, placebo_commitment = _placebo_for_v2(campaign=campaign, benchmark=benchmark, binding=binding)
            causal = materialize_causal_capability_attribution(
                campaign=campaign, baseline=plan.baseline, benchmark=benchmark, task_id=task_id,
                acquisition=result, placebo=placebo, placebo_commitment=placebo_commitment,
                arm_evidence_materializer=materialize_v2_capability_arm_evidence,
            )
            self.assertTrue(hidden.adjudication.verdict.value == "PASS")
            self.assertTrue(transfer.adjudication.verdict.value == "PASS")
            self.assertTrue(composition.validate())
            self.assertTrue(causal.validate())
            hidden_trace = hidden.persist_trace(store)
            transfer_trace = transfer.persist_trace(store)
            composition_traces = tuple(item.persist_trace(store) for item in composition.measurements)
            causal_persistence = persist_causal_capability_attribution(store, causal, benchmark=benchmark)
            self.assertTrue(replay_m6_trace(store, hidden_trace.closure_hash).admitted)
            self.assertTrue(replay_m6_trace(store, transfer_trace.closure_hash).admitted)
            self.assertTrue(all(replay_m6_trace(store, item.closure_hash).admitted for item in composition_traces))
            causal_replay = replay_v2_causal_capability_attribution(store, causal_persistence.manifest_hash)
            self.assertTrue(causal_replay.admitted, causal_replay.reasons)
            attestation = V2GEICampaignAttestation(
                policy, battery, campaign, plan.baseline, benchmark, binding, execution, result,
                hidden, transfer, composition, causal,
                (hidden_trace, transfer_trace, *composition_traces), causal_persistence,
            )
            assessment = attestation.assess(store)
            self.assertEqual(
                assessment.status.value,
                "GE_I_CAMPAIGN_SUPPORTED",
                {key: value.value for key, value in assessment.gates.items() if value.value != "PASS"},
            )
            replayed = replay_v2_fixture_execution(
                binding=execution, specification=benchmark.specification, training=training, outcome=outcome,
            )
            self.assertEqual(replayed.receipt.semantic_payload(), outcome.receipt.semantic_payload())


if __name__ == "__main__":
    unittest.main()
