# Order-7 fixed-value transitions v1 preregistration

Status: **frozen before held-out execution; paper eligibility depends on the
conjunctive gate below**  
Freeze date: 2026-07-19

## 1. Question

When exact combinatorial-game value is fixed, can a proof-carrying search move
through more than one formally distinct residue of representation?

The study separates three levels:

```text
directed colored graph  ->  complete literal game  ->  CGT value
      embodiment                game form              identity
```

It tests for two quotient-changing local transitions:

1. **embodiment-only:** the color-preserving directed-graph quotient changes,
   while the complete literal-game digest does not;
2. **literal-tree crossing:** both the graph quotient and complete literal-game
   digest change, while exact CGT value does not.

These are existence claims inside a frozen sampled trajectory. The study does
not estimate their prevalence in the complete order-7 universe and does not
assign beauty, elegance, surprise, or human preference scores.

## 2. Frozen representation and semantics

Every candidate is a Digraph Placement position with:

- exactly seven vertices numbered `0` through `6`;
- a red or blue bit on every vertex;
- any subset of the 42 directed off-diagonal arcs;
- no loops;
- a weakly connected underlying undirected graph; and
- finite normal play: selecting a vertex removes it and all currently active
  out-neighbors; the player without a move loses.

Blue vertices are Left moves and red vertices are Right moves. The complete
literal game is recursively derived without a depth cutoff. Equality to a
target is mutual Conway comparison. Graph identity is exact color-preserving
directed-graph isomorphism, represented by the frozen canonical quotient code.

The targets, fixed before this study, are:

- `0 = {|}`;
- `* = {0|0}`; and
- `{0|1} = 1/2`.

## 3. Calibration boundary and immutable inputs

The only order-7 launch controls are the three first-match seeds from the
completed Stage-0 calibration directory:

`output/research/digraph-order7-seed-calibration-v1-eb6feb7bdd84`

The held-out generator and verifier must refuse to proceed unless all of the
following file identities and embedded completion gates replay:

| File | SHA-256 |
|---|---|
| `manifest.json` | `f53642fc48171fa23151c2c5dde86ea9600631cb581ff187bf910aed1afdb480` |
| `extensions.jsonl` | `6d162a7629e7b22a5e4925ac2741d248a680675fe25e9b249c0475f5d48cc672` |
| `leakage_registry.json` | `13156553aba96ea455ca57894121cdad310f9bfb5a12bf82156af2b5d41f8aba` |
| `seed_controls.json` | `ac719d0eda3f7fc5f729ba0511e4bd42275fef85848a72db0b51b190fa78a824` |
| `independent_verification.json` | `177d23418c42bbf9519aec2a19b8699d715d47df191cb8d734ad9c9d3e635f3a` |
| `negative_tests.json` | `9a695ab6addb0f2b1a348817576978f2cfcdd148f873af102a5040e93bc259c5` |
| `RUN_COMPLETE.json` | `a6974e5fa8d32a8daf69d2078a074e777fe8fa66e41a40556c6f9ca52a0896a8` |

Required embedded identities include manifest
`eb6feb7bdd848613c5bf3752ab0a91f08d9b3f6cda61e4b0fbf3b482cb56d04c`,
leakage registry
`dd42ea0518d077cf576bfac062f0329af04de80f97a44fe3bf8c3e26da5d0501`,
seed controls
`ae9749d984c6047db29d3788f3fa9a8432a5d93de0355e9c92cb1539f78d98f7`,
independent verification
`13ef0264afaeed49896992aead62d35fa7f9c3842d22d16e096edbc8c0a75467`,
and completion
`affea5aed0a606f16ec8a28318fab217cfad908cfcbc89433bca4e707dba4949`.

The failed calibration attempt is also bound for disclosure:

`output/research/digraph-order7-seed-calibration-v1-c4b2bb2ec334/FAILURE.json`

Its file SHA-256 is
`3a43b283b8bc278007d23a3efac33d4d809b499e1588d089f6a0a6533e109029`.
Its additional exposed candidate is already present at extension index `1`
of target `0` in the successful leakage registry. The held-out verifier must
check that correspondence explicitly.

All 1,689 inspected Stage-0 extensions and the registered order-7 derivation
fixture are leakage. Collision is defined by canonical candidate-record
SHA-256, not by author judgment. The three selected order-7 seeds are controls:
they may be parents but never discoveries, primary endpoints, or figures.

