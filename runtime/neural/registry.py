"""Registro lazy de backends con verificacion criptografica."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import RLock
from typing import Callable

from .contracts import NeuralBackend, NeuralModelManifest


BackendFactory = Callable[[], NeuralBackend]


class BackendRegistryError(RuntimeError):
    pass


class LazyBackendRegistry:
    def __init__(self, *, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root).resolve()
        self._factories: dict[str, BackendFactory] = {}
        self._loaded: dict[tuple[str, str, str], NeuralBackend] = {}
        self._lock = RLock()

    def register(self, backend_name: str, factory: BackendFactory) -> None:
        normalized = backend_name.strip()
        if not normalized:
            raise ValueError("backend_name_is_required")
        with self._lock:
            if normalized in self._factories:
                raise ValueError(f"backend_already_registered:{normalized}")
            self._factories[normalized] = factory

    def acquire(
        self,
        manifest: NeuralModelManifest,
        *,
        device: str,
    ) -> tuple[NeuralBackend, tuple[str, str, str], bool]:
        key = (manifest.backend, manifest.manifest_sha256, device)
        with self._lock:
            existing = self._loaded.get(key)
            if existing is not None:
                return existing, key, False
            factory = self._factories.get(manifest.backend)
            if factory is None:
                raise BackendRegistryError(f"backend_not_registered:{manifest.backend}")
            artifact = self.resolve_and_verify(manifest)
            backend = factory()
            backend.load(manifest, str(artifact), device)
            self._loaded[key] = backend
            return backend, key, True

    def resolve_and_verify(self, manifest: NeuralModelManifest) -> Path:
        artifact = (self.artifact_root / manifest.artifact_path).resolve()
        try:
            artifact.relative_to(self.artifact_root)
        except ValueError as exc:
            raise BackendRegistryError("artifact_path_escapes_root") from exc
        if not artifact.is_file():
            raise BackendRegistryError(f"artifact_missing:{manifest.artifact_path}")
        digest = _sha256_file(artifact)
        if digest != manifest.artifact_sha256:
            raise BackendRegistryError("artifact_sha256_mismatch")
        return artifact

    def unload(self, key: tuple[str, str, str]) -> bool:
        with self._lock:
            backend = self._loaded.pop(key, None)
        if backend is None:
            return False
        backend.unload()
        return True

    def unload_all(self) -> int:
        with self._lock:
            items = list(self._loaded.items())
            self._loaded.clear()
        for _, backend in items:
            backend.unload()
        return len(items)

    @property
    def loaded_count(self) -> int:
        with self._lock:
            return len(self._loaded)


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
