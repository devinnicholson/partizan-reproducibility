# Fixed-Value Scope Extension V1: Terminal Result

Status: **SCOPE_EXTENSION_READY**

The scope extension supplies a second finite partizan ruleset and twelve
stratified target values without weakening the exact admission standard.

## Domineering result

Each of three policies received 2,048 exact-verifier calls for each of twelve
values and three acquisition seeds: 221,184 calls in total. The values comprise
one zero, three positive games, three negative games, and five fuzzy games.
Target is the bootstrap unit; the three acquisition seeds are averaged inside
each target.

| Policy | Exact equality rate | Certified literals | Ruleset quotients |
|---|---:|---:|---:|
| Random | 0.0362 | 74.19 | 69.14 |
| Neural equality | 0.5162 | 1,057.08 | 402.28 |
| Neural equality + novelty | 0.5148 | 1,054.31 | 405.69 |

Novelty guidance increased certified player-preserving ruleset quotients by
3.42 per target and seed over equality-only acquisition. The 95% target-level
bootstrap interval is [0.81, 6.78]. Its certified-literal ratio relative to
equality-only acquisition is 0.9974, with interval [0.9962, 0.9988]. Against
random acquisition, the quotient difference is 336.56 with interval
[224.17, 453.75].

All target-policy-seed cells contained at least one certified realization. The
run had zero resource failures. Independent replay reconstructed every one of
the 221,184 decisions and rejected all thirteen frozen corruption families.

## What this supports

The result addresses the paper's scope limitation in two ways.

- The existing fresh Birthday-5 Digraph Placement evidence covers 24 values,
  reaches every target, and raises mean distinct exact quotients from 6.17 to
  10.83 over the frozen earlier reranker. One stricter ablation gate failed, so
  this remains supporting evidence.
- Domineering changes the realization language from coloured directed graphs
  to geometric cell sets. Under the same exact Conway comparison, novelty
  guidance produces a small, target-level robust increase in certified
  player-preserving representations while retaining essentially all equality
  yield.

The evidence supports a cross-family claim about certified representational
search. It does not establish human aesthetic preference, a universal effect
over all combinatorial games, or target-value generalization beyond the frozen
bounded universes.

## Authorities

- Protocol: `a4a645d1be3781b56ed43ac8cf5cc25bec82a43857d2d69329986aa0c5441003`
- Model and policy freeze: `2b0ff2cdbad0d25698f234636b1fa8d5f88cb16b5315a8a5452d14ce62af04ad`
- Frozen schedule: `68fef708fbfa252bd6d3476ffd3f483029b931742d34d8fd390954dab40af202`
- Evaluation: `476952d72cbd36542e0c2a653ce6f050a6dd3b33fc8ea981da8bc5a9e1bec57b`
- Independent replay: `25a00f47d70866a785363835bb050b36d7f9a680ac61a0778f84352ab3674f31`
- Terminal result: `af03f22103ca7cef0c233d6d529896bb95b3f0418e5e04bb31dcf308099e096a`

The current paper and its PDF were not changed during the experiment.
