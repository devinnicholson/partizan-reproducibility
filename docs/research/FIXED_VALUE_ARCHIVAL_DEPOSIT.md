# Fixed-Value Evidence Archival Deposit

Status: published

The compact reproducibility package and complete evidence archive were
published together under GPL-3.0-or-later at
[10.5281/zenodo.21833142](https://doi.org/10.5281/zenodo.21833142).

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

Both archives are attached to the same public Zenodo record. The record lists
the release SHA-256 values, while Zenodo reports an independent MD5 checksum
for each uploaded object. The public Git repository linked from the record is
`https://github.com/devinnicholson/partizan-reproducibility`.

## Current local authorities

- Compact candidate: `output/release/partizan-fixed-value-reproducibility-rc1.zip`
- Compact candidate SHA-256: `e7c969361a8f3d899163e18ee41ea3274c26657b560a7f343df3f0a8319011c6`
- Compact candidate Zenodo MD5: `6723d8b9ce00d31fa695d5c6c32a2a8c`
- Full archive: `output/release/partizan-fixed-value-full-evidence-rc1.tar.gz`
- Full archive SHA-256: `59e8a1e2d68801f605eb98a2632c5a6265858365af8018af51c68f2e6f45e197`
- Full archive Zenodo MD5: `9a8db69fc90904b258ce21c8438d45b4`
- Full archive bytes: `884915670`
- Full archive members: `585418`
- Full archive authority: `output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json`
- Authority artifact: `c769e932ee57b06f8c00d78671b212e94ac02347057494d5d2a6fe8b934e87b0`
- License: `GPL-3.0-or-later`
- Version DOI: `10.5281/zenodo.21833142`
- Concept DOI: `10.5281/zenodo.21833141`
