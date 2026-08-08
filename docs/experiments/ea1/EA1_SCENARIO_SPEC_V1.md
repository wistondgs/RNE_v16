# EA1 Scenario Specification V1

Status: `FROZEN_BEFORE_CONFIRMATORY_DATA`

## 1. Common instance contract

Every instance contains a private causal specification and a public projection. The private specification includes causal class, equations, latent values, lag structure, canonical variable roles, safe intervention domain and oracle solution. The public projection contains aliased observations, aliased actions, declared cost/risk, reversibility, horizon and outcome schema.

All aliases are generated independently of causal role. A name, ordering position, ID, serialized byte pattern or `situation_key` must not identify the correct hypothesis. Each causal class appears equally often under every representation transform.

Each confirmatory instance must provide:

- two or more initially live causal rivals plus `unknown/abstain`;
- identical likelihood for rivals on the initial passive prefix within numerical tolerance `1e-9`;
- at least one admissible intervention with divergent predictions;
- exactly six actions, all in one public cost/risk stratum, of which exactly two are class-discriminating and four are non-discriminating;
- exactly four epistemic-token opportunities;
- eight non-updating held-out prediction probes;
- four downstream decision probes;
- an oracle proof that the class is identifiable within the budget.

An instance failing any construction check is rejected during generation, before publication of its commitment.

## 2. Splits and transformations

The instance universe is generated in three disjoint namespaces:

- `DEV`: scenario debugging, budget validation and adapter development;
- `DRY_RUN`: end-to-end plumbing and leakage audits using distinct mechanisms;
- `CONFIRMATORY`: generated only after code, documents and analysis are frozen.

No private mechanism tuple, parameter vector or representation transform may occur in more than one namespace. Confirmatory seeds are generated from a sealed seed root. Arm RNG streams are derived from public block IDs and arm IDs, never the hidden-mechanism seed.

Causal templates are disjoint, not merely renamed:

| Family | DEV template | DRY_RUN template | CONFIRMATORY template |
|---|---|---|---|
| S2 | two-context conjunctive gate `C1 AND C2` versus unconditional effect | XOR gate `C1 XOR C2` versus unconditional effect | unary hidden precondition/gate versus unconditional effect |
| S3 | direct one-shot delayed sign reversal, no latent state | two-stage observable mediator `B -> M -> Y` | latent accumulated debt state with delayed harm versus transient benefit |
| S5 | mediated path versus selection-collider explanation | reverse-causal edge versus latent cause with observable proxy | direct `X -> Y` versus latent common cause without proxy |

Nodes, edge topology, precondition arity and latent/observable roles differ across namespaces. No DEV or DRY_RUN trace from these templates may enter confirmatory initialization or retrieval. Shared contract field names and generic inference code are allowed; template instances and fitted parameters are not.

Representation transforms include:

1. random variable/action renaming;
2. permutation of serialized field order;
3. affine rescaling with public units;
4. perceptually equivalent numeric versus binned observation encoding.

The last transform must preserve the information needed by every arm. If an adapter cannot consume it without a semantic mapping, the mapping is public and role-neutral.

## 3. Frozen confirmatory generator

S2, S3 and S5 use binary factual targets and Bernoulli likelihoods. Each family contains exactly 216 assigned blocks: `2 causal classes x 3 difficulty tiers x 2 representation modes x 18 replicates`. Class, tier and representation cells are therefore exactly balanced.

Each confirmatory substrate starts from exactly the two family-defined rivals at weights `0.49/0.49` plus `unknown_weight=0.02`. The hypothesis records contain the two public causal alternatives and their tier-conditioned Bernoulli prediction tables, but never indicate which alternative generated the block. Additional generated hypotheses are disabled in EA1-C-v1 so the experiment isolates informative selection and revision rather than open-ended hypothesis invention.

Difficulty controls the discriminating Bernoulli pair:

| Tier | `p_low` | `p_high` | Replicates per class/representation |
|---|---:|---:|---:|
| easy | 0.01 | 0.99 | 18 |
| medium | 0.03 | 0.97 | 18 |
| hard | 0.05 | 0.95 | 18 |

The two representation modes are frozen. `R_AFFINE_ALIAS` maps binary `y` to `z=a*y+b`, with `a` cycling through `{0.5, 2.0}` and `b` through `{-1.0, 1.0, 3.0}`; the six Cartesian pairs occur three times among the 18 replicates in every class/tier cell. The inverse `(a,b)` is public and role-neutral. `R_BINNED_ALIAS` maps `0/1` to two opaque tokens using a public block-stream coin flip; each polarity occurs nine times per 18-replicate cell. Field and action order use an independent balanced public permutation. Each causal class therefore occurs equally under every transform.

