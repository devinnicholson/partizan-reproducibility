# Submission evidence index

Freeze audit: 2026-07-28
Repository root: `partizan-fugue`

## Fixed-value scope extension V1

- Terminal interpretation:
  `docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_RESULT.md`
- Prospective protocol artifact:
  `a4a645d1be3781b56ed43ac8cf5cc25bec82a43857d2d69329986aa0c5441003`
- Model/policy freeze artifact:
  `2b0ff2cdbad0d25698f234636b1fa8d5f88cb16b5315a8a5452d14ce62af04ad`
- Evaluation authority artifact:
  `476952d72cbd36542e0c2a653ce6f050a6dd3b33fc8ea981da8bc5a9e1bec57b`
- Independent replay artifact:
  `25a00f47d70866a785363835bb050b36d7f9a680ac61a0778f84352ab3674f31`
- Terminal result artifact:
  `af03f22103ca7cef0c233d6d529896bb95b3f0418e5e04bb31dcf308099e096a`
- Cross-implementation Thermograph authority:
  `c427c27fb6c22078fc5251d61dfa54de1a1ccf33e4913a92e5901e3b4152d421`
- Frozen-prefix discovery-curve authority:
  `0e5c656f8563a16968e7dddb04feb209389884f3d7d8f111f68deb767d51d95f`
- Combined validation authority:
  `2defec1917d485d3e70aee19b50d4ffd9c2c216bc6c39f5c4f2885ab2700032b`
- Boundary: 12 bounded Domineering values; 221,184 evaluation calls;
  zero V5-test exposure; paper unchanged.

The cross-oracle check matched all 1,872 frozen verdicts across the Python and
Rust implementations. A secondary analysis of frozen acquisition prefixes
found a positive novelty-minus-equality quotient interval at every budget from
128 through 2,048 calls. Its relative lift declined from 3.66% at 128 calls to
0.85% at 2,048 calls as both neural policies accumulated common quotient
classes. See `docs/research/FIXED_VALUE_SCOPE_VALIDATION_V1_RESULT.md`.

This index identifies the evidence that may support the current manuscript.
Paths are relative to the repository root. Frozen evidence files listed below
must remain byte-identical. Large raw ledgers remain in the local research
archive until an immutable artifact host is selected.

## Authoritative V3 held-out policy study

The primary confirmatory result for the paper is:

`output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4`

The study evaluated 221,184 selected proposals: twelve 2,048-call paired
streams for each target and each of three arms. The completion record says
`GO`, `evidence_eligible: true`, `independent_replay_pass: true`, and
`corruption_suite_pass: true`.

| Arm | Quotient discoveries | Literal-game discoveries |
| --- | ---: | ---: |
| Structural random | 45,076 | 31,647 |
| Equality-only | 67,151 | 33,796 |
| Equality + novelty | 70,506 | 45,863 |

Novelty acquisition exceeded equality-only acquisition by 335.194 literal
games per paired target-macro stream, with 95% interval
`[266.361, 407.194]`. The quotient ratio to equality was 1.050 with interval
`[1.034, 1.069]`. All twelve scientific checks and all thirty corruption
families passed.

### Binding files

