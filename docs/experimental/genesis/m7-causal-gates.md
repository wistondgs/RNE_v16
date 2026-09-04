# M7-E2 — Causal capability attribution

M7-E2 answers a narrower scientific question than M7-F1/F2:

\[
z \text{ caused the observed certified capability within this experiment.}
\]

It does not declare GE-I, GE-R, GE-M, AGI, or a global capability verdict.
Those remain outside this unit.

## Three experiments, not a false five-arm symmetry

The seven observed states belong to three legitimate M5 experiments:

| Experiment | Frozen root | States | Derived question |
| --- | --- | --- | --- |
| C1 | \(\Gamma_0 = Snapshot(G_0)\) | `CONTROL`, `TREATMENT`, `PLACEBO` | effect beyond installing an arbitrary artifact |
| C2 | \(\Gamma_1 = Snapshot(G_1)\) | `INTACT`, `ABLATION` | necessity of exactly \(z\) |
| C3 | \(\Gamma'_0 = Snapshot(G'_0)\) | `FRESH_CONTROL`, `TRANSPLANT` | sufficiency of exactly \(z\) in a fresh matched baseline |

`GenericInterventionKernel` remains the only M5 lifecycle: it captures and
seals each root, forks state, records allowed deltas and isolation, seals a
decision before evaluator access, matches budgets, and derives the CFI
report. M7 adds only a declarative capability runtime to that kernel; it does
not define an M7 fork, M7 CFI, or a second intervention engine.

## Executable rather than metadata-only interventions

An action commits pre/post `CapabilityManifest` sets and the exact skill hash:

- install: \(Caps' = Caps \cup \{z\}\);
- remove: \(Caps' = Caps - \{z\}\);
- none: unchanged set.

For C2, removal also clears the active executable binding. A manifest that
merely omits `z` while retaining a callable `z` is invalid. A M6 candidate
identity is derived from the actual M5 root snapshot, arm, manifest and active
skill. No-capability arms have an explicit `NO_CAPABILITY` identity; they are
not falsified as a synthetic installed “zero skill”.

## Evidence and causal gate

Every one of the seven states is closed separately on `HIDDEN` and `TRANSFER`
through the existing M6 path:

```text
M5 observed arm
  -> declared executable state
  -> DifferentialVerifier (SUPPORTING)
  -> FederationPlan -> execution -> COMPLETE evidence bundle
  -> requirement adjudication -> TraceClosure / CAS
```

`DifferentialVerifier` remains supporting and `ExactVerifier` is untouched.
The trusted target and split labels remain evaluator-side; the M5 root holds
only capability identity, raw inputs and a predeclared root-instance identity.

The immutable causal certificate rederives, rather than receives booleans:

\[
CFI_{C1,C2,C3}=PASS
\land J(T)>J(C)
\land J(T)>J(P)
\land J(I)>J(A)
\land J(X)>J(F)
\land skill(T)=skill(I)=skill(X)=z.
\]

Any CFI `FAIL` yields `FAIL`; an incomplete or invalid closure yields
`NOT_PROVEN`. There is no weighted average and no post-hoc threshold.

## Fresh replay and adversarial semantics

The causal index is not an authority. From fresh CAS it reconstructs the
sealed benchmark, re-runs C1/C2/C3 through M5, replays all fourteen M6 scope
closures, and rederives the causal conjunction. It rejects re-sealed attempts
to swap arms, substitute a valid but wrong skill, use treatment as placebo,
launder a root, contaminate `G'_0` with `z` history, or alter CFI evidence.

M7-E2 therefore closes causal attribution only. The next unit is M7-G, which
must audit the complete GE-I conjunction across acquisition, hidden/transfer,
persistence, semantic replay and these causal gates.
