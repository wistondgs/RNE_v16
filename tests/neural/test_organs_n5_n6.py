from __future__ import annotations

import hashlib

from runtime.neural import InferenceScope, NeuralInferenceRequest, NeuralModelManifest, ResourceSnapshot
from runtime.neural.organs import (
    BoundaryOffsets,
    BoundarySemantics,
    DeterministicChunker,
    HNetBoundaryAdmission,
    HNetBoundaryBackend,
    KANSpline,
    LTCCell,
    OffsetUnit,
    StructuralEvolutionGate,
    StructuralMutationProposal,
    UnstructuredIngestionService,
)


def test_n5_chunker_is_unicode_safe_and_calls_real_ingestion_ports() -> None:
    chunker = DeterministicChunker(max_bytes=32)
    text = "Órgano uno.\n\n```python\nprint('simbiosis')\n```\nFin."
    chunks = chunker.chunk(text)
    assert "".join(item.text for item in chunks) == text
    assert all(len(item.text.encode("utf-8")) <= 32 for item in chunks)

    signs = []
    memories = []
    service = UnstructuredIngestionService(
        sign_sink=lambda item: signs.append(dict(item)) or f"sign-{len(signs)}",
        memory_candidate_sink=lambda item: memories.append(dict(item)) or f"memory-{len(memories)}",
        fallback_chunker=chunker,
    )
    result = service.ingest(text, run_id="run-5", source_id="source-5")
    assert len(result["chunks"]) == len(signs) == len(memories)
    assert all(item["status"] == "candidate" for item in signs)
    assert all(item["promotion"] == "requires_existing_mfm_gate" for item in memories)
    assert all("byte" in item["chunk"]["offsets"] for item in signs)
    assert all("codepoint" in item["chunk"]["offsets"] for item in signs)


def test_n5_offset_contract_roundtrips_multilingual_text() -> None:
    corpus = [
        "Español: órgano, razón y simbiosis.",
        "Français : mémoire, causalité et évolution.",
        "中文因果图与记忆。",
        "🙂🧠⚙️ RNFE",
        "```python\nvalor = 'é🙂中'\n```",
    ]
    chunker = DeterministicChunker(max_bytes=32)
    for text in corpus:
        chunks = chunker.chunk(text)
        assert "".join(item.text for item in chunks) == text
        for item in chunks:
            assert item.text.encode("utf-8") == text.encode("utf-8")[item.byte_start : item.byte_end]
            assert item.text == text[item.codepoint_start : item.codepoint_end]


def _n5_manifest() -> NeuralModelManifest:
    return NeuralModelManifest(
        organ="N5",
        capability="hierarchical_ingestion",
        model_id="hnet-fixture",
        version="1",
        backend="hnet-fixture",
        artifact_path="n5/hnet.bin",
        artifact_sha256=hashlib.sha256(b"hnet").hexdigest(),
        input_schema_version="1",
        output_schema_version="1",
        supported_devices=("cpu",),
        license_id="MIT",
        upstream_url="https://github.com/goombalab/hnet",
        upstream_commit="fixture-commit",
        training_provenance={"fixture": True},
    )


def _n5_request(text: str) -> NeuralInferenceRequest:
    return NeuralInferenceRequest(
        inference_id="n5-offset-test",
        run_id="run-n5",
        organ="N5",
        capability="hierarchical_ingestion",
        payload={"text": text, "boundary_threshold": 0.5},
        scope=InferenceScope.LAB,
        resources=ResourceSnapshot(),
    )


