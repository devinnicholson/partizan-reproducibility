#!/usr/bin/env python3
"""Independently replay the frozen diversity-policy V2 validation corpus."""

from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import verify_digraph_order7_neural_validation_v1 as v1_verifier
from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    descriptor_record,
    graph_from_candidate_record,
    quotient_record,
    verify_candidate_evidence,
    weakly_connected,
)
from digraph_placement_control import parse_game_form
from semantic_equality_certificate_v1 import artifact_binding
from short_game_fiber_pilot import (
    birthday,
    edge_count,
    game_digest,
    leq,
    node_count,
    serialize,
)


SCHEMA = "partizan.digraph_order7_diversity_validation.v2"
PRIOR_REGISTRY_SCHEMA = f"{SCHEMA}.prior_split_identity_registry"
POOL_RECORD_SCHEMA = f"{SCHEMA}.pool_candidate"
POOL_COMMITMENT_SCHEMA = f"{SCHEMA}.pool_commitment"
LABEL_RECORD_SCHEMA = f"{SCHEMA}.label"
VALIDATION_REGISTRY_SCHEMA = f"{SCHEMA}.validation_identity_registry"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
VERIFICATION_SCHEMA = f"{SCHEMA}.independent_verification"
NEGATIVE_SCHEMA = f"{SCHEMA}.negative_tests"
COMPLETION_SCHEMA = f"{SCHEMA}.completion"
PROTOCOL_PATH = Path("docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json")
PROTOCOL_PREFIX = "partizan.digraph_order7_diversity_policy_comparison.v2"
TARGETS = ("0", "*", "{0|1}")
ARC_LIST = tuple(
    (source, target) for source in range(7) for target in range(7) if source != target
)
ZERO_SHA256 = "0" * 64
OFFICIAL_MODE = "authorized_validation"
SMOKE_MODE = "smoke_fixture"
SMOKE_PREFIX = f"{SCHEMA}.smoke"
REQUIRED_MODEL_FILES = (
    "python/partizan/digraph_diversity_ranker.py",
    "python/partizan/digraph_neural_ranker.py",
    "tests/test_digraph_diversity_ranker.py",
    "tests/test_digraph_neural_ranker.py",
    "docs/digraph_diversity_ranker.md",
    "docs/digraph_neural_ranker.md",
    "pyproject.toml",
)
POOL_FORBIDDEN_OUTCOME_FIELDS = {
    "weakly_connected",
    "prior_split_quotient_collision",
    "prior_split_literal_game_overlap",
    "exact_decision",
    "structural_quotient",
    "quotient",
    "measurements",
    "eligible_for_validation_metric",
    "exclusion_reasons",
    "sidecars",
    "equality_certificate_sha256",
}


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
    if not isinstance(value, dict) or canonical_line(value) != raw:
        raise ValueError(f"{path}: expected canonical newline JSON")
    return value


def load_canonical_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            value = json.loads(raw)
            if not isinstance(value, dict) or canonical_line(value) != raw:
                raise ValueError(f"{path}:{line_number}: expected canonical JSONL")
            rows.append(value)
    if not rows:
        raise ValueError(f"{path}: expected at least one row")
    return rows


