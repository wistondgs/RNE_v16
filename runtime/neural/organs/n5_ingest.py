"""N5: frontera real de ingestion con fallback determinista."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from ..contracts import AdmissionDecision, BackendOutput, NeuralInferenceRequest, NeuralModelManifest


OFFSET_CONTRACT_VERSION = "n5-offset-contract-v1"


class OffsetUnit(str, Enum):
    BYTE = "byte"
    CODEPOINT = "codepoint"
    TOKEN = "token"


class BoundarySemantics(str, Enum):
    AFTER_UNIT = "after_unit"
    SPLIT_OFFSET = "split_offset"


@dataclass(frozen=True, slots=True)
class TextOffsetMap:
    text: str
    utf8_bytes: bytes
    codepoint_to_byte: tuple[int, ...]

    @classmethod
    def from_content(cls, content: str | bytes) -> "TextOffsetMap":
        text = normalize_text(content)
        offsets = [0]
        cursor = 0
        for character in text:
            cursor += len(character.encode("utf-8"))
            offsets.append(cursor)
        return cls(text=text, utf8_bytes=text.encode("utf-8"), codepoint_to_byte=tuple(offsets))

    @property
    def byte_length(self) -> int:
        return len(self.utf8_bytes)

    @property
    def codepoint_length(self) -> int:
        return len(self.text)

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.utf8_bytes).hexdigest()

    def byte_split_to_codepoint(self, byte_offset: int) -> int:
        try:
            return self.codepoint_to_byte.index(int(byte_offset))
        except ValueError as exc:
            raise ValueError(f"byte_offset_inside_multibyte_codepoint:{byte_offset}") from exc

    def codepoint_split_to_byte(self, codepoint_offset: int) -> int:
        offset = int(codepoint_offset)
        if offset < 0 or offset > self.codepoint_length:
            raise ValueError(f"codepoint_offset_out_of_range:{offset}")
        return self.codepoint_to_byte[offset]


@dataclass(frozen=True, slots=True)
class BoundaryOffsets:
    values: tuple[int, ...]
    unit: OffsetUnit
    semantics: BoundarySemantics
    contract_version: str = OFFSET_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != OFFSET_CONTRACT_VERSION:
            raise ValueError("n5_offset_contract_version_mismatch")
        normalized = tuple(sorted({int(value) for value in self.values}))
        if any(value < 0 for value in normalized):
            raise ValueError("n5_boundary_offsets_must_be_non_negative")
        object.__setattr__(self, "values", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "values": list(self.values),
            "unit": self.unit.value,
            "semantics": self.semantics.value,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BoundaryOffsets":
        return cls(
            values=tuple(int(value) for value in raw.get("values", ())),
            unit=OffsetUnit(str(raw.get("unit", ""))),
            semantics=BoundarySemantics(str(raw.get("semantics", ""))),
            contract_version=str(raw.get("contract_version", "")),
        )

    def to_codepoint_splits(
        self,
        offsets: TextOffsetMap,
        *,
        token_to_codepoint: Sequence[int] | None = None,
    ) -> tuple[int, ...]:
        splits = []
        for value in self.values:
            split = value + 1 if self.semantics is BoundarySemantics.AFTER_UNIT else value
            if self.unit is OffsetUnit.BYTE:
                codepoint = offsets.byte_split_to_codepoint(split)
            elif self.unit is OffsetUnit.CODEPOINT:
                codepoint = split
            else:
                if token_to_codepoint is None or split < 0 or split >= len(token_to_codepoint):
                    raise ValueError("token_offset_map_required")
                codepoint = int(token_to_codepoint[split])
            if codepoint <= 0 or codepoint >= offsets.codepoint_length:
                continue
            splits.append(codepoint)
        return tuple(sorted(set(splits)))


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    codepoint_start: int
    codepoint_end: int
    byte_start: int
    byte_end: int
    source: str
    offset_contract_version: str = OFFSET_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.offset_contract_version != OFFSET_CONTRACT_VERSION:
            raise ValueError("n5_chunk_offset_contract_version_mismatch")
        if not (0 <= self.codepoint_start <= self.codepoint_end):
            raise ValueError("n5_chunk_codepoint_span_invalid")
        if not (0 <= self.byte_start <= self.byte_end):
            raise ValueError("n5_chunk_byte_span_invalid")
        if len(self.text) != self.codepoint_end - self.codepoint_start:
            raise ValueError("n5_chunk_codepoint_length_mismatch")
        if len(self.text.encode("utf-8")) != self.byte_end - self.byte_start:
            raise ValueError("n5_chunk_byte_length_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "source": self.source,
            "offset_contract_version": self.offset_contract_version,
            "offsets": {
                "codepoint": {"start": self.codepoint_start, "end": self.codepoint_end},
                "byte": {"start": self.byte_start, "end": self.byte_end},
            },
        }


def normalize_text(content: str | bytes) -> str:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


class DeterministicChunker:
    def __init__(self, *, max_bytes: int = 1024):
        if max_bytes < 32:
            raise ValueError("max_bytes_must_be_at_least_32")
        self.max_bytes = max_bytes

    def chunk(self, content: str | bytes) -> list[TextChunk]:
        offset_map = TextOffsetMap.from_content(content)
        text = offset_map.text
        boundaries = {0, len(text)}
        for match in re.finditer(r"\n\s*\n|(?<=[.!?])\s+|\n(?=```)|(?<=```)\n", text):
            boundaries.add(match.end())
        points = sorted(boundaries)
        raw_segments = [text[points[i] : points[i + 1]] for i in range(len(points) - 1)]
        pieces: list[str] = []
        for segment in raw_segments:
            pieces.extend(_split_utf8(segment, self.max_bytes))
        chunks = []
        cursor = 0
        for piece in pieces:
            if not piece:
                continue
            start = text.find(piece, cursor)
            if start < 0:
                start = cursor
            end = start + len(piece)
            chunks.append(
                TextChunk(
                    len(chunks),
                    piece,
                    start,
                    end,
                    offset_map.codepoint_split_to_byte(start),
                    offset_map.codepoint_split_to_byte(end),
                    "deterministic",
                )
            )
            cursor = end
        return chunks


def _split_utf8(text: str, limit: int) -> list[str]:
    if len(text.encode("utf-8")) <= limit:
        return [text]
    pieces = []
    current = ""
    for character in text:
        candidate = current + character
        if current and len(candidate.encode("utf-8")) > limit:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


class HNetBoundaryBackend:
    """Puerto inyectable al H-Net certificado; evita asumir una API vendor."""

    def __init__(
        self,
        loader: Callable[[str, str], Any],
        infer_boundaries: Callable[[Any, bytes], Sequence[float]],
    ):
        self.loader = loader
        self.infer_boundaries = infer_boundaries
        self.model: Any | None = None

    def load(self, manifest: NeuralModelManifest, artifact_path: str, device: str) -> None:
        if manifest.organ != "N5" or manifest.license_id.upper() != "MIT":
            raise ValueError("hnet_requires_certified_n5_mit_manifest")
        if manifest.upstream_commit.lower() in {"", "unknown", "unresolved"}:
            raise ValueError("hnet_upstream_commit_unresolved")
        self.model = self.loader(artifact_path, device)

    def infer(self, request: NeuralInferenceRequest) -> BackendOutput:
        if self.model is None:
            raise RuntimeError("backend_not_loaded")
        offsets = TextOffsetMap.from_content(str(request.payload.get("text", "")))
        probabilities = [
            min(max(float(value), 0.0), 1.0)
            for value in self.infer_boundaries(self.model, offsets.utf8_bytes)
        ]
        if len(probabilities) != offsets.byte_length:
            raise ValueError("hnet_boundary_length_mismatch")
        threshold = float(request.payload.get("boundary_threshold", 0.5))
        boundaries = [index for index, value in enumerate(probabilities) if value >= threshold]
        return BackendOutput(
            candidate_output={
                "boundary_offsets": BoundaryOffsets(
                    values=tuple(boundaries),
                    unit=OffsetUnit.BYTE,
                    semantics=BoundarySemantics.AFTER_UNIT,
                ).to_dict(),
                "probabilities": probabilities,
                "source": "hnet",
                "text_sha256": offsets.text_sha256,
                "byte_length": offsets.byte_length,
                "codepoint_length": offsets.codepoint_length,
            },
            confidence=max(probabilities, default=0.0),
            uncertainty=1.0 - max(probabilities, default=0.0),
            cost={
                "bytes": offsets.byte_length,
                "codepoints": offsets.codepoint_length,
            },
        )

    def unload(self) -> None:
        self.model = None


class HNetBoundaryAdmission:
    def __call__(self, candidate: Any, request: NeuralInferenceRequest) -> AdmissionDecision:
        if not isinstance(candidate, Mapping) or candidate.get("source") != "hnet":
            return AdmissionDecision(False, reason="n5_hnet_schema_invalid")
        offsets = TextOffsetMap.from_content(str(request.payload.get("text", "")))
        try:
            byte_length = int(candidate.get("byte_length", -1))
            codepoint_length = int(candidate.get("codepoint_length", -1))
            identity_matches = bool(
                candidate.get("text_sha256") == offsets.text_sha256
                and byte_length == offsets.byte_length
                and codepoint_length == offsets.codepoint_length
            )
        except (TypeError, ValueError):
            return AdmissionDecision(False, reason="n5_text_identity_metadata_invalid")
        if not identity_matches:
            return AdmissionDecision(False, reason="n5_text_identity_mismatch")
        try:
            raw_boundaries = candidate.get("boundary_offsets")
            if not isinstance(raw_boundaries, Mapping):
                raise ValueError("n5_boundary_contract_missing")
            boundary_offsets = BoundaryOffsets.from_mapping(raw_boundaries)
            if (
                boundary_offsets.unit is not OffsetUnit.BYTE
                or boundary_offsets.semantics is not BoundarySemantics.AFTER_UNIT
            ):
                raise ValueError("n5_hnet_must_use_after_byte_offsets")
            codepoint_splits = boundary_offsets.to_codepoint_splits(offsets)
        except (TypeError, ValueError) as exc:
            return AdmissionDecision(False, reason=f"n5_boundary_conversion_rejected:{exc}")
        return AdmissionDecision(
            True,
            output={
                "boundary_offsets": BoundaryOffsets(
                    values=codepoint_splits,
                    unit=OffsetUnit.CODEPOINT,
                    semantics=BoundarySemantics.SPLIT_OFFSET,
                ).to_dict(),
                "source": "hnet",
                "provenance": {
                    "native_offsets": boundary_offsets.to_dict(),
                    "text_sha256": offsets.text_sha256,
                },
            },
            reason="n5_boundaries_valid",
        )


class UnstructuredIngestionService:
    """Caller vivo: segmenta y entrega signos/candidatos por puertos inyectados."""

    def __init__(
        self,
        *,
        sign_sink: Callable[[Mapping[str, Any]], Any],
        memory_candidate_sink: Callable[[Mapping[str, Any]], Any],
        fallback_chunker: DeterministicChunker | None = None,
    ):
        self.sign_sink = sign_sink
        self.memory_candidate_sink = memory_candidate_sink
        self.fallback_chunker = fallback_chunker or DeterministicChunker()

    def ingest(
        self,
        content: str | bytes,
        *,
        run_id: str,
        source_id: str,
        neural_boundaries: BoundaryOffsets | Mapping[str, Any] | None = None,
        token_to_codepoint: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        if neural_boundaries is None:
            chunks = self.fallback_chunker.chunk(content)
        else:
            boundary_contract = (
                BoundaryOffsets.from_mapping(neural_boundaries)
                if isinstance(neural_boundaries, Mapping)
                else neural_boundaries
            )
            if not isinstance(boundary_contract, BoundaryOffsets):
                raise TypeError("n5_neural_boundaries_require_explicit_offset_contract")
            chunks = _chunks_from_boundaries(
                content,
                boundary_contract,
                token_to_codepoint=token_to_codepoint,
            )
        signs = []
        memories = []
        for chunk in chunks:
            sign = {
                "run_id": run_id,
                "source_id": source_id,
                "chunk": chunk.to_dict(),
                "status": "candidate",
                "offset_contract_version": OFFSET_CONTRACT_VERSION,
            }
            signs.append(self.sign_sink(sign))
            memories.append(
                self.memory_candidate_sink(
                    {**sign, "promotion": "requires_existing_mfm_gate"}
                )
            )
        return {"chunks": [item.to_dict() for item in chunks], "signs": signs, "memory_candidates": memories}


def _chunks_from_boundaries(
    content: str | bytes,
    boundaries: BoundaryOffsets,
    *,
    token_to_codepoint: Sequence[int] | None = None,
) -> list[TextChunk]:
    offset_map = TextOffsetMap.from_content(content)
    text = offset_map.text
    splits = boundaries.to_codepoint_splits(
        offset_map,
        token_to_codepoint=token_to_codepoint,
    )
    points = [0, *splits, len(text)]
    return [
        TextChunk(
            index,
            text[start:end],
            start,
            end,
            offset_map.codepoint_split_to_byte(start),
            offset_map.codepoint_split_to_byte(end),
            "hnet",
        )
        for index, (start, end) in enumerate(zip(points, points[1:]))
        if end > start
    ]
