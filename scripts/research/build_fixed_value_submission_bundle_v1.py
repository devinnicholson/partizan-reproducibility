#!/usr/bin/env python3
"""Build the deterministic GPL-licensed fixed-value release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


FIXED_TIMESTAMP = (2026, 8, 6, 0, 0, 0)
SCHEMA_VERSION = "partizan.fixed_value_submission_bundle.v3"

FINAL_RUN = Path(
    "output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4"
)
MODEL_PACKAGE = Path(
    "output/research/digraph-order7-diversity-model-v2-3cf1bb0ba101"
)
INITIALIZATIONS = Path(
    "output/research/digraph-order7-policy-v3-initializations-v1"
)

FILES = (
    "docs/paper/neurips_2026/main_fixed_value.tex",
    "docs/paper/neurips_2026/references.bib",
    "docs/paper/neurips_2026/checklist.tex",
    "docs/paper/neurips_2026/README.md",
    "docs/paper/neurips_2026/supplement/fixed_value_reproducibility.md",
    "docs/paper/neurips_2026/work/evidence_eligibility_matrix.md",
    "docs/paper/neurips_2026/work/order7_fixed_value_transition_dossier.md",
    "docs/paper/neurips_2026/work/fixed_value_descriptor_atlas_v1.md",
    "docs/paper/neurips_2026/work/elkies_historical_control_v1.json",
    "docs/paper/neurips_2026/work/repository_commit_lock.json",
    "docs/paper/neurips_2026/figures/fig_same_value_forms.tex",
    "docs/paper/neurips_2026/figures/fig_same_value_forms.pdf",
    "docs/paper/neurips_2026/figures/fig_fixed_value_transitions.tex",
    "docs/paper/neurips_2026/figures/fig_fixed_value_transitions.pdf",
    "docs/paper/neurips_2026/figures/fig_fixed_value_descriptor_atlas.tex",
    "docs/paper/neurips_2026/figures/fig_fixed_value_descriptor_atlas.pdf",
    "docs/paper/neurips_2026/figures/fig_elkies_historical_control.tex",
    "docs/paper/neurips_2026/figures/fig_elkies_historical_control.pdf",
    "docs/paper/neurips_2026/figures/fig_policy_comparison.pdf",
    "docs/paper/neurips_2026/figures/fig_domineering_discovery_curves.pdf",
    "docs/paper/neurips_2026/figures/fig_system_authority.tex",
    "docs/paper/neurips_2026/figures/fig_system_authority.pdf",
    "docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_PREREGISTRATION.md",
    "docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_LAUNCH.json",
    "docs/research/EVIDENCE_INDEX.md",
    "docs/research/EVIDENCE_FIGURE_PIPELINE_REPORT.md",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_1_AMENDMENT.json",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_2_CLARIFICATION.json",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_3_EXECUTION.json",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_4_ANALYSIS.json",
    "docs/research/FIXED_VALUE_SCOPE_DISCOVERY_CURVES_V1_PROTOCOL.json",
    "docs/research/FIXED_VALUE_SCOPE_CROSS_ORACLE_V1_PROTOCOL.json",
    "docs/research/FIXED_VALUE_SCOPE_CROSS_ORACLE_V1_1_AMENDMENT.json",
    "docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_RESULT.md",
    "docs/research/FIXED_VALUE_SCOPE_VALIDATION_V1_RESULT.md",
    "docs/research/FIXED_VALUE_EVIDENCE_CITATION.cff",
    "docs/research/FIXED_VALUE_ZENODO_METADATA.json",
    "docs/research/FIXED_VALUE_ARCHIVAL_DEPOSIT.md",
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json",
    "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json",
    "scripts/research/digraph_order7_fixed_value_transitions_v1.py",
    "scripts/research/verify_digraph_order7_fixed_value_transitions_v1.py",
    "scripts/research/test_digraph_order7_fixed_value_transitions_v1.py",
    "scripts/research/digraph_derivation_certificate_v3.py",
    "scripts/research/digraph_ledger_verifier_v3.py",
    "scripts/research/digraph_derivation_certificate_v2.py",
    "scripts/research/digraph_ledger_verifier_v2.py",
    "scripts/research/digraph_placement_control.py",
    "scripts/research/semantic_equality_certificate_v1.py",
    "scripts/research/short_game_fiber_pilot.py",
    "scripts/research/fixed_value_descriptor_atlas_v1.py",
    "scripts/research/verify_fixed_value_descriptor_atlas_v1.py",
    "scripts/research/test_fixed_value_descriptor_atlas_v1.py",
    "scripts/research/build_fixed_value_submission_bundle_v1.py",
    "scripts/research/build_fixed_value_full_archive_v1.py",
    "scripts/research/test_build_fixed_value_full_archive_v1.py",
    "scripts/research/stage_and_verify_digraph_order7_diversity_policy_v3.py",
    "scripts/research/test_stage_and_verify_digraph_order7_diversity_policy_v3.py",
    "scripts/research/domineering_exact_v1.py",
    "scripts/research/domineering_scope_model_v1.py",
    "scripts/research/reduce_domineering_scope_evaluation_v1.py",
    "scripts/research/reduce_domineering_discovery_curves_v1.py",
    "scripts/research/verify_domineering_cross_oracle_v1.py",
    "scripts/research/build_fixed_value_scope_discovery_figure_v1.py",
    "output/release/PORTABLE_V3_REPLAY_STAGING_AUTHORITY.json",
    "output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json",
    "output/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_RESOURCE_PREFLIGHT_V3.json",
    "output/research/digraph-order7-diversity-policy-validation-v3-e5a2280aac6b/VALIDATION_COMPLETE.json",
    "output/research/digraph-order7-diversity-policy-validation-v3-e5a2280aac6b/test_prior_split_registry.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/manifest.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/events.jsonl",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/summary.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/GENERATION_COMPLETE.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/independent_verification.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/negative_tests.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/STUDY_REPORT.md",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/RUN_COMPLETE.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/descriptor_atlas_v1.json",
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/descriptor_atlas_v1_verification.json",
    "output/research/fixed-value-scope-v1/DOMINEERING_RESOURCE_BENCHMARK_V1.json",
    "output/research/fixed-value-scope-v1/schedule/SCHEDULE_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/training/MODEL_FREEZE_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/evaluation/EVALUATION_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/evaluation/REPLAY_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/evaluation/SCOPE_RESULT_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/validation-v1/VALIDATION_PREPARATION_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/validation-v1/VALIDATION_RESULT_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/validation-v1/DISCOVERY_CURVES_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/validation-v1/DISCOVERY_CURVES_V1.csv",
    "output/research/fixed-value-scope-v1/validation-v1/CROSS_ORACLE_AUTHORITY_V1.json",
    "output/research/fixed-value-scope-v1/validation-v1/CROSS_ORACLE_SAMPLE_V1.tsv",
    "output/research/fixed-value-scope-v1/validation-v1/CROSS_ORACLE_RESULTS_V1.tsv",
)


NOTICE = """\
# LOCAL RELEASE CANDIDATE