DEV uses only `R_RAW` and Bernoulli pair `(0.12,0.88)` for S2/S5; DRY_RUN uses `R_ONE_HOT` and `(0.08,0.92)`. These parameters and the disjoint templates above are excluded from confirmation. S3 has its separate excluded DEV/DRY_RUN values below. Public adapters may know the confirmatory contract and tier table but may not tune on realized confirmatory outcomes.

Every decision epoch exposes exactly six repeatable actions with equal cost `1.0` and risk allocation `0.25`. Exactly two have positive class divergence under the oracle; four have zero class divergence. The private generator assigns these roles before aliasing. There are four epochs. Every arm receives the identical prespecified natural passive observation at each epoch. Its likelihood is the family-common passive distribution under both rivals and unknown, producing Bayes factor one and no TheoryState weight change. A selected action adds its experimental outcome; abstention and C0 receive no additional outcome. Thus abstention cannot create extra time or informative passive evidence.

Potential outcomes are paired across arms using a sealed table of uniform variates indexed by `(block, epoch, canonical action role)`. An arm never sees the variate or another action's potential outcome. The same table makes policy comparisons paired without sharing oracle information.

The public `DECISION_DESIGN_DISTRIBUTION_V1` contains only the balanced distribution over canonical public state roles and the binary oracle-optimal-action scoring rule. EDV integrates over that distribution. Four final decision probes per block are drawn from a separate sealed stream and are not part of that distribution's finite support manifest.

Held-out probability tuples are fixed by difficulty: easy uses `(p_low,p_high)=(0.015,0.985)` and `(0.005,0.995)`; medium uses `(0.035,0.965)` and `(0.025,0.975)`; hard uses `(0.055,0.945)` and `(0.045,0.955)`. Held-out representation transforms are exactly `R_H1: z=1.5*y-0.5` and `R_H2: 0->K7, 1->Q2`; neither occurs in DEV, DRY_RUN or confirmatory learning episodes. The eight probes are the Cartesian product of the two parameter tuples, two family-informative action roles and `R_H1/R_H2`.

For functional scoring, each family declares four equiprobable design-state roles: two class-dependent roles and two control/recovery roles. In a class-dependent role, the true-class action has terminal utility `1.00`, the rival-class action `0.00`, the neutral action `0.60`, and unknown assigns expected utility `0.50` to either class action. Thus the initial `0.49/0.49/0.02` mixture uniquely chooses neutral (`0.60 > 0.50`), while any correctly committed posterior `>=0.80` uniquely chooses its class action (`>=0.81 > 0.60`). In each control role, one role-declared recovery action has utility `1.00` and every other action `0.00` independent of class. Accuracy is `1` when `DOWNSTREAM_EXPLOIT_V1` selects any action tied for maximum true terminal utility and `0` otherwise. The policy maximizes posterior expected terminal utility under the supplied TheoryState and public substrate predictions; ties use canonical action hash. The sealed evaluation probes instantiate one of each role with independent alias, field order and parameter-boundary draws. Initial and committed states are evaluated without state updates, fixing baseline accuracy `0.50`, acquired-correct accuracy `1.00` and gate delta `0.50`.

Correct-class evaluation uses a frozen canonical signature after applying the private representation inverse:

`signature = (node_role_count, sorted_directed_edge_roles, precondition_role_and_polarity, lag_presence, intervention_response_truth_table)`.

Signatures must match exactly; names, numeric parameters and serialized ordering are discarded. In addition, mean absolute error between the candidate and true Bernoulli interventional probabilities over the eight held-out probes must be `<= 0.10`. The first condition evaluates causal class; the second prevents a correct label with unusable predictions.

Design-time exhaustive enumeration of all `2^6` experimental-plus-persistence outcome sequences found correct first-crossing-and-persistence probabilities no lower than `0.75` for S2/S5 and `0.9488` for S3. A separate pre-confirmatory Monte Carlo calculation (seed `20260808`, 500,000 replicates per class/tier) used the exact held-out tuples/transforms above and the first-crossing posterior mixture; its minimum estimated probability after the `0.05`-nat gate was `0.4774`. Functional gain is `0.50` by the frozen four-role construction after correct acquisition. Therefore the implementation readiness floor is oracle valid acquisition `>= 0.45` separately for every causal class and tier. During implementation, 10,000 DEV blocks per family using only excluded DEV tuples must show construction/leakage failure below 1% and reproduce their own exact/Monte Carlo design bounds. Confirmatory instances are never simulated for tuning or filtered using realized outcomes.

