# Digraph Placement diversity policy V3

**Status:** frozen before V3 validation or test generation  
**Freeze date:** 2026-07-27  
**Scope:** acquisition-support repair; model and scientific thresholds unchanged

## 1. Reason for V3

V2 completed its full 221,184-call test and received `NO_GO`. Independent
replay passed every integrity check and all 26 corruption controls. The failure
was an acquisition deadlock shared by all three arms.

Every Stage-0 control had 42 possible one-arc toggles. All 42 were already in
the prior-split candidate quarantine. A candidate could enter the adaptive
repertoire only after becoming a clean quotient discovery. Consequently every
stream remained at structural tier 3, every selected candidate was a
prior-split collision, and no arm could leave its initial control. The run
contained 190,027 certified exact matches and zero eligible discoveries.

V3 changes the initial controls. It does not change the learned models,
rank-fusion weight, proposal operator, exact verifier, outcomes, test budget,
or scientific thresholds.

## 2. Frozen evidence boundary

The V2 test remains a complete paper-eligible `NO_GO` diagnostic. V3 may use
V2 only to:

- quarantine every observed candidate and quotient identity;
- record literal-game identifiers for audit without blocking on them; and
- establish that the Stage-0 one-toggle neighborhood is closed.

V2 outcomes cannot train a model, select a model, select λ, lower a threshold,
or become proposal features.

## 3. Historical warm starts

The historical transition corpus contains thousands of independently
certified exact-target controls for each target. A semantic-free audit counts,
for every historical control, its weakly connected one-toggle neighbors whose
candidate identities are absent from the full pre-V3 quarantine.

A control is eligible when this count is at least 32 of 42. Eligible controls
are ordered by a domain-separated SHA-256 key. The first 16 controls per target
are frozen:

- the first four are assigned to V3 validation;
- the next twelve are assigned to the confirmatory test.

Every paired triplet shares the same target, pair seed, and initialization
control across all three arms. Initial controls are prior identities and never
count as discoveries. Novelty memory begins with that control alone.

This rule uses graph connectivity and prior candidate membership. It does not
inspect a neighbor's exact value, graph quotient, literal-game digest,
descriptor, model score, or future trajectory.

## 4. Frozen policies

The arms remain:

1. structural random selection;
2. the frozen V1 equality neural policy; and
3. equality plus the frozen V2 graph-embedding novelty term.

All arms generate 16 distinct single-arc toggles, apply the same first-nonempty
structural tier, select one candidate, and consume one exact-verifier call.

The novelty arm uses the V2 ensemble
`ensemble-sha256:313da31b97d65fe2ee12be075c1c21ac866a061db00ef5e8bb15ed55b65142f9`
and λ = 0.5. Its memory appends every selected, prior-split-nonleaking exact
match after verification. Parameters never update online.

## 5. V3 validation

Validation uses four fresh paired triplets per target, 128 calls per arm:

`3 targets × 4 triplets × 3 arms × 128 calls = 4,608 calls`.

Validation performs no model or hyperparameter selection. It is an execution
and support check. Test authorization requires:

- independent replay and all corruption controls pass;
- every first proposal pool uses structural tier 0;
- every stream selects at least one nonprior candidate;
- every arm produces at least one clean exact match for every target;
- every arm produces at least one quotient discovery for every target;
- no V3 test seed or initialization is used; and
- no parameter, threshold, budget, or analysis rule changes.

All validation candidates and quotients enter the test quarantine. Literal
digests remain audit-only.

## 6. Confirmatory test

Test uses twelve fresh paired triplets per target. Each arm receives 2,048
calls in every triplet:

`3 targets × 12 triplets × 3 arms × 2,048 calls = 221,184 calls`.

The raw proposal budget is:

`221,184 calls × 16 candidates = 3,538,944 candidates`.

Checkpoints remain 128, 512, 1,024, and 2,048 calls. Success stopping is
disabled. The paired target stream is the analysis unit.

## 7. Outcomes and inference

A quotient discovery is a selected, independently certified exact match that
has no prior-split candidate or quotient collision and introduces a quotient
not previously seen by that arm.

A literal-game discovery satisfies the same conditions and introduces a
literal-game digest not previously seen by that arm. Literal discovery is
counted independently from quotient discovery.

The co-primary analyses remain:

- the target-macro paired difference in literal discoveries between novelty
  and equality; and
- the ratio of target-macro quotient discovery between novelty and equality,
  with a noninferiority margin of 0.95.

Intervals use 20,000 stratified paired percentile-bootstrap resamples with
seed `12792362788753498044`. A zero denominator fails its ratio check; `0/0`
cannot establish noninferiority or preservation.

## 8. Frozen `GO` gate

`GO` requires every condition:

1. all integrity and independent replay checks pass;
2. literal superiority to equality has a positive point estimate and lower
   95% interval endpoint;
3. quotient ratio to equality has a point estimate and lower endpoint at
   least 0.95;
4. quotient discovery exceeds random with a positive point estimate and lower
   endpoint;
5. total quotient lift over random is at least 5%;
6. total literal discovery reaches at least 95% of random;
7. the mean literal difference from equality is positive for every target;
8. descriptor-cell coverage reaches at least 90% of random;
9. both embodiment-only and literal-tree-crossing transitions occur for every
   target; and
10. every arm and target has nonzero quotient and literal support.

Secondary metrics cannot rescue a failed condition.

## 9. Execution order

1. preserve the independently verified V2 `NO_GO`;
2. freeze and independently verify the V2 reachability diagnostic;
3. freeze and independently verify V3 initializations and fresh seeds;
4. freeze this preregistration, protocol, schema, validator, and mutation tests;
5. implement and test the V3 validation runner and verifier;
6. authorize and generate V3 validation once;
7. independently replay V3 validation and freeze its identity registry;
8. repeat the semantic-free resource preflight;
9. authorize the V3 confirmatory test once;
10. generate and independently replay the test; and
11. promote `GO` or `NO_GO` without threshold changes or secondary rescue.

Any model change requires a new protocol version, new validation, and new test
seeds. All V1, V2, and V3 outcomes must remain disclosed.

## 10. Claim boundary

If V3 receives `GO`, the permitted claim is:

> Within the frozen order-7 Digraph Placement grammar, using leakage-safe
> historical exact controls and equal exact-verifier budgets, a
> graph-embedding novelty term increased literal-game diversity over the
> frozen equality-only neural policy while retaining quotient discovery and
> preserving an advantage over structural random selection.

The experiment does not measure human preference, aesthetic quality,
autonomous taste, complete fiber size, unrestricted chess generalization, or
the best representation of a value. The neural policies propose
representations; the exact verifier certifies correctness.
