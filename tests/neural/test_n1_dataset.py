from runtime.neural.training import CounterfactualDatasetBuilder


def _record(enabled: bool, *, seed=1, generator="grid", context="ctx", family="IND"):
    return {
        "context_key": context,
        "scenario_generator": generator,
        "seed": seed,
        "family": family,
        "family_enabled": enabled,
        "initial_state_hash": "same-state",
        "features": {"pressure": 0.2, "uncertainty": 0.7},
        "reward": 0.8 if enabled else 0.5,
        "closure": 1.0,
        "certified": 1.0 if enabled else 0.0,
        "continuity": 0.9 if enabled else 0.8,
    }


def test_n1_builder_requires_real_paired_ablation_and_grouped_split() -> None:
    builder = CounterfactualDatasetBuilder()
    samples, report = builder.build([_record(False), _record(True)])
    assert report.valid_pairs == 1
    assert samples[0].positive_utility is True
    split = builder.split(samples)
    assert sum(len(values) for values in split.values()) == 1
    assert report.training_ready() is False


def test_n1_builder_rejects_historical_proxy_as_causal_label() -> None:
    bad = _record(False)
    bad["family_delta_reward"] = 0.3
    _, report = CounterfactualDatasetBuilder().build([bad, _record(True)])
    assert report.valid_pairs == 0
    assert report.rejected_records == 2


def test_n1_builder_rejects_ambiguous_boolean_and_unpaired_features() -> None:
    ambiguous = _record(False)
    ambiguous["family_enabled"] = "false"
    _, ambiguous_report = CounterfactualDatasetBuilder().build([ambiguous, _record(True)])
    assert ambiguous_report.valid_pairs == 0

    off = _record(False)
    on = _record(True)
    on["features"] = {"pressure": 0.9, "uncertainty": 0.7}
    _, mismatch_report = CounterfactualDatasetBuilder().build([off, on])
    assert mismatch_report.valid_pairs == 0