def test_n5_hnet_converts_after_byte_boundaries_to_codepoint_splits() -> None:
    text = "é🙂中A"
    seen = []

    def infer(_model, payload: bytes):
        seen.append(payload)
        probabilities = [0.0] * len(payload)
        for byte_index in (1, 5, 8):
            probabilities[byte_index] = 0.9
        return probabilities

    backend = HNetBoundaryBackend(lambda path, device: object(), infer)
    backend.load(_n5_manifest(), "/tmp/hnet-fixture", "cpu")
    request = _n5_request(text)
    output = backend.infer(request)
    assert seen == [text.encode("utf-8")]
    decision = HNetBoundaryAdmission()(output.candidate_output, request)
    assert decision.accepted is True
    assert decision.output["boundary_offsets"] == BoundaryOffsets(
        values=(1, 2, 3),
        unit=OffsetUnit.CODEPOINT,
        semantics=BoundarySemantics.SPLIT_OFFSET,
    ).to_dict()

    service = UnstructuredIngestionService(
        sign_sink=lambda item: item,
        memory_candidate_sink=lambda item: item,
    )
    ingested = service.ingest(
        text,
        run_id="run-n5",
        source_id="unicode",
        neural_boundaries=decision.output["boundary_offsets"],
    )
    assert [item["text"] for item in ingested["chunks"]] == ["é", "🙂", "中", "A"]


def test_n5_rejects_hnet_boundary_inside_multibyte_codepoint() -> None:
    text = "éA"

    def infer(_model, payload: bytes):
        probabilities = [0.0] * len(payload)
        probabilities[0] = 0.9  # después del primer byte de é: frontera UTF-8 inválida
        return probabilities

    backend = HNetBoundaryBackend(lambda path, device: object(), infer)
    backend.load(_n5_manifest(), "/tmp/hnet-fixture", "cpu")
    request = _n5_request(text)
    decision = HNetBoundaryAdmission()(backend.infer(request).candidate_output, request)
    assert decision.accepted is False
    assert "inside_multibyte_codepoint" in decision.reason


def test_n5_rejects_corrupt_identity_metadata_without_escaping_gate() -> None:
    text = "éA"
    request = _n5_request(text)
    candidate = {
        "source": "hnet",
        "text_sha256": "invalid",
        "byte_length": "not-an-int",
        "codepoint_length": 2,
        "boundary_offsets": BoundaryOffsets(
            values=(1,),
            unit=OffsetUnit.BYTE,
            semantics=BoundarySemantics.AFTER_UNIT,
        ).to_dict(),
    }
    decision = HNetBoundaryAdmission()(candidate, request)
    assert decision.accepted is False
    assert decision.reason == "n5_text_identity_metadata_invalid"


def test_n6_kan_exports_equivalent_sympy_expression() -> None:
    spline = KANSpline(knots=(0.0, 1.0, 2.0), coefficients=(0.0, 2.0, 2.0))
    expression = spline.to_sympy("x")
    assert spline.evaluate(0.5) == 1.0
    assert float(expression.subs({"x": 0.5})) == 1.0
    assert spline.evaluate(3.0) == 2.0


def test_n6_ltc_is_bounded_and_structural_gate_requires_real_apply_fn() -> None:
    cell = LTCCell(
        input_weights=((1.0,), (0.5,)),
        recurrent_weights=((0.1, 0.0), (0.0, 0.1)),
        bias=(0.0, 0.0),
        tau=(1.0, 2.0),
    )
    state = cell.step((0.0, 0.0), (0.8,), dt=0.1)
    assert all(-1.0 <= value <= 1.0 for value in state)

    proposal = StructuralMutationProposal(
        mutation_type="parameter_bound",
        target="n1.max_optional_families",
        value=2,
        expected_gain=0.1,
        rollback_token="rollback-1",
    )
    gate = StructuralEvolutionGate()
    blocked = gate.evaluate_and_apply(
        proposal,
        sandbox=lambda item: {"safe": True},
        certify=lambda report: bool(report["safe"]),
        apply_fn=None,
        rollback=None,
    )
    assert blocked == {"applied": False, "reason": "apply_fn_and_rollback_required_p29"}

    applied = []
    result = gate.evaluate_and_apply(
        proposal,
        sandbox=lambda item: {"safe": True, "closure_delta": 0.01},
        certify=lambda report: bool(report["safe"]),
        apply_fn=lambda item: applied.append(item) or "applied",
        rollback=lambda token: None,
    )
    assert result["applied"] is True
    assert applied == [proposal]
