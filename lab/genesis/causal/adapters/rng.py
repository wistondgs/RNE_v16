"""Optional, explicit RNG capture and restoration adapters."""

from __future__ import annotations

import importlib.util
import random
from typing import Any

from lab.genesis.causal.snapshot import SurfaceState
from lab.genesis.contracts.serialization import canonical_sha256


def capture_rng() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {"python_rng": {"state": SurfaceState.RESETTABLE.value, "payload": random.getstate()}}
    for name, module in (("numpy_rng", "numpy"), ("torch_cpu_rng", "torch")):
        if importlib.util.find_spec(module) is None:
            result[name] = {"state": SurfaceState.UNAVAILABLE.value}
            continue
        try:
            if module == "numpy":
                import numpy
                raw = numpy.random.get_state()
                result[name] = {"state": SurfaceState.RESETTABLE.value, "payload": {"bit_generator": str(raw[0]), "keys": raw[1].tolist(), "position": int(raw[2]), "has_gauss": int(raw[3]), "cached_gaussian": float(raw[4])}}
            else:
                import torch
                result[name] = {"state": SurfaceState.RESETTABLE.value, "payload": torch.random.get_rng_state().tolist()}
        except Exception as exc:
            result[name] = {"state": SurfaceState.UNKNOWN.value, "error": type(exc).__name__}
    try:
        if result["torch_cpu_rng"]["state"] == SurfaceState.UNAVAILABLE.value:
            result["torch_cuda_rng"] = {"state": SurfaceState.UNAVAILABLE.value}
        else:
            import torch
            result["torch_cuda_rng"] = {"state": SurfaceState.RESETTABLE.value, "payload": [item.tolist() for item in torch.cuda.get_rng_state_all()]} if torch.cuda.is_available() else {"state": SurfaceState.UNAVAILABLE.value}
    except Exception as exc:
        result["torch_cuda_rng"] = {"state": SurfaceState.UNKNOWN.value, "error": type(exc).__name__}
    for value in result.values():
        value["digest"] = canonical_sha256(value)
    return result


def restore_rng(snapshot: dict[str, dict[str, Any]]) -> None:
    random.setstate(_tuple_tree(snapshot["python_rng"]["payload"]))
    if snapshot["numpy_rng"]["state"] == SurfaceState.RESETTABLE.value:
        import numpy
        raw = snapshot["numpy_rng"]["payload"]
        numpy.random.set_state((raw["bit_generator"], numpy.array(raw["keys"], dtype=numpy.uint32), raw["position"], raw["has_gauss"], raw["cached_gaussian"]))
    if snapshot["torch_cpu_rng"]["state"] == SurfaceState.RESETTABLE.value:
        import torch
        torch.random.set_rng_state(torch.tensor(snapshot["torch_cpu_rng"]["payload"], dtype=torch.uint8))
    if snapshot["torch_cuda_rng"]["state"] == SurfaceState.RESETTABLE.value:
        import torch
        torch.cuda.set_rng_state_all([torch.tensor(item, dtype=torch.uint8) for item in snapshot["torch_cuda_rng"]["payload"]])


def _tuple_tree(value: Any) -> Any:
    return tuple(_tuple_tree(item) for item in value) if isinstance(value, (list, tuple)) else value


def verify_equivalence(snapshot: dict[str, dict[str, Any]]) -> bool:
    restore_rng(snapshot)
    first = random.random()
    restore_rng(snapshot)
    return first == random.random()