After the four experimental epochs, every arm receives exactly two ordinary decision epochs, `PERSIST_1` and `PERSIST_2`. Informative proposal selection is disabled. `DOWNSTREAM_EXPLOIT_V1` chooses from the public task-action set. For S2/S5, the resulting evidence-bearing task action has likelihood `p_high` under `H_UNCONDITIONAL/H_DIRECT` and `0.50` under `H_CONDITIONAL/H_COMMON_CAUSE`; for S3 it has likelihood `p_high` under `H_DEFERRED_DEBT` and `p_low` under `H_TRANSIENT`. These exact likelihoods apply in both persistence epochs. The factual outcome follows F1A and the normal Bayesian updater may revise TheoryState. Persistence passes only if the first-crossing class remains top-ranked and non-refuted after both outcomes. These epochs are distinct from the four sealed, non-updating functional probes.

## 4. S1 — Regime change positive control

### Purpose

Demonstrate that the shared research loop can detect and persist a change already reachable by historical MCI. S1 is developmental and cannot establish EA1-C.

### Rival classes

- `H_STABLE`: the action-effect parameter remains constant.
- `H_CHANGED`: after an unknown public-time boundary, the parameter changes within the declared safe range.

### Informative intervention

Repeat a reversible calibrated action at two state-matched times. The outcome is hidden until each selection receipt is sealed.

### Success and falsifier

The cycle must revise the active class and improve held-out prediction after the change. Failure blocks implementation debugging but does not count in confirmatory inference.

## 5. S2 — Hidden causal precondition

### Private mechanism templates

- `H_UNCONDITIONAL`: intervention `A` changes outcome `Y` by effect `beta` throughout the admissible context range.
- `H_CONDITIONAL`: `A` changes `Y` by the same `beta` only when controllable context `C` satisfies a hidden threshold or categorical gate `G`; otherwise its causal effect is zero.

The initial passive prefix contains eight observations at gate-satisfying context `C=1`. Under both classes and the passive unknown reference, `P(Y=1|A=1,C=1)=p_high` and `P(Y=1|A=0,C=1)=p_low`, with four observations of each action in canonical alternating order before alias permutation. Thus all three components have identical initial likelihood and weights remain fixed.

### Informative tests

The six composite actions are fixed by role: two discriminating actions `(C=0,A=1)` and `(C=0,A=0)`; two non-discriminating actions `(C=1,A=1)` and `(C=1,A=0)`; and two sham repetitions at `C=1`. Under `H_UNCONDITIONAL`, the two `C=0` probabilities are `p_high` and `p_low`; under `H_CONDITIONAL`, both are `0.50`. Manipulating `C` never exposes the hidden class directly.

### Held-out structure

DEV uses gate role `C=1` and confirmatory generation balances the canonical gate polarity before the private representation inverse. Held-out probes use the common frozen Cartesian product of two probability tuples, the two discriminating context/action roles and `R_H1/R_H2`. They are private `EVALUATION_ONLY` samples and do not update beliefs.

### Architecture and falsifier

The primary architecture is `C3_MCI_VOI`. It is falsified for S2 if it does not exceed random matched-cost acquisition by the preregistered criterion or if it succeeds through threshold/name leakage rather than intervention-conditioned prediction.

## 6. S3 — Deferred consequence

### Private mechanism templates

- `H_TRANSIENT`: action `B` improves immediate utility and has no delayed debt after the public horizon lag.
- `H_DEFERRED_DEBT`: `B` has the same immediate benefit but accumulates a hidden state that produces delayed harm after lag `L`.

The initial prefix contains eight immediate outcomes with identical `P(immediate_benefit=1)=0.80` under both classes and the passive unknown reference, and never exposes the delayed target. Public horizon is six. Lags are fixed by difficulty as 2, 3 and 4 steps. For a debt-triggering pulse, `P(delayed_harm=1)` is `p_low` under `H_TRANSIENT` and `p_high` under `H_DEFERRED_DEBT`.

### Informative tests

The six actions are two bounded debt-triggering pulses and four neutral/sham controls. All pulses have the same immediate benefit distribution, cost and risk; only their delayed Bernoulli outcome discriminates the classes. The canonical outcome for a pulse is unavailable until the full six-step horizon. Pre-horizon observations contain immediate benefit only and cannot encode debt or the future variate.

### Held-out structure

