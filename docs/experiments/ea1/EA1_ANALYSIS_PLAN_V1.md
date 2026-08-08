# EA1-C Confirmatory Analysis Plan V1

Status: `FROZEN_BEFORE_CONFIRMATORY_DATA`

## 1. Analysis population and unit

The unit is a sealed paired scenario instance. Every confirmatory arm receives the same public initial observations, action set, budget, horizon, perturbation schedule and hidden mechanism within that block. The analysis is intention-to-treat at assigned-arm level.

Confirmatory causal templates, not only seeds and parameters, are excluded from DEV and DRY_RUN as enumerated in the scenario specification. The tested estimand is acquisition among two supplied rival candidates; it does not estimate open-ended hypothesis-generation capability.

Primary samples are:

- H1-S2: 216 S2 blocks;
- H1-S5: 216 S5 blocks;
- H2: 216 S3 blocks.

Every block runs all arms. Blocking factors are family, preregistered difficulty tier and causal mechanism class. Each cell is balanced before commitments are published.

## 2. Primary estimand

For active arm `a` and its substrate-matched random control `r`, define `A[i,a]` and `A[i,r]` as binary valid `SourceAcquisitionReceipt` outcomes. The estimand is the paired risk difference:

`Delta_a = mean_i(A[i,a] - A[i,r])`.

H1-S2 and H1-S5 separately estimate `Delta_MCI` against `C2[MCI]`. H2 estimates `Delta_A11` against `C2[A11]`. There is no pooled primary S2/S5 estimand and one family cannot rescue another.

The smallest effect of scientific interest is an absolute 0.20 increase in valid acquisition rate.

## 3. Sample-size design

Sample size was fixed using a pre-confirmatory Monte Carlo design calculation with RNG seed `20260808`, 400,000 replicates per cell, exact two-sided McNemar tests, conservative per-test alpha `0.05/3`, true paired risk difference `0.30`, discordant-pair probability from `0.35` through `0.80`, and the complete success rule: exact-test rejection **and** observed point difference `>= 0.20`.

At `n=216`, estimated power for the complete rule ranged from `0.956` at discordance `0.80` to `0.998` at discordance `0.35`. The `0.20` value remains the SESOI; `0.30` is the design alternative used for power, not a replacement success threshold. Therefore `n=216` is frozen for each of the three primary comparisons. This calculation used no EA1 scenario outcomes.

Target power is at least 0.90. Familywise alpha is 0.05. There is no efficacy stopping. The campaign may stop only for safety, leakage, infrastructure invalidation or a preregistered stop condition; stopped campaigns make no confirmatory claim.

## 4. Primary tests and multiplicity

For H1-S2, H1-S5 and H2:

1. construct paired 2x2 acquisition table;
2. calculate exact two-sided McNemar p-value;
3. apply Holm correction across the three primary p-values at familywise alpha 0.05;
4. report paired risk difference and a two-sided 95% paired bootstrap interval using 100,000 block-stratified resamples with RNG seed derived from `SHA256("EA1-C-v1-primary-CI")`;
5. report all four paired-table cells.

Support for a primary hypothesis requires all of:

- Holm-adjusted significance;
- positive paired risk difference;
- point estimate at least 0.20;
- valid leakage, matching and F1A audits.

The 0.20 point criterion prevents a trivial but highly powered difference from becoming the target claim. Confidence intervals and exact p-values remain visible even when the criterion fails.

## 5. Hierarchical interpretation

H1-S2, H1-S5 and H2 are co-primary and multiplicity-corrected. None can rescue another. A successful MCI result applies only to its passed family. A successful H2 supports A11/A12 only for S3. Head-to-head architecture comparisons are secondary and cannot establish global superiority.

No aggregate across S2, S3 and S5 is a primary endpoint.

## 6. Secondary outcomes

Reported separately by family and arm:

- experiments-to-acquisition, with non-acquisition represented as no event rather than time zero;
- held-out predictive log loss and delta from initial mixture;
- Brier score when outcomes are binary and full predictive probabilities exist;
- downstream oracle-optimal action accuracy delta;
- experimental regret relative to the isolated oracle among actually admissible actions;
- tokens, physical cost and invariant risk;
- abstention rate and reasons; correctness is evaluated only in a separate non-confirmatory abstention challenge set;
- ordinal belief transitions and persistence;
- safety/invariant breaches.

Time-to-acquisition uses cumulative-incidence curves through token four and a paired restricted-mean experiments-to-acquisition contrast. A run without acquisition remains a failure through the horizon. It is not assigned zero regret or immediate acquisition.

Continuous paired outcomes use paired mean/median differences with block bootstrap intervals. Binary secondary outcomes use paired risk differences. These are estimation-focused and labelled exploratory unless explicitly listed as primary gates.

## 7. Source-acquisition computation

The evaluator computes each gate independently and stores raw components. `valid` is their logical conjunction. The correctness gate is unavailable until ground truth opening; all other gates are sealed first. After opening, evaluator code operates on structural roles and interventional distributions, not aliases.

