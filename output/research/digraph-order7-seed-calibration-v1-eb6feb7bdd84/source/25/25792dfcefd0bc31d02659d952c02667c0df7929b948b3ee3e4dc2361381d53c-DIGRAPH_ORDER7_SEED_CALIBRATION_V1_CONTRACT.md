# Digraph order-7 seed calibration v1 contract

Status: **frozen before any order-7 semantic evaluation; calibration only**  
Freeze date: 2026-07-19

This contract authorizes only the construction and independent replay of one
order-7 launch seed for each frozen target. It does not authorize the held-out
search, a manuscript claim, a figure, or a PDF rebuild.

## Purpose

The future order-7 validation needs a known exact parent for each target while
ensuring that no order-7 seed is counted as a discovery. Stage 0 therefore
constructs seeds openly, registers every inspected order-7 graph as exposed,
and freezes the resulting leakage registry before any held-out proposal.

Targets:

- `0 = {|}`;
- `* = {0|0}`; and
- `{0|1} = 1/2`.

Ruleset: Digraph Placement under finite normal play. Playing a vertex removes
it and all active out-neighbors; a player without a move loses. Exact equality
is mutual recursive Conway comparison over the complete literal game. There
is no depth cutoff or heuristic value.

## Bound prior calibration

Only the finalized v2 calibration may supply order-6 parent controls:

- directory:
  `output/research/digraph-fiber-calibration-v2-9e8d78ec958a`;
- manifest SHA-256:
  `9e8d78ec958aac4008ded59fb5f65ba3e319570503f298212f3ab7fafc2942bb`;
- event-ledger file SHA-256:
  `3943fbd9fa9e8308872d385ef0f74a31edf36414da4d5e6880626eb406e22cd3`;
- summary payload SHA-256:
  `67cb2de42fcfb75ba5a78dc0e2b11bc196ba2438b8d1e18344acee803c27bc99`;
- independent-replay report SHA-256:
  `0e494771b40b27bb7278e26652cce4cd6f3d266422510f696f6124837f2e897c`;
- completion marker must say all checks pass; and
- calibration decision must remain `NO_GO`.

The selected controls are mechanically the first retained order-6 exact match
for each target under policy `seeded_unstructured_repertoire`, ordered by
global event index.

### `0` parent

```json
{"arcs":[[0,1],[0,3],[0,4],[0,5],[1,2],[1,4],[2,3],[2,4],[3,0],[3,2],[3,4],[3,5],[4,1],[5,0],[5,4]],"blue_vertices":[0,3,5],"order":6}
```

- global event index: `338`
- event SHA-256:
  `139192ec4cf01b2f02610251fe582049a6c07c5fe0780b7d9572e0d45cd85aeb`
- candidate SHA-256:
  `e03503499a331913704cdaf663c9a184ad3950065b6ab505b406bc2f5abf83da`
- quotient SHA-256:
  `d57c656db3de1302d098e1d6911aa1a7ff0cbff9716d04d837fad2abb5e3bd9a`
- literal-game SHA-256:
  `b2f4f1a75c9a372f4e8a255e10795f043beda975d6b55aea71e56803b895eb66`

### `*` parent

```json
{"arcs":[[0,3],[0,5],[1,2],[1,5],[2,0],[2,1],[2,3],[3,1],[3,5],[4,1],[4,3],[4,5],[5,1],[5,2],[5,3]],"blue_vertices":[0,1,2],"order":6}
```

- global event index: `41,065`
- event SHA-256:
  `1930813c8b341d6341657076dd95e8ceb5ec123b7fd120cdfe263dd9a8a34a35`
- candidate SHA-256:
  `88817ee933eb1b5286670e99a77b5547327ae1bbe2260a2ec77bc6ff31ca6056`
- quotient SHA-256:
  `136941846da7c360629d5ad33cc667ca26db9efffaf8c1c3ecf1e75e58754046`
- literal-game SHA-256:
  `b1e7d2bc7f66531d2b0523763143faa9c18a385bf22506bc685aad5cdeffd447`

### `{0|1}` parent

```json
{"arcs":[[0,2],[0,4],[1,0],[1,3],[1,4],[1,5],[2,0],[2,4],[2,5],[3,0],[3,1],[3,2],[3,4],[3,5],[4,0],[4,3],[5,0],[5,1],[5,2]],"blue_vertices":[0,2,3,4],"order":6}
```

