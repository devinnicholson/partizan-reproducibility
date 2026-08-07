# Submission Evidence Audit V1

Audit date: 2026-08-06

## Decision

**Scientific evidence: PASS**  
**Submission release: BLOCKED pending one external archival action**

The final local audit recorded 87 checks. Eighty-six scientific, integrity,
provenance, reconstruction, and release checks passed. There were no
scientific failures and no warnings. The public archival DOI remains open.

The audit did not edit the manuscript or any frozen experiment directory.

## Canonical evidence boundary

Only three result directories support claims in the current paper.

| Role | Canonical directory | Independent audit result |
|---|---|---|
| Primary held-out policy evidence | `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4` | Exact reconstruction of inference and gate authorities from 108 frozen streams; all twelve gates passed |
| Cross-ruleset scope evidence | `output/research/fixed-value-scope-v1` | Primary and prefix reducers reproduced byte-for-byte; independent oracle comparison found zero disagreements |
| Historical structural case and figure evidence | `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db` | Fresh full replay passed; scientific projection matched; all fifteen corruption tests passed |

Five directories are classified as supporting or calibration material. Sixty-four directories, including all Birthday-5/V5 iterations and the pawn studies, are excluded from paper claims. They remain preserved as research history.

## Claim audit

### Primary held-out Digraph Placement experiment

- Exact-verifier calls: **221,184**, comprising **73,728 per arm**.
- Equality-only acquisition: **67,151 quotient discoveries** and **33,796 literal discoveries**.
- Equality-plus-novelty acquisition: **70,506 quotient discoveries** and **45,863 literal discoveries**.
- Uniform-random acquisition: **45,076 quotient discoveries** and **31,647 literal discoveries**.
- Literal discovery increase over equality-only: **35.7%** from the aggregate totals.
- Quotient retention relative to equality-only: **1.04996**, with 95% bootstrap interval **[1.03381, 1.06852]**.
- Quotient discovery increase over random: **56.4%** from the aggregate totals.
- Corruption tests: **30 of 30 families rejected**.
- Independent reconstruction: exact match for both the inference and gate authorities.

These values support the paper's claim that a learned acquisition policy can search among certified-equal realizations and substantially increase literal diversity while preserving, and slightly increasing, quotient discovery.

### Domineering scope experiment

- Exact-verifier calls: **221,184**.
- Ruleset-quotient effect of novelty over equality-only: **+3.4167**, with 95% bootstrap interval **[0.8056, 6.7778]**.
- Certified-literal ratio relative to equality-only: **0.99737**, with 95% bootstrap interval **[0.99623, 0.99878]**.
- Independent cross-oracle check: **1,872 results**, **0 disagreements**, **0 errors**.
- Primary authority reconstruction: byte-for-byte identical.
- Prefix-curve reconstruction: authority and CSV byte-for-byte identical.

These values support a bounded scope claim: the acquisition principle transfers to a second ruleset while retaining essentially all certified literal yield. They do not establish universal transfer across combinatorial games.

### Historical structural case

- Event ledger: **73,728 events**.
- Linked certified motifs: **8,111**.
- Fresh independent replay: **PASS**.
- Scientific projection relative to the frozen authority: **exact match**.
- Corruption tests: **15 of 15 families rejected**.

This evidence supports the structural figure and the discussion of distinct literal encounters inside a certified value class. It is historical training and case-study evidence, rather than the held-out policy estimate.

## Provenance and leakage findings

- The V3 primary test authorities, protocol, authorization, streams, inference, gate, corruption report, and completion marker all match their frozen SHA-256 bindings.
- The scope reducers reconstructed their frozen outputs from the retained records.
- The historical verifier completed from a fresh copied input layout and reproduced the frozen scientific content.
- The current manuscript does not cite Birthday-5/V5 results as evidence for its claims.
- The current submission PDF matches the handoff record at SHA-256 `fc1ab38ff2fdd2a9d4d16efb72ae20462985a146fe3417c8de684110985fe29b`.

## Completed release remediations

1. The evidence-eligibility matrix now binds the current submission PDF and transition figure.
2. The deterministic compact release candidate now contains 149 members, including the canonical scope authorities, compact bindings, scope figure, V3 dependency closure, replay wrapper, archive authority, citation metadata, and Zenodo metadata. Its SHA-256 is `e7c969361a8f3d899163e18ee41ea3274c26657b560a7f343df3f0a8319011c6`.
3. The portable V3 staging wrapper passed the frozen verifier's authorization-path and dependency checks without modifying the verifier.
4. The licensed full-evidence archive contains 585,418 members across all three canonical evidence trees. Its SHA-256 is `59e8a1e2d68801f605eb98a2632c5a6265858365af8018af51c68f2e6f45e197`.
5. The compact ZIP and full tarball passed compressed-stream integrity checks. The archive builder also passed a two-build determinism regression test.

## Remaining external action

Create a Zenodo record using `docs/research/FIXED_VALUE_ZENODO_METADATA.json`,
upload both archives, verify their checksums, reserve or mint the DOI, and bind
that DOI in the archive authority, supplement, and submission metadata. The
record must remain unpublished until the uploaded files and metadata have been
reviewed by the author.

## Machine-readable authority

The canonical audit manifest is `output/research/submission-evidence-audit-v1/AUDIT_MANIFEST.json`.

- Audit artifact SHA-256: `b0f8e1ada0f6488d8e561b68d956359d5ee243f1029c535f2ba6a38a63ac20a5`
- Status: `PASS_WITH_RELEASE_REMEDIATIONS`
- Scientific evidence status: `PASS`
- Submission release status: `BLOCKED`