DEV uses lag 1 and Bernoulli pairs `(0.15,0.85)`, which are excluded from confirmation. Confirmation uses the frozen tier table and lags 2/3/4. The two representation modes are assigned exactly as in the common generator.

For S3, the two held-out probability tuples additionally carry lags `5` and `6`, respectively; confirmatory learning lags are 2/3/4. The probes are two pulse roles by the two `(probability,lag)` tuples by `R_H1/R_H2`: eight binary delayed-harm predictions.

### Architecture and falsifier

The primary architecture is `C4_A11_A12_SCIENTIFIC`. Before confirmation, DRY_RUN uses lags 8/9/10 and Bernoulli pairs `(0.25,0.75)` and `(0.35,0.65)`, all excluded from confirmation and held-out evaluation, with roles permuted across aliases. C4 must produce predictions through the generic hypothesis contract, not a scenario transition callable. Static dependency inspection must show no import or callable path from A11 to the private S3 mechanism. Failure is a stop condition. During confirmation, H2 failure, any future-state access, or non-positive C4-minus-random acquisition in any difficulty tier abandons C4 for this family.

## 7. S5 — Observational confounding

### Private mechanism templates

- `H_DIRECT`: `X` causally affects `Y` with background variable `U` affecting only their baseline levels.
- `H_COMMON_CAUSE`: latent `U` causes both `X` and `Y`; there is no `X -> Y` edge.

Both classes and the passive unknown reference emit the exact passive joint table `P(0,0)=0.40`, `P(0,1)=0.10`, `P(1,0)=0.10`, `P(1,1)=0.40`. Under `H_DIRECT`, `P(Y=1|do(X=0))=p_low` and `P(Y=1|do(X=1))=p_high`. Under `H_COMMON_CAUSE`, both probabilities are `0.50`. These observational and interventional tables are the canonical mechanism definition.

### Informative tests

The six actions are the two discriminating interventions setting canonical `X=0` and `X=1`, two sham interventions preserving the passive joint table and two passive-resample controls. No public label contains `do`, `cause`, `confound` or a causal role.

### Held-out structure

Confirmatory instances use the frozen tier table, balanced sign/polarity through the private representation inverse, and both common representation modes. Held-out probes are the two `X` settings times the two exact common held-out probability tuples times `R_H1/R_H2`.

### Architecture and falsifier

The primary architecture is `C3_MCI_VOI`. Success from passive correlations alone is impossible by construction. The architecture is falsified if it cannot select an intervention that separates the rivals more often than random matched-cost.

## 8. S4 — Piecewise symbolic law pilot

S4 is non-confirmatory. Several formulas fit the initial range and diverge outside it. `EML_ONLY` uses a fixed symbolic score with complexity and held-out fit. `EML_PLUS_N4_SHADOW` receives the identical proposal set and may only reorder it in shadow.

N4 advances only if the shadow ordering would change the selected experiment and improve held-out acquisition or downstream decisions. Calibration or ranking changes without a selection/capability change fail the pilot.

### Abstention challenge set

A separate non-confirmatory diagnostic removes the two discriminating actions after initialization or assigns them invariant risk above the public admissibility ceiling. The expected correct response is `abstain`; no source acquisition is possible or claimed. These instances never enter S2/S3/S5 primary samples.

## 9. Admissibility and safety

Experimental actions must be reversible, bounded, observable and compatible with invariant checks. Shutdown, rollback, quarantine, mutation, identity changes, memory writes and authority changes are never scenario actions.

Each action declares normalized cost, invariant-risk ceiling, reversible-state proof and required public state. Admission occurs before scoring. An unsafe or incompletely specified action is unavailable to every non-oracle arm and cannot appear in the oracle ceiling.

## 10. Canonical outcome timing

The scenario exposes no factual outcome for an experimental action until its `ExperimentSelectionReceipt` is sealed. Simulated and symbolic predictions use different provenance and namespaces. After execution, the factual transition is committed through F1A and only its anchor/witness reference enters scientific memory.

## 11. Scenario construction acceptance tests

Before confirmatory generation, implementation review must demonstrate on DEV and DRY_RUN instances:

- observational equivalence of initial rivals;
- interventional divergence;
- oracle acquisition feasibility within four tokens and DEV gate rates required by the frozen generator;
- matched public action sets;
- equal information interfaces across arms;
- no alias-to-class association;
- no future-outcome field in preselection objects;
- reproducible ground-truth commitment and opening;
- stable F1A witness resolution;
- resource use within 16 GB RAM and 8 GB VRAM.
