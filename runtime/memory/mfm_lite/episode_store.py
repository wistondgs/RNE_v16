"""Persistencia multiescala de episodios certificados.

B24: el argumento `no_interference=True` de las tres escrituras de abajo es un
**campo NO computado**; se escribe `True` por default de schema (la columna es
NOT NULL). **No confiar en este valor**: no hay consumidor y nadie verificó que
esta memoria no interfiera con otras. Ver `runtime/storage/records.py`.
"""

from __future__ import annotations

from typing import Any, Dict

from runtime.storage import StorageFacade


class EpisodeMemoryStore:
    def __init__(self, *, storage: StorageFacade):
        self.storage = storage

    def write_micro(
        self,
        *,
        run_id: str,
        episode_id: str,
        certificate_id: str,
        ioc_proxy: float,
        structure: Dict[str, Any],
        extra_metadata: Dict[str, Any] | None = None,
    ):
        metadata = {"origin": "episode_store.micro"}
        if extra_metadata:
            metadata.update(extra_metadata)
        return self.storage.write_memory_record(
            run_id=run_id,
            episode_id=episode_id,
            scale="micro",
            structure_json=structure,
            certificate_id=certificate_id,
            ioc_proxy=ioc_proxy,
            ttl_seconds=7 * 24 * 3600,
            no_interference=True,  # B24: NO computado (default de schema); no confiar
            support_count=1,
            metadata=metadata,
        )

    def write_meso(
        self,
        *,
        run_id: str,
        episode_id: str,
        certificate_id: str,
        ioc_proxy: float,
        structure: Dict[str, Any],
        extra_metadata: Dict[str, Any] | None = None,
    ):
        metadata = {"origin": "episode_store.meso"}
        if extra_metadata:
            metadata.update(extra_metadata)
        return self.storage.write_memory_record(
            run_id=run_id,
            episode_id=episode_id,
            scale="meso",
            structure_json=structure,
            certificate_id=certificate_id,
            ioc_proxy=ioc_proxy,
            ttl_seconds=30 * 24 * 3600,
            no_interference=True,  # B24: NO computado (default de schema); no confiar
            support_count=1,
            metadata=metadata,
        )

    def write_macro(
        self,
        *,
        run_id: str,
        episode_id: str,
        certificate_id: str,
        ioc_proxy: float,
        support_count: int,
        structure: Dict[str, Any],
        extra_metadata: Dict[str, Any] | None = None,
    ):
        metadata = {"origin": "episode_store.macro"}
        if extra_metadata:
            metadata.update(extra_metadata)
        return self.storage.write_memory_record(
            run_id=run_id,
            episode_id=episode_id,
            scale="macro",
            structure_json=structure,
            certificate_id=certificate_id,
            ioc_proxy=ioc_proxy,
            ttl_seconds=None,
            no_interference=True,  # B24: NO computado (default de schema); no confiar
            support_count=support_count,
            metadata=metadata,
        )
