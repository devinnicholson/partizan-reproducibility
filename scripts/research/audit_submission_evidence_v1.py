#!/usr/bin/env python3
"""Consolidated, read-only audit of the evidence used by the NeurIPS paper.

The audit deliberately distinguishes scientific validity from release
readiness.  It recomputes the compact V3 analysis from independently replayed
stream records, re-runs the Domineering reducers in temporary directories,
checks all terminal file bindings, and records manuscript/release drift.  It
never writes into a frozen experiment directory or the paper tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

import verify_digraph_order7_diversity_policy_test_v3 as v3


SCHEMA = "partizan.submission_evidence_audit.v1"
AUDIT_DATE = "2026-08-06"

V3_DIR = Path(
    "output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4"
)
HISTORICAL_DIR = Path(
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db"
)
SCOPE_DIR = Path("output/research/fixed-value-scope-v1")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def embedded_hash_matches(value: dict[str, Any], field: str) -> bool:
    payload = dict(value)
    supplied = payload.pop(field, None)
    return supplied == object_sha256(payload)


class Audit:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.checks: list[dict[str, Any]] = []

    def path(self, relative: str | Path) -> Path:
        return self.repo_root / relative

    def check(
        self,
        check_id: str,
        passed: bool,
        detail: str,
        *,
        severity: str = "error",
    ) -> None:
        self.checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "severity": severity,
                "detail": detail,
            }
        )

    def verify_known_files(
        self, prefix: str, expected: dict[str, str]
    ) -> dict[str, str]:
        observed: dict[str, str] = {}
        for relative, digest in expected.items():
            path = self.path(relative)
            actual = file_sha256(path) if path.is_file() else "MISSING"
            observed[relative] = actual
            self.check(
                f"{prefix}.file.{Path(relative).name}",
                actual == digest,
                f"{relative}: expected {digest}; observed {actual}",
            )
        return observed

    def verify_embedded(
        self, prefix: str, relative: str | Path, field: str
    ) -> dict[str, Any]:
        value = load_json(self.path(relative))
        self.check(
            f"{prefix}.self_hash.{Path(relative).name}",
            embedded_hash_matches(value, field),
            f"{relative}: replay {field}",
        )
        return value


def audit_v3(audit: Audit) -> dict[str, Any]:
    expected_files = {
        "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PROTOCOL.json":
            "052056db8f32f054af563333ea4d37b8da96565f8e630f35c774ef20cf07d9cd",
        "output/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_TEST_V3_AUTHORIZED_ONCE.json":
            "3d6c57694296831af43ffa83aa027dadcf0d0e3181240b904c7eeb33a388a1a0",
        f"{V3_DIR}/GENERATION_COMPLETE.json":
            "c94ddeff37dba04864091a2fab0f0eaf1137290e3147ff4ecbe06f0f6f3c05dd",
        f"{V3_DIR}/independent_inference.json":
            "14cdba3628bca2bede75c7768a2a9cc8c5bd103c8490ae43ee75457f53339cae",
        f"{V3_DIR}/independent_gate.json":
            "456b01d6f63cc9f9ccbcf23105276f12ea2b8bfb1a00b84644fc290e642b539b",
        f"{V3_DIR}/independent_verification.json":
            "dfb6255b0e168b83a630eb6bf566d3dc0912fe054db686bee7f8fc33dce9bf4c",
        f"{V3_DIR}/corruption_tests.json":
            "fe9cff6fcc69b2bbbf0df6268166b23e259ba4e871ce2e6ba5c667e3f0b2fa6b",
        f"{V3_DIR}/report.json":
            "0ea1d0bcc1ca6b0f6b4a440f53e7fb6a295ffe47590940419b8a38663895fdf2",
        f"{V3_DIR}/RUN_COMPLETE.json":
            "0fd109dd7ef43c42738948678e64a523289bad534a1771733ae2e20611728cfb",
    }
    audit.verify_known_files("v3", expected_files)

    fields = {
        "manifest.json": "manifest_sha256",
        "initialization_manifest.json": "manifest_sha256",
        "prior_split_registry.json": "registry_sha256",
        "stream_metrics.json": "bundle_sha256",
        "GENERATION_COMPLETE.json": "generation_sha256",
        "independent_inference.json": "inference_sha256",
        "independent_gate.json": "gate_sha256",
        "independent_verification.json": "verification_sha256",
        "corruption_tests.json": "corruption_tests_sha256",
        "report.json": "report_sha256",
        "RUN_COMPLETE.json": "completion_sha256",
    }
    values = {
        name: audit.verify_embedded("v3", V3_DIR / name, field)
        for name, field in fields.items()
    }
    completion = values["RUN_COMPLETE.json"]
    frozen_file_bindings = {
        "generation_file_sha256": "GENERATION_COMPLETE.json",
        "stream_metrics_file_sha256": "stream_metrics.json",
        "independent_stream_metrics_file_sha256": "independent_stream_metrics.json",
        "inference_file_sha256": "independent_inference.json",
        "gate_file_sha256": "independent_gate.json",
        "verification_file_sha256": "independent_verification.json",
        "corruption_tests_file_sha256": "corruption_tests.json",
        "report_file_sha256": "report.json",
    }
    for field, name in frozen_file_bindings.items():
        actual = file_sha256(audit.path(V3_DIR / name))
        audit.check(
            f"v3.completion_binding.{field}",
            completion.get(field) == actual,
            f"{field}: completion={completion.get(field)}; file={actual}",
        )

    independent_path = audit.path(V3_DIR / "independent_stream_metrics.json")
    generated_path = audit.path(V3_DIR / "stream_metrics.json")
    audit.check(
        "v3.independent_stream_bundle.byte_match",
        independent_path.read_bytes() == generated_path.read_bytes(),
        "generated and independently reconstructed stream bundles are byte-identical",
    )
    stream_bundle = load_json(independent_path)
    streams = stream_bundle["streams"]
    protocol = load_json(
        audit.path("docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PROTOCOL.json")
    )
    rebuilt_inference = v3.independent_inference(streams, protocol)
    rebuilt_gate = v3.independent_gate(streams, rebuilt_inference, protocol)
    audit.check(
        "v3.inference.byte_reconstruction",
        rebuilt_inference == values["independent_inference.json"],
        "recomputed inference exactly matches frozen independent inference",
    )
    audit.check(
        "v3.gate.byte_reconstruction",
        rebuilt_gate == values["independent_gate.json"],
        "recomputed twelve-check gate exactly matches frozen independent gate",
    )

    total_calls = sum(int(row["verifier_calls"]) for row in streams)
    calls_by_arm = {
        arm: sum(
            int(row["verifier_calls"]) for row in streams if row["arm"] == arm
        )
        for arm in v3.ARMS
    }
    all_gates = all(rebuilt_gate["checks"].values())
    audit.check(
        "v3.design.contract",
        len(streams) == 108
        and total_calls == 221_184
        and set(calls_by_arm.values()) == {73_728},
        f"streams={len(streams)}, calls={total_calls}, calls_by_arm={calls_by_arm}",
    )
    audit.check(
        "v3.terminal_authority",
        completion.get("status") == "GO"
        and completion.get("evidence_eligible") is True
        and completion.get("paper_evidence") is True
        and completion.get("independent_replay_pass") is True
        and completion.get("corruption_suite_pass") is True
        and all_gates,
        "GO, evidence eligible, independent replay, corruption suite, and 12/12 gates",
    )
    return {
        "role": "primary held-out policy evidence",
        "directory": str(V3_DIR),
        "stream_count": len(streams),
        "exact_verifier_calls": total_calls,
        "exact_verifier_calls_per_arm": calls_by_arm,
        "total_discoveries": rebuilt_inference["total_discoveries"],
        "literal_gain_over_equality": rebuilt_inference[
            "literal_superiority_to_equality"
        ],
        "quotient_retention_to_equality": rebuilt_inference[
            "quotient_noninferiority_to_equality"
        ],
        "quotient_gain_over_random": rebuilt_inference[
            "quotient_superiority_to_random"
        ],
        "all_twelve_gates_pass": all_gates,
        "corruption_families_rejected": 30,
    }


def _run_scope_reductions(audit: Audit) -> tuple[bool, bool]:
    evaluation = audit.path(SCOPE_DIR / "evaluation")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(audit.path("scripts/research"))
    with tempfile.TemporaryDirectory(prefix="partizan-scope-audit-") as raw:
        temp = Path(raw)
        for name in ("EVALUATION_AUTHORITY_V1.json", "REPLAY_AUTHORITY_V1.json"):
            shutil.copy2(evaluation / name, temp / name)
        os.symlink(
            (evaluation / "EVENTS_V1.jsonl").resolve(), temp / "EVENTS_V1.jsonl"
        )
        subprocess.run(
            [
                sys.executable,
                str(audit.path("scripts/research/reduce_domineering_scope_evaluation_v1.py")),
                "--evaluation-dir",
                str(temp),
            ],
            cwd=audit.repo_root,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        primary_match = (
            (temp / "SCOPE_RESULT_AUTHORITY_V1.json").read_bytes()
            == (evaluation / "SCOPE_RESULT_AUTHORITY_V1.json").read_bytes()
        )
        curves = temp / "curves"
        subprocess.run(
            [
                sys.executable,
                str(audit.path("scripts/research/reduce_domineering_discovery_curves_v1.py")),
                "--output-dir",
                str(curves),
            ],
            cwd=audit.repo_root,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        frozen_curves = audit.path(SCOPE_DIR / "validation-v1")
        curves_match = (
            (curves / "DISCOVERY_CURVES_AUTHORITY_V1.json").read_bytes()
            == (frozen_curves / "DISCOVERY_CURVES_AUTHORITY_V1.json").read_bytes()
            and (curves / "DISCOVERY_CURVES_V1.csv").read_bytes()
            == (frozen_curves / "DISCOVERY_CURVES_V1.csv").read_bytes()
        )
    return primary_match, curves_match


def audit_scope(audit: Audit, *, deep_reduction: bool) -> dict[str, Any]:
    paths = {
        "protocol": Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json"),
        "analysis": Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_4_ANALYSIS.json"),
        "evaluation": SCOPE_DIR / "evaluation/EVALUATION_AUTHORITY_V1.json",
        "replay": SCOPE_DIR / "evaluation/REPLAY_AUTHORITY_V1.json",
        "result": SCOPE_DIR / "evaluation/SCOPE_RESULT_AUTHORITY_V1.json",
        "cross_oracle": SCOPE_DIR / "validation-v1/CROSS_ORACLE_AUTHORITY_V1.json",
        "curves": SCOPE_DIR / "validation-v1/DISCOVERY_CURVES_AUTHORITY_V1.json",
        "validation": SCOPE_DIR / "validation-v1/VALIDATION_RESULT_AUTHORITY_V1.json",
    }
    values = {
        name: audit.verify_embedded("scope", path, "artifact_sha256")
        for name, path in paths.items()
    }
    expected_artifacts = {
        "protocol": "a4a645d1be3781b56ed43ac8cf5cc25bec82a43857d2d69329986aa0c5441003",
        "evaluation": "476952d72cbd36542e0c2a653ce6f050a6dd3b33fc8ea981da8bc5a9e1bec57b",
        "replay": "25a00f47d70866a785363835bb050b36d7f9a680ac61a0778f84352ab3674f31",
        "result": "af03f22103ca7cef0c233d6d529896bb95b3f0418e5e04bb31dcf308099e096a",
        "cross_oracle": "c427c27fb6c22078fc5251d61dfa54de1a1ccf33e4913a92e5901e3b4152d421",
        "curves": "0e5c656f8563a16968e7dddb04feb209389884f3d7d8f111f68deb767d51d95f",
        "validation": "2defec1917d485d3e70aee19b50d4ffd9c2c216bc6c39f5c4f2885ab2700032b",
    }
    for name, expected in expected_artifacts.items():
        actual = values[name].get("artifact_sha256")
        audit.check(
            f"scope.artifact.{name}",
            actual == expected,
            f"{name}: expected {expected}; observed {actual}",
        )
    evaluation = values["evaluation"]
    events = audit.path(SCOPE_DIR / "evaluation" / evaluation["events_file"]["path"])
    observed_event_hash = file_sha256(events)
    audit.check(
        "scope.events.file_binding",
        observed_event_hash == evaluation["events_file"]["file_sha256"],
        f"event stream {observed_event_hash}",
    )
    result = values["result"]
    cross = values["cross_oracle"]
    audit.check(
        "scope.terminal_authority",
        result.get("status") == "SCOPE_EXTENSION_READY"
        and result.get("exact_verifier_call_count") == 221_184
        and all(result.get("readiness", {}).values())
        and evaluation.get("resource_failure_count") == 0
        and values["replay"].get("status") == "PASS",
        "scope ready, 221,184 calls, zero resource failures, replay PASS, all readiness checks",
    )
    audit.check(
        "scope.cross_oracle",
        cross.get("status") == "PASS"
        and cross.get("result_count") == 1_872
        and cross.get("verdict_mismatch_count") == 0
        and cross.get("oracle_error_count") == 0,
        "1,872/1,872 frozen verdicts reconstructed without mismatch",
    )
    if deep_reduction:
        primary_match, curves_match = _run_scope_reductions(audit)
        audit.check(
            "scope.primary.byte_reconstruction",
            primary_match,
            "primary authority regenerated byte-for-byte from EVENTS_V1.jsonl",
        )
        audit.check(
            "scope.curves.byte_reconstruction",
            curves_match,
            "prefix authority and CSV regenerated byte-for-byte from EVENTS_V1.jsonl",
        )
    else:
        primary_match = curves_match = False
        audit.check(
            "scope.deep_reduction.skipped",
            True,
            "deep reducer replay was explicitly skipped",
            severity="warning",
        )
    return {
        "role": "cross-ruleset scope evidence",
        "directory": str(SCOPE_DIR),
        "exact_verifier_calls": result["exact_verifier_call_count"],
        "arm_metrics": result["arm_metrics"],
        "effects": result["effects"],
        "readiness": result["readiness"],
        "primary_byte_reconstruction": primary_match,
        "prefix_byte_reconstruction": curves_match,
        "cross_oracle_result_count": cross["result_count"],
        "cross_oracle_disagreement_count": cross["verdict_mismatch_count"],
    }


def audit_historical(
    audit: Audit, *, fresh_replay_dir: Path | None
) -> dict[str, Any]:
    expected_files = {
        f"{HISTORICAL_DIR}/manifest.json":
            "7faebafb572b15423b0be2e612986c7d61bd16615edbea3de53999d0b5fabfe1",
        f"{HISTORICAL_DIR}/events.jsonl":
            "304797fe69622f4d2d88363e89538d10a6ef33d39eac01533b8aebf3bf3b5b6c",
        f"{HISTORICAL_DIR}/summary.json":
            "a991aa9e26d96abbea4276696437c2aa71a3880dd5f89243431a088028fcb98f",
        f"{HISTORICAL_DIR}/GENERATION_COMPLETE.json":
            "632250aa91d18544d6c6e4aed31af8c327047dd3d4e0876de7cf04bedeccd7a4",
        f"{HISTORICAL_DIR}/independent_verification.json":
            "ec4c8bc36b842f3c6a1efb3ff8f141270e2d676e0ec9d88ea883a9bd4c129f24",
        f"{HISTORICAL_DIR}/negative_tests.json":
            "c3e5d6e32bc0db9db0f3172c61d91e534b1553dbb42faff924973988111fbe9d",
        f"{HISTORICAL_DIR}/STUDY_REPORT.md":
            "076d6f0e2a56b8a20ecdca9cf371b1f70e593190b3fc3119b116e189ac1f7066",
        f"{HISTORICAL_DIR}/RUN_COMPLETE.json":
            "61ca66ce5b107145cfa8e51181e71174d5685eb3789cdcbc7dc44518e97cf38b",
    }
    audit.verify_known_files("historical", expected_files)
    fields = {
        "manifest.json": "manifest_sha256",
        "summary.json": "summary_sha256",
        "GENERATION_COMPLETE.json": "generation_sha256",
        "independent_verification.json": "verification_sha256",
        "negative_tests.json": "negative_tests_sha256",
        "RUN_COMPLETE.json": "completion_sha256",
    }
    values = {
        name: audit.verify_embedded("historical", HISTORICAL_DIR / name, field)
        for name, field in fields.items()
    }
    completion = values["RUN_COMPLETE.json"]
    bindings = {
        "events_file_sha256": "events.jsonl",
        "manifest_file_sha256": "manifest.json",
        "summary_file_sha256": "summary.json",
        "verification_file_sha256": "independent_verification.json",
        "negative_tests_file_sha256": "negative_tests.json",
        "report_file_sha256": "STUDY_REPORT.md",
    }
    for field, name in bindings.items():
        actual = file_sha256(audit.path(HISTORICAL_DIR / name))
        audit.check(
            f"historical.completion_binding.{field}",
            completion.get(field) == actual,
            f"{field}: completion={completion.get(field)}; file={actual}",
        )
    summary = values["summary.json"]
    verification = values["independent_verification.json"]
    negative = values["negative_tests.json"]
    target_counts = {
        target: payload["counts"]
        for target, payload in summary["target_unions"].items()
    }
    motif = summary["mechanical_linked_motif"]
    motif_valid = (
        motif["target"] == "0"
        and motif["literal_tree_crossing_edge"]["candidate_quotient_sha256"]
        == motif["central_quotient_sha256"]
        and motif["literal_tree_crossing_edge"]["candidate_literal_game_sha256"]
        == motif["embodiment_only_edge"]["parent_literal_game_sha256"]
        == motif["embodiment_only_edge"]["candidate_literal_game_sha256"]
    )
    audit.check(
        "historical.terminal_authority",
        completion.get("status") == "GO"
        and completion.get("evidence_eligible") is True
        and completion.get("paper_evidence") is True
        and verification.get("status") == "PASS"
        and negative.get("status") == "PASS"
        and negative.get("rejected_family_count") == 15,
        "GO, independently replayed, and 15/15 mutation families rejected",
    )
    audit.check(
        "historical.mechanical_motif",
        summary.get("event_count") == 73_728
        and summary.get("linked_motif_count") == 8_111
        and motif_valid,
        "73,728 events; first of 8,111 qualifying motifs has the declared literal/embodiment relations",
    )
    fresh_replay: dict[str, Any] | None = None
    if fresh_replay_dir is not None:
        fresh_verification = load_json(fresh_replay_dir / "independent_verification.json")
        frozen_projection = dict(verification)
        fresh_projection = dict(fresh_verification)
        for value in (frozen_projection, fresh_projection):
            value.pop("wall_seconds", None)
            value.pop("verification_sha256", None)
        fresh_completion = load_json(fresh_replay_dir / "RUN_COMPLETE.json")
        projection_match = fresh_projection == frozen_projection
        audit.check(
            "historical.fresh_full_replay",
            projection_match
            and fresh_completion.get("status") == "GO"
            and fresh_completion.get("independent_replay_pass") is True
            and fresh_completion.get("negative_tests_pass") is True,
            "fresh 73,728-event replay matches the frozen scientific projection; timing-dependent authority bytes may differ",
        )
        fresh_replay = {
            "directory": str(fresh_replay_dir),
            "scientific_projection_exact_match": projection_match,
            "status": fresh_completion.get("status"),
            "independent_replay_pass": fresh_completion.get(
                "independent_replay_pass"
            ),
            "negative_tests_pass": fresh_completion.get("negative_tests_pass"),
            "verification_file_sha256": file_sha256(
                fresh_replay_dir / "independent_verification.json"
            ),
        }
    return {
        "role": "historical training and certified structural case",
        "directory": str(HISTORICAL_DIR),
        "event_count": summary["event_count"],
        "linked_motif_count": summary["linked_motif_count"],
        "target_counts": target_counts,
        "mechanical_linked_motif": motif,
        "independent_replay": verification["status"],
        "corruption_families_rejected": negative["rejected_family_count"],
        "fresh_full_replay": fresh_replay,
    }


def audit_manuscript_and_release(audit: Audit) -> dict[str, Any]:
    paper = audit.path("docs/paper/neurips_2026/main_fixed_value.tex").read_text(
        encoding="utf-8"
    )
    handoff = audit.path("docs/paper/neurips_2026/SUBMISSION_HANDOFF.md").read_text(
        encoding="utf-8"
    )
    matrix = audit.path(
        "docs/paper/neurips_2026/work/evidence_eligibility_matrix.md"
    ).read_text(encoding="utf-8")
    assets = {
        "submission_pdf": "output/pdf/what_value_forgets_neurips_2026_submission_candidate.pdf",
        "policy_figure": "docs/paper/neurips_2026/figures/fig_policy_comparison.pdf",
        "scope_figure": "docs/paper/neurips_2026/figures/fig_domineering_discovery_curves.pdf",
        "transition_figure": "docs/paper/neurips_2026/figures/fig_fixed_value_transitions.pdf",
    }
    hashes = {name: file_sha256(audit.path(path)) for name, path in assets.items()}
    audit.check(
        "paper.handoff.pdf_hash",
        hashes["submission_pdf"] in handoff,
        f"current PDF {hashes['submission_pdf']} is bound by SUBMISSION_HANDOFF.md",
    )
    audit.check(
        "paper.matrix.pdf_hash_current",
        hashes["submission_pdf"] in matrix,
        f"eligibility matrix must bind current PDF {hashes['submission_pdf']}",
        severity="release_blocker",
    )
    audit.check(
        "paper.matrix.transition_figure_hash_current",
        hashes["transition_figure"] in matrix,
        f"eligibility matrix must bind current transition figure {hashes['transition_figure']}",
        severity="release_blocker",
    )
    required_claim_fragments = (
        "45,863",
        "33,796",
        "35.7\\%",
        "1.050",
        "56.4\\%",
        "221,184",
        "3.42",
        "0.9974",
        "1,872",
        "8,111",
    )
    missing_claims = [fragment for fragment in required_claim_fragments if fragment not in paper]
    audit.check(
        "paper.claim_inventory",
        not missing_claims,
        f"required canonical claim fragments missing={missing_claims}",
    )
    audit.check(
        "paper.excluded_iteration_boundary",
        "birthday5" not in paper.lower() and "v5.11" not in paper.lower(),
        "development-only Birthday-5 selector iterations are absent from the manuscript",
    )

    archive = audit.path("output/release/partizan-fixed-value-reproducibility-rc1.zip")
    archive_hash = file_sha256(archive)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        bad_member = bundle.testzip()
    contains_scope = any(name.startswith("output/research/fixed-value-scope-v1/") for name in names)
    contains_scope_figure = (
        "docs/paper/neurips_2026/figures/fig_domineering_discovery_curves.pdf"
        in names
    )
    audit.check(
        "release.rc_zip_integrity",
        bad_member is None,
        f"zip test result={bad_member}; archive_sha256={archive_hash}",
    )
    audit.check(
        "release.rc_includes_scope_authority",
        contains_scope,
        "release candidate must include the canonical scope authority and compact bindings",
        severity="release_blocker",
    )
    audit.check(
        "release.rc_includes_scope_figure",
        contains_scope_figure,
        "release candidate must include the current scope figure",
        severity="release_blocker",
    )
    full_authority_path = audit.path(
        "output/release/FULL_EVIDENCE_ARCHIVE_AUTHORITY.json"
    )
    full_authority: dict[str, Any] = {}
    full_archive_valid = False
    if full_authority_path.is_file():
        full_authority = load_json(full_authority_path)
        full_archive_path = audit.path("output/release") / str(
            full_authority.get("archive_path", "")
        )
        full_archive_valid = (
            embedded_hash_matches(full_authority, "artifact_sha256")
            and full_authority.get("status") in {"READY_FOR_DEPOSIT", "DEPOSITED"}
            and full_authority.get("license") == "GPL-3.0-or-later"
            and full_authority.get("evidence_roots")
            == [V3_DIR.as_posix(), HISTORICAL_DIR.as_posix(), SCOPE_DIR.as_posix()]
            and full_archive_path.is_file()
            and full_authority.get("archive_sha256") == file_sha256(full_archive_path)
            and full_authority.get("archive_bytes") == full_archive_path.stat().st_size
        )
    audit.check(
        "release.full_archive_licensed_and_bound",
        full_archive_valid,
        (
            "licensed full archive is checksum-bound and ready for deposit"
            if full_archive_valid
            else "build and license the checksum-bound full evidence archive"
        ),
        severity="release_blocker",
    )
    archive_doi = full_authority.get("doi") if full_archive_valid else None
    audit.check(
        "release.full_archive_public_doi",
        isinstance(archive_doi, str) and archive_doi.startswith("10."),
        (
            f"public archive DOI={archive_doi}"
            if archive_doi
            else "reserve, verify, and publish the evidence record to obtain a DOI"
        ),
        severity="release_blocker",
    )
    portable_authority_path = audit.path(
        "output/release/PORTABLE_V3_REPLAY_STAGING_AUTHORITY.json"
    )
    portable_wrapper_path = audit.path(
        "scripts/research/stage_and_verify_digraph_order7_diversity_policy_v3.py"
    )
    frozen_verifier_path = audit.path(
        V3_DIR
        / "source_bundle/scripts/research/verify_digraph_order7_diversity_policy_test_v3.py"
    )
    portable_authority: dict[str, Any] = {}
    portable_pass = False
    if portable_authority_path.is_file():
        portable_authority = load_json(portable_authority_path)
        portable_pass = (
            embedded_hash_matches(portable_authority, "artifact_sha256")
            and portable_authority.get("status")
            in {"PASS_AUTHORIZED_LAYOUT", "PASS_FULL_REPLAY"}
            and portable_authority.get("authorization_path_check_preserved") is True
            and portable_authority.get("frozen_verifier_modified") is False
            and portable_authority.get("authorization_sha256")
            == "c6d34e38c2b4dbf7c856a635f0c96067fb533550fa16a52f03f01c64d073eb4d"
            and portable_authority.get("expected_output_directory")
            == V3_DIR.as_posix()
            and portable_wrapper_path.is_file()
            and portable_authority.get("wrapper_sha256")
            == file_sha256(portable_wrapper_path)
            and frozen_verifier_path.is_file()
            and portable_authority.get("frozen_verifier_sha256")
            == file_sha256(frozen_verifier_path)
        )
    audit.check(
        "release.v3_portable_replay_staging",
        portable_pass,
        (
            "authorized-layout staging wrapper passed while preserving the frozen "
            "verifier's path check"
            if portable_pass
            else "provide a validated disposable full-layout staging wrapper"
        ),
        severity="release_blocker",
    )
    return {
        "paper_source": "docs/paper/neurips_2026/main_fixed_value.tex",
        "asset_hashes": hashes,
        "release_candidate": {
            "path": "output/release/partizan-fixed-value-reproducibility-rc1.zip",
            "sha256": archive_hash,
            "member_count": len(names),
            "zip_integrity": bad_member is None,
            "contains_scope_authority": contains_scope,
            "contains_scope_figure": contains_scope_figure,
            "portable_replay_staging": portable_authority,
            "full_evidence_archive": full_authority,
        },
    }


def classify_research_directories(audit: Audit) -> dict[str, list[str]]:
    root = audit.path("output/research")
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name != "submission-evidence-audit-v1"
    )
    canonical = {
        V3_DIR.name,
        HISTORICAL_DIR.name,
        SCOPE_DIR.name,
    }
    supporting = {
        "digraph-order7-diversity-model-v2-3cf1bb0ba101",
        "digraph-order7-diversity-policy-validation-v3-e5a2280aac6b",
        "digraph-order7-policy-v3-initializations-v1",
        "digraph-order7-seed-calibration-v1-eb6feb7bdd84",
        "figures",
    }
    return {
        "canonical_paper_evidence": sorted(canonical & set(names)),
        "supporting_or_calibration": sorted(supporting & set(names)),
        "excluded_from_paper_claims": sorted(set(names) - canonical - supporting),
    }


def run(
    repo_root: Path,
    *,
    deep_scope_reduction: bool,
    historical_replay_dir: Path | None = None,
) -> dict[str, Any]:
    audit = Audit(repo_root)
    primary = audit_v3(audit)
    scope = audit_scope(audit, deep_reduction=deep_scope_reduction)
    historical = audit_historical(
        audit, fresh_replay_dir=historical_replay_dir
    )
    manuscript = audit_manuscript_and_release(audit)
    classification = classify_research_directories(audit)
    scientific_failures = [
        row
        for row in audit.checks
        if not row["passed"] and row["severity"] == "error"
    ]
    release_blockers = [
        row
        for row in audit.checks
        if not row["passed"] and row["severity"] == "release_blocker"
    ]
    warnings = [
        row
        for row in audit.checks
        if not row["passed"] and row["severity"] == "warning"
    ]
    payload = {
        "schema_version": SCHEMA,
        "audit_date": AUDIT_DATE,
        "status": (
            "FAIL"
            if scientific_failures
            else "PASS_WITH_RELEASE_REMEDIATIONS"
            if release_blockers
            else "PASS"
        ),
        "scientific_evidence_status": "FAIL" if scientific_failures else "PASS",
        "submission_release_status": "BLOCKED" if release_blockers else "READY",
        "paper_changed_by_audit": False,
        "frozen_experiment_directories_changed_by_audit": False,
        "primary": primary,
        "scope": scope,
        "historical_structural_case": historical,
        "manuscript_and_release": manuscript,
        "research_directory_classification": classification,
        "check_summary": {
            "total": len(audit.checks),
            "passed": sum(row["passed"] for row in audit.checks),
            "scientific_failures": len(scientific_failures),
            "release_blockers": len(release_blockers),
            "warnings": len(warnings),
        },
        "checks": audit.checks,
        "release_remediations": [row["detail"] for row in release_blockers],
    }
    payload["artifact_sha256"] = object_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "output/research/submission-evidence-audit-v1/AUDIT_MANIFEST.json"
        ),
    )
    parser.add_argument("--skip-deep-scope-reduction", action="store_true")
    parser.add_argument(
        "--historical-replay-dir",
        type=Path,
        help="optional fresh replay directory whose scientific projection is compared with the frozen authority",
    )
    arguments = parser.parse_args()
    root = arguments.repo_root.resolve()
    result = run(
        root,
        deep_scope_reduction=not arguments.skip_deep_scope_reduction,
        historical_replay_dir=(
            arguments.historical_replay_dir.resolve()
            if arguments.historical_replay_dir is not None
            else None
        ),
    )
    output = arguments.output
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(result) + b"\n")
    print(
        json.dumps(
            {
                "artifact_sha256": result["artifact_sha256"],
                "check_summary": result["check_summary"],
                "scientific_evidence_status": result["scientific_evidence_status"],
                "status": result["status"],
                "submission_release_status": result["submission_release_status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if result["scientific_evidence_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