| Path | SHA-256 | Role |
| --- | --- | --- |
| `docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PROTOCOL.json` | `052056db8f32f054af563333ea4d37b8da96565f8e630f35c774ef20cf07d9cd` | Frozen V3 design and gates |
| `output/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_TEST_V3_AUTHORIZED_ONCE.json` | `3d6c57694296831af43ffa83aa027dadcf0d0e3181240b904c7eeb33a388a1a0` | One-time launch |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/GENERATION_COMPLETE.json` | `c94ddeff37dba04864091a2fab0f0eaf1137290e3147ff4ecbe06f0f6f3c05dd` | Generation completion |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/independent_inference.json` | `14cdba3628bca2bede75c7768a2a9cc8c5bd103c8490ae43ee75457f53339cae` | Paired estimators and intervals |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/independent_gate.json` | `456b01d6f63cc9f9ccbcf23105276f12ea2b8bfb1a00b84644fc290e642b539b` | Twelve scientific checks |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/independent_verification.json` | `dfb6255b0e168b83a630eb6bf566d3dc0912fe054db686bee7f8fc33dce9bf4c` | Full independent replay |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/corruption_tests.json` | `fe9cff6fcc69b2bbbf0df6268166b23e259ba4e871ce2e6ba5c667e3f0b2fa6b` | 30/30 corruptions rejected |
| `output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4/RUN_COMPLETE.json` | `0fd109dd7ef43c42738948678e64a523289bad534a1771733ae2e20611728cfb` | Final `GO` |

## Historical training and structural study

The historical study is:

`output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db`

It evaluated 73,728 proposals in frozen sampled trajectories and supplies
training data, transition evidence, and the mechanically selected linked
motif.

| Target | Held-out quotients | Literal-game digests | Embodiment-only edges | Literal-tree crossings |
| --- | ---: | ---: | ---: | ---: |
| `0` | 7,555 | 6,386 | 588 | 7,181 |
| `*` | 7,132 | 5,352 | 814 | 6,549 |
| `{0|1}` | 7,010 | 4,382 | 1,227 | 5,950 |

The six default exemplars and linked motif are selected mechanically in
`summary.json`. The summary reports 8,111 linked motifs.

### Historical binding files

| Path | SHA-256 | Role |
| --- | --- | --- |
| `docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_PREREGISTRATION.md` | `4a9328e40d53ee4ffe9626b51a40ed4b97741ee9f75ac8e9e798a02cd9f444a9` | Frozen question, search policy, gates, claim boundary |
| `docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_LAUNCH.json` | `06f30a76438d66bb0378076b79ba23b59a160297a468f2231bddbf0827b00c51` | One-shot launch, interpreter, sources, budget |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/manifest.json` | `7faebafb572b15423b0be2e612986c7d61bd16615edbea3de53999d0b5fabfe1` | Input, source, and generated-file bindings |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/events.jsonl` | `304797fe69622f4d2d88363e89538d10a6ef33d39eac01533b8aebf3bf3b5b6c` | 73,728-row hash-chained ledger; local archive |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/summary.json` | `a991aa9e26d96abbea4276696437c2aa71a3880dd5f89243431a088028fcb98f` | Counts, unions, gates, exemplars, motifs |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/GENERATION_COMPLETE.json` | `632250aa91d18544d6c6e4aed31af8c327047dd3d4e0876de7cf04bedeccd7a4` | Generation completion |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/independent_verification.json` | `ec4c8bc36b842f3c6a1efb3ff8f141270e2d676e0ec9d88ea883a9bd4c129f24` | Independent semantic replay of every event |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/negative_tests.json` | `c3e5d6e32bc0db9db0f3172c61d91e534b1553dbb42faff924973988111fbe9d` | All 15 required corruption families rejected |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/STUDY_REPORT.md` | `076d6f0e2a56b8a20ecdca9cf371b1f70e593190b3fc3119b116e189ac1f7066` | Human-readable gate table |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/RUN_COMPLETE.json` | `61ca66ce5b107145cfa8e51181e71174d5685eb3789cdcbc7dc44518e97cf38b` | Final `GO` and evidence-eligibility root |

`RUN_COMPLETE.json` binds the event ledger, summary, manifest, verification,
negative tests, and report. The full directory contains 65,135 files and is
about 1.0 GiB. `events.jsonl` alone is 165,571,762 bytes, beyond GitHub's
ordinary 100 MiB object limit. Archive the full directory through Zenodo or
another immutable artifact service before public artifact release, then add
its DOI and archive SHA-256 here.

The local deterministic full-run archive is
`output/supplement/what_value_forgets_full_run_internal_unlicensed.tar.gz`
(72,115,477 bytes; SHA-256
`e857853f0c7cbed59fd306f37f1d24a2e6dc20d858eb4c3cbc284878d3cc41e1`).
It contains all content-addressed sidecars, an internal license notice, and a
65,137-file manifest. It remains internal until licensing review; a DOI is
still pending.

## Frozen descriptive secondary analysis

The structural atlas was frozen after completion of the confirmatory run. Its
population rule retains the first accepted held-out event for every graph
quotient, separately for each target. It reconstructs 21,697 quotient-unique
certified representatives: 7,555 for `0`, 7,132 for `*`, and 7,010 for
`{0|1}`. This analysis is descriptive and preserves the confirmatory claim
boundary.

| Path | SHA-256 | Role |
| --- | --- | --- |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/descriptor_atlas_v1.json` | `c35eaf26cd1da6c7e4c95b588d15ceb9a839b30490346d72e0acbe4b8320b7ac` | Frozen descriptor distributions and population binding |
| `output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/descriptor_atlas_v1_verification.json` | `7fde00a5bd0bedc6b830c3541a793c5e2d5d2ed233f05c90e5e445d48453f28f` | Independent reconstruction; zero failed checks |
| `scripts/research/fixed_value_descriptor_atlas_v1.py` | `7025329c3e3ad09103991ecede177e625403802ed953d052847c59bfc94c43e9` | Population reconstruction, statistics, and figure source |
| `scripts/research/verify_fixed_value_descriptor_atlas_v1.py` | `acc4be3ff3940d574a30bd6ca1900715a4b8e3942a1114e94c74111c685f89d5` | Independent analysis verifier |
| `scripts/research/test_fixed_value_descriptor_atlas_v1.py` | `c1ad8d1fd569f97c7325a1a48a5fc972163057321087f459eb2b0778a0d7189c` | Unit tests |
| `docs/paper/neurips_2026/figures/fig_fixed_value_descriptor_atlas.pdf` | `875f27df43e63168e506bad4f4dba1410a8651e0e23ba8f9441df81684b75140` | Rendered secondary-analysis figure |

