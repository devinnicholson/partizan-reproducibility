# Partizan reproducibility materials

This repository contains the public experiment code, preregistered protocols,
schemas, and compact verification authorities for the Partizan fixed-value
representation study.

The study asks what varies among combinatorial-game realizations after exact
game value is held fixed. Its main experiments compare equality-only,
novelty-guided, and structural acquisition in bounded Digraph Placement, then
test the same fixed-value search principle in Domineering.

## Repository boundary

This Git repository contains code and compact authorities. It deliberately
excludes the manuscript, rendered paper, private submission notes, model
weights, and large event or certificate ledgers. The complete immutable
evidence is available from
[the archival deposit record](https://doi.org/10.5281/zenodo.21833142), with
deposit details in `docs/research/FIXED_VALUE_ARCHIVAL_DEPOSIT.md`.

The reusable game engine and public visualization live in the main
[Partizan repository](https://github.com/devinnicholson/partizan).

## Layout

- `scripts/research/`: generators, exact verifiers, replay tools, corruption
  tests, scope evaluation, and archive builders.
- `docs/research/`: preregistrations, protocol amendments, result summaries,
  schemas, and the evidence index.
- `output/release/`: compact archive and replay authorities.
- `output/research/`: compact terminal authorities. Large ledgers are supplied
  by Zenodo.

## Environment

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

PyTorch is required only for neural-model reconstruction. Exact replay and the
lightweight test suite use NumPy and the Python standard library.

## Lightweight checks

```bash
PYTHONPATH=scripts/research python -m unittest \
  scripts/research/test_validate_digraph_order7_diversity_policy_protocol_v3.py \
  scripts/research/test_fixed_value_descriptor_atlas_v1.py \
  scripts/research/test_stage_and_verify_digraph_order7_diversity_policy_v3.py
```

The fixed-value transition replay test requires content-addressed Stage-0
sidecars from the full evidence archive. Run it as part of the full replay
after extracting that archive.

## Full replay

1. Download both files attached to the Zenodo record.
2. Verify their SHA-256 values against the Zenodo description and
   `output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json`.
3. Extract the full evidence archive at the repository root.
4. Run the commands in `docs/research/EVIDENCE_INDEX.md` and
   `docs/research/SUBMISSION_EVIDENCE_AUDIT_V1.md`.

The terminal local audit passed 86 of 87 checks. The remaining release check
was the external DOI assignment. The published record completes that check.

## Citation and license

Citation metadata is in `CITATION.cff`. The versioned evidence DOI is
[10.5281/zenodo.21833142](https://doi.org/10.5281/zenodo.21833142). Code,
generated data, documentation, and newly rendered figures are licensed under
GPL-3.0-or-later. See `LICENSE`.