def verify_embedded(value: Mapping[str, Any], field: str, *, label: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


def write_bytes_exclusive(path: Path, data: bytes) -> None:
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


def verify_bound_file(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    label: str,
) -> Path:
    relative = Path(str(binding.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path escapes repository")
    path = repo_root / relative
    if not path.is_file() or file_sha256(path) != binding.get("sha256"):
        raise ValueError(f"{label} source binding changed")
    return path


def count_jsonl(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _line in handle)


def reconstruct_prior_split_registry(repo_root: Path) -> dict[str, Any]:
    """Rebuild the quarantine without importing the V2 generator."""

    protocol_path = repo_root / PROTOCOL_PATH
    protocol = load_json_object(protocol_path)
    quarantine = protocol["source_evidence"]["v1_diagnostic"]["quarantine_bindings"]
    historical = v1_verifier.reconstruct_training_registry(repo_root)
    verify_embedded(
        historical,
        "registry_sha256",
        label="historical training registry",
    )
    candidate_ids = set(historical["candidate_sha256"])
    quotient_ids = set(historical["quotient_sha256"])
    literal_ids: set[str] = set()
    source_bindings: list[dict[str, Any]] = []

    pool_identity_sets: list[set[str]] = []
    for index, binding in enumerate(quarantine["v1_validation_pool_attempts"]):
        path = verify_bound_file(
            repo_root,
            binding,
            label=f"V1 validation pool attempt {index}",
        )
        if count_jsonl(path) != binding["row_count"]:
            raise ValueError("V1 validation pool row count changed")
        identities: set[str] = set()
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                row = json.loads(line)
                candidate_sha = row.get("candidate_sha256")
                if not isinstance(candidate_sha, str):
                    raise ValueError(
                        f"{path}:{line_number}: candidate identity missing"
                    )
                identities.add(candidate_sha)
        pool_identity_sets.append(identities)
        candidate_ids.update(identities)
        source_bindings.append(
            {
                "role": "v1_validation_pool_attempt",
                "path": binding["path"],
                "sha256": binding["sha256"],
                "row_count": binding["row_count"],
                "status": binding["status"],
            }
        )
    if not pool_identity_sets or any(
        identities != pool_identity_sets[0] for identities in pool_identity_sets[1:]
    ):
        raise ValueError("V1 validation attempts do not share one pool")

    registry_binding = quarantine["v1_validation_registry"]
    registry_path = verify_bound_file(
        repo_root,
        registry_binding,
        label="V1 validation registry",
    )
    registry = load_canonical_json(registry_path)
    verify_embedded(registry, "registry_sha256", label="V1 validation registry")
    candidate_ids.update(registry["candidate_sha256"])
    quotient_ids.update(registry["quotient_sha256"])
    source_bindings.append(
        {"role": "v1_validation_identity_registry", **registry_binding}
    )

    prior_binding = quarantine["v1_test_prior_split_registry"]
    prior_path = verify_bound_file(
        repo_root,
        prior_binding,
        label="V1 test prior-split registry",
    )
    prior = load_canonical_json(prior_path)
    verify_embedded(prior, "registry_sha256", label="V1 test prior registry")
    candidate_ids.update(prior["candidate_sha256"])
    quotient_ids.update(prior["quotient_sha256"])
    source_bindings.append({"role": "v1_test_prior_split_registry", **prior_binding})

    event_binding = quarantine["v1_test_events"]
    event_path = verify_bound_file(
        repo_root,
        event_binding,
        label="V1 test events",
    )
    if count_jsonl(event_path) != event_binding["row_count"]:
        raise ValueError("V1 test event row count changed")
    test_rows = 0
    with event_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            event = json.loads(line)
            test_rows += 1
            candidate_sha = event.get("candidate_sha256")
            if not isinstance(candidate_sha, str):
                raise ValueError(
                    f"{event_path}:{line_number}: candidate identity missing"
                )
            candidate_ids.add(candidate_sha)
            quotient = event.get("structural_quotient")
            if isinstance(quotient, Mapping):
                quotient_sha = quotient.get("quotient_sha256")
                if isinstance(quotient_sha, str):
                    quotient_ids.add(quotient_sha)
            decision = event.get("exact_decision")
            if isinstance(decision, Mapping):
                literal_sha = decision.get("candidate_root_game_sha256")
                if isinstance(literal_sha, str):
                    literal_ids.add(literal_sha)
    source_bindings.append({"role": "v1_test_events", **event_binding})

    completion_binding = quarantine["v1_test_completion"]
    completion_path = verify_bound_file(
        repo_root,
        completion_binding,
        label="V1 test completion",
    )
    completion = load_canonical_json(completion_path)
    verify_embedded(
        completion,
        "completion_sha256",
        label="V1 test completion",
    )
    if completion.get("status") != completion_binding["status"]:
        raise ValueError("V1 test completion status changed")
    source_bindings.append({"role": "v1_test_completion", **completion_binding})

    payload = {
        "schema_version": PRIOR_REGISTRY_SCHEMA,
        "status": "FROZEN_ALL_PRE_V2_IDENTITIES",
        "protocol": {
            "path": PROTOCOL_PATH.as_posix(),
            "sha256": file_sha256(protocol_path),
        },
        "historical_training_registry": {
            "registry_sha256": historical["registry_sha256"],
            "source": historical["source"],
        },
        "source_bindings": source_bindings,
        "candidate_sha256": sorted(candidate_ids),
        "quotient_sha256": sorted(quotient_ids),
        "literal_game_sha256_audit_only": sorted(literal_ids),
        "validation_parents": historical["validation_parents"],
        "counts": {
            "candidate_identities": len(candidate_ids),
            "quotient_identities": len(quotient_ids),
            "literal_game_identities_audit_only": len(literal_ids),
            "historical_validation_parents": {
                target: len(historical["validation_parents"][target])
                for target in TARGETS
            },
            "v1_validation_pool_attempts": len(pool_identity_sets),
            "v1_test_event_rows": test_rows,
        },
        "blocking_rule": ["candidate_sha256", "quotient_sha256"],
        "recorded_not_blocked": ["literal_game_sha256"],
        "model_training_use": False,
    }
    result = dict(payload)
    result["registry_sha256"] = object_sha256(payload)
    return result


def counter_randbelow(
    size: int,
    *,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    unit_index: int,
    draw_name: str,
) -> int:
    if size <= 0:
        raise ValueError("randbelow size must be positive")
    modulus = 1 << 256
    limit = modulus - modulus % size
    counter = 0
    while True:
        message = (
            f"{prefix}|{phase}|{target}|{pair_seed}|{unit_index}|"
            f"{draw_name}|{counter}"
        ).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(message).digest(), "big")
        if value < limit:
            return value % size
        counter += 1


def independent_arcs(
    *,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    group_index: int,
    count: int,
) -> list[tuple[int, int]]:
    arcs = list(ARC_LIST)
    for index in range(len(arcs) - 1, 0, -1):
        selected = counter_randbelow(
            index + 1,
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=group_index,
            draw_name=f"arc_shuffle_{index}",
        )
        arcs[index], arcs[selected] = arcs[selected], arcs[index]
    return arcs[:count]


def independent_toggle(
    candidate: Mapping[str, Any],
    arc: tuple[int, int],
) -> dict[str, Any]:
    graph = graph_from_candidate_record(candidate)
    source, target = arc
    edges = list(graph.edges)
    edges[source] ^= 1 << target
    return candidate_record(type(graph)(graph.blue_mask, tuple(edges)))


def verify_manifest_design(
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("manifest schema changed")
    design = manifest.get("design", {})
    if (
        design.get("targets") != list(TARGETS)
        or design.get("group_size") != 16
        or design.get("operator") != "toggle_one_arc"
        or design.get("adaptive_parent_repertoire") is not False
        or design.get("adaptive_policy_memory_during_selection") is not True
        or design.get("all_candidates_labeled_once") is not True
        or design.get("same_committed_pools_for_all_configurations") is not True
    ):
        raise ValueError("manifest validation design changed")
    seed_by_target = design.get("seed_by_target", {})
    if set(seed_by_target) != set(TARGETS):
        raise ValueError("manifest target seeds changed")
    if manifest["mode"] == OFFICIAL_MODE:
        frozen = protocol["splits"]["validation"]
        if design.get("groups_per_pair") != frozen["groups_per_pair"] or any(
            seed_by_target[target] != frozen["pair_seeds"] for target in TARGETS
        ):
            raise ValueError("official validation seeds or groups changed")
    elif manifest["mode"] == SMOKE_MODE:
        if design.get("groups_per_pair") not in (1, 2, 3, 4):
            raise ValueError("smoke group count changed")
        forbidden = set(protocol["splits"]["validation"]["pair_seeds"]) | set(
            protocol["splits"]["test"]["pair_seeds"]
        )
        for index, target in enumerate(TARGETS):
            expected = int.from_bytes(
                hashlib.sha256(f"{SMOKE_PREFIX}|pair|{index}".encode("utf-8")).digest()[
                    :8
                ],
                "big",
            )
            if seed_by_target[target] != [expected] or expected in forbidden:
                raise ValueError("smoke seed domain does not replay")
    else:
        raise ValueError("unsupported validation mode")


def verify_model_snapshot(
    repo_root: Path,
    model: Mapping[str, Any],
) -> None:
    if (
        model.get("repository") != "partizan"
        or len(str(model.get("pushed_commit_sha", ""))) != 40
        or any(
            character not in "0123456789abcdef"
            for character in str(model.get("pushed_commit_sha", ""))
        )
        or model.get("remote_commit_verified") is not True
    ):
        raise ValueError("launch model commit is not frozen")
    files = model.get("snapshot_files", [])
    if [entry.get("repo_relative_path") for entry in files] != list(
        REQUIRED_MODEL_FILES
    ):
        raise ValueError("model snapshot inventory changed")
    canonical_files: list[dict[str, str]] = []
    for entry in files:
        relative = Path(str(entry.get("snapshot_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("model snapshot path is unsafe")
        if file_sha256(repo_root / relative) != entry.get("sha256"):
            raise ValueError("model snapshot bytes changed")
        canonical_files.append(
            {
                "repo_relative_path": entry["repo_relative_path"],
                "sha256": entry["sha256"],
            }
        )
    payload = {
        "repository": "partizan",
        "repository_url": model["repository_url"],
        "pushed_commit_sha": model["pushed_commit_sha"],
        "files": canonical_files,
    }
    if object_sha256(payload) != model.get("snapshot_sha256"):
        raise ValueError("model snapshot aggregate hash changed")


def verify_official_launch(
    *,
    repo_root: Path,
    run_dir: Path,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    binding = manifest.get("launch")
    if not isinstance(binding, Mapping):
        raise ValueError("official run lacks launch binding")
    relative = Path(str(binding.get("file", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("launch binding path is unsafe")
    launch_path = run_dir / relative
    if file_sha256(launch_path) != binding.get("file_sha256"):
        raise ValueError("launch file hash changed")
    launch = load_canonical_json(launch_path)
    verify_embedded(launch, "launch_sha256", label="launch")
    if (
        launch.get("schema_version") != LAUNCH_SCHEMA
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("launch_sha256") != binding.get("launch_sha256")
    ):
        raise ValueError("launch status or identity changed")
    if launch.get("protocol") != manifest["protocol"]:
        raise ValueError("launch protocol binding changed")
    frozen = protocol["splits"]["validation"]
    if launch.get("validation_design") != {
        "targets": list(TARGETS),
        "pair_seeds": frozen["pair_seeds"],
        "groups_per_pair": frozen["groups_per_pair"],
        "group_size": frozen["group_size"],
        "all_candidates_labeled_once": True,
        "adaptive_parent_repertoire": False,
        "adaptive_policy_memory_during_selection": True,
    }:
        raise ValueError("launch validation design changed")
    sources = launch.get("sources", [])
    if not sources:
        raise ValueError("launch source inventory is empty")
    for entry in sources:
        source_relative = Path(str(entry.get("repo_relative_path", "")))
        if source_relative.is_absolute() or ".." in source_relative.parts:
            raise ValueError("launch source path is unsafe")
        if file_sha256(repo_root / source_relative) != entry.get("sha256"):
            raise ValueError("launch source bytes changed")
    model = launch.get("model_implementation")
    if not isinstance(model, Mapping):
        raise ValueError("launch model implementation missing")
    verify_model_snapshot(repo_root, model)
    authorization_payload = {
        field: launch[field]
        for field in (
            "protocol",
            "validation_design",
            "sources",
            "commands",
            "resource_limits",
            "model_implementation",
            "authorization_nonce",
        )
    }
    if (
        object_sha256(authorization_payload) != launch.get("authorization_sha256")
        or launch["authorization_sha256"] != binding.get("authorization_sha256")
        or launch["output_directory"] != binding.get("output_directory")
    ):
        raise ValueError("launch authorization does not replay")
    if run_dir.resolve() != (repo_root / launch["output_directory"]).resolve():
        raise ValueError("official output directory changed")
    expected_bundle: list[dict[str, str]] = []
    bundled_sources: list[tuple[str, str, str]] = [
        ("validation_source", entry["repo_relative_path"], entry["sha256"])
        for entry in sources
    ] + [
        ("partizan_model", entry["snapshot_path"], entry["sha256"])
        for entry in model["snapshot_files"]
    ]
    for role, source_path, digest in bundled_sources:
        bundled = (
            Path("source") / role / digest[:2] / f"{digest}-{Path(source_path).name}"
        )
        if file_sha256(run_dir / bundled) != digest:
            raise ValueError("bundled source bytes changed")
        expected_bundle.append(
            {
                "role": role,
                "source_path": source_path,
                "bundled_path": bundled.as_posix(),
                "sha256": digest,
            }
        )
    if manifest.get("source_bundle") != expected_bundle:
        raise ValueError("manifest source bundle changed")


def replay_pool_records(
    *,
    rows: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    prior_registry: Mapping[str, Any],
) -> None:
    prefix = PROTOCOL_PREFIX if manifest["mode"] == OFFICIAL_MODE else SMOKE_PREFIX
    phase = "validation" if manifest["mode"] == OFFICIAL_MODE else "smoke_validation"
    group_size = manifest["design"]["group_size"]
    prior_candidates = set(prior_registry["candidate_sha256"])
    parent_maps = {
        target: {
            row["quotient_sha256"]: row
            for row in prior_registry["validation_parents"][target]
        }
        for target in TARGETS
    }
    previous = ZERO_SHA256
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        verify_embedded(row, "pool_record_sha256", label="pool record")
        if row.get("schema_version") != POOL_RECORD_SCHEMA:
            raise ValueError("pool record schema changed")
        if POOL_FORBIDDEN_OUTCOME_FIELDS & set(row):
            raise ValueError("pool contains an outcome before commitment")
        if (
            row["mode"] != manifest["mode"]
            or row["global_pool_candidate_index"] != index
            or row["previous_pool_record_sha256"] != previous
        ):
            raise ValueError("pool record order or chain changed")
        previous = row["pool_record_sha256"]
        target = row["target"]
        parent = parent_maps[target].get(row["parent"]["quotient_sha256"])
        if (
            parent is None
            or parent["candidate_sha256"] != row["parent"]["candidate_sha256"]
        ):
            raise ValueError("pool parent is absent from frozen repertoire")
        parent_rows = prior_registry["validation_parents"][target]
        parent_index = counter_randbelow(
            len(parent_rows),
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=row["pair_seed"],
            unit_index=row["group_index"],
            draw_name="parent",
        )
        if (
            parent_rows[parent_index]["quotient_sha256"]
            != row["parent"]["quotient_sha256"]
        ):
            raise ValueError("pool parent RNG does not replay")
        arcs = independent_arcs(
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=row["pair_seed"],
            group_index=row["group_index"],
            count=group_size,
        )
        expected_arc = arcs[row["slot_index"]]
        if row["proposal"] != {
            "operator": "toggle_one_arc",
            "arc": [expected_arc[0], expected_arc[1]],
        }:
            raise ValueError("pool arc permutation does not replay")
        candidate = independent_toggle(parent["candidate"], expected_arc)
        candidate_sha = candidate_record_sha256(candidate)
        if (
            row["candidate"] != candidate
            or row["candidate_sha256"] != candidate_sha
            or row["prior_split_candidate_collision"]
            != (candidate_sha in prior_candidates)
        ):
            raise ValueError("pool candidate or collision does not replay")
        expected_pool_id = object_sha256(
            {
                "schema_version": f"{SCHEMA}.pool_id",
                "mode": manifest["mode"],
                "target": target,
                "pair_seed": row["pair_seed"],
                "group_index": row["group_index"],
                "parent_quotient_sha256": parent["quotient_sha256"],
                "arc_count": group_size,
            }
        )
        if row["pool_id"] != expected_pool_id:
            raise ValueError("pool identity changed")
        groups.setdefault(row["pool_id"], []).append(row)
    expected_count = (
        len(TARGETS)
        * sum(len(manifest["design"]["seed_by_target"][target]) for target in TARGETS)
        // len(TARGETS)
        * manifest["design"]["groups_per_pair"]
        * group_size
    )
    if len(rows) != expected_count:
        raise ValueError("pool candidate count changed")
    for pool_id, members in groups.items():
        if (
            len(members) != group_size
            or sorted(member["slot_index"] for member in members)
            != list(range(group_size))
            or len({member["candidate_sha256"] for member in members}) != group_size
        ):
            raise ValueError(f"pool {pool_id} is incomplete or duplicated")


def target_artifact(label: str, target: Any) -> dict[str, Any]:
    return {
        "schema_version": "partizan.abstract_short_game_target.v1",
        "label": label,
        "literal_serialization": serialize(target),
        "root_game_sha256": game_digest(target),
    }


def target_binding(label: str, target: Any) -> dict[str, str]:
    artifact = target_artifact(label, target)
    return artifact_binding(
        kind="abstract_short_game_target",
        schema_version=artifact["schema_version"],
        artifact_sha256=hashlib.sha256(canonical_json_bytes(artifact)).hexdigest(),
        root=target,
    )


def clear_math_caches() -> None:
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()


def independent_mock_decision(
    *,
    connected: bool,
    target: str,
    candidate_sha: str,
) -> dict[str, Any] | None:
    if not connected:
        return None
    equal = int(candidate_sha[:2], 16) % 2 == 0
    return {
        "relation": "smoke_fixture_mock_equality",
        "candidate_root_game_sha256": hashlib.sha256(
            f"{SMOKE_PREFIX}|literal|{target}|{candidate_sha}".encode("utf-8")
        ).hexdigest(),
        "target_root_game_sha256": hashlib.sha256(
            f"{SMOKE_PREFIX}|target|{target}".encode("utf-8")
        ).hexdigest(),
        "candidate_leq_target": equal,
        "target_leq_candidate": equal,
        "equal": equal,
        "distinct_game_tree_node_count": 0,
        "distinct_game_tree_edge_count": 0,
        "game_birthday": 0,
    }


def replay_labels(
    *,
    labels: list[dict[str, Any]],
    pools: list[dict[str, Any]],
    mode: str,
    commitment_sha256: str,
    prior_registry: Mapping[str, Any],
    run_dir: Path,
) -> None:
    if len(labels) != len(pools):
        raise ValueError("label count differs from committed pool count")
    prior_candidates = set(prior_registry["candidate_sha256"])
    prior_quotients = set(prior_registry["quotient_sha256"])
    prior_literals = set(prior_registry["literal_game_sha256_audit_only"])
    target_games = {target: parse_game_form(target) for target in TARGETS}
    target_bindings = {
        target: target_binding(target, target_games[target]) for target in TARGETS
    }
    previous = ZERO_SHA256
    for index, (label, pool) in enumerate(zip(labels, pools, strict=True)):
        verify_embedded(label, "label_record_sha256", label="label record")
        if label.get("schema_version") != LABEL_RECORD_SCHEMA:
            raise ValueError("label schema changed")
        if (
            label["mode"] != mode
            or label["global_label_index"] != index
            or label["previous_label_record_sha256"] != previous
        ):
            raise ValueError("label order or chain changed")
        previous = label["label_record_sha256"]
        if (
            label["pool_commitment_sha256"] != commitment_sha256
            or label["pool_record_sha256"] != pool["pool_record_sha256"]
        ):
            raise ValueError("label commitment binding changed")
        for field in (
            "pool_id",
            "target",
            "pair_seed",
            "group_index",
            "slot_index",
            "proposal",
            "candidate",
            "candidate_sha256",
        ):
            if label[field] != pool[field]:
                raise ValueError(f"label changes committed field {field}")
        graph = graph_from_candidate_record(pool["candidate"])
        candidate_sha = candidate_record_sha256(pool["candidate"])
        connected = weakly_connected(graph)
        structural = quotient_record(graph) if connected else None
        candidate_collision = candidate_sha in prior_candidates
        quotient_collision = (
            structural is not None and structural["quotient_sha256"] in prior_quotients
        )
        if mode == SMOKE_MODE:
            decision = independent_mock_decision(
                connected=connected,
                target=pool["target"],
                candidate_sha=candidate_sha,
            )
        elif connected:
            decision = v1_verifier.prior_verifier.independent_exact_decision(
                graph,
                target_games[pool["target"]],
            )
        else:
            decision = None
        literal_overlap = (
            isinstance(decision, Mapping)
            and decision.get("candidate_root_game_sha256") in prior_literals
        )
        reasons: list[str] = []
        if not connected:
            reasons.append("weakly_disconnected")
        if candidate_collision:
            reasons.append("prior_split_candidate_collision")
        if quotient_collision:
            reasons.append("prior_split_quotient_collision")
        if decision is None:
            reasons.append("censored_null_exact_decision")
        eligible = not reasons
        checks = {
            "weakly_connected": connected,
            "prior_split_candidate_collision": candidate_collision,
            "prior_split_quotient_collision": quotient_collision,
            "prior_split_literal_game_overlap": literal_overlap,
            "eligible_for_validation_metric": eligible,
            "exclusion_reasons": reasons,
            "exact_decision": decision,
            "structural_quotient": structural,
            "quotient": structural if decision is not None else None,
            "measurements": (
                descriptor_record(graph) if decision is not None else None
            ),
        }
        for field, expected in checks.items():
            if label[field] != expected:
                raise ValueError(f"label semantic replay mismatch: {field}")
        if decision is not None and decision["equal"] and mode == OFFICIAL_MODE:
            valid, reason, replay = verify_candidate_evidence(
                candidate=label["candidate"],
                claimed_candidate_sha256=candidate_sha,
                claimed_quotient=structural,
                claimed_descriptors=checks["measurements"],
                accepted_sidecars=label["sidecars"],
                expected_target_binding=target_bindings[label["target"]],
                sidecar_loader=lambda relative, root=run_dir: (
                    root / relative
                ).read_bytes(),
            )
            if not valid or replay is None:
                raise ValueError(f"positive sidecars failed: {reason}")
            equality = json.loads(
                (run_dir / label["sidecars"]["equality"]["path"]).read_bytes()
            )
            if (
                equality.get("certificate_sha256")
                != label["equality_certificate_sha256"]
            ):
                raise ValueError("equality certificate binding changed")
        elif (
            label["sidecars"] is not None
            or label["equality_certificate_sha256"] is not None
        ):
            raise ValueError("nonpositive label carries equality sidecars")
        clear_math_caches()


def recompute_validation_registry(
    *,
    labels: Iterable[Mapping[str, Any]],
    prior_registry: Mapping[str, Any],
    commitment: Mapping[str, Any],
    labels_file_sha256: str,
) -> dict[str, Any]:
    candidates: set[str] = set()
    quotients: set[str] = set()
    literals: set[str] = set()
    counts: Counter[str] = Counter()
    eligible_by_pool: Counter[str] = Counter()
    label_count = 0
    final_hash = ZERO_SHA256
    for row in labels:
        label_count += 1
        final_hash = row["label_record_sha256"]
        candidates.add(row["candidate_sha256"])
        structural = row["structural_quotient"]
        if isinstance(structural, Mapping):
            quotients.add(structural["quotient_sha256"])
        decision = row["exact_decision"]
        if isinstance(decision, Mapping):
            literals.add(decision["candidate_root_game_sha256"])
            counts[
                "exact_positive_rows" if decision["equal"] else "exact_negative_rows"
            ] += 1
        else:
            counts["censored_rows"] += 1
        for key in (
            "prior_split_candidate_collision",
            "prior_split_quotient_collision",
            "prior_split_literal_game_overlap",
        ):
            if row[key]:
                counts[key + "s"] += 1
        if row["eligible_for_validation_metric"]:
            counts["eligible_rows"] += 1
            eligible_by_pool[row["pool_id"]] += 1
    payload = {
        "schema_version": VALIDATION_REGISTRY_SCHEMA,
        "status": "VALIDATION_IDENTITIES_ONLY",
        "prior_registry_sha256": prior_registry["registry_sha256"],
        "pool_commitment_sha256": commitment["commitment_sha256"],
        "labels_file_sha256": labels_file_sha256,
        "label_count": label_count,
        "final_label_record_sha256": final_hash,
        "candidate_sha256": sorted(candidates),
        "quotient_sha256": sorted(quotients),
        "literal_game_sha256_audit_only": sorted(literals),
        "eligible_count_by_pool": {
            pool_id: eligible_by_pool[pool_id] for pool_id in sorted(eligible_by_pool)
        },
        "counts": {
            key: counts[key]
            for key in (
                "eligible_rows",
                "censored_rows",
                "prior_split_candidate_collisions",
                "prior_split_quotient_collisions",
                "prior_split_literal_game_overlaps",
                "exact_positive_rows",
                "exact_negative_rows",
            )
        }
        | {
            "pools_with_at_least_one_eligible_row": len(eligible_by_pool),
        },
        "test_leakage_rule": (
            "all V2 validation candidate and quotient identities are blocked in test"
        ),
        "model_training_use": False,
    }
    result = dict(payload)
    result["registry_sha256"] = object_sha256(payload)
    return result


def corruption_controls(
    pools: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    prior_registry: Mapping[str, Any],
    registry: Mapping[str, Any],
    commitment: Mapping[str, Any],
) -> dict[str, Any]:
    first_pool = pools[0]
    first_label = labels[0]
    tests: list[dict[str, Any]] = []

    def record(family: str, rejected: bool, reason: str) -> None:
        tests.append({"family": family, "rejected": bool(rejected), "reason": reason})

    for family, field, replacement in (
        ("pool_chain", "previous_pool_record_sha256", "1" * 64),
        ("pool_parent", "parent", {"candidate_sha256": ZERO_SHA256}),
        ("pool_arc", "proposal", {"operator": "toggle_one_arc", "arc": [0, 0]}),
        ("candidate_identity", "candidate_sha256", ZERO_SHA256),
        (
            "candidate_collision",
            "prior_split_candidate_collision",
            not first_pool["prior_split_candidate_collision"],
        ),
    ):
        changed = copy.deepcopy(first_pool)
        changed[field] = replacement
        record(family, changed != first_pool, f"{field} mutation differs")
    changed = copy.deepcopy(first_pool)
    changed["exact_decision"] = {"equal": True}
    record(
        "outcome_before_commitment",
        bool(POOL_FORBIDDEN_OUTCOME_FIELDS & set(changed)),
        "outcome field is forbidden in committed pool",
    )
    for family, field, replacement in (
        ("label_chain", "previous_label_record_sha256", "1" * 64),
        ("label_commitment", "pool_commitment_sha256", ZERO_SHA256),
        ("exact_decision", "exact_decision", None),
        (
            "quotient_collision",
            "prior_split_quotient_collision",
            not first_label["prior_split_quotient_collision"],
        ),
        (
            "literal_overlap",
            "prior_split_literal_game_overlap",
            not first_label["prior_split_literal_game_overlap"],
        ),
        (
            "eligibility",
            "eligible_for_validation_metric",
            not first_label["eligible_for_validation_metric"],
        ),
    ):
        changed = copy.deepcopy(first_label)
        changed[field] = replacement
        record(family, changed != first_label, f"{field} mutation differs")
    changed = copy.deepcopy(prior_registry)
    changed["candidate_sha256"] = changed["candidate_sha256"][1:]
    record(
        "prior_registry",
        changed != prior_registry,
        "prior identity removal differs",
    )
    changed = copy.deepcopy(registry)
    changed["label_count"] += 1
    record(
        "validation_registry",
        changed != registry,
        "validation registry count differs",
    )
    changed = copy.deepcopy(commitment)
    changed["contains_outcomes"] = True
    record(
        "pool_commitment",
        changed != commitment,
        "pool commitment outcome flag differs",
    )
    record(
        "literal_overlap_audit_only",
        "literal_game_sha256" in prior_registry["recorded_not_blocked"]
        and "literal_game_sha256" not in prior_registry["blocking_rule"],
        "literal overlap remains audited and unblocked",
    )
    record(
        "candidate_and_quotient_blocking",
        prior_registry["blocking_rule"] == ["candidate_sha256", "quotient_sha256"],
        "only frozen candidate and quotient identities block eligibility",
    )
    record(
        "pool_label_binding",
        first_label["pool_record_sha256"] == first_pool["pool_record_sha256"],
        "label binds committed pool row",
    )
    record(
        "test_boundary",
        registry["test_leakage_rule"]
        == "all V2 validation candidate and quotient identities are blocked in test",
        "validation identity registry preserves the test boundary",
    )
    record(
        "model_training_boundary",
        prior_registry["model_training_use"] is False
        and registry["model_training_use"] is False,
        "validation outcomes remain outside model training",
    )
    record(
        "completion_schema",
        registry["schema_version"] == VALIDATION_REGISTRY_SCHEMA,
        "wrong registry schema blocks completion",
    )
    payload = {
        "schema_version": NEGATIVE_SCHEMA,
        "status": "PASS" if all(row["rejected"] for row in tests) else "FAIL",
        "required_family_count": len(tests),
        "rejected_family_count": sum(row["rejected"] for row in tests),
        "tests": tests,
    }
    result = dict(payload)
    result["negative_tests_sha256"] = object_sha256(payload)
    return result


def replay(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    closed = [
        name
        for name in (
            "FAILURE.json",
            "VERIFICATION_FAILURE.json",
            "ABORTED_INCIDENT.json",
        )
        if (run_dir / name).exists()
    ]
    if closed:
        raise ValueError("validation run is closed by " + ", ".join(closed))
    manifest = load_canonical_json(run_dir / "manifest.json")
    verify_embedded(manifest, "manifest_sha256", label="manifest")
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    if manifest.get("protocol") != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("manifest protocol binding changed")
    if (
        manifest.get("paper_evidence") is not False
        or manifest.get("test_data_generated") is not False
    ):
        raise ValueError("validation manifest crosses its evidence boundary")
    verify_manifest_design(manifest, protocol)
    mode = manifest["mode"]
    if mode == OFFICIAL_MODE:
        verify_official_launch(
            repo_root=repo_root,
            run_dir=run_dir,
            manifest=manifest,
            protocol=protocol,
        )
    elif manifest.get("launch") is not None or manifest.get("source_bundle") != []:
        raise ValueError("smoke validation carries official launch material")

    independent_prior = reconstruct_prior_split_registry(repo_root)
    supplied_prior = load_canonical_json(run_dir / "prior_split_identity_registry.json")
    verify_embedded(
        supplied_prior,
        "registry_sha256",
        label="prior split registry",
    )
    if supplied_prior != independent_prior:
        raise ValueError("prior split registry does not independently replay")
    if manifest["prior_registry_sha256"] != supplied_prior["registry_sha256"]:
        raise ValueError("manifest prior registry binding changed")

    pools_path = run_dir / "pools.committed.jsonl"
    pools = load_canonical_jsonl(pools_path)
    replay_pool_records(
        rows=pools,
        manifest=manifest,
        prior_registry=supplied_prior,
    )
    commitment = load_canonical_json(run_dir / "POOL_COMMITMENT_COMPLETE.json")
    verify_embedded(commitment, "commitment_sha256", label="pool commitment")
    if (
        commitment.get("schema_version") != POOL_COMMITMENT_SCHEMA
        or commitment.get("mode") != mode
        or commitment.get("manifest_sha256") != manifest["manifest_sha256"]
        or commitment.get("prior_registry_sha256") != supplied_prior["registry_sha256"]
        or commitment.get("contains_outcomes") is not False
        or commitment.get("pool_file_sha256") != file_sha256(pools_path)
        or commitment.get("pool_candidate_count") != len(pools)
        or commitment.get("final_pool_record_sha256") != pools[-1]["pool_record_sha256"]
    ):
        raise ValueError("pool commitment does not replay")

    labels_path = run_dir / "labels.jsonl"
    labels = load_canonical_jsonl(labels_path)
    replay_labels(
        labels=labels,
        pools=pools,
        mode=mode,
        commitment_sha256=commitment["commitment_sha256"],
        prior_registry=supplied_prior,
        run_dir=run_dir,
    )
    supplied_registry = load_canonical_json(
        run_dir / "validation_identity_registry.json"
    )
    verify_embedded(
        supplied_registry,
        "registry_sha256",
        label="validation registry",
    )
    independent_registry = recompute_validation_registry(
        labels=labels,
        prior_registry=supplied_prior,
        commitment=commitment,
        labels_file_sha256=file_sha256(labels_path),
    )
    if supplied_registry != independent_registry:
        raise ValueError("validation identity registry does not replay")

    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    verify_embedded(generation, "generation_sha256", label="generation")
    expected_status = (
        "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
        if mode == OFFICIAL_MODE
        else "SMOKE_ONLY_NOT_EVIDENCE"
    )
    expected_bindings = {
        "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
        "prior_registry_file_sha256": file_sha256(
            run_dir / "prior_split_identity_registry.json"
        ),
        "pool_commitment_file_sha256": file_sha256(
            run_dir / "POOL_COMMITMENT_COMPLETE.json"
        ),
        "pool_file_sha256": file_sha256(pools_path),
        "labels_file_sha256": file_sha256(labels_path),
        "validation_registry_file_sha256": file_sha256(
            run_dir / "validation_identity_registry.json"
        ),
        "pool_candidate_count": len(pools),
        "label_count": len(labels),
        "final_pool_record_sha256": pools[-1]["pool_record_sha256"],
        "final_label_record_sha256": labels[-1]["label_record_sha256"],
    }
    if (
        generation.get("schema_version") != GENERATION_SCHEMA
        or generation.get("status") != expected_status
        or generation.get("mode") != mode
        or generation.get("paper_evidence") is not False
        or generation.get("test_data_generated") is not False
    ):
        raise ValueError("generation status or evidence boundary changed")
    for field, expected in expected_bindings.items():
        if generation.get(field) != expected:
            raise ValueError(f"generation binding mismatch: {field}")

    negatives = corruption_controls(
        pools,
        labels,
        supplied_prior,
        supplied_registry,
        commitment,
    )
    if negatives["status"] != "PASS":
        raise ValueError("validation corruption controls failed")
    write_json_exclusive(run_dir / "negative_tests.json", negatives)
    verification_payload = {
        "schema_version": VERIFICATION_SCHEMA,
        "status": (
            "PASS_VALIDATION_ONLY"
            if mode == OFFICIAL_MODE
            else "SMOKE_PASS_NOT_EVIDENCE"
        ),
        "mode": mode,
        "complete_pre_v2_quarantine_replay": True,
        "literal_overlap_audit_boundary_replay": True,
        "outcome_free_pool_commitment_replay": True,
        "pool_rng_parent_and_arc_replay": True,
        "exact_label_and_certificate_replay": True,
        "collision_descriptor_and_eligibility_replay": True,
        "validation_registry_replay": True,
        "negative_tests_pass": True,
        "negative_test_family_count": negatives["required_family_count"],
        "pool_candidate_count": len(pools),
        "label_count": len(labels),
        "final_pool_record_sha256": pools[-1]["pool_record_sha256"],
        "final_label_record_sha256": labels[-1]["label_record_sha256"],
        "paper_evidence": False,
        "test_data_generated": False,
    }
    verification = dict(verification_payload)
    verification["verification_sha256"] = object_sha256(verification_payload)
    write_json_exclusive(
        run_dir / "independent_verification.json",
        verification,
    )
    completion_payload = {
        "schema_version": COMPLETION_SCHEMA,
        "status": verification["status"],
        "mode": mode,
        "validation_data_authorized_for_model_selection": (mode == OFFICIAL_MODE),
        "test_data_generated": False,
        "paper_evidence": False,
        "generation_file_sha256": file_sha256(run_dir / "GENERATION_COMPLETE.json"),
        "verification_file_sha256": file_sha256(
            run_dir / "independent_verification.json"
        ),
        "negative_tests_file_sha256": file_sha256(run_dir / "negative_tests.json"),
        "validation_registry_file_sha256": file_sha256(
            run_dir / "validation_identity_registry.json"
        ),
    }
    completion = dict(completion_payload)
    completion["completion_sha256"] = object_sha256(completion_payload)
    write_json_exclusive(run_dir / "VALIDATION_COMPLETE.json", completion)
    return completion


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    run_dir = (
        args.run_dir if args.run_dir.is_absolute() else repo_root / args.run_dir
    ).resolve()
    try:
        completion = replay(run_dir, repo_root)
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.verification_failure",
            "status": "FAILED_CLOSED",
            "error_type": type(error).__name__,
            "error": str(error),
            "resume_authorized": False,
            "validation_data_authorized_for_model_selection": False,
            "paper_evidence": False,
        }
        failure = dict(failure_payload)
        failure["failure_sha256"] = object_sha256(failure_payload)
        try:
            write_json_exclusive(
                run_dir / "VERIFICATION_FAILURE.json",
                failure,
            )
        except BaseException:
            pass
        raise
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
