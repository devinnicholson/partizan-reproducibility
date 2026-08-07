# Fixed-Value Scope Validation V1

Status: **VALIDATION_COMPLETE**

This phase adds implementation-independence evidence and budget-resolved
discovery evidence to the completed Domineering scope extension. It makes no
new calls to the primary verifier and leaves the manuscript unchanged.

## Cross-oracle agreement

The original evaluation used the Python short-game oracle. A frozen,
verdict-balanced sample was reconstructed through Thermograph's separate Rust
arena and Conway-comparison implementation.

- 1,728 event samples: eight from every target-policy-seed-verdict stratum.
- 144 controls: the complete 12 by 12 target comparison matrix.
- 1,872 verdicts returned, with zero resource errors and zero disagreements.
- Thermograph commit and source hashes matched the frozen protocol, and its
  worktree was clean.

The first attempt preserved in `failed-resource-runtime1` stopped on five
positions because the adapter allowed eight root moves. A prospective
amendment raised that bound to twelve, the true maximum for a 4 by 4 board.
The sample, comparison algorithm, and acceptance criteria remained fixed.

## Discovery over budget

The already-frozen 221,184-event ledger was reduced at prefix budgets 128,
256, 512, 1,024, and 2,048. Values below are means per target-policy-seed cell.

| Calls | Equality quotients | Novelty quotients | Difference | 95% target interval | Relative lift |
|---:|---:|---:|---:|---:|---:|
| 128 | 76.75 | 79.56 | 2.81 | [1.92, 3.67] | 3.66% |
| 256 | 124.86 | 129.08 | 4.22 | [2.78, 5.67] | 3.38% |
| 512 | 190.64 | 193.92 | 3.28 | [1.72, 4.97] | 1.72% |
| 1,024 | 280.72 | 284.06 | 3.33 | [1.42, 5.44] | 1.19% |
| 2,048 | 402.28 | 405.69 | 3.42 | [0.81, 6.81] | 0.85% |

The novelty advantage appears at the first frozen prefix and remains positive
at every later budget. Its relative effect is largest early, then narrows as
both neural policies exhaust easier quotient classes. Certified-literal yield
remains nearly identical: the novelty-to-equality ratio ranges from 0.9974 to
0.9993 across the five budgets.

## Interpretation boundary

The oracle check supports the correctness of the Domineering labels across
two implementations. The prefix curves place the terminal novelty effect
throughout acquisition, beginning at the first frozen budget.
The curves are a post-hoc secondary analysis of frozen events. Neither result
establishes human preference, unrestricted combinatorial-game generality, or
zero-shot generalization to unseen target values.

## Authorities

- Cross-oracle protocol: `70b663f1772cdc5124ed572f6119d56b6ae73e525234e828c850e5934ab5cf5a`
- Resource amendment: `fab4da97fa3296c67f77016ede6bfe80e964a6c6e2d7c84ce924c8592f8b0fd4`
- Cross-oracle result: `c427c27fb6c22078fc5251d61dfa54de1a1ccf33e4913a92e5901e3b4152d421`
- Discovery-curve protocol: `7168e72c4a02a02a59e44bf396e92995370a9088c6bc4cf1e46faabda761127e`
- Discovery-curve result: `0e5c656f8563a16968e7dddb04feb209389884f3d7d8f111f68deb767d51d95f`

The terminal combined authority is
`output/research/fixed-value-scope-v1/validation-v1/VALIDATION_RESULT_AUTHORITY_V1.json`,
artifact `2defec1917d485d3e70aee19b50d4ffd9c2c216bc6c39f5c4f2885ab2700032b`.