The atlas supports observed structural variation in directed arc count,
literal-game size, game birthday, and root simplification count. Population
inference, fiber-size estimation, aesthetic ranking, and cross-target
performance comparison remain outside this descriptive analysis.

## Historical chess control

The Stiller--Elkies panel is prior-work motivation and a historical control.
It contributes no confirmatory experiment claim. Stiller's Figure 7 supplies
the published analysis, endpoint positions, line, and attribution. The
Partizan native witness at public commit
`ef004f50be5073ee2f6d249082067f996cbeef9a` checks legality of all thirteen
plies.

| Path | SHA-256 | Role |
| --- | --- | --- |
| `docs/paper/neurips_2026/work/elkies_historical_control_v1.json` | `f8bac92761dd636005cb7691e3378a5ea7b13379bd25f56677f1bfd4475da6b9` | Source, scope, FEN, move-line, and witness binding |
| `docs/paper/neurips_2026/figures/fig_elkies_historical_control.pdf` | `7990917ab4a6c04c1571065312c731200337bf49f38911dc093eacebdc44441a` | Newly rendered vector panel |
| `docs/paper/neurips_2026/work/repository_commit_lock.json` | `d50a4d3b7f057ddf0a04cdc5e9e6470d0e68c084c60963cf5c2ff9e1f2b75072` | Public repository version lock |

Machine-checked scope is legal replay. The historical analysis supplies the
mutual-zugzwang kernel. Forcedness, optimality, unrestricted chess value, and
Partizan generation of the composition remain outside this control.

### Executable sources

| Path | SHA-256 |
| --- | --- |
| `scripts/research/digraph_order7_fixed_value_transitions_v1.py` | `be35a82d0520a0896e47594f51f67eaad1dcf552e23e4a6eea3a98cd6f66323a` |
| `scripts/research/verify_digraph_order7_fixed_value_transitions_v1.py` | `19e87422c239c7766981ce37d02d38a8417d264461ffb15fa12c4f1156e295af` |
| `scripts/research/test_digraph_order7_fixed_value_transitions_v1.py` | `08103611e469f38857cdeb254557646d02234c7f4e32539fcfb80b7d07ad623b` |
| `scripts/research/digraph_derivation_certificate_v3.py` | `0d68f7ab0959826a2dac296f8e26c3834f7ef9f17b99d5ddf3428a77bcf2db43` |
| `scripts/research/digraph_ledger_verifier_v3.py` | `cbb21d7162c4cd97340372d6ee6c6b7c372e2eb4d4e5e5109f015f04ace016a2` |
| `scripts/research/digraph_derivation_certificate_v2.py` | `06f4d8c0e28cf9390a041dd7ae711eb7af2849db7ce2be2dfe424152bf96d1cd` |
| `scripts/research/digraph_ledger_verifier_v2.py` | `de830fbecab8a56c1f492f2611897d7a8e98546db7119a316a4a6532b08e1e6d` |
| `scripts/research/digraph_placement_control.py` | `b3db1f7ec34887ff6edc419e53f77d7109ed6a28d2f42b6d36fb8042292f3c3b` |
| `scripts/research/semantic_equality_certificate_v1.py` | `d2cc42745e4f93ed01977f8332281b18818e508f52431d6528c17128adc64764` |
| `scripts/research/short_game_fiber_pilot.py` | `85cca4817a7509b37402a222e3bd0dafec8f8e19ee93068b0e4c0491e4d1512c` |

Additional unit-test sources:

