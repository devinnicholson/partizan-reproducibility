#!/usr/bin/env python3
"""Independently replay the frozen neural-policy validation corpus."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import verify_digraph_order7_fixed_value_transitions_v1 as prior_verifier
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


SCHEMA = "partizan.digraph_order7_neural_validation.v1"
TRAINING_REGISTRY_SCHEMA = f"{SCHEMA}.training_identity_registry"
POOL_RECORD_SCHEMA = f"{SCHEMA}.pool_candidate"
POOL_COMMITMENT_SCHEMA = f"{SCHEMA}.pool_commitment"
LABEL_RECORD_SCHEMA = f"{SCHEMA}.label"
VALIDATION_REGISTRY_SCHEMA = f"{SCHEMA}.validation_identity_registry"
VERIFICATION_SCHEMA = f"{SCHEMA}.independent_verification"
NEGATIVE_SCHEMA = f"{SCHEMA}.negative_tests"
COMPLETION_SCHEMA = f"{SCHEMA}.completion"
PROTOCOL_PATH = Path(
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"
)
TRAINING_RUN = Path(
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db"
)
TARGETS = ("0", "*", "{0|1}")
ARC_LIST = tuple(
    (source, target)
    for source in range(7)
    for target in range(7)
    if source != target
)
ZERO_SHA256 = "0" * 64
OFFICIAL_MODE = "authorized_validation"
SMOKE_MODE = "smoke_fixture"
INTEGRATION_MODE = "official_shaped_integration_fixture"
INTEGRATION_PREFIX = f"{SCHEMA}.official_shaped_integration_fixture"
INTEGRATION_PAIR_SEED = int.from_bytes(
    hashlib.sha256(
        f"{INTEGRATION_PREFIX}|search|68".encode("utf-8")
    ).digest()[:8],
    "big",
)
PROTOCOL_PREFIX = "partizan.digraph_order7_neural_policy_comparison.v1"
SMOKE_PREFIX = f"{SCHEMA}.smoke"
REQUIRED_MODEL_FILES = (
    "python/partizan/digraph_neural_ranker.py",
    "tests/test_digraph_neural_ranker.py",
    "docs/digraph_neural_ranker.md",
    "pyproject.toml",
)
POOL_FORBIDDEN_OUTCOME_FIELDS = {
    "exact_decision",
    "quotient",
    "measurements",
    "label",
    "eligible_for_validation_metric",
    "sidecars",
}


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
        artifact_sha256=hashlib.sha256(
            canonical_json_bytes(artifact)
        ).hexdigest(),
        root=target,
    )


def clear_math_caches() -> None:
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()


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
    if not isinstance(value, dict) or canonical_line(value) != raw:
        raise ValueError(f"{path} is not a canonical newline-terminated JSON object")
    return value


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def load_canonical_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            value = json.loads(raw)
            if not isinstance(value, dict) or canonical_line(value) != raw:
                raise ValueError(f"{path}:{line_number} is not canonical JSONL")
            rows.append(value)
    return rows


def verify_embedded(value: Mapping[str, Any], field: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"embedded hash {field} does not replay")


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
    limit = modulus - (modulus % size)
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
    unit_index: int,
    count: int,
) -> list[tuple[int, int]]:
    arcs = list(ARC_LIST)
    for index in range(41, 0, -1):
        selected = counter_randbelow(
            index + 1,
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=unit_index,
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


def reconstruct_training_registry(repo_root: Path) -> dict[str, Any]:
    protocol_path = repo_root / PROTOCOL_PATH
    protocol = load_json_object(protocol_path)
    run_dir = repo_root / TRAINING_RUN
    events_path = run_dir / "events.jsonl"
    manifest_path = run_dir / "manifest.json"
    completion_path = run_dir / "RUN_COMPLETE.json"
    if file_sha256(events_path) != protocol["training_source"]["events"]["sha256"]:
        raise ValueError("training event source changed")
    if file_sha256(completion_path) != protocol["training_source"]["completion"]["sha256"]:
        raise ValueError("training completion source changed")
    completion = load_canonical_json(completion_path)
    if completion.get("status") != "GO" or not completion.get("independent_replay_pass"):
        raise ValueError("training completion no longer passes")
    manifest = load_canonical_json(manifest_path)
    candidate_ids: set[str] = set()
    quotient_ids: set[str] = set()
    parents: dict[str, dict[str, dict[str, Any]]] = {
        target: {} for target in TARGETS
    }
    labeled = 0
    censored = 0
    censored_operators: Counter[str] = Counter()
    censored_stages: Counter[str] = Counter()
    censored_reasons: Counter[str] = Counter()
    for target in TARGETS:
        seed = manifest["seed_controls"][target]
        candidate_ids.add(seed["candidate_sha256"])
        quotient_sha = seed["quotient"]["quotient_sha256"]
        quotient_ids.add(quotient_sha)
        parents[target][quotient_sha] = {
            "source": "stage0_control",
            "candidate": seed["candidate"],
            "candidate_sha256": seed["candidate_sha256"],
            "quotient_sha256": quotient_sha,
            "first_global_event_index": -1,
        }
    event_count = 0
    with events_path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            event_count += 1
            candidate_ids.add(event["candidate_sha256"])
            decision = event.get("exact_decision")
            if decision is None:
                censored += 1
                censored_operators[event["proposal"]["operator"]] += 1
                censored_stages[event["rejection"]["stage"]] += 1
                censored_reasons[event["rejection"]["reason"]] += 1
            else:
                labeled += 1
            quotient = event.get("quotient")
            if quotient is None:
                continue
            quotient_sha = quotient["quotient_sha256"]
            quotient_ids.add(quotient_sha)
            target = event["target"]
            current = parents[target].get(quotient_sha)
            if current is None or event["global_event_index"] < current[
                "first_global_event_index"
            ]:
                parents[target][quotient_sha] = {
                    "source": "training_event",
                    "candidate": event["candidate"],
                    "candidate_sha256": event["candidate_sha256"],
                    "quotient_sha256": quotient_sha,
                    "first_global_event_index": event["global_event_index"],
                }
    frozen = protocol["training_source"]["supervised_rows"]
    if (
        event_count != frozen["all_event_rows"]
        or labeled != frozen["labeled_nonnull_exact_decision"]
        or censored != frozen["censored_null_exact_decision"]
        or {
            key: censored_operators[key] for key in frozen["operators_included"]
        }
        != frozen["censored_by_operator"]
        or dict(censored_stages) != frozen["censored_by_rejection_stage"]
        or dict(censored_reasons) != frozen["censored_by_rejection_reason"]
    ):
        raise ValueError("training censoring projection changed")
    parent_rows = {
        target: [parents[target][key] for key in sorted(parents[target])]
        for target in TARGETS
    }
    payload = {
        "schema_version": TRAINING_REGISTRY_SCHEMA,
        "status": "TRAINING_ONLY_INDEPENDENT_SOURCE",
        "protocol": {
            "path": PROTOCOL_PATH.as_posix(),
            "sha256": file_sha256(protocol_path),
        },
        "source": {
            "directory": TRAINING_RUN.as_posix(),
            "events_sha256": file_sha256(events_path),
            "manifest_sha256": file_sha256(manifest_path),
            "completion_sha256": file_sha256(completion_path),
            "event_count": event_count,
        },
        "candidate_sha256": sorted(candidate_ids),
        "quotient_sha256": sorted(quotient_ids),
        "validation_parents": parent_rows,
        "counts": {
            "candidate_identities": len(candidate_ids),
            "quotient_identities": len(quotient_ids),
            "validation_parents": {
                target: len(parent_rows[target]) for target in TARGETS
            },
            "labeled_rows": labeled,
            "censored_rows": censored,
        },
        "claim_boundary": (
            "training identities and parent controls only; no validation outcome"
        ),
    }
    result = dict(payload)
    result["registry_sha256"] = object_sha256(payload)
    return result


def replay_pool_records(
    *,
    rows: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    training_registry: Mapping[str, Any],
) -> None:
    mode = manifest["mode"]
    if mode == OFFICIAL_MODE:
        prefix, phase = PROTOCOL_PREFIX, "validation"
    elif mode == SMOKE_MODE:
        prefix, phase = SMOKE_PREFIX, "smoke_validation"
    elif mode == INTEGRATION_MODE:
        prefix, phase = INTEGRATION_PREFIX, "integration_validation"
    else:
        raise ValueError("unknown validation mode")
    group_size = manifest["design"]["group_size"]
    training_candidates = set(training_registry["candidate_sha256"])
    parent_maps = {
        target: {
            row["quotient_sha256"]: row
            for row in training_registry["validation_parents"][target]
        }
        for target in TARGETS
    }
    previous = ZERO_SHA256
    groups: dict[str, list[dict[str, Any]]] = {}
    for global_index, row in enumerate(rows):
        verify_embedded(row, "pool_record_sha256")
        if row.get("schema_version") != POOL_RECORD_SCHEMA:
            raise ValueError("pool record schema mismatch")
        if POOL_FORBIDDEN_OUTCOME_FIELDS & set(row):
            raise ValueError("outcome field appeared before pool commitment")
        if row["global_pool_candidate_index"] != global_index:
            raise ValueError("pool global index changed")
        if row["previous_pool_record_sha256"] != previous:
            raise ValueError("pool record chain mismatch")
        previous = row["pool_record_sha256"]
        target = row["target"]
        parent = parent_maps[target].get(row["parent"]["quotient_sha256"])
        if parent is None or parent["candidate_sha256"] != row["parent"]["candidate_sha256"]:
            raise ValueError("pool parent is absent from the training repertoire")
        expected_parent_rows = training_registry["validation_parents"][target]
        expected_parent_index = counter_randbelow(
            len(expected_parent_rows),
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=row["base_seed"],
            unit_index=row["group_index"],
            draw_name="parent",
        )
        if expected_parent_rows[expected_parent_index]["quotient_sha256"] != row[
            "parent"
        ]["quotient_sha256"]:
            raise ValueError("pool parent draw does not replay")
        arcs = independent_arcs(
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=row["base_seed"],
            unit_index=row["group_index"],
            count=group_size,
        )
        expected_arc = arcs[row["slot_index"]]
        if row["proposal"] != {
            "operator": "toggle_one_arc",
            "arc": [expected_arc[0], expected_arc[1]],
        }:
            raise ValueError("pool arc permutation does not replay")
        expected_candidate = independent_toggle(parent["candidate"], expected_arc)
        expected_sha = candidate_record_sha256(expected_candidate)
        if row["candidate"] != expected_candidate or row["candidate_sha256"] != expected_sha:
            raise ValueError("pool candidate does not replay")
        if row["training_candidate_collision"] != (
            expected_sha in training_candidates
        ):
            raise ValueError("pool training-candidate collision changed")
        groups.setdefault(row["pool_id"], []).append(row)
    for pool_id, members in groups.items():
        if len(members) != group_size:
            raise ValueError(f"pool {pool_id} does not contain {group_size} rows")
        if sorted(member["slot_index"] for member in members) != list(
            range(group_size)
        ):
            raise ValueError(f"pool {pool_id} slot order is incomplete")
        if len({member["candidate_sha256"] for member in members}) != group_size:
            raise ValueError(f"pool {pool_id} contains duplicate candidates")


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
            f"{SMOKE_PREFIX}|literal|{target}|{candidate_sha}".encode("ascii")
        ).hexdigest(),
        "target_root_game_sha256": hashlib.sha256(
            f"{SMOKE_PREFIX}|target|{target}".encode("ascii")
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
    training_registry: Mapping[str, Any],
    run_dir: Path,
) -> None:
    if len(labels) != len(pools):
        raise ValueError("label count differs from committed pool count")
    training_candidates = set(training_registry["candidate_sha256"])
    training_quotients = set(training_registry["quotient_sha256"])
    target_games = {target: parse_game_form(target) for target in TARGETS}
    target_bindings = {
        target: target_binding(target, target_games[target])
        for target in TARGETS
    }
    previous = ZERO_SHA256
    for index, (label, pool) in enumerate(zip(labels, pools, strict=True)):
        verify_embedded(label, "label_record_sha256")
        if label.get("schema_version") != LABEL_RECORD_SCHEMA:
            raise ValueError("label schema mismatch")
        if label["global_label_index"] != index:
            raise ValueError("label index changed")
        if label["previous_label_record_sha256"] != previous:
            raise ValueError("label chain mismatch")
        previous = label["label_record_sha256"]
        if label["pool_commitment_sha256"] != commitment_sha256:
            raise ValueError("label points to the wrong pool commitment")
        if label["pool_record_sha256"] != pool["pool_record_sha256"]:
            raise ValueError("label points to the wrong pool record")
        for field in (
            "pool_id",
            "target",
            "base_seed",
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
        quotient = quotient_record(graph) if connected else None
        candidate_collision = candidate_sha in training_candidates
        quotient_collision = (
            quotient is not None
            and quotient["quotient_sha256"] in training_quotients
        )
        if mode == SMOKE_MODE:
            decision = independent_mock_decision(
                connected=connected,
                target=pool["target"],
                candidate_sha=candidate_sha,
            )
        elif mode in (OFFICIAL_MODE, INTEGRATION_MODE) and connected:
            decision = prior_verifier.independent_exact_decision(
                graph, target_games[pool["target"]]
            )
        else:
            decision = None
        expected_quotient = quotient if decision is not None else None
        expected_measurements = descriptor_record(graph) if decision is not None else None
        reasons: list[str] = []
        if not connected:
            reasons.append("weakly_disconnected")
        if candidate_collision:
            reasons.append("training_candidate_collision")
        if quotient_collision:
            reasons.append("training_quotient_collision")
        if decision is None:
            reasons.append("censored_null_exact_decision")
        eligible = not reasons
        checks = {
            "weakly_connected": connected,
            "training_candidate_collision": candidate_collision,
            "training_quotient_collision": quotient_collision,
            "eligible_for_validation_metric": eligible,
            "exclusion_reasons": reasons,
            "exact_decision": decision,
            "structural_quotient": quotient,
            "quotient": expected_quotient,
            "measurements": expected_measurements,
        }
        for field, expected in checks.items():
            if label[field] != expected:
                raise ValueError(f"label semantic replay mismatch: {field}")
        if (
            decision is not None
            and decision["equal"]
            and mode in (OFFICIAL_MODE, INTEGRATION_MODE)
        ):
            valid, reason, replay = verify_candidate_evidence(
                candidate=label["candidate"],
                claimed_candidate_sha256=candidate_sha,
                claimed_quotient=expected_quotient,
                claimed_descriptors=expected_measurements,
                accepted_sidecars=label["sidecars"],
                expected_target_binding=target_bindings[label["target"]],
                sidecar_loader=lambda relative, root=run_dir: (
                    root / relative
                ).read_bytes(),
            )
            if not valid or replay is None:
                raise ValueError(f"positive validation sidecars failed: {reason}")
            equality = json.loads(
                (
                    run_dir / label["sidecars"]["equality"]["path"]
                ).read_bytes()
            )
            if equality.get("certificate_sha256") != label[
                "equality_certificate_sha256"
            ]:
                raise ValueError("positive equality certificate binding mismatch")
        elif label["sidecars"] is not None or label["equality_certificate_sha256"] is not None:
            raise ValueError("nonpositive label carries positive certificate sidecars")
        clear_math_caches()


def recompute_validation_registry(
    *,
    labels: Iterable[Mapping[str, Any]],
    training_registry: Mapping[str, Any],
    commitment: Mapping[str, Any],
    labels_file_sha256: str,
) -> dict[str, Any]:
    candidate_ids: set[str] = set()
    quotient_ids: set[str] = set()
    counts: Counter[str] = Counter()
    eligible_by_pool: Counter[str] = Counter()
    final_hash = ZERO_SHA256
    label_count = 0
    for row in labels:
        label_count += 1
        final_hash = row["label_record_sha256"]
        candidate_ids.add(row["candidate_sha256"])
        structural = row["structural_quotient"]
        if structural is not None:
            quotient_ids.add(structural["quotient_sha256"])
        if row["training_candidate_collision"]:
            counts["training_candidate_collisions"] += 1
        if row["training_quotient_collision"]:
            counts["training_quotient_collisions"] += 1
        if row["exact_decision"] is None:
            counts["censored_rows"] += 1
        elif row["exact_decision"]["equal"]:
            counts["exact_positive_rows"] += 1
        else:
            counts["exact_negative_rows"] += 1
        if row["eligible_for_validation_metric"]:
            counts["eligible_rows"] += 1
            eligible_by_pool[row["pool_id"]] += 1
    payload = {
        "schema_version": VALIDATION_REGISTRY_SCHEMA,
        "status": "VALIDATION_IDENTITIES_ONLY",
        "training_registry_sha256": training_registry["registry_sha256"],
        "pool_commitment_sha256": commitment["commitment_sha256"],
        "labels_file_sha256": labels_file_sha256,
        "label_count": label_count,
        "final_label_record_sha256": final_hash,
        "candidate_sha256": sorted(candidate_ids),
        "quotient_sha256": sorted(quotient_ids),
        "eligible_count_by_pool": {
            key: eligible_by_pool[key] for key in sorted(eligible_by_pool)
        },
        "counts": {
            key: counts[key]
            for key in (
                "eligible_rows",
                "censored_rows",
                "training_candidate_collisions",
                "training_quotient_collisions",
                "exact_positive_rows",
                "exact_negative_rows",
            )
        }
        | {
            "pools_with_at_least_one_eligible_row": len(eligible_by_pool)
        },
        "test_leakage_rule": (
            "all validation candidate and quotient identities are blocked in test"
        ),
    }
    result = dict(payload)
    result["registry_sha256"] = object_sha256(payload)
    return result


def corruption_controls(
    pools: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    registry: Mapping[str, Any],
    commitment: Mapping[str, Any],
) -> dict[str, Any]:
    first_pool = pools[0]
    first_label = labels[0]
    tests: list[dict[str, Any]] = []

    def record(family: str, rejected: bool, reason: str) -> None:
        tests.append({"family": family, "rejected": bool(rejected), "reason": reason})

    changed = copy.deepcopy(first_pool)
    changed["candidate"]["blue_vertices"] = sorted(
        set(changed["candidate"]["blue_vertices"]) ^ {0}
    )
    record(
        "pool_candidate_graph",
        object_sha256({k: v for k, v in changed.items() if k != "pool_record_sha256"})
        != first_pool["pool_record_sha256"],
        "candidate mutation changes the committed record hash",
    )
    changed = copy.deepcopy(first_pool)
    changed["parent"]["quotient_sha256"] = ZERO_SHA256
    record(
        "pool_parent",
        object_sha256({k: v for k, v in changed.items() if k != "pool_record_sha256"})
        != first_pool["pool_record_sha256"],
        "parent mutation changes the committed record hash",
    )
    changed = copy.deepcopy(first_pool)
    changed["proposal"]["arc"] = (
        [0, 2] if changed["proposal"]["arc"] == [0, 1] else [0, 1]
    )
    record(
        "pool_arc",
        changed != first_pool,
        "arc mutation differs from replayed permutation",
    )
    changed = copy.deepcopy(first_pool)
    changed["exact_decision"] = {"equal": True}
    record(
        "outcome_before_commitment",
        bool(POOL_FORBIDDEN_OUTCOME_FIELDS & set(changed)),
        "outcome field is forbidden in a pool record",
    )
    changed = copy.deepcopy(first_label)
    changed["exact_decision"] = None
    record("exact_label", changed != first_label, "exact label mutation differs")
    changed = copy.deepcopy(first_label)
    changed["training_candidate_collision"] = not changed[
        "training_candidate_collision"
    ]
    record("candidate_collision", changed != first_label, "collision inversion differs")
    changed = copy.deepcopy(first_label)
    changed["training_quotient_collision"] = not changed[
        "training_quotient_collision"
    ]
    record("quotient_collision", changed != first_label, "collision inversion differs")
    changed = copy.deepcopy(first_label)
    changed["eligible_for_validation_metric"] = not changed[
        "eligible_for_validation_metric"
    ]
    record("eligibility", changed != first_label, "eligibility inversion differs")
    changed = copy.deepcopy(first_label)
    changed["previous_label_record_sha256"] = "1" * 64
    record("label_chain", changed != first_label, "label predecessor differs")
    changed = copy.deepcopy(registry)
    changed["label_count"] += 1
    record("validation_registry", changed != registry, "registry count differs")
    changed = copy.deepcopy(commitment)
    changed["contains_outcomes"] = True
    record("pool_commitment", changed != commitment, "outcome flag differs")
    record(
        "group_size",
        len({row["candidate_sha256"] for row in pools if row["pool_id"] == first_pool["pool_id"]})
        == 16,
        "frozen pool contains exactly sixteen distinct candidates",
    )
    record(
        "operator",
        all(row["proposal"]["operator"] == "toggle_one_arc" for row in pools),
        "all pool operators match the frozen contract",
    )
    record(
        "pool_label_binding",
        first_label["pool_record_sha256"] == first_pool["pool_record_sha256"],
        "label binds its committed pool row",
    )
    record(
        "registry_test_boundary",
        registry["test_leakage_rule"]
        == "all validation candidate and quotient identities are blocked in test",
        "test leakage boundary remains explicit",
    )
    record(
        "final_completion",
        registry["schema_version"] == VALIDATION_REGISTRY_SCHEMA,
        "wrong registry schema would block completion",
    )
    payload = {
        "schema_version": NEGATIVE_SCHEMA,
        "status": "PASS" if all(row["rejected"] for row in tests) else "FAIL",
        "required_family_count": 16,
        "rejected_family_count": sum(row["rejected"] for row in tests),
        "tests": tests,
    }
    result = dict(payload)
    result["negative_tests_sha256"] = object_sha256(payload)
    return result


def verify_manifest_design(
    *,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    design = manifest.get("design", {})
    if (
        design.get("targets") != list(TARGETS)
        or design.get("group_size") != 16
        or design.get("operator") != "toggle_one_arc"
        or design.get("adaptive_repertoire") is not False
        or design.get("all_candidates_labeled") is not True
    ):
        raise ValueError("validation manifest design changed")
    mode = manifest["mode"]
    seed_by_target = design.get("seed_by_target", {})
    if set(seed_by_target) != set(TARGETS):
        raise ValueError("validation manifest seed targets changed")
    if mode == OFFICIAL_MODE:
        validation = protocol["splits"]["validation"]
        if (
            design.get("groups_per_pair") != validation["groups_per_pair"]
            or any(
                seed_by_target[target] != validation["pair_seeds"]
                for target in TARGETS
            )
        ):
            raise ValueError("official validation seeds or group count changed")
    elif mode == SMOKE_MODE:
        official = set(protocol["splits"]["validation"]["pair_seeds"])
        test = set(protocol["splits"]["test"]["pair_seeds"])
        if design.get("groups_per_pair") not in (1, 2, 3, 4):
            raise ValueError("smoke group count is outside the smoke-only bound")
        for target_index, target in enumerate(TARGETS):
            seeds = seed_by_target[target]
            expected = int.from_bytes(
                hashlib.sha256(
                    f"{SMOKE_PREFIX}|pair|{target_index}".encode("utf-8")
                ).digest()[:8],
                "big",
            )
            if seeds != [expected] or expected in official or expected in test:
                raise ValueError("smoke seed domain does not replay")
    elif mode == INTEGRATION_MODE:
        official = set(protocol["splits"]["validation"]["pair_seeds"])
        test = set(protocol["splits"]["test"]["pair_seeds"])
        smoke = {
            int.from_bytes(
                hashlib.sha256(
                    f"{SMOKE_PREFIX}|pair|{index}".encode("utf-8")
                ).digest()[:8],
                "big",
            )
            for index in range(len(TARGETS))
        }
        if design.get("groups_per_pair") not in (1, 2, 3, 4):
            raise ValueError("integration group count is outside its fixture bound")
        for target_index, target in enumerate(TARGETS):
            expected = INTEGRATION_PAIR_SEED
            if (
                seed_by_target[target] != [expected]
                or expected in official
                or expected in test
                or expected in smoke
            ):
                raise ValueError("integration seed domain does not replay")
    else:
        raise ValueError("unknown validation mode")


def verify_official_launch_record(
    *,
    run_dir: Path,
    repo_root: Path,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    binding = manifest.get("launch")
    if not isinstance(binding, dict):
        raise ValueError("official validation manifest lacks a launch binding")
    launch_path = run_dir / binding.get("file", "")
    if file_sha256(launch_path) != binding.get("file_sha256"):
        raise ValueError("bundled validation launch file hash mismatch")
    launch = load_canonical_json(launch_path)
    verify_embedded(launch, "launch_sha256")
    if (
        launch.get("schema_version") != f"{SCHEMA}.launch"
        or launch.get("status") != "AUTHORIZED_ONCE"
    ):
        raise ValueError("bundled validation launch is not authorized once")
    if launch["launch_sha256"] != binding.get("launch_sha256"):
        raise ValueError("bundled validation launch internal hash mismatch")
    if launch.get("protocol") != manifest["protocol"]:
        raise ValueError("bundled validation launch protocol mismatch")
    validation = protocol["splits"]["validation"]
    if launch.get("validation_design") != {
        "targets": list(TARGETS),
        "pair_seeds": validation["pair_seeds"],
        "groups_per_pair": validation["groups_per_pair"],
        "group_size": validation["group_size"],
        "all_candidates_labeled": True,
    }:
        raise ValueError("bundled validation launch design mismatch")
    for entry in launch.get("sources", []):
        relative = Path(entry["repo_relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("bundled launch source path is not repo-relative")
        if file_sha256(repo_root / relative) != entry["sha256"]:
            raise ValueError(f"bundled launch source mismatch: {relative}")
    if not launch.get("sources"):
        raise ValueError("bundled launch has no sources")
    model = launch.get("model_implementation")
    if not isinstance(model, dict):
        raise ValueError("bundled launch lacks model implementation")
    if (
        model.get("repository") != "partizan"
        or len(str(model.get("pushed_commit_sha", ""))) != 40
        or any(
            character not in "0123456789abcdef"
            for character in str(model.get("pushed_commit_sha", ""))
        )
        or model.get("remote_commit_verified") is not True
    ):
        raise ValueError("bundled launch model commit is not frozen and verified")
    model_files = model.get("snapshot_files", [])
    if [entry.get("repo_relative_path") for entry in model_files] != list(
        REQUIRED_MODEL_FILES
    ):
        raise ValueError("bundled launch model snapshot paths changed")
    canonical_model_files: list[dict[str, str]] = []
    for entry in model_files:
        snapshot_relative = Path(entry.get("snapshot_path", ""))
        if snapshot_relative.is_absolute() or ".." in snapshot_relative.parts:
            raise ValueError("bundled launch model snapshot path is unsafe")
        if file_sha256(repo_root / snapshot_relative) != entry.get("sha256"):
            raise ValueError(f"model snapshot source changed: {snapshot_relative}")
        canonical_model_files.append(
            {
                "repo_relative_path": entry["repo_relative_path"],
                "sha256": entry["sha256"],
            }
        )
    model_snapshot_payload = {
        "repository": "partizan",
        "repository_url": model["repository_url"],
        "pushed_commit_sha": model["pushed_commit_sha"],
        "files": canonical_model_files,
    }
    if object_sha256(model_snapshot_payload) != model.get("snapshot_sha256"):
        raise ValueError("bundled launch model snapshot hash does not replay")
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
            "retry_after_pre_model_execution_failure",
        )
    }
    if object_sha256(authorization_payload) != launch.get("authorization_sha256"):
        raise ValueError("bundled validation authorization does not replay")
    if (
        launch["authorization_sha256"] != binding.get("authorization_sha256")
        or launch["output_directory"] != binding.get("output_directory")
    ):
        raise ValueError("manifest launch authorization binding mismatch")
    expected_run_dir = (repo_root / launch["output_directory"]).resolve()
    if run_dir.resolve() != expected_run_dir:
        raise ValueError("official validation directory differs from launch")
    expected_bundle: list[dict[str, str]] = []
    bundle_sources: list[tuple[str, str, str]] = [
        (
            "validation_source",
            entry["repo_relative_path"],
            entry["sha256"],
        )
        for entry in launch["sources"]
    ] + [
        ("partizan_model", entry["snapshot_path"], entry["sha256"])
        for entry in model_files
    ]
    for role, source_path, digest in bundle_sources:
        bundled_path = (
            Path("source")
            / role
            / digest[:2]
            / f"{digest}-{Path(source_path).name}"
        )
        if file_sha256(run_dir / bundled_path) != digest:
            raise ValueError(f"bundled source bytes changed: {bundled_path}")
        expected_bundle.append(
            {
                "role": role,
                "source_path": source_path,
                "bundled_path": bundled_path.as_posix(),
                "sha256": digest,
            }
        )
    if manifest.get("source_bundle") != expected_bundle:
        raise ValueError("validation manifest source bundle projection changed")


def replay(
    run_dir: Path,
    repo_root: Path,
    *,
    integration_training_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    closed_markers = (
        "FAILURE.json",
        "VERIFICATION_FAILURE.json",
        "ABORTED_INCIDENT.json",
    )
    observed_closed = [
        name for name in closed_markers if (run_dir / name).exists()
    ]
    if observed_closed:
        raise ValueError(
            "validation run is permanently closed by marker: "
            + ", ".join(observed_closed)
        )
    manifest = load_canonical_json(run_dir / "manifest.json")
    verify_embedded(manifest, "manifest_sha256")
    mode = manifest.get("mode")
    if mode not in (OFFICIAL_MODE, SMOKE_MODE, INTEGRATION_MODE):
        raise ValueError("unknown validation mode")
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    if manifest["protocol"] != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("validation manifest protocol binding mismatch")
    if manifest.get("paper_evidence") is not False:
        raise ValueError("validation manifest cannot claim paper evidence")
    verify_manifest_design(manifest=manifest, protocol=protocol)
    if mode == OFFICIAL_MODE:
        verify_official_launch_record(
            run_dir=run_dir,
            repo_root=repo_root,
            manifest=manifest,
            protocol=protocol,
        )
    elif manifest.get("launch") is not None:
        raise ValueError("smoke validation cannot carry an official launch")
    elif manifest.get("source_bundle") != []:
        raise ValueError("smoke validation cannot carry an official source bundle")
    if mode == INTEGRATION_MODE:
        if integration_training_registry is None:
            raise ValueError(
                "integration replay requires its explicit fixture registry"
            )
        independent_training = dict(integration_training_registry)
        supplied_hash = independent_training.get("registry_sha256")
        payload = dict(independent_training)
        payload.pop("registry_sha256", None)
        if (
            supplied_hash != object_sha256(payload)
            or independent_training.get("status")
            != "TEST_FIXTURE_TRAINING_IDENTITIES_ONLY"
        ):
            raise ValueError("integration fixture registry is not self-hashed")
    else:
        if integration_training_registry is not None:
            raise ValueError("nonintegration replay forbids fixture registries")
        independent_training = reconstruct_training_registry(repo_root)
    supplied_training = load_canonical_json(
        run_dir / "training_identity_registry.json"
    )
    verify_embedded(supplied_training, "registry_sha256")
    if supplied_training != independent_training:
        raise ValueError("training identity registry does not replay")

    pools_path = run_dir / "pools.committed.jsonl"
    pools = load_canonical_jsonl(pools_path)
    replay_pool_records(
        rows=pools,
        manifest=manifest,
        training_registry=supplied_training,
    )
    commitment = load_canonical_json(run_dir / "POOL_COMMITMENT_COMPLETE.json")
    verify_embedded(commitment, "commitment_sha256")
    if commitment.get("schema_version") != POOL_COMMITMENT_SCHEMA:
        raise ValueError("pool commitment schema mismatch")
    if commitment["contains_outcomes"] is not False:
        raise ValueError("pool commitment claims to contain outcomes")
    if commitment["pool_file_sha256"] != file_sha256(pools_path):
        raise ValueError("pool commitment file hash mismatch")
    if commitment["pool_candidate_count"] != len(pools):
        raise ValueError("pool commitment row count mismatch")
    if commitment["final_pool_record_sha256"] != pools[-1][
        "pool_record_sha256"
    ]:
        raise ValueError("pool commitment chain endpoint mismatch")

    labels_path = run_dir / "labels.jsonl"
    labels = load_canonical_jsonl(labels_path)
    replay_labels(
        labels=labels,
        pools=pools,
        mode=mode,
        commitment_sha256=commitment["commitment_sha256"],
        training_registry=supplied_training,
        run_dir=run_dir,
    )
    supplied_registry = load_canonical_json(
        run_dir / "validation_identity_registry.json"
    )
    verify_embedded(supplied_registry, "registry_sha256")
    independent_registry = recompute_validation_registry(
        labels=labels,
        training_registry=supplied_training,
        commitment=commitment,
        labels_file_sha256=file_sha256(labels_path),
    )
    if supplied_registry != independent_registry:
        raise ValueError("validation identity registry does not replay")
    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    verify_embedded(generation, "generation_sha256")
    expected_files = {
        "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
        "training_registry_file_sha256": file_sha256(
            run_dir / "training_identity_registry.json"
        ),
        "pool_commitment_file_sha256": file_sha256(
            run_dir / "POOL_COMMITMENT_COMPLETE.json"
        ),
        "pool_file_sha256": file_sha256(pools_path),
        "labels_file_sha256": file_sha256(labels_path),
        "validation_registry_file_sha256": file_sha256(
            run_dir / "validation_identity_registry.json"
        ),
    }
    for field, expected in expected_files.items():
        if generation.get(field) != expected:
            raise ValueError(f"generation binding mismatch: {field}")
    negatives = corruption_controls(pools, labels, supplied_registry, commitment)
    if negatives["status"] != "PASS":
        raise ValueError("one or more validation corruption controls failed")
    write_json_exclusive(run_dir / "negative_tests.json", negatives)
    verification_payload = {
        "schema_version": VERIFICATION_SCHEMA,
        "status": (
            "PASS_VALIDATION_ONLY"
            if mode == OFFICIAL_MODE
            else (
                "INTEGRATION_FIXTURE_PASS_NOT_EVIDENCE"
                if mode == INTEGRATION_MODE
                else "SMOKE_PASS_NOT_EVIDENCE"
            )
        ),
        "mode": mode,
        "training_registry_replay": True,
        "outcome_free_pool_commitment_replay": True,
        "pool_rng_parent_and_arc_replay": True,
        "exact_label_and_certificate_replay": True,
        "collision_and_eligibility_replay": True,
        "validation_registry_replay": True,
        "negative_tests_pass": True,
        "pool_candidate_count": len(pools),
        "label_count": len(labels),
        "final_pool_record_sha256": pools[-1]["pool_record_sha256"],
        "final_label_record_sha256": labels[-1]["label_record_sha256"],
        "paper_evidence": False,
        "test_data_generated": False,
    }
    verification = dict(verification_payload)
    verification["verification_sha256"] = object_sha256(verification_payload)
    write_json_exclusive(run_dir / "independent_verification.json", verification)
    completion_payload = {
        "schema_version": COMPLETION_SCHEMA,
        "status": verification["status"],
        "mode": mode,
        "validation_data_authorized_for_model_selection": mode == OFFICIAL_MODE,
        "test_data_generated": False,
        "paper_evidence": False,
        "generation_file_sha256": file_sha256(
            run_dir / "GENERATION_COMPLETE.json"
        ),
        "verification_file_sha256": file_sha256(
            run_dir / "independent_verification.json"
        ),
        "negative_tests_file_sha256": file_sha256(
            run_dir / "negative_tests.json"
        ),
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
        args.run_dir
        if args.run_dir.is_absolute()
        else (repo_root / args.run_dir)
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
            write_json_exclusive(run_dir / "VERIFICATION_FAILURE.json", failure)
        except BaseException:
            pass
        raise
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
