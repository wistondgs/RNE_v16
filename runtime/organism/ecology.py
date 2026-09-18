"""Ecología multi-organismo (canon f2.4: μₜ linaje + selección por fitness certificado).

AEON corre por defecto UN organismo. Esta ecología orquesta una POBLACIÓN: varios
organismos exploran en paralelo el paisaje de recompensa del canon
(r = ΔIoC* − λE·ΔE − λB·B_safe), y — según el modo de transferencia — comparten la
política de razonamiento aprendida y heredan la de los más aptos. El objetivo es
*multiplicar la ganancia cognitiva*: la colonia converge más rápido que un individuo
sobre qué razonamiento paga en cada régimen.

Anti-engaño por construcción:
- **Fitness GUARDADO**: solo cuentan episodios certificados con cierre estable. Un
  organismo sin episodios certificados tiene fitness −∞ (es eliminado). No se puede
  "ganar" rompiendo seguridad o cierre.
- **Herencia REAL**: la reproducción activa `LineageState.check_inheritance_eligibility`
  (código que existía pero nadie llamaba) — solo se hereda lo elegible.
- **Transferencia GATED**: el cruce de contexto entre escenarios pasa por el morfismo
  causal real; las clases adversarial/incompatible bloquean la transferencia.
- **Auditable**: cada selección/reproducción/transferencia se persiste como evento
  `ecology.*` y se resume JSON-safe.

Modos de transferencia (`TransferMode`):
- ``isolated``: organismos que aprenden individualmente (reward-guided ON) pero NO
  forman colonia (ni herencia ni compartir). Baseline honesto del experimento.
- ``inheritance_only``: + reproducción con herencia padre→hijo (evidencia + knobs).
- ``reasoning_policy``: + compartir en vivo entre pares la evidencia Δr̄-por-régimen
  (morfismo-gated en cruce de escenario).
- ``reasoning_policy_plus_rules``: + transferir reglas IND vía morfismo + assess_transfer.

Python puro, determinista (semillas), sqlite; sin dependencias nuevas, sin GPU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import os
import random
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from runtime.organism.lineage import LineageState
from runtime.organism.state import OrganismState
from runtime.reasoning.scheduler_meta.reward_guided import (
    Observation,
    RewardGuidedOverlaySelector,
)
from runtime.storage.records import utc_now_iso
from runtime.world.scenario_runner import ScenarioEpisodeRunner


class TransferMode(str, Enum):
    ISOLATED = "isolated"
    INHERITANCE_ONLY = "inheritance_only"
    REASONING_POLICY = "reasoning_policy"
    REASONING_POLICY_PLUS_RULES = "reasoning_policy_plus_rules"


# Mando mutable acotado y su rango (reproducción introduce variación aquí).
_KNOB_SPACE: Dict[str, List[Any]] = {
    "memory_retrieval_limit": [2, 3, 4, 5],
    "memory_filter_mode": ["strict_same_scenario", "cross_scenario_analogical"],
}


@dataclass
class EcologyMember:
    """Un organismo de la población: identidad + linaje + knobs + política aprendida."""

    member_id: str
    scenario: str
    scenario_kwargs: Dict[str, Any]
    lineage: LineageState
    selector: RewardGuidedOverlaySelector
    knobs: Dict[str, Any]
    # Perfil de familias del organismo. Por defecto la exploración total, que
    # admite TODAS las opcionales (incl. plan/opt) — el selector guiado-por-
    # recompensa decide cuáles usar. Permite diversidad de población.
    profile: str = "full_family_exploration"
    organism_state: Optional[OrganismState] = None
    inherited_rules: List[Dict[str, Any]] = field(default_factory=list)
    fitness: float = float("-inf")
    certified_episodes: int = 0
    total_episodes: int = 0
    generation_born: int = 0

    @property
    def run_id(self) -> str:
        # El run_id agrupa toda la evidencia/eventos del organismo en storage.
        return f"ecology-{self.member_id}"


def _safe_float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class OrganismEcology:
    """Población de organismos con selección por fitness certificado y transferencia."""

    def __init__(
        self,
        members: Sequence[EcologyMember],
        *,
        storage,
        transfer_mode: TransferMode = TransferMode.REASONING_POLICY,
        survivor_fraction: float = 0.5,
        seed: int = 0,
        closure_profile: str = "adaptive_min",
        reasoning_max_steps: int = 10,
    ) -> None:
        self.members: List[EcologyMember] = list(members)
        self.storage = storage
        self.transfer_mode = TransferMode(transfer_mode)
        self.survivor_fraction = survivor_fraction
        self.closure_profile = closure_profile
        self.reasoning_max_steps = reasoning_max_steps
        self._rng = random.Random(seed)
        self.generation = 0
        self._spawn_counter = 0
        self.history: List[Dict[str, Any]] = []

    # ----------------------------------------------------------- generación

    def run_generation(self, episodes_per_member: int) -> Dict[str, Any]:
        """Cada miembro corre K episodios; luego comparte, evalúa y selecciona."""
        self.generation += 1
        for member in self.members:
            self._run_member(member, episodes_per_member)

        if self.transfer_mode in (
            TransferMode.REASONING_POLICY,
            TransferMode.REASONING_POLICY_PLUS_RULES,
        ):
            self._share_knowledge()

        for member in self.members:
            member.fitness = self._fitness(member)

        ranking = sorted(self.members, key=lambda m: m.fitness, reverse=True)
        reproduction = self._select_and_reproduce(ranking)

        summary = {
            "generation": self.generation,
            "transfer_mode": self.transfer_mode.value,
            "ranking": [
                {
                    "member_id": m.member_id,
                    "fitness": None if math.isinf(m.fitness) else round(m.fitness, 6),
                    "certified_episodes": m.certified_episodes,
                    "total_episodes": m.total_episodes,
                    "generation_born": m.generation_born,
                    "consistency_score": round(m.lineage.consistency_score(), 4),
                }
                for m in ranking
            ],
            "reproduction": reproduction,
        }
        self.history.append(summary)
        self._emit("ecology.generation", summary)
        return summary

    def _run_member(self, member: EcologyMember, episodes: int) -> None:
        runner = ScenarioEpisodeRunner(
            storage=self.storage,
            run_id=member.run_id,
            scenario=member.scenario,
            scenario_kwargs=member.scenario_kwargs or None,
            memory_filter_mode=member.knobs.get("memory_filter_mode", "strict_same_scenario"),
            closure_profile=self.closure_profile,
            organism_state=member.organism_state,
            lineage=member.lineage,
            reward_guided=member.selector,
        )
        # §XXXVIII: el genoma del miembro es una intención, no una escritura
        # lateral. La ecología construye su propio runner, así que no toca el
        # organismo del kernel, pero pasa por la misma autoridad y la misma
        # validación que las demás fuentes.
        runner.apply_parameter_intent(
            {"memory_retrieval_limit": member.knobs.get("memory_retrieval_limit", 3)},
            source="ecology",
            reason=f"genoma del miembro {member.member_id}" if hasattr(member, "member_id") else "genoma del miembro",
        )
        if self.transfer_mode == TransferMode.REASONING_POLICY_PLUS_RULES and member.inherited_rules:
            runner._inherited_rules = list(member.inherited_rules)

        prev_steps = os.environ.get("RNFE_REASONING_MAX_STEPS")
        prev_profile = os.environ.get("RNFE_REASONING_FAMILY_PROFILE")
        prev_mode = os.environ.get("RNFE_REASONING_MODE")
        os.environ["RNFE_REASONING_MAX_STEPS"] = str(self.reasoning_max_steps)
        os.environ["RNFE_REASONING_FAMILY_PROFILE"] = member.profile
        os.environ["RNFE_REASONING_MODE"] = "adaptive"
        try:
            for _ in range(episodes):
                runner.run_episode(external_input=0.04)
        finally:
            for key, prev in (
                ("RNFE_REASONING_MAX_STEPS", prev_steps),
                ("RNFE_REASONING_FAMILY_PROFILE", prev_profile),
                ("RNFE_REASONING_MODE", prev_mode),
            ):
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev
        # Continuidad de vida: el siguiente generación parte del estado vivo.
        member.organism_state = runner.organism_state

    # -------------------------------------------------------------- fitness

    def _fitness(self, member: EcologyMember) -> float:
        """Recompensa canon media sobre episodios CERTIFICADOS con cierre estable.

        Lee los eventos reasoning.reward y los certificados del run del miembro.
        Sin episodios certificados ⇒ −inf (será eliminado). Anti-engaño: no se
        puede subir el fitness rompiendo cierre/seguridad.
        """
        certified_ids = self._certified_episode_ids(member.run_id)
        rewards: List[float] = []
        total = 0
        try:
            events = self.storage.list_events(run_id=member.run_id, limit=1024)
        except Exception:
            events = []
        for item in events:
            if getattr(item, "event_type", None) != "reasoning.reward":
                continue
            total += 1
            payload = getattr(item, "payload", None) or {}
            episode_id = payload.get("episode_id")
            reward = _safe_float(payload.get("reward"))
            if reward is not None and episode_id in certified_ids:
                rewards.append(reward)
        member.total_episodes = total
        member.certified_episodes = len(rewards)
        if not rewards:
            return float("-inf")
        return sum(rewards) / len(rewards)

    def _certified_episode_ids(self, run_id: str) -> set:
        """IDs de episodios con certificado certified y cierre estable."""
        ids: set = set()
        try:
            certs = self.storage.list_episode_certificates(run_id=run_id, limit=1024)
        except Exception:
            certs = []
        for cert in certs:
            verdict = getattr(cert, "verdict", None)
            if verdict != "certified":
                continue
            meta = getattr(cert, "metadata", None) or {}
            if meta.get("closure_passed") is False:
                continue
            episode_id = getattr(cert, "episode_id", None) or meta.get("episode_id")
            if episode_id:
                ids.add(episode_id)
        return ids

    # ---------------------------------------------------- selección + cría

    def _select_and_reproduce(self, ranking: List[EcologyMember]) -> Dict[str, Any]:
        n = len(ranking)
        n_survivors = max(1, int(round(n * self.survivor_fraction)))
        survivors = [m for m in ranking if not math.isinf(m.fitness)][:n_survivors]
        if not survivors:  # nadie certificó: la población se mantiene, no hay cría
            return {"survivors": [], "culled": [], "offspring": []}
        culled = ranking[len(survivors):]

        offspring_records: List[Dict[str, Any]] = []
        new_members: List[EcologyMember] = list(survivors)
        for slot, _dead in enumerate(culled):
            parent = survivors[slot % len(survivors)]
            child = self._reproduce(parent)
            new_members.append(child)
            offspring_records.append(
                {
                    "child_id": child.member_id,
                    "parent_id": parent.member_id,
                    "inherited": child.lineage.inherited_certificates[-1:],
                    "mutated_knob": child.knobs.get("_mutated"),
                }
            )
        self.members = new_members
        return {
            "survivors": [m.member_id for m in survivors],
            "culled": [m.member_id for m in culled],
            "offspring": offspring_records,
        }

    def _reproduce(self, parent: EcologyMember) -> EcologyMember:
        """Cría un hijo del padre: herencia GATED + mutación de un knob."""
        self._spawn_counter += 1
        child_id = f"{parent.member_id}.g{self.generation}s{self._spawn_counter}"

        # Gate de herencia REAL (activa el código muerto de lineage).
        eligible, failed = parent.lineage.check_inheritance_eligibility(
            is_certified_safe=parent.certified_episodes > 0,
            is_constitution_consistent=True,  # misma constitución compartida
            is_baseline_preserved=not math.isinf(parent.fitness),
            is_contamination_free=len(parent.lineage.rollback_ancestry) == 0,
        )

        child_lineage = LineageState(lineage_id=f"lineage-{child_id}")
        child_lineage.record_genesis(_ANY_CONSTITUTION(), timestamp=utc_now_iso())
        child_lineage.record_divergence(
            divergence_id=f"div-{child_id}",
            description=f"offspring of {parent.member_id} (eligible={eligible})",
            timestamp=utc_now_iso(),
        )

        child_selector = RewardGuidedOverlaySelector(storage=self.storage)
        child_knobs = dict(parent.knobs)
        inherited_rules: List[Dict[str, Any]] = []

        if eligible:
            # Heredar la política aprendida (evidencia Δr̄) y los knobs del padre.
            child_selector.merge_from(
                f"ecology-{child_id}",
                parent.selector.export_evidence(parent.run_id),
                eligible=True,
            )
            child_lineage.inherited_certificates.append(f"policy-from-{parent.member_id}")
            child_lineage.record_modification(
                modification_id=f"inherit-{child_id}",
                description=f"inherited reasoning policy from {parent.member_id}",
                posterior=min(1.0, parent.lineage.consistency_score()),
                timestamp=utc_now_iso(),
            )
            if self.transfer_mode == TransferMode.REASONING_POLICY_PLUS_RULES:
                inherited_rules = list(parent.inherited_rules)
        else:
            self._emit(
                "ecology.inheritance_blocked",
                {"child_id": child_id, "parent_id": parent.member_id, "failed_rules": failed},
            )

        # Mutación: variar UN knob (vecino en el espacio acotado).
        mutated = self._mutate_knob(child_knobs)

        child = EcologyMember(
            member_id=child_id,
            scenario=parent.scenario,
            scenario_kwargs=dict(parent.scenario_kwargs),
            lineage=child_lineage,
            selector=child_selector,
            knobs=child_knobs,
            profile=parent.profile,
            inherited_rules=inherited_rules,
            generation_born=self.generation,
        )
        self._emit(
            "ecology.reproduction",
            {
                "child_id": child_id,
                "parent_id": parent.member_id,
                "eligible": eligible,
                "failed_rules": failed,
                "mutated_knob": mutated,
            },
        )
        return child

    def _mutate_knob(self, knobs: Dict[str, Any]) -> Dict[str, Any]:
        knob = self._rng.choice(list(_KNOB_SPACE.keys()))
        choices = [v for v in _KNOB_SPACE[knob] if v != knobs.get(knob)]
        new_value = self._rng.choice(choices) if choices else knobs.get(knob)
        knobs[knob] = new_value
        knobs["_mutated"] = {"knob": knob, "value": new_value}
        return knobs["_mutated"]

    # -------------------------------------------------------- transferencia

    def _share_knowledge(self) -> None:
        """Comparte la política aprendida entre pares (morfismo-gated en cruce)."""
        morphism_cache: Dict[Tuple[str, str], Any] = {}
        applied = 0
        blocked = 0
        # Cada par ordenado (donante→receptor): el receptor fusiona la evidencia
        # del donante. Mismo escenario ⇒ sin morfismo (idéntico). Distinto ⇒ gated.
        for donor in list(self.members):
            donor_obs = donor.selector.export_evidence(donor.run_id)
            if not donor_obs:
                continue
            for recipient in self.members:
                if recipient is donor:
                    continue
                morphism = None
                if recipient.scenario != donor.scenario:
                    morphism = self._morphism_for(
                        donor.scenario, recipient.scenario, morphism_cache
                    )
                merged = recipient.selector.merge_from(
                    recipient.run_id, donor_obs, morphism=morphism, eligible=True
                )
                if merged > 0:
                    applied += merged
                    if self.transfer_mode == TransferMode.REASONING_POLICY_PLUS_RULES:
                        self._transfer_rules(donor, recipient, morphism)
                else:
                    blocked += 1
        self._emit(
            "ecology.knowledge_shared",
            {"generation": self.generation, "observations_merged": applied, "pairs_blocked": blocked},
        )

    def _transfer_rules(
        self, donor: EcologyMember, recipient: EcologyMember, morphism: Any
    ) -> None:
        """Transfiere la mejor regla IND del donante al receptor (assess_transfer-gated)."""
        rule = self._latest_induced_rule(donor.run_id)
        if rule is None or not rule.get("best_intervention"):
            return
        # Transportar el best_intervention por el proposition_map del morfismo.
        best_iv = rule["best_intervention"]
        info_loss = 0.0
        overall = 1.0
        verdict = "certified_transfer_safe"
        if morphism is not None:
            transport = getattr(morphism, "transport_operator", None)
            prop_map = dict(getattr(transport, "proposition_map", ()) or ())
            best_iv = prop_map.get(best_iv, best_iv)
            info_loss = float(getattr(transport, "estimated_information_loss", 0.0) or 0.0)
            # Sin `or 1.0`: un score de morfismo MEDIDO de 0.0 —escenarios sin
            # nada en común— se leía como 1.0 y la transferencia se certificaba
            # `transfer_safe` (umbral 0.75). Es la puerta causal de la herencia
            # de reglas: el `or` la dejaba abierta justo en el caso que debe cerrar.
            _ov = getattr(morphism, "overall_score", None)
            overall = 1.0 if _ov is None else float(_ov)
            mclass = getattr(morphism, "morphism_class", None)
            if mclass in {"adversarial", "incompatible"}:
                return
            verdict = (
                "certified_transfer_safe" if overall >= 0.75 else "certified_analogical_only"
            )
        recipient.inherited_rules.append(
            {
                "best_intervention": best_iv,
                "confidence_lcb": rule.get("confidence_lcb", 0.0),
                "consequent_relation": rule.get("consequent_relation", "support"),
                "source_member": donor.member_id,
                "transfer": {"verdict": verdict, "info_loss": info_loss, "overall_score": overall},
            }
        )

    def _latest_induced_rule(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            traces = self.storage.list_reasoning_traces(run_id=run_id, limit=512)
        except Exception:
            return None
        for trace in reversed(list(traces)):
            if getattr(trace, "family", "").upper() != "IND":
                continue
            detail = getattr(trace, "detail", None) or {}
            rule = (detail.get("state_delta") or {}).get("ind_rule") or detail.get("ind_rule")
            if isinstance(rule, Mapping) and rule.get("best_intervention"):
                return dict(rule)
        return None

    def _morphism_for(self, source: str, target: str, cache: Dict[Tuple[str, str], Any]) -> Any:
        if source == target:
            return None
        key = (source, target)
        if key in cache:
            return cache[key]
        morphism = None
        try:  # lazy + tolerante (mismo patrón que coherence_obstruction)
            from runtime.world.morphism_engine import MorphismEngine
            from runtime.world.registry import get_scenario

            morphism = MorphismEngine().compute_morphism(
                get_scenario(source).causal_signature,
                get_scenario(target).causal_signature,
            )
        except Exception:
            morphism = None
        cache[key] = morphism
        return morphism

    # ------------------------------------------------------------- helpers

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        try:
            self.storage.append_event(
                event_type=event_type,
                run_id="ecology",
                source="organism_ecology",
                payload=dict(payload),
            )
        except Exception:
            pass

    def population_summary(self) -> Dict[str, Any]:
        ranked = sorted(self.members, key=lambda m: m.fitness, reverse=True)
        return {
            "schema": "ecology.v1",
            "generation": self.generation,
            "transfer_mode": self.transfer_mode.value,
            "population_size": len(self.members),
            "best_member": ranked[0].member_id if ranked else None,
            "best_fitness": (
                None if not ranked or math.isinf(ranked[0].fitness) else round(ranked[0].fitness, 6)
            ),
            "mean_fitness": _mean_finite([m.fitness for m in self.members]),
        }


def _mean_finite(values: Sequence[float]) -> Optional[float]:
    finite = [v for v in values if not math.isinf(v)]
    return round(sum(finite) / len(finite), 6) if finite else None


def _ANY_CONSTITUTION():
    # Constitución compartida por toda la población (misma identidad constitucional).
    from runtime.organism.constitution import OrganismConstitution

    return OrganismConstitution()


def build_member(
    *,
    member_id: str,
    scenario: str,
    scenario_kwargs: Optional[Dict[str, Any]] = None,
    storage,
    knobs: Optional[Dict[str, Any]] = None,
    profile: str = "full_family_exploration",
) -> EcologyMember:
    """Crea un miembro de génesis con su propio linaje y selector."""
    lineage = LineageState(lineage_id=f"lineage-{member_id}")
    lineage.record_genesis(_ANY_CONSTITUTION(), timestamp=utc_now_iso())
    return EcologyMember(
        member_id=member_id,
        scenario=scenario,
        scenario_kwargs=dict(scenario_kwargs or {}),
        lineage=lineage,
        selector=RewardGuidedOverlaySelector(storage=storage),
        knobs=dict(knobs or {"memory_retrieval_limit": 3, "memory_filter_mode": "strict_same_scenario"}),
        profile=profile,
    )
