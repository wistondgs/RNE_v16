"""Propuestas de reflexión del alumno local 7B sobre golpes observados.

Codex/frontier es el maestro externo de referencia. El modelo local 7B sólo propone
una lección estructurada; su salida es auditable y no tiene autoridad conductual.

La reflexión se invoca off-hot-path y está gated por ``RNFE_TEACHER``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from runtime.storage import StorageFacade
from runtime.organism.experience import (
    ExperienceProvenance,
    ExperienceStore,
    WOUND_THRESHOLD,
)

_TRUE = {"1", "true", "yes", "on"}
LOCAL_7B_PRODUCER_TYPE = "local_7b"
BEHAVIORAL_AUTHORITY_NONE = "none"


def teacher_enabled() -> bool:
    """True si el alumno local 7B puede producir propuestas de reflexión."""
    return os.environ.get("RNFE_TEACHER", "").strip().lower() in _TRUE


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrae el primer objeto JSON balanceado del texto (parseo defensivo del LLM)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


class Teacher:
    """Puerto legado que invoca al 7B como proponente local supervisado."""

    def __init__(self, *, storage: StorageFacade, experience: ExperienceStore):
        self.storage = storage
        self.experience = experience
        self._client = None  # lazy: el 7B es caro de construir

    def _get_client(self):
        if self._client is None:
            import dataclasses

            from runtime.reasoning.external_models.config import ExternalReasonerConfig
            from runtime.reasoning.external_models.llama_cpp_client import LlamaCppClient

            # El maestro reflexiona en formato propio {avoid,prefer,lesson}. Se le fija su
            # PROPIO schema (no el decision-shaped del razonador) para forzar JSON directo
            # — el 7B es un modelo de razonamiento que si no, "piensa en voz alta" sin cerrar.
            import os as _os

            cfg = ExternalReasonerConfig.from_env()
            lesson_schema = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "reasoning", "external_models", "schemas", "experience_lesson.schema.json",
            )
            try:
                cfg = dataclasses.replace(
                    cfg, structured_output_mode="json_schema", json_schema_path=lesson_schema
                )
            except Exception:
                pass
            self._client = LlamaCppClient(cfg)
        return self._client

    def reflect(
        self,
        *,
        organism_id: str,
        valid_interventions: List[str],
        max_reflections: int = 1,
    ) -> List[Dict[str, Any]]:
        """Reflexiona sobre las peores heridas observadas → propuestas auditables.

        Las propuestas nunca se graban como experiencia canónica.
        """
        if not teacher_enabled():
            return []
        experiences = self.experience.verified_recall(organism_id=organism_id, limit=200)
        wounds = [
            e
            for e in experiences
            if e.get("provenance") == ExperienceProvenance.OBSERVED_OUTCOME.value
            and float(e.get("severity", 0.0)) >= WOUND_THRESHOLD
            and e.get("intervention")
        ]
        if not wounds:
            return []
        # Las heridas más profundas primero (∝ daño): el maestro atiende lo que más dolió.
        wounds.sort(key=lambda e: float(e.get("severity", 0.0)), reverse=True)
        lessons: List[Dict[str, Any]] = []
        for wound in wounds[: max(1, int(max_reflections))]:
            lesson = self._reflect_one(
                organism_id=organism_id, wound=wound, valid_interventions=valid_interventions
            )
            if lesson is not None:
                lessons.append(lesson)
        return lessons

    def _reflect_one(
        self, *, organism_id: str, wound: Dict[str, Any], valid_interventions: List[str]
    ) -> Optional[Dict[str, Any]]:
        situation = str(wound.get("situation_key") or "")
        scenario = str(wound.get("scenario") or "")
        regime = str(wound.get("regime") or "")
        hurt_iv = str(wound.get("intervention") or "")
        severity = float(wound.get("severity", 0.0))
        alternatives = [iv for iv in valid_interventions if iv != hurt_iv]
        prompt = (
            "You are the local 7B supervised reflection proposer of a self-preserving "
            "cognitive organism. Codex/frontier is the external teacher of reference. "
            "You have no behavioral authority. Propose ONE lesson after this wound.\n"
            f"Situation: scenario='{scenario}', regime='{regime}'.\n"
            f"It chose intervention '{hurt_iv}' and suffered a wound (severity {severity:.2f}, "
            f"viability_margin {float(wound.get('viability_margin',0)):.2f}, ioc {float(wound.get('ioc',0)):.2f}, "
            f"risk {float(wound.get('risk',0)):.2f}).\n"
            f"Valid interventions: {valid_interventions}.\n"
            "Respond ONLY with a JSON object: "
            '{"avoid": "<the intervention to avoid>", "prefer": "<a better intervention from the valid list>", '
            '"lesson": "<one short sentence>"}'
        )
        try:
            client = self._get_client()
            # Sin schema constraint (el schema global es decision-shaped); parseo defensivo.
            res = client.generate(prompt, backend="cuda", max_tokens=160)
        except Exception:
            return None
        if not res or not res.get("ok"):
            return None
        text = res.get("output_text") or res.get("stdout") or ""
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            return None
        avoid = str(parsed.get("avoid") or hurt_iv)
        prefer = str(parsed.get("prefer") or "")
        if prefer not in valid_interventions or prefer == avoid:
            prefer = alternatives[0] if alternatives else ""
        lesson_text = str(parsed.get("lesson") or "")[:280]
        lesson = {
            "organism_id": organism_id,
            "situation_key": situation,
            "scenario": scenario,
            "regime": regime,
            "avoid": avoid,
            "prefer": prefer,
            "lesson": lesson_text,
            "from_severity": severity,
            "producer_type": LOCAL_7B_PRODUCER_TYPE,
            "behavioral_authority": BEHAVIORAL_AUTHORITY_NONE,
        }
        self._persist_lesson(lesson)
        return lesson

    def _persist_lesson(self, lesson: Dict[str, Any]) -> None:
        """Persiste una propuesta auditable con autoridad conductual nula."""
        proposal = {
            **lesson,
            "producer_type": LOCAL_7B_PRODUCER_TYPE,
            "behavioral_authority": BEHAVIORAL_AUTHORITY_NONE,
        }
        try:
            self.storage.append_event(
                event_type="experience.lesson",
                run_id=LOCAL_7B_PRODUCER_TYPE,
                source=LOCAL_7B_PRODUCER_TYPE,
                payload=proposal,
            )
        except Exception:
            pass
