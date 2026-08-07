#!/usr/bin/env python3
"""Freeze leakage-safe historical warm starts and fresh V3 split seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256


SCHEMA = "partizan.digraph_order7_policy_v3_initializations.v1"
DIAGNOSTIC_DIR = Path(
    "output/research/digraph-order7-v2-reachability-diagnostic-v1"
)
OUTPUT_DIR = Path(
    "output/research/digraph-order7-policy-v3-initializations-v1"
)
V1_PROTOCOL = Path(
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"
)
V2_PROTOCOL = Path(
    "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json"
)
TARGETS = ("0", "*", "{0|1}")
MINIMUM_SUPPORT = 32
VALIDATION_COUNT = 4
TEST_COUNT = 12
SEED_PREFIX = "partizan.digraph_order7_policy_v3.split.v1"


def canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


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


def seed(split: str, index: int) -> int:
    return int.from_bytes(
        hashlib.sha256(
            f"{SEED_PREFIX}|{split}|pair|{index}".encode("ascii")
        ).digest()[:8],
        "big",
    )


def previous_seeds(repo_root: Path) -> set[int]:
    values = set()
    for path in (V1_PROTOCOL, V2_PROTOCOL):
        protocol = load_json_object(repo_root / path)
        for split in ("validation", "test"):
            values.update(protocol["splits"][split]["pair_seeds"])
    return values


def initialization_record(
    row: Mapping[str, Any],
    *,
    target: str,
    split: str,
    index: int,
    pair_seed: int,
) -> dict[str, Any]:
    return {
        "target": target,
        "split": split,
        "index": index,
        "pair_seed": pair_seed,
        "candidate": row["candidate"],
        "candidate_sha256": row["candidate_sha256"],
        "quotient_sha256": row["quotient_sha256"],
        "literal_game_sha256": row["literal_game_sha256"],
        "source": row["source"],
        "one_toggle_neighbor_count": row["one_toggle_neighbor_count"],
        "weakly_connected_neighbor_count": row[
            "weakly_connected_neighbor_count"
        ],
        "nonprior_candidate_neighbor_count": row[
            "nonprior_candidate_neighbor_count"
        ],
        "weakly_connected_nonprior_candidate_neighbor_count": row[
            "weakly_connected_nonprior_candidate_neighbor_count"
        ],
        "initialization_key": row["initialization_key"],
        "initialization_id": object_sha256(
            {
                "schema_version": f"{SCHEMA}.initialization_id",
                "target": target,
                "split": split,
                "index": index,
                "pair_seed": pair_seed,
                "candidate_sha256": row["candidate_sha256"],
                "quotient_sha256": row["quotient_sha256"],
                "initialization_key": row["initialization_key"],
            }
        ),
        "counts_as_discovery": False,
        "shared_across_arms": True,
        "selected_using_semantic_outcome": False,
        "new_semantic_evaluation_count": 0,
    }


def build(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    diagnostic = load_canonical_json(
        repo_root / DIAGNOSTIC_DIR / "REACHABILITY_DIAGNOSTIC.json"
    )
    verify_self_hash(
        diagnostic,
        "diagnostic_sha256",
        label="reachability diagnostic",
    )
    support = load_canonical_json(
        repo_root / DIAGNOSTIC_DIR / "HISTORICAL_CONTROL_SUPPORT.json"
    )
    verify_self_hash(support, "support_sha256", label="support rows")
    registry = load_canonical_json(
        repo_root
        / DIAGNOSTIC_DIR
        / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
    )
    verify_self_hash(registry, "registry_sha256", label="V3 prior registry")
    if (
        diagnostic.get("status")
        != "CONFIRMED_ACQUISITION_SUPPORT_DEADLOCK"
        or diagnostic.get("new_semantic_evaluation_count") != 0
        or support.get("new_semantic_evaluation_count") != 0
        or registry.get("model_training_use") is not False
    ):
        raise ValueError("reachability diagnostic boundary changed")
    prior_seed_values = previous_seeds(repo_root)
    validation_seeds = [seed("validation", index) for index in range(VALIDATION_COUNT)]
    test_seeds = [seed("test", index) for index in range(TEST_COUNT)]
    new_seeds = validation_seeds + test_seeds
    if (
        len(new_seeds) != len(set(new_seeds))
        or set(new_seeds) & prior_seed_values
    ):
        raise ValueError("V3 split seed collision")
    by_split = {
        "validation": {target: [] for target in TARGETS},
        "test": {target: [] for target in TARGETS},
    }
    eligible_counts = {}
    selected_ids = set()
    for target in TARGETS:
        eligible = [
            row
            for row in support["rows_by_target"][target]
            if row["weakly_connected_nonprior_candidate_neighbor_count"]
            >= MINIMUM_SUPPORT
        ]
        eligible.sort(key=lambda row: row["initialization_key"])
        eligible_counts[target] = len(eligible)
        if len(eligible) < VALIDATION_COUNT + TEST_COUNT:
            raise ValueError(f"{target}: insufficient V3 initialization support")
        selected = eligible[: VALIDATION_COUNT + TEST_COUNT]
        if len({row["candidate_sha256"] for row in selected}) != len(selected):
            raise ValueError("V3 initialization candidate duplication")
        for index, row in enumerate(selected[:VALIDATION_COUNT]):
            record = initialization_record(
                row,
                target=target,
                split="validation",
                index=index,
                pair_seed=validation_seeds[index],
            )
            by_split["validation"][target].append(record)
            selected_ids.add(record["initialization_id"])
        for index, row in enumerate(selected[VALIDATION_COUNT:]):
            record = initialization_record(
                row,
                target=target,
                split="test",
                index=index,
                pair_seed=test_seeds[index],
            )
            by_split["test"][target].append(record)
            selected_ids.add(record["initialization_id"])
    if len(selected_ids) != len(TARGETS) * (VALIDATION_COUNT + TEST_COUNT):
        raise ValueError("V3 initialization identifiers are not unique")
    payload = {
        "schema_version": SCHEMA,
        "status": "FROZEN_BEFORE_V3_VALIDATION_AND_TEST",
        "selection": {
            "source": "historical exact-target controls only",
            "ordering": "ascending domain-separated initialization_key",
            "minimum_weakly_connected_nonprior_candidate_neighbors": (
                MINIMUM_SUPPORT
            ),
            "uses_graph_connectivity": True,
            "uses_prior_candidate_membership": True,
            "uses_exact_outcome_of_neighbor": False,
            "uses_literal_or_quotient_of_neighbor": False,
            "uses_v2_test_outcome_as_label": False,
            "model_training_use": False,
            "model_selection_use": False,
        },
        "split_seed_derivation": {
            "prefix": SEED_PREFIX,
            "algorithm": "first_8_bytes_of_sha256_big_endian",
            "validation_pair_seeds": validation_seeds,
            "test_pair_seeds": test_seeds,
            "fresh_against_v1_and_v2": True,
        },
        "eligible_historical_control_count": eligible_counts,
        "initializations": by_split,
        "counts": {
            "validation_per_target": VALIDATION_COUNT,
            "test_per_target": TEST_COUNT,
            "total": len(selected_ids),
        },
        "source_bindings": {
            "diagnostic": {
                "path": (
                    DIAGNOSTIC_DIR / "REACHABILITY_DIAGNOSTIC.json"
                ).as_posix(),
                "sha256": file_sha256(
                    repo_root
                    / DIAGNOSTIC_DIR
                    / "REACHABILITY_DIAGNOSTIC.json"
                ),
                "diagnostic_sha256": diagnostic["diagnostic_sha256"],
            },
            "support": {
                "path": (
                    DIAGNOSTIC_DIR / "HISTORICAL_CONTROL_SUPPORT.json"
                ).as_posix(),
                "sha256": file_sha256(
                    repo_root
                    / DIAGNOSTIC_DIR
                    / "HISTORICAL_CONTROL_SUPPORT.json"
                ),
                "support_sha256": support["support_sha256"],
            },
            "prior_registry": {
                "path": (
                    DIAGNOSTIC_DIR
                    / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
                ).as_posix(),
                "sha256": file_sha256(
                    repo_root
                    / DIAGNOSTIC_DIR
                    / "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
                ),
                "registry_sha256": registry["registry_sha256"],
            },
        },
        "new_semantic_evaluation_count": 0,
        "test_data_generated": False,
        "paper_evidence": False,
    }
    manifest = hashed_record(payload, "manifest_sha256")
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(output_dir / "INITIALIZATION_MANIFEST.json", manifest)
    completion = hashed_record(
        {
            "schema_version": f"{SCHEMA}.completion",
            "status": "PASS_INITIALIZATION_FREEZE_ONLY",
            "manifest_file_sha256": file_sha256(
                output_dir / "INITIALIZATION_MANIFEST.json"
            ),
            "manifest_sha256": manifest["manifest_sha256"],
            "initialization_count": len(selected_ids),
            "new_semantic_evaluation_count": 0,
            "test_data_generated": False,
            "paper_evidence": False,
        },
        "completion_sha256",
    )
    write_json_exclusive(output_dir / "INITIALIZATION_FREEZE_COMPLETE.json", completion)
    return completion


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
