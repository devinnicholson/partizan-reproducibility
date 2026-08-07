#!/usr/bin/env python3
"""Semantic-free resource projection for the frozen V3 held-out test."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import validate_digraph_order7_diversity_policy_protocol_v3 as protocol_validator


SCHEMA = "partizan.digraph_order7_diversity_policy_resource_preflight.v3"
OUTPUT_PATH = Path(
    "output/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_RESOURCE_PREFLIGHT_V3.json"
)
V2_RUN = Path(
    "output/research/digraph-order7-diversity-policy-test-v2-fd029f79ddfc"
)
V3_VALIDATION_RUN = Path(
    "output/research/digraph-order7-diversity-policy-validation-v3-e5a2280aac6b"
)
SOURCES = {
    "v2_generation": V2_RUN / "GENERATION_COMPLETE.json",
    "v2_verification": V2_RUN / "independent_verification.json",
    "v2_completion": V2_RUN / "RUN_COMPLETE.json",
    "v3_validation_generation": V3_VALIDATION_RUN / "GENERATION_COMPLETE.json",
    "v3_validation_verification": (
        V3_VALIDATION_RUN / "independent_verification.json"
    ),
    "v3_validation_completion": V3_VALIDATION_RUN / "VALIDATION_COMPLETE.json",
}
RUNTIME_SAFETY = 1.25
DISK_SAFETY = 2.0
RSS_SAFETY = 2.0


def canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_line(value):
        raise ValueError(f"{path}: expected canonical newline JSON")
    return value


def verify_self_hash(
    value: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> None:
    payload = dict(value)
    supplied = payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def binding(repo_root: Path, relative: Path) -> dict[str, Any]:
    path = repo_root / relative
    if not path.is_file():
        raise ValueError(f"missing preflight source: {relative}")
    return {
        "path": relative.as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def build_report(repo_root: Path) -> dict[str, Any]:
    protocol = json.loads((repo_root / protocol_validator.PROTOCOL_PATH).read_bytes())
    errors = protocol_validator.validate(
        protocol,
        repo_root,
        check_bound_files=True,
    )
    if errors:
        raise ValueError("V3 protocol validation failed: " + "; ".join(errors))
    values = {
        name: load_canonical_json(repo_root / relative)
        for name, relative in SOURCES.items()
    }
    verify_self_hash(
        values["v2_generation"],
        "generation_sha256",
        label="V2 generation",
    )
    verify_self_hash(
        values["v2_verification"],
        "verification_sha256",
        label="V2 verification",
    )
    verify_self_hash(
        values["v2_completion"],
        "completion_sha256",
        label="V2 completion",
    )
    verify_self_hash(
        values["v3_validation_generation"],
        "generation_sha256",
        label="V3 validation generation",
    )
    verify_self_hash(
        values["v3_validation_verification"],
        "verification_sha256",
        label="V3 validation verification",
    )
    verify_self_hash(
        values["v3_validation_completion"],
        "completion_sha256",
        label="V3 validation completion",
    )
    if (
        values["v2_completion"].get("status") != "NO_GO"
        or values["v2_completion"].get("independent_replay_pass") is not True
        or values["v3_validation_completion"].get("status")
        != "PASS_VALIDATION_ONLY"
        or values["v3_validation_completion"].get(
            "test_authorization_allowed"
        )
        is not True
    ):
        raise ValueError("historical resource evidence boundary changed")
    total_events = (
        len(protocol["domain"]["targets"])
        * protocol["splits"]["test"]["pair_count_per_target"]
        * len(protocol["arms"])
        * protocol["splits"]["test"]["verifier_calls_per_arm_pair"]
    )
    v2_events = values["v2_generation"]["event_count"]
    validation_events = values["v3_validation_generation"]["event_count"]
    if total_events != 221184 or v2_events != total_events:
        raise ValueError("V3 and V2 test event budgets are no longer identical")
    generation_rate_projection = (
        values["v3_validation_generation"]["generation_wall_seconds"]
        / validation_events
        * total_events
    )
    verification_rate_projection = (
        values["v3_validation_verification"]["wall_seconds"]
        / validation_events
        * total_events
    )
    projected_generation = RUNTIME_SAFETY * max(
        values["v2_generation"]["generation_wall_seconds"],
        generation_rate_projection,
    )
    projected_verification = RUNTIME_SAFETY * max(
        values["v2_verification"]["wall_seconds"],
        verification_rate_projection,
    )
    v2_directory_bytes = directory_size(repo_root / V2_RUN)
    v3_validation_directory_bytes = directory_size(
        repo_root / V3_VALIDATION_RUN
    )
    projected_disk = math.ceil(
        DISK_SAFETY * (v2_directory_bytes + v3_validation_directory_bytes)
    )
    projected_rss = math.ceil(
        RSS_SAFETY
        * max(
            values["v2_generation"]["peak_resident_memory_bytes"],
            values["v3_validation_generation"]["peak_resident_memory_bytes"],
        )
    )
    caps = protocol["resource_gate"]
    checks = {
        "same_event_budget_as_completed_v2_test": total_events == v2_events,
        "projected_generation_within_limit": (
            projected_generation <= caps["test_generation_wall_seconds"]
        ),
        "projected_verification_within_limit": (
            projected_verification <= caps["test_verification_wall_seconds"]
        ),
        "projected_disk_within_limit": (
            projected_disk <= caps["run_directory_bytes"]
        ),
        "projected_rss_within_limit": (
            projected_rss <= caps["peak_resident_memory_bytes"]
        ),
        "v3_validation_authorized_test": (
            values["v3_validation_completion"]["test_authorization_allowed"]
            is True
        ),
    }
    payload = {
        "schema_version": SCHEMA,
        "status": "PASS" if all(checks.values()) else "FAIL_CLOSED",
        "protocol": binding(repo_root, protocol_validator.PROTOCOL_PATH),
        "historical_sources": {
            name: binding(repo_root, relative)
            for name, relative in SOURCES.items()
        },
        "method": {
            "same_frozen_v2_kernel_and_equal_test_event_budget": True,
            "v3_pair_local_overhead_rate_from_completed_validation": True,
            "generation_safety_multiplier": RUNTIME_SAFETY,
            "verification_safety_multiplier": RUNTIME_SAFETY,
            "disk_safety_multiplier": DISK_SAFETY,
            "rss_safety_multiplier": RSS_SAFETY,
            "semantic_test_evaluation_performed": False,
            "new_exact_verifier_calls_performed": 0,
            "test_seeds_or_test_initializations_executed": False,
        },
        "inputs": {
            "total_test_events": total_events,
            "v2_test_events": v2_events,
            "v3_validation_events": validation_events,
            "v2_generation_seconds": values["v2_generation"][
                "generation_wall_seconds"
            ],
            "v2_verification_seconds": values["v2_verification"][
                "wall_seconds"
            ],
            "v3_validation_generation_seconds": values[
                "v3_validation_generation"
            ]["generation_wall_seconds"],
            "v3_validation_verification_seconds": values[
                "v3_validation_verification"
            ]["wall_seconds"],
            "v2_directory_bytes": v2_directory_bytes,
            "v3_validation_directory_bytes": v3_validation_directory_bytes,
        },
        "projection": {
            "projected": {
                "generation_seconds": projected_generation,
                "independent_verification_seconds": projected_verification,
                "run_directory_bytes": projected_disk,
                "peak_resident_memory_bytes": projected_rss,
            },
            "caps": caps,
            "checks": checks,
            "status": "PASS" if all(checks.values()) else "FAIL_CLOSED",
        },
        "semantic_test_evaluation_performed": False,
        "test_data_generated": False,
        "paper_evidence": False,
    }
    report = dict(payload)
    report["report_sha256"] = object_sha256(payload)
    return report


def write_exclusive(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_line(report))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    output = (
        args.output if args.output.is_absolute() else repo_root / args.output
    ).resolve()
    report = build_report(repo_root)
    write_exclusive(output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
