# Model card: masked historical draft logistic regression

## Intended use

Offline research into associations between visible ranked champion composition and match outcome. The target is the probability of the user's team winning in the selected region/queue population. Proposed live use is gated pending Riot review. No prediction of an individual player's skill, hidden identity, matchmaking rating, or future actions is provided.

## Data and freshness

Only validated, deduplicated official Match-V5 records dated within the rolling 30-day window are eligible. Default collection targets 100,000 EUW1 queue-420 matches. Training uses up to the most recent 29 days, leaving a one-day safety margin before its oldest input violates the maximum age. A 50,000-match floor is enforced in production. It is an engineering readiness threshold, not proof of calibration or utility.

Ladder tiers define current seed cohorts. Match-V5 does not establish everyone's rank at match time; no rank labels are invented. Sampling based on active ladder seeds can be biased, and differences in patch population, rank, geography, and time of day may limit generalization. The database intentionally discards player identities, so repeat-player correlation cannot be grouped out of the evaluation. No player-level causal or independence claim is made.

## Features

Blue-versus-red signed champion indicators, allied pairs, unordered allied triples, antisymmetric opposing pairs, role/champion indicators when known, patch/champion interactions, patch/platform/queue context, and visible-team counts. Features are hashed into 262,144 dimensions with deterministic hashing. Features occurring in fewer than 20 unique fit matches are omitted. Hash collisions are possible. Contributions are measured by omission at inference, so the UI does not falsely attribute a hashed coefficient to one unique feature.

Region/queue fitting is scoped separately. Patch coverage for serving means patches observed in the **fit cohort**; patch frequencies in the untouched test cohort do not determine inference weights. Unknown patch predictions average covered patch predictions using recency-weighted fit-cohort frequencies. Newer patch outcomes still need to arrive before patch-specific associations can be learned.

No game duration, kills, economy, surrender outcome flags, match-end telemetry, player identifiers, or other future information is used as a predictive feature. Duration and remake flags are used only for dataset eligibility.

## Partial drafts

For each fit match, create eight deterministic seeded views: empty, complete, and six masks with independent 0–5 visible champions per side. Role labels are randomly omitted in masks to train cases where roles are unavailable. Every view retains that match's outcome, but weights sum to the original match weight. Masking happens after chronological splitting.

The masked loss estimates a conditional association given the revealed subset, averaged over unobserved champions in the historical data distribution. Inference never inserts remaining champions. The assumption is that training masks reasonably approximate the missing-information pattern of the target draft. Real pick order, counter-picking, role swaps, and team preferences need not be missing at random; this is a limitation and not causal marginalization over a real team's strategic policy.

Hover predictions and locked-only predictions run independently. Conflicting hovers suppress the tentative estimate. Rare/unseen visible champions suppress estimates. Side reversal changes the perspective; unknown side is an equal mixture of both orientations, with no claim that side has been detected.

## Fitting and calibration

L2 logistic regression, fixed C=0.1, liblinear solver, deterministic seed. Time weighting has a seven-day half-life. The initial 60% of chronologically ordered unique matches fit the estimator. The next 20% fit a sigmoid calibrator over estimator logits. The last 20% are untouched final evaluation. Timestamp ties stay together. Nonconvergent fits do not publish an artifact.

The baseline is the weighted historical blue win rate of the fit cohort. It is not forced to 50%. Empty drafts return the baseline rather than treating a model intercept as measured evidence. A specific supported patch has its own empirical weighted baseline. For an unknown side and no visible picks, equal weighting of the two sides mathematically yields 50%; that is a stated mixture assumption, not a universal baseline.

## Evaluation and uncertainty

Evaluation reports Brier score, log loss, equal-width calibration bins, and expected calibration error at 0/2/4/6/8/10 visible champions. Each group uses the same independent test matches with deterministic masks. Baseline scores use the same test outcomes. Results across reveal groups share matches and must not be treated as independent evidence. A warning flags groups whose model Brier score is more than 0.002 worse than baseline; this flag is not a hypothesis test or a confidence threshold.

The displayed band is the 95% Wilson interval of observed wins within the corresponding held-out probability bin at the nearest evaluated reveal count. It describes aggregate calibration uncertainty. It is not an individual-match probability confidence interval, does not include model parameter uncertainty, and is not validated separately for odd reveal counts, each champion combination, each rank, or each patch. No band is given for unknown side. Users should inspect sample counts and calibration tables.

Historical pair rates use at least 100 fit-cohort occurrences and are unadjusted descriptive statistics. Champion omission differences reflect this fitted model, include correlated features, and are neither additive decompositions nor causal contributions. Hovers can change before locking.

## Artifact lifecycle and limitations

Local artifacts include model/calibrator, supported feature set, cohort counts, patch coverage, baseline, pair counts, version, schema, scikit-learn version, and evaluation. Only artifacts generated locally should be loaded: joblib is an executable serialization format and must not be imported from untrusted sources. There is deliberately no model-upload API.

Corrupt/incompatible/synthetic-labelled/expired artifacts fail closed. Predictions for an unsupported region/queue/patch or a visible champion with fewer than 20 fit occurrences are unavailable. A model may still be statistically weak with many matches; inspect its real held-out performance. Champion composition alone cannot measure individual skill or gameplay. No causal effect, guaranteed improvement, or broad generalization is claimed.

Synthetic test outcomes validate the software pipeline only. They are never installed into the real dataset or used to claim real model quality.