## 4. Frozen search policy

The sole policy is a seeded unstructured repertoire. It was selected because
the earlier calibration did not establish a coverage advantage for MAP-Elites.
No policy comparison is performed here.

There are twelve streams per target. Their base seeds are:

```text
104729 + 1009*i, for i = 0, 1, ..., 11
```

Thus the fixed base seeds are `104729`, `105738`, `106747`, `107756`,
`108765`, `109774`, `110783`, `111792`, `112801`, `113810`, `114819`, and
`115828`. Each target/seed stream receives exactly 2,048 raw proposals, for
73,728 proposals in total. Checkpoints are 128, 512, 1,024, and 2,048. There
is no success stopping rule.

Separate proposal and parent-selection RNG streams are derived by taking the
first eight bytes, big-endian, of:

```text
SHA256("partizan.digraph_order7_fixed_value_transitions.v1|"
       + base_seed + "|" + target + "|" + stream_name)
```

where `stream_name` is `proposal` or `parent_selection`. The launch record
binds the exact Python interpreter and all source bytes. The independent
verifier reconstructs every draw from these derivations.

At the start of a stream, the live repertoire contains only the target's
Stage-0 order-7 seed. Every later held-out quotient-unique exact match is
inserted. Parent selection is uniform over the lexicographically sorted live
quotient SHA-256 keys and occurs once for every proposal, including an
immigrant proposal.

### 4.1 Proposal kernel

One `randrange(8)` draw selects the proposal mode:

- result `0`: uniform order-7 immigrant;
- results `1` through `7`: local mutation.

An immigrant draws seven fair color bits, then 42 fair arc bits in nested
source-major, target-minor order, skipping self-arcs.

A local mutation selects uniformly with `randrange(3)` among:

1. `flip_colour`: uniformly select one of seven vertices and flip its color;
2. `toggle_one_arc`: uniformly select one of the 42 directed off-diagonal
   arcs and toggle it;
3. `toggle_two_arcs`: uniformly select two distinct members of the same
   ordered 42-arc list without replacement, then toggle both.

The ordered arc list is
`[(s,t) for s in range(7) for t in range(7) if s != t]`. A local proposal
records its selected parent. An immigrant consumes the parent-selection draw
for deterministic accounting but does not create a local transition edge.

## 5. Evaluation and rejection accounting

Every raw proposal consumes one budget unit. There is no resampling.
Evaluation proceeds in this order:

1. construct and record the canonical candidate;
2. reject if weakly disconnected;
3. reject if its candidate SHA-256 is in the frozen leakage registry;
4. derive the complete literal game and decide exact target equality;
5. reject exact mismatches;
6. compute the color-preserving directed-graph quotient and descriptors;
7. classify a local exact transition against its selected parent; and
8. insert the candidate only if its quotient is new within that stream.

Candidate-record duplicates within the held-out run are not leakage and are
not free resamples. Exact quotient rediscoveries may contribute an observed
local transition but not a new representative. Content-addressed graph,
derivation, and positive equality sidecars are written for every retained
quotient-unique held-out representative. The event row still binds the exact
decision and literal digest for all connected, nonleaking proposals.

For a local exact proposal, transition class is recomputed as:

```text
parent quotient == candidate quotient
    -> quotient_self
else parent literal digest == candidate literal digest
    -> embodiment_only
else
    -> literal_tree_crossing
```

Only `embodiment_only` and `literal_tree_crossing` are quotient-changing.
An event is a primary transition only when both its parent quotient and its
candidate quotient were first discovered in the held-out portion of the same
stream. A seed-to-held-out transition is reported but cannot satisfy a gate.

## 6. Frozen formal measurements

For every retained representative the study records:

- candidate and quotient SHA-256;
- complete literal-game SHA-256;
- graph arc count and blue/red vertex counts;
- distinct literal-tree node and edge counts;
- game birthday;
- dominated and reversible root-option counts;
- root simplification count; and
- the pre-existing executable descriptor cell.

These are structural descriptions, not aesthetic measurements. Primary
counts are unioned across twelve streams separately by target. A quotient or
literal digest observed in more than one stream counts once in the union.
Primary transition existence is assessed within streams; edges are then
unioned by target with provenance preserved.

