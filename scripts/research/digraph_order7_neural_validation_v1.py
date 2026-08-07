#!/usr/bin/env python3
"""Build the frozen order-7 neural-policy validation corpus.

The builder has two deliberately separate phases:

1. write and fsync every outcome-free candidate pool plus its commitment;
2. compute labels without changing pool membership or order.

The public CLI can run smoke fixtures immediately. An official validation run
requires a separate self-hashed launch record that does not exist in the
repository at the time this source was written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import digraph_order7_fixed_value_transitions_v1 as fixed_value
from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    descriptor_record,
    graph_from_candidate_record,
    quotient_record,
    weakly_connected,
)
from digraph_placement_control import DigraphPlacement, parse_game_form


SCHEMA = "partizan.digraph_order7_neural_validation.v1"
TRAINING_REGISTRY_SCHEMA = f"{SCHEMA}.training_identity_registry"
POOL_RECORD_SCHEMA = f"{SCHEMA}.pool_candidate"
POOL_COMMITMENT_SCHEMA = f"{SCHEMA}.pool_commitment"
LABEL_RECORD_SCHEMA = f"{SCHEMA}.label"
VALIDATION_REGISTRY_SCHEMA = f"{SCHEMA}.validation_identity_registry"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
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
SMOKE_PREFIX = f"{SCHEMA}.smoke"
PROTOCOL_PREFIX = "partizan.digraph_order7_neural_policy_comparison.v1"
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
REQUIRED_MODEL_FILES = (
    "python/partizan/digraph_neural_ranker.py",
    "tests/test_digraph_neural_ranker.py",
    "docs/digraph_neural_ranker.md",
    "pyproject.toml",
)


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


def write_json_exclusive(path: Path, value: Any) -> None:
    write_bytes_exclusive(path, canonical_line(value))


def write_jsonl_exclusive(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    hash_field: str,
) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    count = 0
    final_hash = ZERO_SHA256
    try:
        with os.fdopen(descriptor, "wb") as handle:
            for row in rows:
                handle.write(canonical_line(row))
                count += 1
                if hash_field not in row:
                    raise ValueError(f"JSONL row lacks required hash field {hash_field}")
                final_hash = str(row[hash_field])
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return count, final_hash


def hashed_record(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = object_sha256(payload)
    return result


def stable_digest(*parts: object) -> bytes:
    joined = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(joined).digest()


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
    """Unbiased SHA-256 counter mapping frozen by the v1 protocol."""

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


def smoke_seed(index: int) -> int:
    return int.from_bytes(
        stable_digest(SMOKE_PREFIX, "pair", index)[:8],
        "big",
    )


def toggle_arc(parent: DigraphPlacement, arc: tuple[int, int]) -> DigraphPlacement:
    source, target = arc
    edges = list(parent.edges)
    edges[source] ^= 1 << target
    return DigraphPlacement(parent.blue_mask, tuple(edges))


def training_identity_registry(repo_root: Path) -> dict[str, Any]:
    """Reconstruct the training registry without semantic reevaluation."""

    run_dir = repo_root / TRAINING_RUN
    events_path = run_dir / "events.jsonl"
    manifest_path = run_dir / "manifest.json"
    completion_path = run_dir / "RUN_COMPLETE.json"
    protocol_path = repo_root / PROTOCOL_PATH
    protocol = load_json_object(protocol_path)
    expected_events = protocol["training_source"]["events"]
    if file_sha256(events_path) != expected_events["sha256"]:
        raise ValueError("training event ledger differs from the frozen protocol")
    if file_sha256(completion_path) != protocol["training_source"]["completion"]["sha256"]:
        raise ValueError("training completion differs from the frozen protocol")
    completion = load_canonical_json(completion_path)
    if completion.get("status") != "GO" or not completion.get("independent_replay_pass"):
        raise ValueError("training source lacks an independently replayed GO")
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
        quotient_ids.add(seed["quotient"]["quotient_sha256"])
        parents[target][seed["quotient"]["quotient_sha256"]] = {
            "source": "stage0_control",
            "candidate": seed["candidate"],
            "candidate_sha256": seed["candidate_sha256"],
            "quotient_sha256": seed["quotient"]["quotient_sha256"],
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
            if not decision or not decision.get("equal"):
                raise ValueError("non-equal training row carries a quotient identity")
            target = event["target"]
            existing = parents[target].get(quotient_sha)
            if existing is None or event["global_event_index"] < existing[
                "first_global_event_index"
            ]:
                parents[target][quotient_sha] = {
                    "source": "training_event",
                    "candidate": event["candidate"],
                    "candidate_sha256": event["candidate_sha256"],
                    "quotient_sha256": quotient_sha,
                    "first_global_event_index": event["global_event_index"],
                }

    expected_rows = protocol["training_source"]["supervised_rows"]
    observed_censored_by_operator = {
        operator: censored_operators[operator]
        for operator in expected_rows["operators_included"]
    }
    if (
        event_count != expected_rows["all_event_rows"]
        or labeled != expected_rows["labeled_nonnull_exact_decision"]
        or censored != expected_rows["censored_null_exact_decision"]
        or observed_censored_by_operator != expected_rows["censored_by_operator"]
        or dict(censored_stages) != expected_rows["censored_by_rejection_stage"]
        or dict(censored_reasons) != expected_rows["censored_by_rejection_reason"]
    ):
        raise ValueError("training censoring counts differ from the frozen protocol")

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
    return hashed_record(payload, "registry_sha256")


def selected_arcs(
    *,
    prefix: str,
    phase: str,
    target: str,
    base_seed: int,
    group_index: int,
    count: int,
) -> list[tuple[int, int]]:
    arcs = list(ARC_LIST)
    for descending_index in range(len(arcs) - 1, 0, -1):
        selected_index = counter_randbelow(
            descending_index + 1,
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=base_seed,
            unit_index=group_index,
            draw_name=f"arc_shuffle_{descending_index}",
        )
        arcs[descending_index], arcs[selected_index] = (
            arcs[selected_index],
            arcs[descending_index],
        )
    return arcs[:count]


def rng_domain(mode: str) -> tuple[str, str]:
    if mode == OFFICIAL_MODE:
        return PROTOCOL_PREFIX, "validation"
    if mode == SMOKE_MODE:
        return SMOKE_PREFIX, "smoke_validation"
    if mode == INTEGRATION_MODE:
        return INTEGRATION_PREFIX, "integration_validation"
    raise ValueError("unknown validation mode")


def integration_seed(target_index: int) -> int:
    if target_index < 0:
        raise ValueError("integration target index must be nonnegative")
    return INTEGRATION_PAIR_SEED


def build_pool_records(
    *,
    training_registry: Mapping[str, Any],
    mode: str,
    seed_by_target: Mapping[str, list[int]],
    groups_per_pair: int,
    group_size: int,
) -> list[dict[str, Any]]:
    if group_size != 16:
        raise ValueError("v1 validation group size must remain 16")
    training_candidates = set(training_registry["candidate_sha256"])
    rows: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    global_index = 0
    prefix, phase = rng_domain(mode)
    for target in TARGETS:
        parent_rows = training_registry["validation_parents"][target]
        if not parent_rows:
            raise ValueError(f"training registry has no parents for {target}")
        for base_seed in seed_by_target[target]:
            for group_index in range(groups_per_pair):
                parent_index = counter_randbelow(
                    len(parent_rows),
                    prefix=prefix,
                    phase=phase,
                    target=target,
                    pair_seed=base_seed,
                    unit_index=group_index,
                    draw_name="parent",
                )
                parent = parent_rows[parent_index]
                parent_graph = graph_from_candidate_record(parent["candidate"])
                arcs = selected_arcs(
                    prefix=prefix,
                    phase=phase,
                    target=target,
                    base_seed=base_seed,
                    group_index=group_index,
                    count=group_size,
                )
                pool_id = object_sha256(
                    {
                        "schema_version": f"{SCHEMA}.pool_id",
                        "mode": mode,
                        "target": target,
                        "base_seed": base_seed,
                        "group_index": group_index,
                        "parent_quotient_sha256": parent["quotient_sha256"],
                        "arc_count": group_size,
                    }
                )
                seen_candidates: set[str] = set()
                for slot_index, arc in enumerate(arcs):
                    graph = toggle_arc(parent_graph, arc)
                    candidate = candidate_record(graph)
                    candidate_sha = candidate_record_sha256(candidate)
                    if candidate_sha in seen_candidates:
                        raise AssertionError("one validation pool contains a duplicate")
                    seen_candidates.add(candidate_sha)
                    payload = {
                        "schema_version": POOL_RECORD_SCHEMA,
                        "mode": mode,
                        "global_pool_candidate_index": global_index,
                        "pool_id": pool_id,
                        "target": target,
                        "base_seed": base_seed,
                        "group_index": group_index,
                        "slot_index": slot_index,
                        "parent": {
                            "candidate_sha256": parent["candidate_sha256"],
                            "quotient_sha256": parent["quotient_sha256"],
                        },
                        "proposal": {
                            "operator": "toggle_one_arc",
                            "arc": [arc[0], arc[1]],
                        },
                        "candidate": candidate,
                        "candidate_sha256": candidate_sha,
                        "training_candidate_collision": (
                            candidate_sha in training_candidates
                        ),
                        "previous_pool_record_sha256": previous,
                    }
                    row = hashed_record(payload, "pool_record_sha256")
                    previous = row["pool_record_sha256"]
                    rows.append(row)
                    global_index += 1
    return rows


def mock_exact_decision(
    graph: DigraphPlacement,
    target: str,
    candidate_sha: str,
) -> tuple[dict[str, Any] | None, None]:
    """Deterministic smoke label. It is never evidence and emits no certificate."""

    if not weakly_connected(graph):
        return None, None
    equal = int(candidate_sha[:2], 16) % 2 == 0
    root = hashlib.sha256(
        f"{SMOKE_PREFIX}|literal|{target}|{candidate_sha}".encode("ascii")
    ).hexdigest()
    return (
        {
            "relation": "smoke_fixture_mock_equality",
            "candidate_root_game_sha256": root,
            "target_root_game_sha256": hashlib.sha256(
                f"{SMOKE_PREFIX}|target|{target}".encode("ascii")
            ).hexdigest(),
            "candidate_leq_target": equal,
            "target_leq_candidate": equal,
            "equal": equal,
            "distinct_game_tree_node_count": 0,
            "distinct_game_tree_edge_count": 0,
            "game_birthday": 0,
        },
        None,
    )


def build_target_bindings(
    *,
    target_games: Mapping[str, Any],
    run_dir: Path,
) -> dict[str, dict[str, str]]:
    """Write official target artifacts and return exact equality bindings."""

    bindings: dict[str, dict[str, str]] = {}
    for target, game in target_games.items():
        artifact = fixed_value.target_artifact(target, game)
        reference = fixed_value.write_content_addressed(
            run_dir, "targets", artifact
        )
        bindings[target] = fixed_value.artifact_binding(
            kind="abstract_short_game_target",
            schema_version=artifact["schema_version"],
            artifact_sha256=reference["sha256"],
            root=game,
        )
    return bindings


def label_pool_records(
    *,
    pool_rows: Iterable[Mapping[str, Any]],
    training_registry: Mapping[str, Any],
    mode: str,
    run_dir: Path,
    pool_commitment_sha256: str,
) -> list[dict[str, Any]]:
    training_candidates = set(training_registry["candidate_sha256"])
    training_quotients = set(training_registry["quotient_sha256"])
    target_games = {
        target: parse_game_form(target)
        for target in TARGETS
    }
    target_bindings: dict[str, dict[str, str]] = {}
    if mode in (OFFICIAL_MODE, INTEGRATION_MODE):
        target_bindings = build_target_bindings(
            target_games=target_games,
            run_dir=run_dir,
        )

    labels: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    for index, pool_row in enumerate(pool_rows):
        graph = graph_from_candidate_record(pool_row["candidate"])
        candidate_sha = candidate_record_sha256(pool_row["candidate"])
        if candidate_sha != pool_row["candidate_sha256"]:
            raise ValueError("committed candidate identity changed before labeling")
        connected = weakly_connected(graph)
        structural_quotient = quotient_record(graph) if connected else None
        quotient_collision = (
            structural_quotient is not None
            and structural_quotient["quotient_sha256"] in training_quotients
        )
        candidate_collision = candidate_sha in training_candidates
        if candidate_collision != pool_row["training_candidate_collision"]:
            raise ValueError("training candidate collision changed after commitment")

        sidecars = None
        equality_certificate_sha256 = None
        if mode == SMOKE_MODE:
            decision, _ = mock_exact_decision(
                graph, pool_row["target"], candidate_sha
            )
        else:
            if not connected:
                decision = None
            else:
                decision, _ = fixed_value.exact_decision(
                    graph, target_games[pool_row["target"]]
                )
                if decision["equal"]:
                    sidecars, equality_certificate_sha256 = (
                        fixed_value.build_match_sidecars(
                            graph=graph,
                            target=target_games[pool_row["target"]],
                            target_binding=target_bindings[pool_row["target"]],
                            run_dir=run_dir,
                        )
                    )
        quotient = structural_quotient if decision is not None else None
        measurements = descriptor_record(graph) if decision is not None else None
        exclusion_reasons: list[str] = []
        if not connected:
            exclusion_reasons.append("weakly_disconnected")
        if candidate_collision:
            exclusion_reasons.append("training_candidate_collision")
        if quotient_collision:
            exclusion_reasons.append("training_quotient_collision")
        if decision is None:
            exclusion_reasons.append("censored_null_exact_decision")
        eligible = not exclusion_reasons
        payload = {
            "schema_version": LABEL_RECORD_SCHEMA,
            "mode": mode,
            "global_label_index": index,
            "pool_commitment_sha256": pool_commitment_sha256,
            "pool_record_sha256": pool_row["pool_record_sha256"],
            "pool_id": pool_row["pool_id"],
            "target": pool_row["target"],
            "base_seed": pool_row["base_seed"],
            "group_index": pool_row["group_index"],
            "slot_index": pool_row["slot_index"],
            "proposal": pool_row["proposal"],
            "candidate": pool_row["candidate"],
            "candidate_sha256": candidate_sha,
            "weakly_connected": connected,
            "training_candidate_collision": candidate_collision,
            "training_quotient_collision": quotient_collision,
            "eligible_for_validation_metric": eligible,
            "exclusion_reasons": exclusion_reasons,
            "exact_decision": decision,
            "structural_quotient": structural_quotient,
            "quotient": quotient,
            "measurements": measurements,
            "sidecars": sidecars,
            "equality_certificate_sha256": equality_certificate_sha256,
            "previous_label_record_sha256": previous,
        }
        row = hashed_record(payload, "label_record_sha256")
        previous = row["label_record_sha256"]
        labels.append(row)
        fixed_value.clear_caches()
    return labels


def validation_identity_registry(
    *,
    labels: Iterable[Mapping[str, Any]],
    training_registry: Mapping[str, Any],
    pool_commitment: Mapping[str, Any],
    labels_path: Path,
) -> dict[str, Any]:
    candidate_ids: set[str] = set()
    quotient_ids: set[str] = set()
    counts: Counter[str] = Counter()
    eligible_by_pool: Counter[str] = Counter()
    label_count = 0
    final_label_hash = ZERO_SHA256
    for row in labels:
        label_count += 1
        final_label_hash = row["label_record_sha256"]
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
    pool_count = len(eligible_by_pool)
    payload = {
        "schema_version": VALIDATION_REGISTRY_SCHEMA,
        "status": "VALIDATION_IDENTITIES_ONLY",
        "training_registry_sha256": training_registry["registry_sha256"],
        "pool_commitment_sha256": pool_commitment["commitment_sha256"],
        "labels_file_sha256": file_sha256(labels_path),
        "label_count": label_count,
        "final_label_record_sha256": final_label_hash,
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
        | {"pools_with_at_least_one_eligible_row": pool_count},
        "test_leakage_rule": (
            "all validation candidate and quotient identities are blocked in test"
        ),
    }
    return hashed_record(payload, "registry_sha256")


def verify_launch(
    repo_root: Path,
    launch_path: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    launch = load_canonical_json(launch_path)
    verify_launch_document(repo_root, launch, protocol)
    return launch


def verify_launch_document(
    repo_root: Path,
    launch: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    supplied = launch.get("launch_sha256")
    payload = dict(launch)
    payload.pop("launch_sha256", None)
    if object_sha256(payload) != supplied:
        raise ValueError("validation launch self-hash does not replay")
    if launch.get("schema_version") != LAUNCH_SCHEMA:
        raise ValueError("wrong validation launch schema")
    if launch.get("status") != "AUTHORIZED_ONCE":
        raise ValueError("validation launch is not authorized once")
    if launch.get("protocol") != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("validation launch protocol binding mismatch")
    expected = protocol["splits"]["validation"]
    if launch.get("validation_design") != {
        "targets": list(TARGETS),
        "pair_seeds": expected["pair_seeds"],
        "groups_per_pair": expected["groups_per_pair"],
        "group_size": expected["group_size"],
        "all_candidates_labeled": True,
    }:
        raise ValueError("validation launch design mismatch")
    for entry in launch.get("sources", []):
        relative = Path(entry["repo_relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("validation launch source path is not repo-relative")
        path = repo_root / relative
        if file_sha256(path) != entry["sha256"]:
            raise ValueError(f"validation launch source mismatch: {path}")
    if not launch.get("sources"):
        raise ValueError("validation launch has no source bundle")
    verify_model_implementation_snapshot(repo_root, launch)
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
        raise ValueError("validation launch authorization hash does not replay")
    retry = launch.get("retry_after_pre_model_execution_failure")
    if retry is not None:
        expected_retry_keys = {
            "prior_incident_path",
            "prior_incident_file_sha256",
            "prior_abort_sha256",
            "prior_launch_sha256",
            "prior_authorization_sha256",
            "prior_failure_phase",
            "prior_incident_chain_depth",
            "prior_incident_chain_sha256",
            "prior_model_selection",
            "resume_prior_run",
            "reuse_prior_pool_or_label_artifacts",
        }
        if (
            not isinstance(retry, dict)
            or set(retry) != expected_retry_keys
            or retry.get("prior_model_selection") is not False
            or retry.get("resume_prior_run") is not False
            or retry.get("reuse_prior_pool_or_label_artifacts") is not False
            or not any(
                entry.get("repo_relative_path") == retry.get("prior_incident_path")
                and entry.get("sha256")
                == retry.get("prior_incident_file_sha256")
                for entry in launch["sources"]
            )
        ):
            raise ValueError("post-abort reauthorization binding changed")
    expected_output = (
        "output/research/digraph-order7-neural-validation-v1-"
        + launch["authorization_sha256"][:12]
    )
    if launch.get("output_directory") != expected_output:
        raise ValueError("validation output directory is not authorization-derived")


def verify_model_implementation_snapshot(
    repo_root: Path,
    launch: Mapping[str, Any],
) -> None:
    model = launch.get("model_implementation")
    if not isinstance(model, dict):
        raise ValueError("validation launch lacks a model implementation binding")
    if model.get("repository") != "partizan":
        raise ValueError("validation model repository binding changed")
    if not re.fullmatch(r"[0-9a-f]{40}", str(model.get("pushed_commit_sha", ""))):
        raise ValueError("validation model commit is not a 40-hex commit")
    if model.get("remote_commit_verified") is not True:
        raise ValueError("validation model commit lacks remote verification")
    if not isinstance(model.get("repository_url"), str) or not model["repository_url"]:
        raise ValueError("validation model repository URL is absent")
    files = model.get("snapshot_files")
    if not isinstance(files, list):
        raise ValueError("validation model snapshot file list is absent")
    observed_paths = [entry.get("repo_relative_path") for entry in files]
    if observed_paths != list(REQUIRED_MODEL_FILES):
        raise ValueError("validation model snapshot paths or order changed")
    canonical_files: list[dict[str, str]] = []
    for entry in files:
        snapshot_relative = Path(entry.get("snapshot_path", ""))
        if snapshot_relative.is_absolute() or ".." in snapshot_relative.parts:
            raise ValueError("model snapshot path is not repo-relative")
        snapshot = repo_root / snapshot_relative
        if file_sha256(snapshot) != entry.get("sha256"):
            raise ValueError(
                f"model snapshot hash mismatch: {entry.get('repo_relative_path')}"
            )
        canonical_files.append(
            {
                "repo_relative_path": entry["repo_relative_path"],
                "sha256": entry["sha256"],
            }
        )
    snapshot_payload = {
        "repository": "partizan",
        "repository_url": model["repository_url"],
        "pushed_commit_sha": model["pushed_commit_sha"],
        "files": canonical_files,
    }
    if object_sha256(snapshot_payload) != model.get("snapshot_sha256"):
        raise ValueError("validation model snapshot aggregate hash does not replay")


def copy_launch_source_bundle(
    *,
    repo_root: Path,
    run_dir: Path,
    launch: Mapping[str, Any],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    sources: list[tuple[str, str, str]] = []
    for entry in launch["sources"]:
        sources.append(
            ("validation_source", entry["repo_relative_path"], entry["sha256"])
        )
    for entry in launch["model_implementation"]["snapshot_files"]:
        sources.append(
            ("partizan_model", entry["snapshot_path"], entry["sha256"])
        )
    for role, source_relative, expected_sha in sources:
        source = repo_root / source_relative
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha:
            raise ValueError(f"source bundle changed before copy: {source_relative}")
        destination_relative = (
            Path("source")
            / role
            / expected_sha[:2]
            / f"{expected_sha}-{Path(source_relative).name}"
        )
        write_bytes_exclusive(run_dir / destination_relative, data)
        entries.append(
            {
                "role": role,
                "source_path": source_relative,
                "bundled_path": destination_relative.as_posix(),
                "sha256": expected_sha,
            }
        )
    return entries


def build_run(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    seed_by_target: Mapping[str, list[int]],
    groups_per_pair: int,
    group_size: int,
    launch: Mapping[str, Any] | None,
    integration_training_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    observed_seeds = {
        target: list(seed_by_target.get(target, []))
        for target in TARGETS
    }
    if set(seed_by_target) != set(TARGETS):
        raise ValueError("validation seed targets differ from the frozen design")
    if mode == OFFICIAL_MODE:
        if integration_training_registry is not None:
            raise ValueError("official validation forbids fixture registries")
        if launch is None:
            raise ValueError(
                "official validation cannot run without an authorized launch"
            )
        verify_launch_document(repo_root, launch, protocol)
        validation = protocol["splits"]["validation"]
        expected_seeds = {
            target: list(validation["pair_seeds"]) for target in TARGETS
        }
        if (
            observed_seeds != expected_seeds
            or groups_per_pair != validation["groups_per_pair"]
            or group_size != validation["group_size"]
        ):
            raise ValueError("official validation design differs from the protocol")
        if run_dir.resolve() != (
            repo_root / launch["output_directory"]
        ).resolve():
            raise ValueError("official output directory differs from the launch")
    elif mode == SMOKE_MODE:
        if integration_training_registry is not None:
            raise ValueError("smoke validation forbids integration registries")
        if launch is not None:
            raise ValueError("smoke validation cannot consume an official launch")
        expected_seeds = {
            target: [smoke_seed(index)]
            for index, target in enumerate(TARGETS)
        }
        if (
            observed_seeds != expected_seeds
            or groups_per_pair not in (1, 2, 3, 4)
            or group_size != 16
        ):
            raise ValueError("smoke validation design differs from its isolated domain")
    elif mode == INTEGRATION_MODE:
        if launch is not None or integration_training_registry is None:
            raise ValueError(
                "integration fixture requires no launch and an explicit fixture registry"
            )
        expected_seeds = {
            target: [integration_seed(index)]
            for index, target in enumerate(TARGETS)
        }
        official = set(protocol["splits"]["validation"]["pair_seeds"])
        test = set(protocol["splits"]["test"]["pair_seeds"])
        smoke = {smoke_seed(index) for index in range(len(TARGETS))}
        integration = {
            value for values in expected_seeds.values() for value in values
        }
        if (
            observed_seeds != expected_seeds
            or groups_per_pair not in (1, 2, 3, 4)
            or integration & (official | test | smoke)
        ):
            raise ValueError(
                "integration fixture design differs from its isolated domain"
            )
    else:
        raise ValueError("unknown validation mode")

    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        launch_binding = None
        source_bundle: list[dict[str, str]] = []
        if launch is not None:
            write_json_exclusive(run_dir / "launch_record.json", launch)
            launch_binding = {
                "file": "launch_record.json",
                "file_sha256": file_sha256(run_dir / "launch_record.json"),
                "launch_sha256": launch["launch_sha256"],
                "authorization_sha256": launch["authorization_sha256"],
                "output_directory": launch["output_directory"],
            }
            source_bundle = copy_launch_source_bundle(
                repo_root=repo_root,
                run_dir=run_dir,
                launch=launch,
            )
        if mode == INTEGRATION_MODE:
            training = dict(integration_training_registry)
            supplied_hash = training.get("registry_sha256")
            payload = dict(training)
            payload.pop("registry_sha256", None)
            if (
                supplied_hash != object_sha256(payload)
                or training.get("status")
                != "TEST_FIXTURE_TRAINING_IDENTITIES_ONLY"
            ):
                raise ValueError("integration fixture registry is not self-hashed")
        else:
            training = training_identity_registry(repo_root)
        write_json_exclusive(run_dir / "training_identity_registry.json", training)
        protocol_path = repo_root / PROTOCOL_PATH
        manifest_payload = {
            "schema_version": MANIFEST_SCHEMA,
            "status": (
                "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
                if mode == OFFICIAL_MODE
                else (
                    "INTEGRATION_FIXTURE_ONLY_NOT_EVIDENCE"
                    if mode == INTEGRATION_MODE
                    else "SMOKE_ONLY_NOT_EVIDENCE"
                )
            ),
            "mode": mode,
            "protocol": {
                "path": PROTOCOL_PATH.as_posix(),
                "sha256": file_sha256(protocol_path),
            },
            "launch": launch_binding,
            "source_bundle": source_bundle,
            "training_registry_sha256": training["registry_sha256"],
            "design": {
                "targets": list(TARGETS),
                "seed_by_target": {
                    target: seed_by_target[target] for target in TARGETS
                },
                "groups_per_pair": groups_per_pair,
                "group_size": group_size,
                "operator": "toggle_one_arc",
                "adaptive_repertoire": False,
                "all_candidates_labeled": True,
            },
            "paper_evidence": False,
            "test_data_generated": False,
        }
        manifest = hashed_record(manifest_payload, "manifest_sha256")
        write_json_exclusive(run_dir / "manifest.json", manifest)

        pools = build_pool_records(
            training_registry=training,
            mode=mode,
            seed_by_target=seed_by_target,
            groups_per_pair=groups_per_pair,
            group_size=group_size,
        )
        pool_count, final_pool_hash = write_jsonl_exclusive(
            run_dir / "pools.committed.jsonl",
            pools,
            hash_field="pool_record_sha256",
        )
        commitment_payload = {
            "schema_version": POOL_COMMITMENT_SCHEMA,
            "mode": mode,
            "manifest_sha256": manifest["manifest_sha256"],
            "training_registry_sha256": training["registry_sha256"],
            "pool_file_sha256": file_sha256(run_dir / "pools.committed.jsonl"),
            "pool_candidate_count": pool_count,
            "final_pool_record_sha256": final_pool_hash,
            "contains_outcomes": False,
        }
        commitment = hashed_record(commitment_payload, "commitment_sha256")
        write_json_exclusive(
            run_dir / "POOL_COMMITMENT_COMPLETE.json", commitment
        )

        labels = label_pool_records(
            pool_rows=pools,
            training_registry=training,
            mode=mode,
            run_dir=run_dir,
            pool_commitment_sha256=commitment["commitment_sha256"],
        )
        label_count, final_label_hash = write_jsonl_exclusive(
            run_dir / "labels.jsonl",
            labels,
            hash_field="label_record_sha256",
        )
        registry = validation_identity_registry(
            labels=labels,
            training_registry=training,
            pool_commitment=commitment,
            labels_path=run_dir / "labels.jsonl",
        )
        write_json_exclusive(
            run_dir / "validation_identity_registry.json", registry
        )
        generation_payload = {
            "schema_version": GENERATION_SCHEMA,
            "status": (
                "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
                if mode == OFFICIAL_MODE
                else (
                    "INTEGRATION_FIXTURE_ONLY_NOT_EVIDENCE"
                    if mode == INTEGRATION_MODE
                    else "SMOKE_ONLY_NOT_EVIDENCE"
                )
            ),
            "mode": mode,
            "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
            "training_registry_file_sha256": file_sha256(
                run_dir / "training_identity_registry.json"
            ),
            "pool_commitment_file_sha256": file_sha256(
                run_dir / "POOL_COMMITMENT_COMPLETE.json"
            ),
            "pool_file_sha256": file_sha256(
                run_dir / "pools.committed.jsonl"
            ),
            "labels_file_sha256": file_sha256(run_dir / "labels.jsonl"),
            "validation_registry_file_sha256": file_sha256(
                run_dir / "validation_identity_registry.json"
            ),
            "pool_candidate_count": pool_count,
            "label_count": label_count,
            "final_pool_record_sha256": final_pool_hash,
            "final_label_record_sha256": final_label_hash,
            "paper_evidence": False,
            "test_data_generated": False,
        }
        generation = hashed_record(generation_payload, "generation_sha256")
        write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
        return generation
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.generation_failure",
            "status": "FAILED_CLOSED",
            "mode": mode,
            "error_type": type(error).__name__,
            "error": str(error),
            "resume_authorized": False,
            "paper_evidence": False,
        }
        failure = hashed_record(failure_payload, "failure_sha256")
        try:
            write_json_exclusive(run_dir / "FAILURE.json", failure)
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=(SMOKE_MODE, OFFICIAL_MODE), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--smoke-groups", type=int, default=1)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    protocol = load_json_object(repo_root / PROTOCOL_PATH)

    if args.mode == SMOKE_MODE:
        if args.launch_record is not None:
            raise SystemExit("smoke mode cannot consume an official launch record")
        if args.output is None:
            raise SystemExit("smoke mode requires --output")
        run_dir = (
            args.output
            if args.output.is_absolute()
            else (repo_root / args.output)
        ).resolve()
        if not run_dir.name.startswith("smoke-"):
            raise SystemExit("smoke output basename must start with 'smoke-'")
        if args.smoke_groups < 1 or args.smoke_groups > 4:
            raise SystemExit("--smoke-groups must be between one and four")
        seed_by_target = {
            target: [smoke_seed(index)]
            for index, target in enumerate(TARGETS)
        }
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=SMOKE_MODE,
            seed_by_target=seed_by_target,
            groups_per_pair=args.smoke_groups,
            group_size=16,
            launch=None,
        )
    else:
        if args.launch_record is None:
            raise SystemExit(
                "official validation requires a separate authorized launch record"
            )
        launch_path = (
            args.launch_record
            if args.launch_record.is_absolute()
            else repo_root / args.launch_record
        )
        launch = verify_launch(repo_root, launch_path, protocol)
        if args.output is not None:
            raise SystemExit("official output is fixed by the launch record")
        run_dir = (repo_root / launch["output_directory"]).resolve()
        validation = protocol["splits"]["validation"]
        seed_by_target = {
            target: list(validation["pair_seeds"]) for target in TARGETS
        }
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=OFFICIAL_MODE,
            seed_by_target=seed_by_target,
            groups_per_pair=validation["groups_per_pair"],
            group_size=validation["group_size"],
            launch=launch,
        )
    print(json.dumps(generation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