| Path | SHA-256 |
| --- | --- |
| `scripts/research/test_digraph_derivation_certificate_v3.py` | `0cba6460b51d95107bdc88b85ff912eb92764ccb1646bdad0833a5532c7e3747` |
| `scripts/research/test_digraph_ledger_verifier_v2.py` | `0ae7fd3cd8725902cd9ab5925ed59cd98045684fda5a04ba627656a78cf53792` |

## Calibration boundary

The successful Stage-0 calibration is:

`output/research/digraph-order7-seed-calibration-v1-eb6feb7bdd84`

It supplies three launch controls and a leakage registry of all 1,689
inspected extensions. It supports method calibration and leakage exclusion.
It supplies no held-out paper result and no paper figure.

| File | SHA-256 |
| --- | --- |
| `manifest.json` | `f53642fc48171fa23151c2c5dde86ea9600631cb581ff187bf910aed1afdb480` |
| `extensions.jsonl` | `6d162a7629e7b22a5e4925ac2741d248a680675fe25e9b249c0475f5d48cc672` |
| `independent_verification.json` | `177d23418c42bbf9519aec2a19b8699d715d47df191cb8d734ad9c9d3e635f3a` |
| `negative_tests.json` | `9a695ab6addb0f2b1a348817576978f2cfcdd148f873af102a5040e93bc259c5` |
| `RUN_COMPLETE.json` | `a6974e5fa8d32a8daf69d2078a074e777fe8fa66e41a40556c6f9ca52a0896a8` |

The first Stage-0 attempt failed. Its immutable disclosure record is
`output/research/digraph-order7-seed-calibration-v1-c4b2bb2ec334/FAILURE.json`
with SHA-256
`3a43b283b8bc278007d23a3efac33d4d809b499e1588d089f6a0a6533e109029`.

## Failed official pawn-study boundary

The official kingless-pawn study produced a held-out bundle and then failed
its mandatory independent-verifier wall-clock gate:

`output/research/kingless-pawn-heldout-fiber-census-v1-official-g9add9534-veb7c4588-cb064395f`

The verifier stopped at the frozen 1,800-second limit. Determinism and mutation
checks remained incomplete. Its completion record states
`status: INCOMPLETE_FAIL`, `evidence_eligible: false`, and
`paper_evidence: false`. The positive counts inside `CENSUS_REPORT.md` cannot
support the manuscript's empirical claims or figures.

| Path | SHA-256 |
| --- | --- |
| `docs/research/KINGLESS_PAWN_HELDOUT_FIBER_CENSUS_V1_PREREGISTRATION.md` | `d3135846d715b9438844b4fb97461c3ef3c7fde7fe0a66cfc2908717eb2d4644` |
| `docs/research/KINGLESS_PAWN_HELDOUT_CENSUS_V1_LAUNCH_RECORD.json` | `87f09b31da0bdb076c63bdd8d842ebe767ba5d8a2fd08638ba21499c429d4e22` |
| `docs/research/KINGLESS_PAWN_HELDOUT_CENSUS_V1_DEPENDENCY_LOCK.json` | `85e428559850762463b64fbacfd358bfdad8eefba792361d1f5209fa6630615c` |
| `scripts/research/kingless_pawn_heldout_fiber_census_v1.py` | `9add9534884477216be11615a0d33eb40ceef2133d7c88b7039119c82d34cbad` |
| `scripts/research/verify_kingless_pawn_heldout_fiber_census_v1.py` | `eb7c45887167f210f4f37a39c284ac94917b36c781d6992df61f82e21474e442` |
| `output/research/kingless-pawn-heldout-fiber-census-v1-official-g9add9534-veb7c4588-cb064395f/run_manifest.json` | `16c8d0b6fd596a3b5c6861dadcc592dfd2c22bf3338a1ef1f3c18b6b6520200c` |
| `output/research/kingless-pawn-heldout-fiber-census-v1-official-g9add9534-veb7c4588-cb064395f/resource_accounting.json` | `d66a41160fa8ea6b4cad4e874a0e00c34766d2ed970ca82dd46e65d4309b1671` |
| `output/research/kingless-pawn-heldout-fiber-census-v1-official-g9add9534-veb7c4588-cb064395f-verification/independent_verification.json` | `1eb6e364454eae1de0aaa0039be6bd4d74c40d1a6d32d228605b9b322551d4b6` |

## Claim permissions

The frozen evidence permits this claim:

> In a frozen order-7 Digraph Placement grammar, proof-carrying search found
> multiple held-out realizations of each target and independently replayed two
> kinds of fixed-value local transition: changes of graph embodiment that left
> the complete literal game intact, and changes of literal game that left exact
> CGT value intact.