Held-out log loss uses the eight exact parameter/action/representation cells frozen in the scenario specification and natural logarithms. They are private `EVALUATION_ONLY` samples produced after arm finalization, not F1A outcomes or learning evidence. The baseline prediction is the initial `0.49/0.49/0.02` posterior predictive mixture; acquired prediction is the immutable first-crossing TheoryState posterior predictive mixture, including unknown at Bernoulli `0.5`. The pure winning hypothesis is never substituted. Probabilities are clipped only for numerical evaluation to `[1e-12, 1-1e-12]`; unclipped values remain in the record. Functional improvement is the change in oracle-optimal action accuracy on four sealed probes when the common `DOWNSTREAM_EXPLOIT_V1` policy receives the substrate's immutable initial TheoryState versus its first-crossing committed TheoryState. EDV uses only the public design distribution, never these probe realizations.

Missing probes, missing canonical references, fewer than two persistence opportunities, or evaluator errors set the relevant gate false. They are never imputed.

## 8. Randomness and reproducibility

The confirmatory seed root remains sealed until campaign finalization. Public arm streams use counter-based derivation from block commitment, arm code and operation label. `C2[MCI]` and `C2[A11]` sample uniformly over the canonical-hash-sorted six-proposal sets produced by their matched substrates. All six actions have identical token, declared cost and allocated risk. The selector is the only replaced component.

Bootstrap and reporting RNG seeds are analysis-specific constants derived from public strings and cannot depend on results. Analysis code must reproduce byte-identical primary tables from the immutable ledger.

## 9. Leakage and matching audits

Before unsealing, an audit must verify:

- field-level allowlists for every non-oracle arm input;
- no hidden seed, mechanism class, target ID, future outcome or oracle output in arm traces;
- selection-receipt logical time and append position precede canonical outcome creation;
- identical public input hashes at block start;
- identical proposal generator, predictor, updater, budget/risk values and admissible action sets within each active-versus-random primary pair;
- oracle output store was unreadable by non-oracle processes;
- all factual evidence resolves through F1A anchor/witness.

Any confirmed leakage invalidates the entire campaign. A construction mismatch may regenerate a block only before assignment, arm initialization and commitment publication. Any later matching failure follows intention-to-treat failure rules.

## 10. Failure, attrition and sensitivity analyses

Primary analysis counts every arm crash or timeout after assignment, budget exhaustion, unevaluated acquisition and scientific abstention without completed gates as acquisition zero. Only construction failures detected before assignment, arm initialization and commitment publication are replaced from a preordered reserve universe and fully reported.

If infrastructure failures exceed 5% of blocks, or differ between either active arm and its substrate-matched random control by more than 2 percentage points, no primary autonomy claim is made. Sensitivity analyses may report completed-protocol results but cannot replace intention-to-treat.

## 11. Oracle and regret

Oracle outputs are revealed only after non-oracle finalization. Oracle regret is computed only when the oracle had at least one admissible alternative and the factual action evaluation exists. Zero alternatives, zero evaluations or censored outcomes yield `not_evaluable`, never zero regret.

Oracle performance defines an empirical ceiling. Failure to reach it does not falsify autonomy; oracle/non-oracle information crossing does.

## 12. S4 pilot analysis

The unit is a paired S4 instance receiving the same EML proposals. Compare `EML_ONLY` and `EML_PLUS_N4_SHADOW` on:

1. whether the selected experiment would change;
2. valid acquisition under the shadow-selected experiment;
3. downstream decision utility.

N4 proceeds beyond shadow only if the selected experiment changes in at least 10% of held-out pairs and acquisition or downstream utility has a positive 95% paired interval. Brier, ECE, nDCG and MRR are diagnostic only. This pilot is labelled non-confirmatory regardless of outcome.

## 13. A11/A12 model-dependence and immediate-reward audits

S3 makes immediate benefit, action cost and declared risk identical under both causal classes; only delayed outcomes discriminate. The primary C4-versus-`C2[A11]` comparison therefore matches immediate reward opportunities by construction.

Before confirmation, a DRY_RUN model-dependence audit uses lags and debt probabilities explicitly excluded from both DEV and confirmation, with permuted aliases. Static dependency inspection must find no import/call path from A11 to private scenario transitions. C4 must produce all predictions through public `HypothesisCandidate` models. Failure of either condition stops C4.

During confirmation, acquisition differences are reported by difficulty tier. A non-positive C4-minus-random point difference in any tier triggers the preregistered abandonment rule even if H2 passes overall; no additional p-value is used for this anti-hand-matching diagnostic.

## 14. Reporting requirements

The report must include every arm, family, assigned block, exclusion, failure and audit flag. It must publish primary tables before secondary metrics, preserve failures as failures, distinguish `UNMEASURED` from zero, and state unsupported hypotheses explicitly.

No post-hoc subgroup, alternative acquisition threshold, different budget, favorable family aggregate or metric substitution may alter the preregistered verdict. Such analyses must be labelled exploratory.

## 15. Architecture abandonment rules

- Abandon MCI+VOI for each family whose own H1-S2 or H1-S5 fails, if leakage is intrinsic to its adapter, or if it cannot maintain two rivals.
- Abandon A11/A12 Scientific Deliberation for deferred mechanisms if H2 fails, if benefit depends on hand-matched world models, or if future state leaks into simulation.
- Keep N4 out of active selection if the S4 advancement gate fails.
- Keep the hybrid ecology blocked throughout EA1-C-v1 regardless of specialist results.
