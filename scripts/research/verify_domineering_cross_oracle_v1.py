#!/usr/bin/env python3
"""Validate the frozen Thermograph cross-oracle result."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess

from fixed_value_scope_protocol_v1 import artifact_sha256, canonical_json_bytes, load_json


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_SCOPE_CROSS_ORACLE_V1_PROTOCOL.json"),
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=Path("output/research/fixed-value-scope-v1/validation-v1"),
    )
    parser.add_argument(
        "--amendment",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_SCOPE_CROSS_ORACLE_V1_1_AMENDMENT.json"),
    )
    parser.add_argument(
        "--thermograph-root",
        type=Path,
        default=Path("../thermograph"),
    )
    args = parser.parse_args()
    protocol = load_json(args.protocol)
    if protocol.get("artifact_sha256") != artifact_sha256(protocol):
        raise ValueError("cross-oracle protocol hash differs")
    amendment = load_json(args.amendment)
    if amendment.get("artifact_sha256") != artifact_sha256(amendment):
        raise ValueError("cross-oracle amendment hash differs")
    if amendment.get("parent_protocol_artifact_sha256") != protocol["artifact_sha256"]:
        raise ValueError("cross-oracle amendment parent differs")
    if amendment.get("unchanged", {}).get("sample_file_sha256") != protocol["sampling"]["sample_file_sha256"]:
        raise ValueError("cross-oracle amendment changed the frozen sample")
    sample_path = Path(protocol["sampling"]["sample_file"])
    if file_sha256(sample_path) != protocol["sampling"]["sample_file_sha256"]:
        raise ValueError("frozen cross-oracle sample hash differs")
    result_path = args.result_dir / "CROSS_ORACLE_RESULTS_V1.tsv"
    thermograph_commit = subprocess.check_output(
        ["git", "-C", str(args.thermograph_root), "rev-parse", "HEAD"], text=True
    ).strip()
    thermograph_status = subprocess.check_output(
        ["git", "-C", str(args.thermograph_root), "status", "--short"], text=True
    ).strip()
    thermograph_hashes = {
        "short_game_rs_sha256": file_sha256(args.thermograph_root / "src/short_game.rs"),
        "lib_rs_sha256": file_sha256(args.thermograph_root / "src/lib.rs"),
        "cargo_lock_sha256": file_sha256(args.thermograph_root / "Cargo.lock"),
    }

    with sample_path.open(encoding="ascii", newline="") as handle:
        samples = {row["sample_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    with result_path.open(encoding="ascii", newline="") as handle:
        results = list(csv.DictReader(handle, delimiter="\t"))
    duplicate_count = len(results) - len({row["sample_id"] for row in results})
    missing = sorted(set(samples) - {row["sample_id"] for row in results})
    unexpected = sorted({row["sample_id"] for row in results} - set(samples))
    errors = [row for row in results if row["error"]]
    mismatches = []
    policy_counts: dict[str, dict[str, int]] = {}
    for row in results:
        sample = samples.get(row["sample_id"])
        if sample is None:
            continue
        policy = sample["policy_id"]
        counts = policy_counts.setdefault(policy, {"checked": 0, "matched": 0})
        counts["checked"] += 1
        observed = row["thermograph_equal"].lower()
        expected = sample["expected_equal"].lower()
        if observed == expected and not row["error"]:
            counts["matched"] += 1
        else:
            mismatches.append(
                {
                    "sample_id": row["sample_id"],
                    "expected_equal": expected,
                    "thermograph_equal": observed,
                    "comparison": row["comparison"],
                    "error": row["error"],
                }
            )
    checks = {
        "sample_hash_matches_frozen_protocol": True,
        "thermograph_commit_matches_frozen_protocol": thermograph_commit == protocol["oracle"]["repository_commit"],
        "thermograph_sources_match_frozen_protocol": all(
            thermograph_hashes[key] == protocol["oracle"][key] for key in thermograph_hashes
        ),
        "thermograph_worktree_is_clean": not thermograph_status,
        "result_count_matches_contract": len(results) == protocol["sampling"]["total_sample_count"],
        "no_duplicate_results": duplicate_count == 0,
        "no_missing_results": not missing,
        "no_unexpected_results": not unexpected,
        "all_samples_return_a_verdict": not errors,
        "thermograph_matches_all_frozen_python_verdicts": not mismatches,
    }
    authority = {
        "schema_version": "partizan.domineering_cross_oracle_authority.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "protocol_artifact_sha256": protocol["artifact_sha256"],
        "amendment_artifact_sha256": amendment["artifact_sha256"],
        "preserved_failed_authority_artifact_sha256": amendment["failed_authority_artifact_sha256"],
        "sample_file_sha256": protocol["sampling"]["sample_file_sha256"],
        "result_file_sha256": file_sha256(result_path),
        "result_count": len(results),
        "duplicate_count": duplicate_count,
        "missing_count": len(missing),
        "unexpected_count": len(unexpected),
        "oracle_error_count": len(errors),
        "verdict_mismatch_count": len(mismatches),
        "policy_counts": policy_counts,
        "thermograph_repository_commit": thermograph_commit,
        "thermograph_source_hashes": thermograph_hashes,
        "checks": checks,
        "mismatches": mismatches,
        "scientific_role": "post-hoc implementation-independence validation",
        "new_primary_experiment_verifier_calls": 0,
        "paper_state_changed": False,
        "v5_test_material_opened": False,
        "modal_used": False,
    }
    authority["artifact_sha256"] = artifact_sha256(authority)
    output = args.result_dir / "CROSS_ORACLE_AUTHORITY_V1.json"
    output.write_bytes(canonical_json_bytes(authority) + b"\n")
    print(json.dumps(authority, indent=2, sort_keys=True))
    return 0 if authority["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
