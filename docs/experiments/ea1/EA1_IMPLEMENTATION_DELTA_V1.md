# EA1-C Implementation Delta V1

Status: `DESIGN_ONLY_NO_RUNTIME_CHANGE`

This document identifies the smallest future implementation delta. It contains no code and authorizes no modification to F1A, runtime or active configuration.

## 0. Exact reference map

The preregistration branch starts at the protected F1A baseline. Candidate behavior was audited at other immutable refs and must be consulted explicitly rather than assumed present at baseline:

| Source | Exact ref | Permitted use |
|---|---|---|
| F1A outcome/experience boundary | `dc1e4393621301310f5252e9f8154d66ccaa1975` | protected authority baseline |
| MCI, A11/A12, EML and N4 audit surface | `6630258da9d49eccc269f1814ca29efec44f73c6` | adapter design reference |
| ASCG conceptual contracts/ledger | `c4084bd7047d1f8e538e78135bac5a87ceb2eab2` | shape reference only |
| N3 technology | `f88a31413c9607175d3be2edbd9049e2049cd04f` | excluded contextual reference |
| P1 neural closure | `71257a66cde77f9b4bfb97d4b1d2df9898e8cb52` | historical failure/development evidence |
| P2 N3 decision | `fe95d1107ca409653d4003bf1548d91470bcb3a0` | historical failure/development evidence |
| P2-v2 | `544ecff54449e97d3f7f19b2ec0486e1be3012f7` | ranking/decision caution |

No wholesale merge is implied. A later implementation plan must resolve the minimal code ancestry while preserving the F1A chain and rerun its boundary tests. Historical artifacts remain developmental only.

## 1. Reuse boundary

### Reuse unchanged

- F1A `CanonicalOutcomeAuthority`, anchor and witness resolution;
- MCI evidence buffering, causal overlays, holdout evaluation and JTMS belief invalidation;
- MCI action-conditioned rollout and planner interfaces where they accept public models;
- A11 horizon simulation shape and safety checkpoint concept;
- A12 defeater, abstention and recommendation pattern;
- DED consistency/UNSAT checks;
- RTCME structural morphism primitives for later transfer design;
- append-only event and artifact conventions.

### Adapt, without granting new authority

- MCI hypothesis records into common `HypothesisCandidate` and `TheoryState`;
- MCI rollout into per-hypothesis, per-intervention predictions;
- A11 world-model input into an explicit hypothesis-conditioned model;
- A12 from current-action arbitration into proposal comparison, leaving belief updates to a separate adapter;
- MFM-like persistence patterns into a separate experiment ledger, not `ExperienceStore`;
- ASCG receipt/ledger shapes where their semantics match, without reusing `ObservedEffect` as outcome.

### Deliberately excluded

- Teacher, Codex and local 7B;
- N3/N4 in confirmatory arms;
- AutoEvolution and self-modification;
- EML outside S4 pilot;
- H-Net, training and GPU requirements;
- hybrid specialist orchestration;
- transfer execution.

## 2. Shared primitives to implement later

Future code may add implementations for:

1. `HypothesisCandidate`
2. `TheoryState`
3. `DivergentPredictionSet`
4. `ExperimentProposal`
5. `ExperimentSelectionReceipt`
6. `CanonicalOutcomeReference`
7. `BeliefRevision`
8. `ExperimentMemoryRecord`
9. `SourceAcquisitionReceipt`

`MethodTransferReceipt` may receive a schema for forward compatibility but has no execution path in EA1-C-v1.

Required shared services are:

- canonical serialization and hashing;
- append-only selection-receipt authority;
- deterministic numeric update/governance policy;
- budget/admissibility authority;
- F1A reference resolver;
- separate experiment ledger;
- acquisition evaluator that opens ground truth only after finalization;
- field-level provenance and leakage audit.

None may write a factual outcome. The existing F1A authority remains the only path.

## 3. MCI-specific adapter delta

Historical MCI already supports versioned overlays, pending hypotheses, train/holdout evaluation, regime detection and later planner consumption. EA1-C needs adapters for four missing semantics:

### Rival retention

Instead of promoting a single best overlay and treating alternatives only as pending/rejected items, expose at least two live structural candidates with normalized weights plus unknown mass. Preserve explicit scope and refutation conditions.

### Intervention-conditioned prediction

For every admissible proposal, run the same public starting state through each candidate model. Emit a `DivergentPredictionSet`; do not call the true scenario transition or hidden parameter path. Unsupported candidate/action cells are marked unavailable.

### VOI selection

Construct proposals from divergent predictions, apply safety/admissibility first, calculate the frozen EIG/EDV/cost/risk score and seal a receipt. The current task-reward planner cannot stand in for VOI.

### Persistent revision

After F1A commits the outcome, resolve its witness, evaluate likelihood/evidence under every rival, create a new `TheoryState`, and ensure the next selection actually consumes it. Existing overlay promotion may be an internal model update but is not itself the common `BeliefRevision` contract.

MCI stop condition: if reasonable public-model adapters cannot produce divergent predictions without scenario ground truth, C3 cannot enter confirmatory execution.

## 4. A11/A12-specific adapter delta

Historical A11 demonstrates delayed-horizon value with narrow hand-authored world models; A12 arbitrates current actions using fixed defeaters. EA1-C requires:

### Hypothesis-conditioned simulation

A11 receives an explicit public candidate model for each hypothesis and returns a trajectory distribution per `(hypothesis, intervention)`. The adapter must prove it cannot import the scenario's true transition implementation, hidden debt parameters or future factual states.

### Information/reward separation

Immediate task utility, EIG, EDV, cost and risk are distinct values. A11 predicts; it does not select by task reward. A12 filters unsafe/incoherent proposals and recommends according to the frozen scientific score.