## 7. Conjunctive paper-eligibility gate

The held-out result is `GO` only if **every target** has:

1. at least four held-out quotient-unique order-7 representatives, excluding
   all calibration seeds and leakage;
2. at least three held-out complete literal-game digests;
3. at least one independently replayed primary `embodiment_only` transition;
4. at least one independently replayed primary `literal_tree_crossing`
   transition; and
5. 100% replay of proposal derivation, parent selection, candidate bytes,
   connectedness, leakage decision, complete literal game, exact equality,
   quotient, descriptors, transition class, repertoire update, event chain,
   summary projection, and source/input hashes.

The gate is conjunctive across targets. A partial pass remains `NO_GO` for the
paper claim. Thresholds cannot be lowered after inspection. Counts from a
`NO_GO` run may be disclosed only as a preregistered null or engineering
diagnostic; they cannot be used to imply the missing existence claim.

## 8. Mechanical evidence selection

No screenshot or graph is selected by visual appeal.

For each target and each transition class, select the earliest primary event
by `(global_event_index, parent_quotient_sha256,
candidate_quotient_sha256)`. These six class exemplars are the only default
paper-figure candidates. If the same directed quotient edge occurs earlier in
another stream, the earliest global event supplies provenance.

As a secondary, explicitly labeled structural motif, search for a held-out
quotient that is incident within one stream to at least one primary
embodiment-only edge and at least one primary literal-tree-crossing edge.
Rank motifs by the earliest maximum global event index of their two selected
edges, then target order `0`, `*`, `{0|1}`, then central quotient SHA-256, then
endpoint SHA-256. Motif absence does not change the primary gate and cannot be
interpreted as structural impossibility.

Every rendered panel must show the graph, player colors, transition operator,
target, quotient-prefix pair, literal-digest-prefix pair, and an exact-value
certificate mark. Captions must state that the examples were mechanically
selected from sampled trajectories. Stage-0 controls and calibration outputs
are forbidden as paper figures.

## 9. Integrity, adversarial tests, and launch control

The generator writes a canonical, globally hash-chained JSONL ledger and an
exclusive run directory. A separate read-only verifier must independently:

- replay the Stage-0 completion and all three seed sidecars;
- reconstruct every RNG draw, parent, proposal, rejection, and repertoire;
- recompute every semantic and structural field;
- replay every retained content-addressed sidecar;
- recompute all target unions, transition sets, exemplars, motifs, and gates;
- verify the global event chain and every source/input/output SHA-256; and
- reject at least one rehashed semantic mutation in each of these families:
  graph bytes, RNG seed, parent, proposal operator, leakage membership,
  equality direction, literal digest, quotient, descriptor, transition class,
  event predecessor, retained-sidecar path/hash, summary count, exemplar, and
  final gate.

Tests written before launch may use only the registered Stage-0 fixture,
registered Stage-0 candidates, or mocked semantic evaluators. No additional
order-7 graph may be semantically evaluated during implementation or testing.

After implementation tests pass, a separate self-hashed launch record binds
the preregistration, all executable sources and tests, interpreter identity,
exact command, exclusive output prefix, and resource limits. It authorizes
one generator execution and one independent verification execution. Source
change, failed execution, or additional semantic debugging requires a new
protocol version; the held-out run is never resumed or overwritten.

Frozen resource limits are 900 wall-clock seconds for generation, 1,200
wall-clock seconds for independent verification, and 4 GiB for the complete
run directory. The harness checks time during execution and size before final
completion. A limit breach, exception, missing row, mutation escape, or replay
failure writes a failure record when possible and forbids `RUN_COMPLETE.json`.

## 10. Claim boundary

A `GO` can support only this form of claim:

> In a frozen order-7 Digraph Placement grammar, proof-carrying search found
> multiple held-out realizations of each target and independently replayed two
> kinds of fixed-value local transition: changes of graph embodiment that left
> the complete literal game intact, and changes of literal game that left only
> exact CGT value intact.

It does not support prevalence over all order-7 graphs, an optimal-search
claim, a human-response claim, a universal theory of beauty, generalization
to unrestricted chess, or reinterpretation of the failed kingless-pawn
census. Chess remains a motivating embodiment; this held-out study is the
new system result.
