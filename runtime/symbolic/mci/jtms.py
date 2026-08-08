"""JTMS pequeño con soportes explícitos y retractación transitiva."""

from __future__ import annotations

from dataclasses import replace

from .contracts import BeliefNode, Justification


class TemporalAssumptionLedger:
    def __init__(self):
        self._beliefs: dict[str, BeliefNode] = {}
        self._justifications: dict[str, Justification] = {}
        self._empirically_stale: set[str] = set()

    @property
    def beliefs(self) -> tuple[BeliefNode, ...]:
        return tuple(self._beliefs[key] for key in sorted(self._beliefs))

    def add_belief(
        self,
        *,
        belief_id: str,
        proposition: str,
        confidence: float,
        logical_time: int,
    ) -> BeliefNode:
        node = BeliefNode(
            belief_id=belief_id,
            proposition=proposition,
            status="IN",
            confidence=round(float(confidence), 6),
            logical_time=int(logical_time),
            justification_ids=(),
        )
        self._beliefs[belief_id] = node
        return node

    def justify(self, justification: Justification) -> None:
        if justification.consequence_id not in self._beliefs:
            raise KeyError(justification.consequence_id)
        if any(item not in self._beliefs for item in justification.antecedent_ids):
            raise KeyError("Antecedente JTMS desconocido")
        self._justifications[justification.justification_id] = justification
        consequence = self._beliefs[justification.consequence_id]
        self._beliefs[consequence.belief_id] = replace(
            consequence,
            justification_ids=tuple(
                sorted(set(consequence.justification_ids) | {justification.justification_id})
            ),
        )

    def contradict(self, belief_id: str) -> dict[str, tuple[str, ...]]:
        if belief_id not in self._beliefs:
            return {"out": (), "revisable": ()}
        out: set[str] = {belief_id}
        changed = True
        while changed:
            changed = False
            for justification in self._justifications.values():
                if justification.consequence_id in out:
                    continue
                if any(item in out for item in justification.antecedent_ids):
                    alternatives = self._valid_justifications(
                        justification.consequence_id, excluded=out
                    )
                    if not alternatives:
                        out.add(justification.consequence_id)
                        changed = True
        revisable: set[str] = set()
        for node_id in out:
            node = self._beliefs[node_id]
            has_alternative = bool(self._valid_justifications(node_id, excluded=out))
            status = (
                "OUT"
                if node_id == belief_id
                else ("IN" if has_alternative else "REVISABLE")
            )
            self._beliefs[node_id] = replace(node, status=status)
            if status == "REVISABLE":
                revisable.add(node_id)
        return {"out": tuple(sorted(out - revisable)), "revisable": tuple(sorted(revisable))}

    def mark_empirically_stale(self, *, before_logical_time: int) -> tuple[str, ...]:
        stale = {
            belief_id
            for belief_id, belief in self._beliefs.items()
            if belief.logical_time < int(before_logical_time) and belief.status == "IN"
        }
        for belief_id in stale:
            self._beliefs[belief_id] = replace(
                self._beliefs[belief_id], status="REVISABLE"
            )
        self._empirically_stale.update(stale)
        return tuple(sorted(stale))

    def resolve_empirical_stale(
        self, belief_id: str, *, confirmed: bool
    ) -> BeliefNode:
        if belief_id not in self._empirically_stale:
            raise KeyError(belief_id)
        node = replace(
            self._beliefs[belief_id],
            status="IN" if confirmed else "OUT",
        )
        self._beliefs[belief_id] = node
        self._empirically_stale.remove(belief_id)
        return node

    def _valid_justifications(self, consequence_id: str, *, excluded: set[str]) -> list[str]:
        return [
            item.justification_id
            for item in self._justifications.values()
            if item.consequence_id == consequence_id
            and all(
                antecedent not in excluded
                and self._beliefs.get(antecedent, BeliefNode("", "", "OUT", 0, 0, ())).status
                == "IN"
                for antecedent in item.antecedent_ids
            )
        ]

    def snapshot(self) -> dict[str, object]:
        return {
            "beliefs": [item.to_dict() for item in self.beliefs],
            "justifications": [
                self._justifications[key].to_dict() for key in sorted(self._justifications)
            ],
        }
