#!/usr/bin/env python3
"""Diagnose the V2 local-search deadlock without new semantic evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
from typing import Any, Mapping

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    graph_from_candidate_record,
    weakly_connected,
)
import verify_digraph_order7_neural_validation_v1 as v1_validation


SCHEMA = "partizan.digraph_order7_v2_reachability_diagnostic.v1"
V2_RUN = Path(
    "output/research/digraph-order7-diversity-policy-test-v2-fd029f79ddfc"
)
OUTPUT_DIR = Path(
    "output/research/digraph-order7-v2-reachability-diagnostic-v1"
)
TARGETS = ("0", "*", "{0|1}")
ARMS = (
    "structural_toggle_one_random",
    "neural_toggle_one_equality",
    "neural_toggle_one_equality_novelty",
)
ARC_LIST = tuple(
    (source, target)
    for source in range(7)
    for target in range(7)
    if source != target
)
INITIALIZATION_PREFIX = "partizan.digraph_order7_policy_v3.initialization.v1"


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


def verify_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    payload = dict(value)
    supplied = payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


def hashed_record(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = object_sha256(payload)
    return result


def write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    write_bytes_exclusive(path, canonical_line(value))


def toggle(candidate: Mapping[str, Any], arc: tuple[int, int]) -> dict[str, Any]:
    graph = graph_from_candidate_record(candidate)
    edges = list(graph.edges)
    edges[arc[0]] ^= 1 << arc[1]
    return candidate_record(type(graph)(graph.blue_mask, tuple(edges)))


def support_record(
    row: Mapping[str, Any],
    *,
    target: str,
    prior_candidates: set[str],
) -> dict[str, Any]:
    connected = 0
    nonprior = 0
    connected_nonprior = 0
    neighbor_ids = []
    for arc in ARC_LIST:
        candidate = toggle(row["candidate"], arc)
        candidate_sha = candidate_record_sha256(candidate)
        graph = graph_from_candidate_record(candidate)
        is_connected = weakly_connected(graph)
        is_nonprior = candidate_sha not in prior_candidates
        connected += int(is_connected)
        nonprior += int(is_nonprior)
        connected_nonprior += int(is_connected and is_nonprior)
        neighbor_ids.append(candidate_sha)
    if len(set(neighbor_ids)) != 42:
        raise ValueError("one-toggle support contains duplicate neighbors")
    initialization_key = hashlib.sha256(
        (
            f"{INITIALIZATION_PREFIX}|{target}|"
            f"{row['candidate_sha256']}|{row['quotient_sha256']}"
        ).encode("ascii")
    ).hexdigest()
    return {
        "target": target,
        "candidate": row["candidate"],
        "candidate_sha256": row["candidate_sha256"],
        "quotient_sha256": row["quotient_sha256"],
        "literal_game_sha256": row.get("literal_game_sha256"),
        "source": row["source"],
        "one_toggle_neighbor_count": 42,
        "weakly_connected_neighbor_count": connected,
        "nonprior_candidate_neighbor_count": nonprior,
        "weakly_connected_nonprior_candidate_neighbor_count": (
            connected_nonprior
        ),
        "initialization_key": initialization_key,
        "new_semantic_evaluation_count": 0,
    }


def distribution(values: list[int]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(values),
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
        "mean": sum(values) / len(values),
        "p10_nearest_rank": ordered[max(0, (len(ordered) + 9) // 10 - 1)],
        "p90_nearest_rank": ordered[max(0, (9 * len(ordered) + 9) // 10 - 1)],
        "count_ge_1": sum(value >= 1 for value in values),
        "count_ge_8": sum(value >= 8 for value in values),
        "count_ge_16": sum(value >= 16 for value in values),
        "count_ge_24": sum(value >= 24 for value in values),
        "count_ge_32": sum(value >= 32 for value in values),
    }


def historical_literals(repo_root: Path) -> dict[str, dict[str, str]]:
    run_dir = repo_root / v1_validation.TRAINING_RUN
    manifest = load_canonical_json(run_dir / "manifest.json")
    values: dict[str, dict[str, str]] = {target: {} for target in TARGETS}
    for target in TARGETS:
        seed = manifest["seed_controls"][target]
        values[target][seed["quotient"]["quotient_sha256"]] = seed[
            "literal_game_sha256"
        ]
    with (run_dir / "events.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            quotient = event.get("quotient")
            decision = event.get("exact_decision")
            if not isinstance(quotient, Mapping) or not isinstance(
                decision,
                Mapping,
            ):
                continue
            values[event["target"]][quotient["quotient_sha256"]] = decision[
                "candidate_root_game_sha256"
            ]
    return values


def build(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    run_dir = repo_root / V2_RUN
    completion = load_canonical_json(run_dir / "RUN_COMPLETE.json")
    verify_self_hash(completion, "completion_sha256", label="V2 completion")
    verification = load_canonical_json(
        run_dir / "independent_verification.json"
    )
    verify_self_hash(
        verification,
        "verification_sha256",
        label="V2 verification",
    )
    if (
        completion.get("status") != "NO_GO"
        or completion.get("independent_replay_pass") is not True
        or verification.get("status") != "PASS"
        or verification.get("corruption_family_count") != 26
    ):
        raise ValueError("V2 is not a complete independently verified NO_GO")
    prior = load_canonical_json(run_dir / "prior_split_registry.json")
    verify_self_hash(prior, "registry_sha256", label="V2 prior registry")
    streams = load_canonical_json(run_dir / "stream_metrics.json")
    verify_self_hash(streams, "bundle_sha256", label="V2 stream bundle")
    if any(
        row["prior_split_collision_count"] != row["verifier_calls"]
        or row["structural_tier_counts"] != {"3": row["verifier_calls"]}
        or row["quotient_unique_discoveries"] != 0
        or row["literal_game_unique_discoveries"] != 0
        for row in streams["streams"]
    ):
        raise ValueError("V2 stream deadlock projection changed")

    candidate_ids = set(prior["candidate_sha256"])
    quotient_ids = set(prior["quotient_sha256"])
    literal_ids = set(prior["literal_game_sha256_audit_only"])
    event_count = 0
    exact_count = 0
    with (run_dir / "events.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            event_count += 1
            candidate_ids.add(event["candidate_sha256"])
            structural = event.get("structural_quotient")
            if isinstance(structural, Mapping):
                quotient_ids.add(structural["quotient_sha256"])
            decision = event.get("exact_decision")
            if isinstance(decision, Mapping):
                exact_count += int(decision.get("equal") is True)
                literal_ids.add(decision["candidate_root_game_sha256"])
    if event_count != 221_184:
        raise ValueError("V2 event count changed")
    historical = v1_validation.reconstruct_training_registry(repo_root)
    literal_by_target_quotient = historical_literals(repo_root)
    supports = {}
    summaries = {}
    stage0 = {}
    for target in TARGETS:
        target_rows = historical["validation_parents"][target]
        support_rows = [
            support_record(
                {
                    **row,
                    "literal_game_sha256": literal_by_target_quotient[target][
                        row["quotient_sha256"]
                    ],
                },
                target=target,
                prior_candidates=candidate_ids,
            )
            for row in target_rows
        ]
        support_rows.sort(key=lambda row: row["initialization_key"])
        supports[target] = support_rows
        values = [
            row["weakly_connected_nonprior_candidate_neighbor_count"]
            for row in support_rows
        ]
        summaries[target] = distribution(values)
        stage_rows = [
            row for row in support_rows if row["source"] == "stage0_control"
        ]
        if len(stage_rows) != 1:
            raise ValueError("Stage-0 support count changed")
        stage0[target] = stage_rows[0]

    registry_payload = {
        "schema_version": f"{SCHEMA}.v3_prior_split_registry",
        "status": "FROZEN_ALL_PRE_V3_IDENTITIES",
        "source": {
            "v2_run": V2_RUN.as_posix(),
            "v2_completion_file_sha256": file_sha256(
                run_dir / "RUN_COMPLETE.json"
            ),
            "v2_completion_sha256": completion["completion_sha256"],
            "v2_event_file_sha256": file_sha256(run_dir / "events.jsonl"),
            "v2_event_count": event_count,
            "v2_prior_registry_sha256": prior["registry_sha256"],
        },
        "candidate_sha256": sorted(candidate_ids),
        "quotient_sha256": sorted(quotient_ids),
        "literal_game_sha256_audit_only": sorted(literal_ids),
        "counts": {
            "candidate_identities": len(candidate_ids),
            "quotient_identities": len(quotient_ids),
            "literal_game_identities_audit_only": len(literal_ids),
            "v2_event_rows": event_count,
            "v2_certified_exact_matches": exact_count,
        },
        "blocking_rule": ["candidate_sha256", "quotient_sha256"],
        "recorded_not_blocked": ["literal_game_sha256"],
        "model_training_use": False,
        "test_outcome_feature_use": False,
        "new_semantic_evaluation_count": 0,
    }
    registry = hashed_record(registry_payload, "registry_sha256")
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        output_dir / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json",
        registry,
    )
    support_payload = {
        "schema_version": f"{SCHEMA}.support_rows",
        "status": "STRUCTURAL_SUPPORT_ONLY",
        "initialization_prefix": INITIALIZATION_PREFIX,
        "rows_by_target": supports,
        "row_count": sum(len(rows) for rows in supports.values()),
        "v3_prior_registry_sha256": registry["registry_sha256"],
        "model_training_use": False,
        "test_outcome_feature_use": False,
        "new_semantic_evaluation_count": 0,
    }
    support = hashed_record(support_payload, "support_sha256")
    write_json_exclusive(
        output_dir / "HISTORICAL_CONTROL_SUPPORT.json",
        support,
    )
    diagnostic_payload = {
        "schema_version": SCHEMA,
        "status": "CONFIRMED_ACQUISITION_SUPPORT_DEADLOCK",
        "v2": {
            "completion_sha256": completion["completion_sha256"],
            "verification_sha256": verification["verification_sha256"],
            "event_count": event_count,
            "exact_match_count": exact_count,
            "prior_split_collision_count": sum(
                row["prior_split_collision_count"]
                for row in streams["streams"]
            ),
            "tier3_selection_count": sum(
                row["structural_tier_counts"]["3"]
                for row in streams["streams"]
            ),
            "quotient_discovery_count": 0,
            "literal_game_discovery_count": 0,
        },
        "stage0_one_toggle_support": stage0,
        "historical_control_support_distribution": summaries,
        "support_file": {
            "path": "HISTORICAL_CONTROL_SUPPORT.json",
            "sha256": file_sha256(
                output_dir / "HISTORICAL_CONTROL_SUPPORT.json"
            ),
            "support_sha256": support["support_sha256"],
        },
        "v3_registry_file": {
            "path": "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json",
            "sha256": file_sha256(
                output_dir / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
            ),
            "registry_sha256": registry["registry_sha256"],
        },
        "diagnosis": (
            "Every Stage-0 one-toggle neighbor was already quarantined. "
            "Because only clean quotient discoveries entered the adaptive "
            "repertoire, no arm could leave its initial control."
        ),
        "permitted_v3_use": (
            "select leakage-safe historical initialization controls from "
            "connectivity and candidate-identity support only"
        ),
        "forbidden_v3_use": [
            "model_training",
            "model_selection",
            "threshold_lowering",
            "reuse_of_v2_test_outcomes_as_labels",
        ],
        "new_semantic_evaluation_count": 0,
        "paper_evidence": True,
    }
    diagnostic = hashed_record(
        diagnostic_payload,
        "diagnostic_sha256",
    )
    write_json_exclusive(
        output_dir / "REACHABILITY_DIAGNOSTIC.json",
        diagnostic,
    )
    completion_payload = {
        "schema_version": f"{SCHEMA}.completion",
        "status": "PASS_DIAGNOSTIC_ONLY",
        "diagnostic_file_sha256": file_sha256(
            output_dir / "REACHABILITY_DIAGNOSTIC.json"
        ),
        "support_file_sha256": file_sha256(
            output_dir / "HISTORICAL_CONTROL_SUPPORT.json"
        ),
        "registry_file_sha256": file_sha256(
            output_dir / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
        ),
        "new_semantic_evaluation_count": 0,
        "model_training_use": False,
        "test_data_generated": True,
        "paper_evidence": True,
    }
    completion_record = hashed_record(
        completion_payload,
        "completion_sha256",
    )
    write_json_exclusive(
        output_dir / "DIAGNOSTIC_COMPLETE.json",
        completion_record,
    )
    return completion_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else repo_root / args.output_dir
    ).resolve()
    completion = build(repo_root, output_dir)
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