Every quantitative sentence must say that the counts were observed in sampled
trajectories. The evidence also permits reporting complete replay and rejection
of all 15 preregistered corruption families.

The evidence grants no claim about:

- prevalence across the complete order-7 graph universe;
- optimality of the search policy;
- beauty, elegance, surprise, creativity, or human preference;
- unrestricted chess or the failed kingless-pawn study;
- causal benefit from machine learning or a language model.

The paper may interpret the formal residue as a space in which form can vary.
Any account of aesthetic experience remains an interpretation or future human
study.

## Verification and tests

Quick integrity check:

```bash
shasum -a 256 \
  output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/{manifest.json,events.jsonl,summary.json,independent_verification.json,negative_tests.json,STUDY_REPORT.md,RUN_COMPLETE.json}
```

The verifier writes completion files with exclusive-create semantics. Preserve
the frozen directory and run a full audit in a disposable copy:

```bash
cp -cR \
  output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db \
  /tmp/order7-fixed-value-audit
rm /tmp/order7-fixed-value-audit/{independent_verification.json,negative_tests.json,STUDY_REPORT.md,RUN_COMPLETE.json}
PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/research/verify_digraph_order7_fixed_value_transitions_v1.py \
  /tmp/order7-fixed-value-audit --repo-root .
```

On GNU/Linux, `cp --reflink=auto -R` is the corresponding copy command.
The original one-shot generation command is recorded in the launch JSON. A new
generation study requires a new protocol version and launch record.

Run the preregistered unit tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research python3 -m unittest \
  scripts/research/test_digraph_order7_fixed_value_transitions_v1.py \
  scripts/research/test_digraph_derivation_certificate_v3.py \
  scripts/research/test_digraph_ledger_verifier_v2.py
```

## Superseded and contextual runs

These directories remain local and immutable. They may document method
development or failed boundaries. They provide no confirmatory paper result:

- `output/research/digraph-fiber-calibration-v0-*`
- `output/research/digraph-fiber-calibration-v1-*`
- `output/research/digraph-fiber-calibration-v2-*`
- `output/research/digraph-fiber-v2-smoke-*`
- `output/research/fixed-value-mutation-topology-*`
- `output/research/elkies-diagram2-pawn-push-*`
- `output/research/kingless-pawn-global-threats-*`
- `output/research/kingless-pawn-heldout-universe-*`
- `output/research/kingless-pawn-heldout-fiber-census-v1-calibration-*`

`output/research/figures` contains derived presentation assets. A figure gains
evidentiary status only through mechanically selected identifiers in the
authoritative `summary.json`.

## Exact staging allowlist

Root should stage these paths explicitly and avoid `git add .`:

1. `.gitignore`
2. `docs/research/EVIDENCE_INDEX.md`
3. `docs/research-readiness-status.md`
4. `docs/research-readiness-orchestration.md`
5. `docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_PREREGISTRATION.md`
6. `docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_LAUNCH.json`
7. The twelve files in **Executable sources** and **Additional unit-test
   sources**
8. `output/research/digraph-order7-seed-calibration-v1-eb6feb7bdd84`
9. `output/research/digraph-order7-seed-calibration-v1-c4b2bb2ec334/FAILURE.json`
10. The seven non-ignored top-level files under the authoritative study:
    `GENERATION_COMPLETE.json`, `RUN_COMPLETE.json`, `STUDY_REPORT.md`,
    `independent_verification.json`, `manifest.json`, `negative_tests.json`,
    and `summary.json`
11. The pawn preregistration, launch record, dependency lock, generator, and
    verifier listed in **Failed official pawn-study boundary**
12. The pawn `CENSUS_REPORT.md`, `resource_accounting.json`,
    `run_manifest.json`, and verification `independent_verification.json`

The two current files in `output/supplement` remain excluded. One is labeled
internal and unlicensed; the other belongs to a superseded manuscript concept.
Regenerate a final supplement after Fugue code/data/document licensing is
settled. The current Fugue deterministic fixture binds event
`5f99f8c2a25f768cf440e55daefc3cd232af411570c3e487411a37724537458e`,
SVG `fe2d0eb597a987155fdffab0fdc8fdd878fda1387848c982329a969597f14215`,
and WAV
`d1a7248d8cef514c5d14365a2b125b48c919ff8bc607914a7315f98632f76ea5`.
These media hashes describe deterministic presentation output and grant no
additional scientific claim. Registry publication, immutable release tags, the
full evidence archive DOI, and the Fugue license remain release gates.
