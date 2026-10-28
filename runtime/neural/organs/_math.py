"""Operaciones pequenas para backends de referencia sin dependencia eager."""

from __future__ import annotations

import math
from typing import Iterable, Sequence


def vector(raw: Iterable[float], *, size: int | None = None, name: str = "vector") -> list[float]:
    values = [float(value) for value in raw]
    if size is not None and len(values) != size:
        raise ValueError(f"{name}_size_mismatch:{len(values)}!={size}")
    return values


def matrix(raw: Iterable[Iterable[float]], *, columns: int | None = None, name: str = "matrix") -> list[list[float]]:
    rows = [vector(row, name=name) for row in raw]
    if not rows:
        raise ValueError(f"{name}_must_not_be_empty")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ValueError(f"{name}_must_be_rectangular")
    if columns is not None and width != columns:
        raise ValueError(f"{name}_column_mismatch:{width}!={columns}")
    return rows


def matvec(weights: Sequence[Sequence[float]], values: Sequence[float], bias: Sequence[float] | None = None) -> list[float]:
    result = [sum(float(weight) * float(value) for weight, value in zip(row, values)) for row in weights]
    if bias is not None:
        if len(bias) != len(result):
            raise ValueError("bias_size_mismatch")
        result = [value + float(offset) for value, offset in zip(result, bias)]
    return result


def silu(value: float) -> float:
    return value / (1.0 + math.exp(-max(min(value, 60.0), -60.0)))


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(value, 60.0), -60.0)))


def softmax(values: Sequence[float], temperature: float = 1.0) -> list[float]:
    if not values:
        return []
    temperature = max(float(temperature), 1e-6)
    shifted = [float(value) / temperature for value in values]
    maximum = max(shifted)
    exponents = [math.exp(value - maximum) for value in shifted]
    total = sum(exponents) or 1.0
    return [value / total for value in exponents]


def tanh_vector(values: Sequence[float]) -> list[float]:
    return [math.tanh(value) for value in values]
