"""Gestor de transición de escala para MSRC.

Atomicidad (CANON §3.1.6)
-------------------------
``ScaleTransitionManager`` no tiene estado propio: ``execute_action`` RECIBE la
escala de origen y DEVUELVE la escala seleccionada. Quien aplica el cambio es el
llamador (``MSRCController.step``), y solo aplica lo que este método devuelve.

Por eso, ante una excepción, ``execute_action`` devuelve la escala de ORIGEN: la
transición se ABORTA **antes** de aplicarse. No hay nada que revertir porque nada
llegó a aplicarse — es un *abort*, no un *rollback*. Si en el futuro leés un
"rollback que no revierte nada", no es un bug: es que el commit vive en el
llamador y solo ocurre en el camino de éxito.

Esa garantía vale SOLO si nadie más escribe ``state.current_scale_id``. El
``ScalePolicyEngine`` lo escribía (decidía y aplicaba a la vez), y entonces un
abort dejaba pegada la escala nueva: la atomicidad estaba rota de hecho. La SSOT
del commit de escala es ``MSRCController.step``; ver el test de atomicidad en
``tests/msrc/test_msrc_controller.py``.

Costes: medido vs estimado
--------------------------
``estimated_*`` sale del catálogo. ``real_*`` se llena SOLO con lo que se midió
de verdad; si no hubo medición vale ``None`` y el nombre del campo queda listado
en ``unmeasured_costs``. Nunca se rellena un ``real_*`` con la estimación del
catálogo ni con un cero inventado: un registro que copia la estimación dentro del
campo "real" destruye la comparación para la que existe el contrato
``msrc_transition_event`` (que exige ambos, justamente para poder contrastarlos).

La única acción que hoy mide de verdad es ``fork_probe``: el probe ejecuta un
episodio real en la escala destino, así que su wall time SÍ es el coste real de
correr ahí. Esa medición viaja dentro del ``ProbeResult`` y ``commit_probe_result``
la commitea. Un ``upgrade_scale``/``downgrade_scale`` sin probe no ejecutó nada en
la escala nueva: su coste real es NO MEDIDO, no "igual al estimado".

Cronometrar los lookups de diccionario de este manager (microsegundos) no es el
coste de la transición: sería medir el objeto equivocado y hacerlo pasar por la
medición buena. No se hace.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from runtime.storage.records import utc_now_iso

from .contracts import (
    REAL_COST_FIELDS,
    ProbeResult,
    ScaleAction,
    ScaleEstimate,
    ScaleTransitionRecord,
)
from .scale_catalog import ScaleCatalog


ProbeExecutor = Callable[[str], ProbeResult]

#: Acciones que no ejecutan trabajo en la escala destino y por lo tanto no pueden
#: medir su coste. No confundir con "coste cero".
_NON_EXECUTING_ACTIONS = {"keep_scale", "lock_scale_for_n_steps", "discard_probe_result"}

#: Unidades de cada coste. Se declaran en metadata porque NO son conmensurables:
#: el catálogo expresa el tiempo en unidades relativas (1.0, 2.2, 12.0) y la
#: medición está en milisegundos. Comparar ``estimated_time_cost`` con
#: ``real_time_cost`` exige normalizar antes; dejarlo implícito invita a restarlos.
_COST_UNITS = {
    "estimated_time_cost": "catalog_relative",
    "estimated_artifact_cost": "catalog_relative",
    "real_time_cost": "milliseconds",
    "real_artifact_cost": "artifact_count",
}


class ScaleTransitionManager:
    """Coordina cambios de escala, probes y abort de transición.

    Sin estado mutable: el catálogo es lo único que guarda. Ver el docstring del
    módulo para la garantía de atomicidad.
    """

    def __init__(self, *, catalog: ScaleCatalog):
        self.catalog = catalog

    def execute_action(
        self,
        *,
        run_id: str,
        episode_id: str,
        current_scale_id: str,
        action: ScaleAction,
        estimate: ScaleEstimate,
        probe_executor: Optional[ProbeExecutor] = None,
        probe_result: Optional[ProbeResult] = None,
    ) -> Dict[str, Any]:
        """Ejecuta una acción de escala y devuelve la escala seleccionada.

        ``probe_result`` es el resultado del ``fork_probe`` de un step anterior,
        que el llamador conserva y devuelve acá. Es lo que permite que
        ``commit_probe_result`` commitee **lo que el probe midió** en vez de la
        estimación del catálogo.

        Nunca lanza: ante un fallo devuelve ``current_scale_id`` (abort) y un
        registro con ``transition_aborted=True`` y el motivo.
        """
        target_scale_id = action.target_scale_id or current_scale_id

        try:
            if action.action_type == "fork_probe":
                return self._run_fork_probe(
                    run_id=run_id,
                    episode_id=episode_id,
                    current_scale_id=current_scale_id,
                    target_scale_id=target_scale_id,
                    action=action,
                    estimate=estimate,
                    probe_executor=probe_executor,
                )

            if action.action_type in _NON_EXECUTING_ACTIONS:
                # No se ejecuta nada en ninguna escala nueva: no hay coste real que
                # medir. Se declara NO MEDIDO en vez de inventar un 0.0.
                return {
                    "selected_scale_id": current_scale_id,
                    "probe_result": None,
                    "transition_record": self._build_record(
                        run_id=run_id,
                        episode_id=episode_id,
                        action=action,
                        source_scale_id=current_scale_id,
                        target_scale_id=current_scale_id,
                        estimate=estimate,
                        real_time_cost=None,
                        real_artifact_cost=None,
                        ioc_delta=0.0,
                        viability_delta=0.0,
                        transition_aborted=False,
                    ),
                }

            if action.action_type in {"upgrade_scale", "downgrade_scale", "commit_probe_result"}:
                return self._run_scale_change(
                    run_id=run_id,
                    episode_id=episode_id,
                    current_scale_id=current_scale_id,
                    target_scale_id=target_scale_id,
                    action=action,
                    estimate=estimate,
                    probe_result=probe_result,
                )

            raise ValueError(f"Acción de escala no soportada: {action.action_type}")

        except Exception as exc:
            # ABORT, no rollback: la escala nunca se aplicó (el commit es del
            # llamador y solo ocurre con lo que devolvemos acá). Devolvemos el
            # origen => el llamador deja la escala como estaba.
            abort_reason = f"{type(exc).__name__}: {exc}"
            record = self._build_record(
                run_id=run_id,
                episode_id=episode_id,
                action=action,
                source_scale_id=current_scale_id,
                target_scale_id=current_scale_id,
                estimate=estimate,
                real_time_cost=None,
                real_artifact_cost=None,
                ioc_delta=0.0,
                viability_delta=-1.0,
                transition_aborted=True,
                abort_reason=abort_reason,
                extra_metadata={"error": abort_reason},
            )
            return {
                "selected_scale_id": current_scale_id,
                "probe_result": None,
                "transition_record": record,
            }

    def _run_fork_probe(
        self,
        *,
        run_id: str,
        episode_id: str,
        current_scale_id: str,
        target_scale_id: str,
        action: ScaleAction,
        estimate: ScaleEstimate,
        probe_executor: Optional[ProbeExecutor],
    ) -> Dict[str, Any]:
        if probe_executor is None:
            raise RuntimeError("probe_executor requerido para fork_probe")

        # Cronometramos EXACTAMENTE la ejecución del probe (que corre un episodio
        # real en la escala destino), no el trabajo administrativo del manager.
        started = time.perf_counter()
        result = probe_executor(target_scale_id)
        probe_wall_ms = (time.perf_counter() - started) * 1000.0

        time_cost, artifact_cost, source = self._probe_measurements(result, probe_wall_ms)

        # La medición se adjunta al ProbeResult para que sobreviva hasta el
        # commit_probe_result (que ocurre en un step posterior).
        measured_probe = replace(
            result,
            measured_time_cost_ms=time_cost,
            measured_artifact_cost=artifact_cost,
        )

        # El probe NO mueve al organismo: seguimos en la escala de origen. Pero el
        # registro es SOBRE la escala probada, así que su target es la escala
        # probada: es la única forma de que estimated_* y real_* hablen de la misma
        # escala y la comparación signifique algo.
        return {
            "selected_scale_id": current_scale_id,
            "probe_result": measured_probe,
            "transition_record": self._build_record(
                run_id=run_id,
                episode_id=episode_id,
                action=action,
                source_scale_id=current_scale_id,
                target_scale_id=target_scale_id,
                estimate=estimate,
                real_time_cost=time_cost,
                real_artifact_cost=artifact_cost,
                ioc_delta=result.cognitive_gain_delta,
                viability_delta=0.0 if result.viability_preserved else -1.0,
                transition_aborted=False,
                cost_measurement_source=source,
                extra_metadata={"probe_scale_id": target_scale_id, "probe_moved_scale": False},
            ),
        }

    def _run_scale_change(
        self,
        *,
        run_id: str,
        episode_id: str,
        current_scale_id: str,
        target_scale_id: str,
        action: ScaleAction,
        estimate: ScaleEstimate,
        probe_result: Optional[ProbeResult],
    ) -> Dict[str, Any]:
        if not self.catalog.has_scale(target_scale_id):
            raise KeyError(f"Escala destino inválida: {target_scale_id}")

        target_spec = self.catalog.get(target_scale_id)
        if not target_spec.is_executable:
            target_spec = self.catalog.nearest_executable(target_scale_id)
            target_scale_id = target_spec.scale_id

        real_time_cost: Optional[float] = None
        real_artifact_cost: Optional[float] = None
        measurement_source = "none"
        ioc_delta = action.expected_gain
        viability_delta = 0.0
        extra: Dict[str, Any] = {}

        if action.action_type == "commit_probe_result":
            # El trabajo entero de esta acción es commitear lo que el probe midió.
            # Si acá escribiéramos la estimación del catálogo, tendríamos la medición
            # real y la tiraríamos justo al commitear.
            measured = self._probe_for_commit(probe_result, target_scale_id)
            if measured is not None:
                real_time_cost = measured.measured_time_cost_ms
                real_artifact_cost = measured.measured_artifact_cost
                # "probe_execution" solo si el probe TRAE alguna medicion. Un probe sin
                # mediciones no vuelve medido un registro por el mero hecho de existir.
                if real_time_cost is not None or real_artifact_cost is not None:
                    measurement_source = "probe_execution"
                ioc_delta = measured.cognitive_gain_delta
                viability_delta = 0.0 if measured.viability_preserved else -1.0
                extra["committed_probe"] = {
                    "target_scale_id": measured.target_scale_id,
                    "outcome": measured.outcome,
                    "evidence_score": measured.evidence_score,
                }
            else:
                # Commit sin ProbeResult disponible: no hay medición que commitear.
                # Se declara, no se inventa.
                extra["commit_without_probe_measurements"] = True
        else:
            # upgrade/downgrade sin probe: NO se ejecutó nada en la escala nueva, así
            # que su coste real no se midió. La estimación del catálogo ya viaja en
            # estimated_* y no tiene por qué disfrazarse de medición.
            extra["scale_change_without_probe"] = True

        return {
            "selected_scale_id": target_scale_id,
            "probe_result": None,
            "transition_record": self._build_record(
                run_id=run_id,
                episode_id=episode_id,
                action=action,
                source_scale_id=current_scale_id,
                target_scale_id=target_scale_id,
                estimate=estimate,
                real_time_cost=real_time_cost,
                real_artifact_cost=real_artifact_cost,
                ioc_delta=ioc_delta,
                viability_delta=viability_delta,
                transition_aborted=False,
                cost_measurement_source=measurement_source,
                extra_metadata=extra,
            ),
        }

    def _probe_measurements(
        self,
        probe_result: ProbeResult,
        probe_wall_ms: float,
    ) -> Tuple[Optional[float], Optional[float], str]:
        """Extrae las mediciones reales del probe.

        El tiempo lo puede reportar el propio productor del ``ProbeResult`` (más
        preciso, excluye el overhead del fork); si no lo reporta, usamos el wall
        time que acabamos de cronometrar alrededor de su ejecución. Ambas son
        mediciones reales.

        El coste de artefactos SOLO existe si el productor lo instrumentó. Hoy
        ninguno lo hace, así que queda ``None`` = NO MEDIDO.
        """
        reported_time = probe_result.measured_time_cost_ms
        if reported_time is not None:
            return float(reported_time), probe_result.measured_artifact_cost, "probe_reported"
        return probe_wall_ms, probe_result.measured_artifact_cost, "probe_execution"

    def _probe_for_commit(
        self,
        probe_result: Optional[ProbeResult],
        target_scale_id: str,
    ) -> Optional[ProbeResult]:
        """Devuelve el ProbeResult a commitear, si corresponde a la escala destino."""
        if probe_result is None:
            return None
        if probe_result.target_scale_id != target_scale_id:
            # Commitear la medición de OTRA escala sería peor que no medir.
            return None
        return probe_result

    def _build_record(
        self,
        *,
        run_id: str,
        episode_id: str,
        action: ScaleAction,
        source_scale_id: str,
        target_scale_id: str,
        estimate: ScaleEstimate,
        real_time_cost: Optional[float],
        real_artifact_cost: Optional[float],
        ioc_delta: float,
        viability_delta: float,
        transition_aborted: bool,
        abort_reason: Optional[str] = None,
        cost_measurement_source: str = "none",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ScaleTransitionRecord:
        target_spec = self.catalog.get(target_scale_id)
        metadata = {
            "required_resolution_score": estimate.required_resolution_score,
            "risk_score": estimate.risk_score,
            "vram_pressure": estimate.vram_pressure,
            "vram_opportunity_score": estimate.vram_opportunity_score,
            "cost_units": dict(_COST_UNITS),
            **action.metadata,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        real_values = {
            "real_time_cost": real_time_cost,
            "real_artifact_cost": real_artifact_cost,
        }
        unmeasured: List[str] = [name for name in REAL_COST_FIELDS if real_values[name] is None]

        return ScaleTransitionRecord(
            run_id=run_id,
            episode_id=episode_id,
            action_type=action.action_type,
            source_scale_id=source_scale_id,
            target_scale_id=target_scale_id,
            reason=action.reason,
            estimated_time_cost=target_spec.expected_time_cost,
            estimated_artifact_cost=target_spec.expected_artifact_cost,
            real_time_cost=real_time_cost,
            real_artifact_cost=real_artifact_cost,
            ioc_delta=ioc_delta,
            viability_delta=viability_delta,
            transition_aborted=transition_aborted,
            timestamp=utc_now_iso(),
            abort_reason=abort_reason,
            unmeasured_costs=unmeasured,
            cost_measurement_source=cost_measurement_source,
            metadata=metadata,
        )
