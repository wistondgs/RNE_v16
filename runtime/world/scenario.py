"""Interfaz base para escenarios cognitivos mínimos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .compatibility import ScenarioStructuralProfile
    from .causal_signature import ScenarioCausalSignature


#: H-047. El escenario ES el mundo, y el mundo tiene historia: el organismo lo
#: calienta, lo enfría, dispara su alarma. Hasta ahora esa historia moría con el
#: runner, que el kernel suelta cada `block_size` episodios — medido: el paso 7
#: cerraba a 0.98 con la alarma encendida y el paso 8 nacía a 0.82 sin alarma.
#:
#: Es I-05 del Canon 2.1 de Terrario: «mundo declarado = mundo ejecutado».
WORLD_STATE_SCHEMA = "world-state-v1"


@dataclass
class ScenarioObservation:
    """Observación del estado del escenario.

    Attributes:
        state: Diccionario con estado observable del mundo.
        propositions: Lista de proposiciones inferibles del estado.
        alarm: Indicador de condición de alarma/umbral.
        level: Nivel discreto del mundo (1=SAFE, 2=ELEVATED, 3=WARNING, 4=CRITICAL).
    """

    state: Dict[str, Any]
    propositions: List[str]
    alarm: bool
    level: int = 1


@dataclass
class ScenarioTransition:
    """Resultado de transición del escenario.

    Attributes:
        state: Nuevo estado después de la transición.
        propositions: Proposiciones actualizadas.
        alarm: Estado de alarma actualizado.
        level: Nivel discreto del mundo (1=SAFE, 2=ELEVATED, 3=WARNING, 4=CRITICAL).
    """

    state: Dict[str, Any]
    propositions: List[str]
    alarm: bool
    level: int = 1


@dataclass
class ScenarioConfig:
    """Configuración de un escenario cognitivo.

    Attributes:
        name: Nombre único del escenario.
        description: Descripción del escenario.
        main_variable: Variable principal del escenario.
        alarm_threshold: Umbral para activar alarma.
        interventions: Lista de intervenciones válidas.
        formula_template: Plantilla de fórmula LOTF.
        type_context: Contexto de tipos para checker LOTF.
    """

    name: str
    description: str
    main_variable: str
    alarm_threshold: float
    interventions: List[str]
    formula_template: str
    type_context: Dict[str, str]


class CognitiveScenario(ABC):
    """Interfaz base para escenarios cognitivos mínimos.

    Un escenario cognitivo define:
    - Estado observable del mundo
    - Transiciones factual y contrafactual
    - Proposiciones y fórmulas LOTF
    - Mapeo a signos SMG
    """

    @property
    @abstractmethod
    def config(self) -> ScenarioConfig:
        """Retorna configuración del escenario."""
        ...

    @property
    @abstractmethod
    def structural_profile(self) -> ScenarioStructuralProfile:
        """Retorna perfil estructural para evaluación de compatibilidad."""
        ...

    @property
    @abstractmethod
    def causal_signature(self) -> ScenarioCausalSignature:
        """Retorna firma causal completa para morfismos dirigidos."""
        ...

    @abstractmethod
    def observe(self) -> ScenarioObservation:
        """Observa el estado actual del escenario.

        Returns:
            ScenarioObservation con estado, proposiciones y alarma.
        """
        ...

    @abstractmethod
    def factual_transition(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        """Ejecuta transición factual con intervención.

        Args:
            intervention: Intervención a aplicar.
            external_input: Entrada externa (perturbación).

        Returns:
            ScenarioTransition con nuevo estado.
        """
        ...

    @abstractmethod
    def simulate_counterfactual(
        self,
        *,
        intervention: str,
        external_input: float,
    ) -> ScenarioTransition:
        """Simula transición contrafactual sin mutar estado.

        Args:
            intervention: Intervención hipotética.
            external_input: Entrada externa simulada.

        Returns:
            ScenarioTransition con estado simulado.
        """
        ...

    @abstractmethod
    def get_formula(self, observation: ScenarioObservation) -> str:
        """Genera fórmula LOTF para la observación.

        Args:
            observation: Observación actual.

        Returns:
            String con fórmula LOTF.
        """
        ...

    @abstractmethod
    def select_intervention(self, observation: ScenarioObservation) -> str:
        """Selecciona intervención apropiada para la observación.

        Args:
            observation: Observación actual.

        Returns:
            Nombre de la intervención a aplicar.
        """
        ...

    @abstractmethod
    def get_main_proposition(self, observation: ScenarioObservation) -> str:
        """Obtiene proposición principal de la observación.

        Args:
            observation: Observación actual.

        Returns:
            Proposición principal (e.g., 'TEMP_HIGH').
        """
        ...

    # ── continuidad del mundo (H-047) ───────────────────────────────────────
    #
    # Concretos, no abstractos: los cuatro escenarios del árbol guardan su mundo
    # en un único `self._state` que es un dataclass, así que una implementación
    # sirve para todos y un escenario nuevo la hereda sin escribir nada. Uno que
    # guarde su estado de otra forma sobreescribe estos dos métodos.

    def export_world_state(self) -> Dict[str, Any]:
        """El estado del mundo, con el nombre del escenario que lo produjo.

        El nombre viaja porque un estado térmico cargado en un mundo de recursos
        pondría campos que no significan lo mismo, y el mundo quedaría en una
        configuración que nunca existió.
        """
        estado = getattr(self, "_state", None)
        return {
            "schema_version": WORLD_STATE_SCHEMA,
            "scenario_name": self.config.name,
            "state": asdict(estado) if is_dataclass(estado) else None,
        }

    def restore_world_state(self, payload: Optional[Dict[str, Any]]) -> bool:
        """`None`/`{}` ⇒ arranque limpio. Esquema o escenario ajeno ⇒ error.

        Devuelve si restauró. No hay silencio intermedio: un payload que no se
        entiende es un fallo, no un no-op, porque seguir con el mundo virgen
        mientras el organismo cree venir de otro sitio es la clase de desajuste
        que esta reparación existe para impedir.
        """
        if not payload:
            return False
        schema = payload.get("schema_version")
        if schema != WORLD_STATE_SCHEMA:
            raise ValueError(f"world_state_schema_unknown: {schema!r}")
        nombre = payload.get("scenario_name")
        if nombre != self.config.name:
            raise ValueError(
                f"world_state_scenario_mismatch: el payload es de {nombre!r} "
                f"y este escenario es {self.config.name!r}"
            )
        valores = payload.get("state")
        estado = getattr(self, "_state", None)
        if not valores or not is_dataclass(estado):
            return False
        conocidos = {f.name for f in fields(estado)}
        self._state = replace(estado, **{k: v for k, v in valores.items() if k in conocidos})
        return True

    @abstractmethod
    def get_intervention_proposition(self, intervention: str) -> str:
        """Obtiene proposición correspondiente a la intervención.

        Args:
            intervention: Intervención aplicada.

        Returns:
            Proposición de intervención (e.g., 'ACTIVATE_COOLING').
        """
        ...

    def evaluate_relation_kind(
        self,
        *,
        factual: ScenarioTransition,
        counterfactual: ScenarioTransition,
    ) -> str:
        """Evalúa tipo de relación entre factual y contrafactual.

        Default implementation assumes lower values are better (e.g., temperature
        in thermal scenarios where lower = cooler = better). Scenarios with different
        optimization goals (e.g., resources where higher stock = better) should
        override this method to provide appropriate comparison logic.

        Args:
            factual: Transición factual.
            counterfactual: Transición contrafactual.

        Returns:
            'support' o 'contradiction'.
        """
        main_var = self.config.main_variable
        factual_val = factual.state.get(main_var, 0.0)
        counterfactual_val = counterfactual.state.get(main_var, 0.0)

        # Default: lower values are better (suitable for thermal scenario)
        # Override in scenarios where higher values are better
        if factual_val <= counterfactual_val:
            return "support"
        return "contradiction"

    def to_observation_dict(self, observation: ScenarioObservation) -> Dict[str, Any]:
        """Convierte observación a diccionario para persistencia.

        Args:
            observation: Observación del escenario.

        Returns:
            Diccionario con estado y metadata.
        """
        return {
            **observation.state,
            "alarm": observation.alarm,
            "propositions": observation.propositions,
            "scenario": self.config.name,
        }

    def to_transition_dict(self, transition: ScenarioTransition) -> Dict[str, Any]:
        """Convierte transición a diccionario para persistencia.

        Args:
            transition: Transición del escenario.

        Returns:
            Diccionario con estado y metadata.
        """
        return {
            **transition.state,
            "alarm": transition.alarm,
        }