### Persistent revision separation

A12's historical action-decision object remains a deliberation receipt. A separate updater converts canonical evidence into `BeliefRevision` and persistent `TheoryState`. The next A11 cycle must consume that state.

### Abstention

A12 must abstain when fewer than two hypotheses are evaluable, all discriminating tests are unsafe/unavailable, or the governance policy leaves excessive unresolved mass. Abstention reasons are sealed before the outcome interface advances.

A11/A12 stop condition: if their advantage requires a hand-coded model isomorphic to the hidden S3 mechanism, C4 cannot enter confirmatory execution.

## 5. Scenario-runner delta

The future runner needs four separable planes:

### Public arm plane

Provides only public observations, aliased actions, declared costs/risks and logical time. It has no reference to private scenario objects.

### Receipt and budget plane

Validates proposal admissibility, reserves one token, seals `ExperimentSelectionReceipt`, then authorizes intervention execution. It must reject any attempt to observe before sealing.

### Canonical outcome plane

Executes the factual transition only after authorization and uses existing F1A authority. It returns an anchor/witness reference, not a duplicate outcome payload, to the epistemic plane.

### Private sealing/oracle plane

Generates hidden mechanisms and nonces, publishes commitments, isolates private state and executes the oracle. Its output store remains unreadable by public arms until block finalization.

Required controls implement the same arm interface:

- passive never requests an experimental authorization;
- greedy scores immediate public utility only;
- `C0`, `C1` and `C2` are instantiated with the MCI or A11 substrate under evaluation, reusing that substrate's hypothesis initializer, predictor, proposal generator and updater;
- `C2[substrate]` replaces only the selector and samples the substrate's six-proposal matched set with its own recorded RNG;
- oracle uses the private plane but cannot write into public arm state.

All six confirmatory actions have identical token cost, declared physical cost and risk allocation. Every policy receives the same scheduled passive observation at each of four epochs; abstention yields no additional experimental observation and cannot extend the horizon.

## 6. Experiment memory boundary

Add a dedicated append-only experiment ledger or namespace. It stores proposal, selection, canonical reference, revision and observed discrimination. It must not:

- call `ExperienceStore.write`;
- create or alter `SituationWisdom`;
- promote simulated predictions as evidence;
- retrieve records across arms during a campaign;
- expose target IDs or private ground truth;
- treat duplicated artifacts as independent observations.

Any later retrieval for method transfer must operate on structural method traces and remain disabled in EA1-C-v1.

## 7. Source-acquisition evaluator delta

The ledger seals the candidate portion of `SourceAcquisitionReceipt` at the first threshold crossing. The evaluator is otherwise inactive until an arm finishes its experiments, held-out probes and persistence checks. It appends non-ground-truth gates first, then reads the private opening in an isolated finalization stage; it cannot substitute a later TheoryState. It must distinguish:

- valid acquisition;
- incorrect acquisition;
- unresolved/abstained;
- budget exhaustion;
- censored or missing evaluation;
- leakage-invalidated campaign.

Only the first can produce `valid=true`. The evaluator never feeds its result back into an ongoing confirmatory arm.

## 8. Development and confirmatory lifecycle

1. Implement contracts and adapters using DEV namespace only.
2. Run S1 positive control and adversarial leakage tests.
3. Run complete DRY_RUN with mechanisms excluded from confirmatory generator.
4. Freeze code hashes, analysis container, scenario-generator hash and five-document manifest.
5. Conduct read-only readiness review.
6. Generate and seal confirmatory universe.
7. Run all arms without inspecting aggregate outcomes.
8. Finalize non-ground-truth gates.
9. Open ground truth and compute acquisition.
10. Execute frozen analysis and publish every assigned block.

No tuning, prompt editing, coefficient changes or scenario repair occurs between steps 6 and 10.

DEV and DRY_RUN must use only their namespace-specific causal templates from the scenario specification. Confirmatory template constructors may be implemented against the frozen document but cannot be executed to produce arm-development traces before code freeze. Confirmatory arms receive exactly two candidates; open-ended candidate generation remains disabled.

## 9. Validation obligations before confirmatory execution

Future tests must demonstrate:

- two rivals remain live after initialization;
- weights normalize and ordinal states are derived deterministically;
- each arm receives byte-identical public initial input;
- predictions change with hypothesis and intervention but not hidden class access;
- selection receipt precedes canonical outcome under forced concurrency;
- counterfactual and simulated payloads are rejected by F1A factual reference validation;
- random matching is uniform and reproducible;
- cost/risk/token enforcement is identical across active and random arms;
- crashes and zero evaluations cannot yield acquisition;
- oracle cross-talk attempts fail;
- representation aliases do not predict class;
- next decisions consume the revised persistent state;
- repository resource use stays below 16 GB RAM and 8 GB VRAM.

## 10. Expected file scope of a later implementation

Exact paths are intentionally not authorized here, but implementation should remain separable into:

- new EA1 contract/ledger modules;
- MCI and A11/A12 adapters;
- scenario-family fixtures and sealing service;
- control policies;
- acquisition evaluator;
- analysis and audit commands;
- tests and new non-historical artifacts.

Protected F1A files should require no semantic change. If implementation discovers otherwise, the stop condition applies and the protocol returns for redesign.

## 11. Minimality and attribution

EA1-C must not integrate EML, N4, N3, Codex, 7B, AutoEvolution or hybrid routing into C3/C4. Shared contracts and runner services are identical across active arms. Architecture-specific differences are limited to generation of intervention-conditioned predictions and selection deliberation. This preserves attribution between MCI+VOI, A11/A12 and random matched-cost.
