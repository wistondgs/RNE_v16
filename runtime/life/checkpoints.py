"""Checkpointing canonico del Life Kernel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict
from uuid import uuid4

from runtime.core.checkpoint_kinds import LIFE_CHECKPOINT_KIND
from runtime.organism.lineage import LineageState
from runtime.organism.state import OrganismState
from runtime.storage.records import ArtifactRecord, utc_now_iso

from .contracts import AutonomyDecision, GoalState, VitalSignsSnapshot
from .serialization import jsonable, lineage_to_payload, organism_to_payload


logger = logging.getLogger(__name__)

LIFE_CHECKPOINT_VERSION = "1.0.0"

# B83 — por qué un candidato a refugio NO sirve. El rechazo por VITALES trae además el
# `restorability_report()` completo (contracts.py), que dice qué ejes se chequearon, cuáles
# no aplicaban y cuáles fallaron. Estos motivos NO se emiten desde acá: `checkpoints.py` es
# el camino de LECTURA y no escribe eventos (P9.5 lo evitó a propósito). La compuerta
# DEVUELVE el rechazo —vía `on_reject`— y el KERNEL, que ya emite eventos, lo publica.
REFUGE_ARTIFACT_MISSING = "artifact_missing"
REFUGE_PAYLOAD_UNREADABLE = "payload_unreadable"
REFUGE_PAYLOAD_INVALID = "payload_invalid"
REFUGE_VITALS_MISSING = "vitals_missing"
REFUGE_VITALS_UNREADABLE = "vitals_unreadable"


class CheckpointManager:
    """Persiste y recupera checkpoints vivos como artifacts indexados."""

    def __init__(self, *, storage):
        self.storage = storage

    def save_checkpoint(
        self,
        *,
        run_id: str,
        organism_state: OrganismState,
        lineage: LineageState,
        goals: list[GoalState],
        vital_signs: VitalSignsSnapshot,
        total_steps: int,
        scenario_index: int,
        scenario_episode_index: int,
        memory_filter_mode: str,
        closure_profile: str,
        organism_id: str | None = None,
        lineage_id: str | None = None,
        decision: AutonomyDecision | None = None,
        runner_knobs: Dict[str, Any] | None = None,
        scale_state: Dict[str, Any] | None = None,
        neural_state: Dict[str, Any] | None = None,
        autoevolution_state: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        checkpoint_id = f"life-ckpt-{uuid4().hex[:12]}"
        # B41 (decisión 4/6): el organism_id vive en el PAYLOAD del checkpoint (no se
        # toca el IdentityState frozen). Fallback legado: si el kernel no lo provee,
        # el genoma es el run_id bajo el que se escribió (organism_id := run_id).
        organism_id = str(organism_id or run_id)
        lineage_id = str(lineage_id or getattr(lineage, "lineage_id", "") or "")
        payload = {
            "version": LIFE_CHECKPOINT_VERSION,
            "checkpoint_id": checkpoint_id,
            "created_at": utc_now_iso(),
            "run_id": run_id,
            "organism_id": organism_id,
            "lineage_id": lineage_id,
            "total_steps": int(total_steps),
            "scenario_index": int(scenario_index),
            "scenario_episode_index": int(scenario_episode_index),
            "memory_filter_mode": memory_filter_mode,
            "closure_profile": closure_profile,
            "organism_state": organism_to_payload(organism_state),
            "lineage": lineage_to_payload(lineage),
            "goals": [goal.to_dict() for goal in goals],
            "vital_signs": vital_signs.to_dict(),
            "decision": decision.to_dict() if decision is not None else None,
            "runner_knobs": dict(runner_knobs or {}),
            "scale_state": dict(scale_state or {}),
            "neural_state": dict(neural_state or {}),
            # H-046: estado longitudinal del lazo ρₜ. Slot aditivo, mismo patrón que
            # neural_state; un payload legacy sin la clave restaura {} (controller fresco).
            "autoevolution_state": dict(autoevolution_state or {}),
            "metadata": dict(metadata or {}),
        }
        blob = json.dumps(jsonable(payload), ensure_ascii=True, sort_keys=True, indent=2)
        artifact = self.storage.materialize_artifact(
            run_id=run_id,
            kind=LIFE_CHECKPOINT_KIND,
            content=blob,
            filename=f"{checkpoint_id}.json",
            mime_type="application/json",
            metadata={
                "checkpoint_id": checkpoint_id,
                # B41: organism_id/lineage_id en metadata ⇒ descubrimiento por genoma
                # (decisión 5, filtro por metadata; path-segment diferido, cero migración).
                "organism_id": organism_id,
                "lineage_id": lineage_id,
                "episode_count": organism_state.episode_count,
                "total_steps": total_steps,
                "mode": vital_signs.mode,
                "healthy": vital_signs.is_restorable,
            },
        )
        self.storage.append_event(
            event_type="life.checkpoint.saved",
            run_id=run_id,
            source="life_kernel",
            payload={
                "checkpoint_id": checkpoint_id,
                "artifact_id": artifact.artifact_id,
                "organism_id": organism_id,
                "lineage_id": lineage_id,
                "episode_count": organism_state.episode_count,
                "mode": vital_signs.mode,
                "healthy": vital_signs.is_restorable,
            },
        )
        return artifact

    def load_latest_payload(
        self,
        *,
        run_id: str | None = None,
        organism_id: str | None = None,
        healthy_only: bool = False,
        on_reject: Callable[[Dict[str, Any]], None] | None = None,
    ) -> tuple[Dict[str, Any], ArtifactRecord] | None:
        """Último checkpoint (opcionalmente, el último SANO) del organismo.

        B83 — ``on_reject``: callback invocado UNA VEZ POR CANDIDATO RECHAZADO durante la
        búsqueda de refugio (``healthy_only=True``), con un dict
        ``{artifact_id, reason, report}``. Existe porque hasta ahora el organismo podía
        descartar TODOS sus refugios y quedarse atascado en cuarentena SIN DEJAR RASTRO de
        por qué: el callejón sin salida que el camino E5 existe justamente para romper.

        Este módulo NO emite eventos (es el camino de lectura): DEVUELVE el rechazo y el
        kernel lo publica en el ledger. Y el callback es FAIL-SAFE — si el emisor falla, se
        loguea y la búsqueda SIGUE: la telemetría del refugio jamás puede costar el refugio.

        Nota: solo se reportan los candidatos que el índice daba por sanos
        (``metadata["healthy"]``) y son de este organismo. Un checkpoint guardado como NO
        sano nunca fue candidato a refugio; contarlo como "rechazo" sería ruido.
        """
        # B41 (§3.8): el descubrimiento se puede scopear por GENOMA (organism_id) en vez
        # de por corrida. Con run_id efímero, "el último checkpoint de cualquier corrida"
        # es incorrecto; debe ser "el último de ESTE organismo". Cuando se da organism_id,
        # escaneamos todos los checkpoints (run_id=None) y filtramos por el genoma vía
        # metadata (fallback legado: el artifact.run_id ES el organism_id legado, §4.1).
        # Sin organism_id, se conserva la mecánica por run_id (byte-idéntico).
        scan_run_id = None if organism_id else run_id
        # Al buscar un REFUGIO sano (healthy_only) o al scopear por organismo escaneamos
        # mucho más hondo: tras un período largo dañado (cuarentena) o a través de varias
        # corridas efímeras, el último yo sano del organismo puede estar lejos en el
        # tiempo, y debe seguir siendo alcanzable — sobrevivir es condición de aprender.
        artifacts = self.storage.list_artifacts(
            run_id=scan_run_id,
            kind=LIFE_CHECKPOINT_KIND,
            limit=400 if (healthy_only or organism_id) else 20,
        )
        for artifact in artifacts:
            if healthy_only and not bool((artifact.metadata or {}).get("healthy")):
                continue
            if organism_id is not None:
                # metadata.organism_id (post-B41) o, para checkpoints legados sin ese
                # campo, el run_id de la corrida bajo la que se escribió (== genoma legado).
                art_org = str((artifact.metadata or {}).get("organism_id") or artifact.run_id or "")
                if art_org != organism_id:
                    continue
            artifact_id = str(getattr(artifact, "artifact_id", "?"))
            reject = self._rejection_sink(on_reject if healthy_only else None, artifact_id)
            path = Path(artifact.abs_path)
            if not path.exists() or not path.is_file():
                reject(REFUGE_ARTIFACT_MISSING)
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                reject(REFUGE_PAYLOAD_UNREADABLE, detail=f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(payload, dict) or not payload.get("version"):
                reject(REFUGE_PAYLOAD_INVALID)
                continue
            # B73: si esto es la búsqueda de un REFUGIO, la salud se re-deriva del
            # CONTENIDO del archivo, no del flag de metadata (ver _restorability_rejection).
            if healthy_only:
                rejection = self._restorability_rejection(payload, artifact_id=artifact_id)
                if rejection is not None:
                    reject(rejection["reason"], report=rejection.get("report"))
                    continue
            return payload, artifact
        return None

    @staticmethod
    def _rejection_sink(
        on_reject: Callable[[Dict[str, Any]], None] | None, artifact_id: str
    ) -> Callable[..., None]:
        """Publica el rechazo de UN candidato — sin poder matar la búsqueda.

        B83 + robustez P9.5: si el emisor del kernel explota (storage caído, ledger lleno),
        el organismo NO puede perder el refugio por eso. Se loguea y se sigue buscando: la
        constancia del rechazo es importante, pero jamás más importante que sobrevivir.
        """

        def _reject(reason: str, *, report: Dict[str, Any] | None = None, detail: str = "") -> None:
            if on_reject is None:
                return
            try:
                on_reject(
                    {
                        "artifact_id": artifact_id,
                        "reason": reason,
                        "detail": detail,
                        "report": report,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - la telemetría no puede costar el refugio
                logger.warning(
                    "[life.refuge] no se pudo publicar el rechazo de %s (%s: %s). "
                    "La búsqueda de refugio CONTINÚA.",
                    artifact_id,
                    type(exc).__name__,
                    exc,
                )

        return _reject

    @staticmethod
    def _restorability_rejection(
        payload: Dict[str, Any], *, artifact_id: str = "?"
    ) -> Dict[str, Any] | None:
        """B73 — el refugio se decide sobre el archivo, no sobre el flag guardado.

        Returns:
            ``None`` si el candidato SIRVE de refugio; si no, ``{"reason", "report"}`` — el
            motivo del rechazo, para que el kernel lo publique (B83).

        ``metadata["healthy"]`` se escribe al GUARDAR, con el snapshot completo en memoria:
        es un índice para no leer todos los artifacts, no una prueba de que el archivo que
        estamos por adoptar siga sano. Si el checkpoint se trunca o se corrompe después de
        escrito, el flag sigue diciendo ``True``. Ese flag era la ÚNICA compuerta del camino
        E5 (``kernel._restore_latest_healthy_checkpoint``), que adoptaba el payload sin
        volver a mirarle los vitales jamás.

        Ahora los vitales se re-derivan del payload real: un checkpoint con vitales
        ausentes/truncadas ya no puede pasar por refugio (``from_dict`` los marca NO
        VERIFICADOS y ``is_restorable`` se cierra). Un checkpoint sano re-deriva
        ``is_restorable=True`` y sigue siendo elegible exactamente como antes.

        FAIL-SAFE **Y TOTAL**: un candidato malo se **saltea**, jamás mata la búsqueda.
        ``from_dict`` no es total —un ``vital_signs`` JSON-válido pero MAL TIPADO
        (``"risk_score": "high"``) revienta en ``float(...)``— y esta función corre dentro
        del loop de selección de refugio: si la excepción escapara, abortaría la búsqueda
        ENTERA y un checkpoint **sano** que estuviera detrás del corrupto **nunca se
        alcanzaría**. Endurecer la compuerta no puede volverla frágil.

        Y el rechazo **deja constancia**: negarse a refugiarse sin decir por qué es el mismo
        callejón sin salida (cuarentena muda) que el camino E5 existe para romper.

        B83 — y la constancia deja de ser SOLO un `logger.warning`. Esta función DEVUELVE el
        motivo (``None`` ⇒ el candidato sirve; dict ⇒ por qué no), y el kernel lo publica como
        ``life.refuge.rejected``. `restorability_report()` —el informe honesto de POR QUÉ se
        rechaza un refugio— existía desde P9.5 y **no tenía ningún llamador en runtime**:
        capacidad sin emisión, la misma patología que el backlog condena en B78.
        """
        vital_payload = payload.get("vital_signs")
        if not isinstance(vital_payload, dict):
            logger.warning(
                "[life.refuge] candidato %s RECHAZADO: bloque 'vital_signs' ausente o no-dict "
                "(checkpoint truncado o ajeno). No sirve de refugio.",
                artifact_id,
            )
            return {"reason": REFUGE_VITALS_MISSING, "report": None}
        try:
            vitals = VitalSignsSnapshot.from_dict(vital_payload)
        except Exception as exc:  # noqa: BLE001 - candidato ilegible: se saltea, no se muere
            logger.warning(
                "[life.refuge] candidato %s RECHAZADO: vitales ilegibles (%s: %s). "
                "Se saltea y se sigue buscando; NO se aborta la búsqueda de refugio.",
                artifact_id,
                type(exc).__name__,
                exc,
            )
            return {
                "reason": REFUGE_VITALS_UNREADABLE,
                "report": {"error": f"{type(exc).__name__}: {exc}"},
            }
        if vitals.is_restorable:
            return None
        report = vitals.restorability_report()
        logger.warning("[life.refuge] candidato %s RECHAZADO: %s", artifact_id, report)
        return {"reason": str(report.get("reason") or "not_restorable"), "report": report}
