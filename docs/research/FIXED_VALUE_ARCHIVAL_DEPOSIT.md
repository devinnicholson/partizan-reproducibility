# Fixed-Value Evidence Archival Deposit

Status: local deposit package preparation

The compact reproducibility candidate and complete evidence archive are
prepared as separate files. Both use GPL-3.0-or-later. No DOI has been assigned.

## Build

From the Fugue repository root:

```sh
python3 scripts/research/build_fixed_value_submission_bundle_v1.py \
  --repo-root . \
  --output output/release/partizan-fixed-value-reproducibility-rc1.zip

python3 scripts/research/build_fixed_value_full_archive_v1.py \
  --repo-root . \
  --output output/release/partizan-fixed-value-full-evidence-rc1.tar.gz \
  --authority-output output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json
```

## Deposit boundary

Upload both archives to one Zenodo record using
`docs/research/FIXED_VALUE_ZENODO_METADATA.json`. Reserve the DOI before the
final paper build, insert the DOI into the supplement and submission metadata,
then publish the record only after verifying every uploaded checksum.

Publication is an external action. The local build and audit do not create a
record, upload files, reserve a DOI, or publish anything.

## Current local authorities

- Compact candidate: `output/release/partizan-fixed-value-reproducibility-rc1.zip`
- Full archive: `output/release/partizan-fixed-value-full-evidence-rc1.tar.gz`
- Full archive SHA-256: `59e8a1e2d68801f605eb98a2632c5a6265858365af8018af51c68f2e6f45e197`
- Full archive bytes: `884915670`
- Full archive members: `585418`
- Full archive authority: `output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json`
- Authority artifact: `c769e932ee57b06f8c00d78671b212e94ac02347057494d5d2a6fe8b934e87b0`
- License: `GPL-3.0-or-later`
- DOI: pending
