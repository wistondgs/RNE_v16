"""T2: re-sealed false receipts fail semantic rederivation in the T1 domain."""
import runpy

from lab.genesis.verifiers import (
    FederationVerdict,
    RequirementAdjudicationReceipt,
    adjudicate_requirement,
    validate_requirement_adjudication,
)


t1 = runpy.run_path("tests/genesis/test_m6b3_adjudication_equivalence.py")
REACHABLE_VERDICTS = (
    FederationVerdict.PASS,
    FederationVerdict.FAIL,
    FederationVerdict.CONFLICT,
    FederationVerdict.INCONCLUSIVE,
)


def reseal(receipt, **changes):
    payload = receipt.canonical_payload() | changes
    return RequirementAdjudicationReceipt(
        payload["schema_version"], payload["federation_plan_hash"],
        payload["requirement_id"], payload["requirement_hash"],
        payload["evidence_bundle_hash"], payload["execution_subject_hash"],
        payload["all_execution_record_hashes"], payload["verdict"],
        payload["qualifying_pass_record_hashes"],
        payload["qualifying_fail_record_hashes"],
        payload["independent_pass_basis_hashes"], payload["conflict_basis_hashes"],
        payload["unknown_record_hashes"], payload["error_record_hashes"],
        payload["reason_codes"],
    )


def semantic_validation(case):
    _, router, plan, subject, records, bundle, receipt = case
    return validate_requirement_adjudication(
        receipt, router=router, federation_plan=plan, subject=subject,
        records=records, bundle=bundle,
    )


def canonical_witnesses():
    """One minimal CaseSpec per reachable verdict, with no new fixture domain."""
    candidates = {}
    for spec in t1["planner_reachable_case_specs"]():
        router, plan, subject, records, bundle = t1["materialize_spec"](spec)
        receipt = adjudicate_requirement(
            router=router, federation_plan=plan, subject=subject,
            records=records, bundle=bundle,
        )
        assert receipt.validate()
        assert semantic_validation((spec, router, plan, subject, records, bundle, receipt))
        assert receipt.verdict is t1["federation_verdict"](router, plan, records)
        candidates.setdefault(receipt.verdict, []).append(
            (spec, router, plan, subject, records, bundle, receipt)
        )
    return {
        verdict: min(candidates[verdict], key=lambda item: item[0].case_spec_hash)
        for verdict in REACHABLE_VERDICTS
    }


def witness_with(field):
    for spec in t1["planner_reachable_case_specs"]():
        router, plan, subject, records, bundle = t1["materialize_spec"](spec)
        receipt = adjudicate_requirement(
            router=router, federation_plan=plan, subject=subject,
            records=records, bundle=bundle,
        )
        if getattr(receipt, field):
            return spec, router, plan, subject, records, bundle, receipt
    raise AssertionError(f"T1 domain contains no witness for {field}")


def assert_hash_valid_but_semantically_rejected(case, **changes):
    false = reseal(case[-1], **changes)
    assert false.validate(), "T2 must not pass merely because a SHA is broken"
    forged = (*case[:-1], false)
    assert not semantic_validation(forged)


def test_t2_cross_verdict_falsification_uses_canonical_t1_witnesses():
    witnesses = canonical_witnesses()
    assert set(witnesses) == set(REACHABLE_VERDICTS)
    for actual, case in witnesses.items():
        for false_verdict in REACHABLE_VERDICTS:
            if false_verdict is not actual:
                assert_hash_valid_but_semantically_rejected(
                    case, verdict=false_verdict.value,
                )


def test_t2_resealed_bases_sets_and_record_universe_are_rejected():
    witnesses = canonical_witnesses()
    passed = witnesses[FederationVerdict.PASS]
    failed = witnesses[FederationVerdict.FAIL]
    conflicted = witnesses[FederationVerdict.CONFLICT]
    unknown = witness_with("unknown_record_hashes")
    error = witness_with("error_record_hashes")

    assert_hash_valid_but_semantically_rejected(
        passed, independent_pass_basis_hashes=(),
    )
    assert_hash_valid_but_semantically_rejected(
        conflicted, conflict_basis_hashes=(),
    )
    assert_hash_valid_but_semantically_rejected(
        passed, qualifying_pass_record_hashes=(),
    )
    assert_hash_valid_but_semantically_rejected(
        failed, qualifying_fail_record_hashes=(),
    )
    assert_hash_valid_but_semantically_rejected(
        unknown, unknown_record_hashes=(),
    )
    assert_hash_valid_but_semantically_rejected(
        error, error_record_hashes=(),
    )

    record_hashes = conflicted[-1].all_execution_record_hashes
    assert_hash_valid_but_semantically_rejected(
        conflicted, all_execution_record_hashes=record_hashes[:-1],
    )
    assert_hash_valid_but_semantically_rejected(
        conflicted,
        all_execution_record_hashes=tuple(sorted((*record_hashes, "0" * 64))),
    )
    assert_hash_valid_but_semantically_rejected(
        conflicted,
        all_execution_record_hashes=tuple(sorted(("f" * 64, *record_hashes[1:]))),
    )