Copyright (C) 2026 Devin Nicholson.

The original code, generated data, documentation, and figures in this archive
are licensed under GNU GPL-3.0-or-later. The complete license text is included
as `LICENSE`. Historical chess facts and citations remain attributed to their
published sources; this archive contains newly rendered diagrams and no scan
of the source publication.

This deterministic candidate is prepared for author review. It has not been
published. The archive contains the 73,728-row transition ledger, compact
authorities for both 221,184-call studies, the frozen source bundle, the frozen
model and initialization packages, the Domineering scope figure, and an
authorized-layout staging wrapper for the frozen V3 verifier. The large policy
and scope event ledgers and content-addressed sidecars remain in the full local
evidence tree. Full independent replay therefore requires the separate
full-evidence archive.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_info(path: str, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, FIXED_TIMESTAMP)
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    return info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--license-source",
        type=Path,
        default=Path("../partizan/LICENSE"),
        help="GPL-3.0 license text to include as LICENSE",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    entries: dict[str, bytes] = {}
    for relative in FILES:
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        entries[relative] = source.read_bytes()

    for directory in (FINAL_RUN / "source_bundle", MODEL_PACKAGE, INITIALIZATIONS):
        source_directory = root / directory
        if not source_directory.is_dir():
            raise FileNotFoundError(source_directory)
        for source in sorted(source_directory.rglob("*")):
            if source.is_file():
                relative = source.relative_to(root).as_posix()
                entries[relative] = source.read_bytes()

    final_run_directory = root / FINAL_RUN
    for source in sorted(final_run_directory.iterdir()):
        if source.is_file():
            relative = source.relative_to(root).as_posix()
            entries[relative] = source.read_bytes()

    license_source = args.license_source
    if not license_source.is_absolute():
        license_source = root / license_source
    if not license_source.is_file():
        raise FileNotFoundError(license_source)
    entries["LICENSE"] = license_source.read_bytes()

    entries["RELEASE_CANDIDATE_NOTICE.md"] = NOTICE.encode("utf-8")
    manifest_files = {
        path: {"bytes": len(data), "sha256": digest(data)}
        for path, data in sorted(entries.items())
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "distribution_status": "local_release_candidate",
        "license": "GPL-3.0-or-later",
        "file_count": len(entries),
        "files": manifest_files,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    entries["BUNDLE_MANIFEST.json"] = manifest_bytes

    checksums = "".join(
        f"{digest(data)}  {path}\n" for path, data in sorted(entries.items())
    ).encode("utf-8")
    entries["SHA256SUMS"] = checksums

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in sorted(entries):
            executable = path.startswith("scripts/") and path.endswith(".py")
            archive.writestr(zip_info(path, executable), entries[path])
    temporary.replace(args.output)

    output_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "bundle_sha256": output_sha,
                "bytes": args.output.stat().st_size,
                "file_count": len(entries),
                "output": str(args.output),
                "status": "LOCAL_RELEASE_CANDIDATE",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