- global event index: `82,835`
- event SHA-256:
  `d0ff86e9258cbe3b626b9b759d3460547802ad8195a594da9f57a4f316f5342b`
- candidate SHA-256:
  `59f0d6de49ca1a34a9e56d6a326778f610abcfd81b82deaad6bef3572480cc81`
- quotient SHA-256:
  `225f3b8352212fe22cf0f06e6a1f6195eef18281aba22a1a488ef2672560f8de`
- literal-game SHA-256:
  `f249e4138d4305dbd96f60afd59c193ef96300ffdc01b99f089cd4276876f117`

The calibration must replay the event-chain position and all three existing
artifact, derivation, and equality sidecars before inspecting an extension.

## Registered order-7 implementation fixture

One order-7 graph is exposed in advance for derivation-schema tests:

```json
{"arcs":[[0,1],[1,2],[2,3],[3,4],[4,5],[5,6]],"blue_vertices":[0,2,4,6],"order":7}
```

It is a schema/replay fixture only. It enters the leakage registry under reason
`ORDER7_DERIVATION_V3_TEST_FIXTURE` and may never count as a seed discovery,
held-out proposal, transition, atlas member, or figure.

No other order-7 graph may appear in a unit test, debug trace, notebook,
terminal experiment, or source fixture before this calibration closes. If one
does, it must be appended to a new version of this contract before evaluation.

## Deterministic extension order

For each bound order-6 parent, add vertex `6`. Enumerate exactly the following
8,192 possible incident patterns in ascending integer index:

```text
extension_index = new_colour_bit * 4096 + incident_arc_mask
```

`new_colour_bit = 0` makes vertex 6 red; `1` makes it blue. The twelve bits of
`incident_arc_mask`, from least to most significant, are:

```text
0->6, 6->0, 1->6, 6->1, ..., 5->6, 6->5.
```

All old colors and arcs remain byte-for-byte unchanged. Each index is visited
once. A disconnected extension is recorded as a grammar rejection without an
equality call. A connected extension receives exactly one exact equality
decision. There is no resampling, randomization, descriptor-based choice, or
author override.

Stop independently per target at the first connected exact match. The selected
extension is the only launch seed for that target. Every earlier inspected
extension, including mismatches and disconnected graphs, remains in the
leakage ledger. Extensions after the first match are never evaluated.

If a target has no exact match by index 8,191, Stage 0 is `NO_GO` and the
held-out study remains closed.

## Proof and output contract

Every connected extension row binds:

1. canonical candidate bytes and SHA-256;
2. exact color-preserving digraph quotient;
3. complete order-7 derivation certificate under a new v3 schema whose only
   semantic extension from v2 is the maximum order 7;
4. literal-game digest;
5. mutual Conway comparison verdict against the frozen target; and
6. previous-row and row SHA-256 in one global chain.

Each selected seed additionally receives content-addressed graph,
derivation-v3, and equality-v1 sidecars. The run creates exclusively:

- `manifest.json`;
- `extensions.jsonl`;
- `leakage_registry.json`;
- `seed_controls.json`;
- content-addressed sidecars;
- `independent_verification.json`;
- `negative_tests.json`;
- `CALIBRATION_REPORT.md`; and
- `RUN_COMPLETE.json` only after all gates pass.

The run directory is created exclusively and never overwritten or resumed.

## Independent verification and mutations

A separate read-only process must:

- recompute every extension from its parent and index;
- replay connectedness, quotient, complete derivation, literal game, and exact
  equality;
- prove that each selected seed is the first matching index;
- verify every source/input/file/event hash; and
- reject rehashed mutations of the fixture order bound, graph bytes, incident
  bit order, target, equality direction, quotient, literal digest, selected
  index, leakage membership, sidecar path/hash, event link, and completion
  status.

Any missing row, failed replay, mutation escape, nondeterminism, resource
failure, or source change yields `NO_GO`. A partial success cannot supply a
seed for the held-out study.

## Evidence boundary

A pass establishes only that three exposed order-7 launch seeds were
constructed deterministically and independently replayed. The seeds and every
inspected extension are calibration leakage. No count, contrast, transition,
or image from Stage 0 is paper evidence.

The held-out order-7 search requires a separate preregistration, source freeze,
launch record, and independent replay. It must reject every graph in this
calibration's leakage registry.

