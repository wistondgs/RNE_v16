from pathlib import Path

from runtime.control.msrc import ScaleAction, ScaleAuditLogger, ScaleDecisionRecord, ScaleEstimate, ScaleTransitionRecord
from runtime.storage import StorageConfig, StorageFactory


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "msrc_audit.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=False,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def _estimate() -> ScaleEstimate:
    return ScaleEstimate(
        required_resolution_score=0.6,
        heterogeneity_score=0.4,
        epistemic_insufficiency_score=0.3,
        risk_score=0.4,
        operational_pressure_score=0.2,
        vram_headroom=0.6,
        vram_pressure=0.4,
        vram_fragmentation_risk=0.1,
        vram_opportunity_score=0.7,
        recommended_scale_candidates=["5x5"],
        signals={},
    )


def test_scale_audit_logger_writes_events_and_jsonl(tmp_path: Path):
    storage = _storage(tmp_path)
    logger = ScaleAuditLogger(storage=storage, output_dir=tmp_path / "audit")

    decision = ScaleDecisionRecord(
        run_id="run-audit",
        episode_id="ep-1",
        step_index=1,
        current_scale_id="1x1",
        action=ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="need detail"),
        estimate=_estimate(),
        selected_scale_id="5x5",
        timestamp="2026-04-20T00:00:00Z",
        metadata={},
    )
    logger.log_decision(decision)

    transition = ScaleTransitionRecord(
        run_id="run-audit",
        episode_id="ep-1",
        action_type="upgrade_scale",
        source_scale_id="1x1",
        target_scale_id="5x5",
        reason="need detail",
        estimated_time_cost=2.2,
        estimated_artifact_cost=2.2,
        real_time_cost=50.0,
        real_artifact_cost=1.8,
        ioc_delta=0.2,
        viability_delta=0.0,
        transition_aborted=False,
        timestamp="2026-04-20T00:00:00Z",
        metadata={},
    )
    logger.log_transition(transition)
    # El alias legacy sigue disponible para los consumidores vivos que lo leen.
    assert transition.rollback_applied is False
    assert transition.to_dict()["rollback_applied"] is False

    events = storage.list_events(run_id="run-audit", limit=50)
    event_types = [e.event_type for e in events]
    assert "msrc.decision" in event_types
    assert "msrc.transition" in event_types

    decisions_file = tmp_path / "audit" / "scale_decisions.jsonl"
    events_file = tmp_path / "audit" / "scale_events.jsonl"
    assert decisions_file.exists()
    assert events_file.exists()
    assert decisions_file.read_text().strip() != ""
    assert events_file.read_text().strip() != ""

    storage.close()
