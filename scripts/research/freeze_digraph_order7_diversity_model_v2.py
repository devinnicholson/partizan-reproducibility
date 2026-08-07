#!/usr/bin/env python3
"""Train, select, and freeze the diversity-policy V2 novelty ensemble.

Only the historical V1 training ledger supplies optimization labels. The
sealed V2 validation corpus selects one member checkpoint, temperature,
embedding width, and rank-fusion weight. No V2 validation row enters a
gradient update, and no V2 test seed is generated or evaluated here.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256


SCHEMA = "partizan.digraph_order7_diversity_model_freeze.v2"
GRID_SCHEMA = f"{SCHEMA}.grid_report"
MODEL_CARD_SCHEMA = f"{SCHEMA}.model_card"
BINDING_SCHEMA = f"{SCHEMA}.model_binding"
PACKAGE_SCHEMA = f"{SCHEMA}.package"
FAILURE_SCHEMA = f"{SCHEMA}.failure"
PROTOCOL_PATH = Path("docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json")
TRAINING_EVENTS = Path(
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db/"
    "events.jsonl"
)
VALIDATION_LAUNCH = Path(
    "output/research/" "DIGRAPH_ORDER7_DIVERSITY_VALIDATION_V2_AUTHORIZED_ONCE.json"
)
VALIDATION_RUN = Path(
    "output/research/digraph-order7-diversity-validation-v2-8a54ee4cd2dc"
)
EQUALITY_PACKAGE = Path(
    "output/research/digraph-order7-neural-model-v1-32b1e3149ea2/" "MODEL_PACKAGE.json"
)
EQUALITY_BINDING = Path(
    "output/research/digraph-order7-neural-model-v1-32b1e3149ea2/" "model_binding.json"
)
TARGETS = ("0", "*", "{0|1}")
ZERO_SHA256 = "0" * 64
EMBED_BATCH = 1024


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
    rows = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            value = json.loads(raw)
            if not isinstance(value, dict) or canonical_line(value) != raw:
                raise ValueError(f"{path}:{line_number}: noncanonical JSONL")
            rows.append(value)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows


def verify_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


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


def write_content_addressed(
    run_dir: Path,
    role: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    data = canonical_line(value)
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("artifacts") / role / digest[:2] / f"{digest}.json"
    write_bytes_exclusive(run_dir / relative, data)
    return {
        "path": relative.as_posix(),
        "sha256": digest,
        "bytes": len(data),
    }


def load_frozen_rankers(
    repo_root: Path,
    launch: Mapping[str, Any],
) -> tuple[Any, Any]:
    snapshots = {
        entry["repo_relative_path"]: repo_root / entry["snapshot_path"]
        for entry in launch["model_implementation"]["snapshot_files"]
    }
    equality_path = snapshots["python/partizan/digraph_neural_ranker.py"]
    diversity_path = snapshots["python/partizan/digraph_diversity_ranker.py"]
    package_name = "_partizan_diversity_v2_frozen"
    package = types.ModuleType(package_name)
    package.__path__ = [str(equality_path.parent)]
    sys.modules[package_name] = package

    def load(relative_name: str, path: Path) -> Any:
        name = f"{package_name}.{relative_name}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load frozen source {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    equality = load("digraph_neural_ranker", equality_path)
    diversity = load("digraph_diversity_ranker", diversity_path)
    return equality, diversity


def validation_sources(
    repo_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    launch = load_canonical_json(repo_root / VALIDATION_LAUNCH)
    verify_self_hash(launch, "launch_sha256", label="validation launch")
    if (
        launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("validation launch boundary changed")
    run_dir = repo_root / launch["output_directory"]
    if run_dir.resolve() != (repo_root / VALIDATION_RUN).resolve():
        raise ValueError("validation run differs from frozen launch")
    completion = load_canonical_json(run_dir / "VALIDATION_COMPLETE.json")
    verify_self_hash(completion, "completion_sha256", label="validation completion")
    if (
        completion.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("validation_data_authorized_for_model_selection") is not True
        or completion.get("test_data_generated") is not False
        or completion.get("paper_evidence") is not False
    ):
        raise ValueError("validation is not authorized for model selection")
    verification = load_canonical_json(run_dir / "independent_verification.json")
    verify_self_hash(
        verification,
        "verification_sha256",
        label="validation verification",
    )
    if verification.get("status") != "PASS_VALIDATION_ONLY" or not all(
        verification.get(field) is True
        for field in (
            "complete_pre_v2_quarantine_replay",
            "literal_overlap_audit_boundary_replay",
            "outcome_free_pool_commitment_replay",
            "pool_rng_parent_and_arc_replay",
            "exact_label_and_certificate_replay",
            "collision_descriptor_and_eligibility_replay",
            "validation_registry_replay",
            "negative_tests_pass",
        )
    ):
        raise ValueError("independent validation verification changed")
    registry = load_canonical_json(run_dir / "validation_identity_registry.json")
    verify_self_hash(registry, "registry_sha256", label="validation registry")
    if registry.get("model_training_use") is not False or registry.get(
        "labels_file_sha256"
    ) != file_sha256(run_dir / "labels.jsonl"):
        raise ValueError("validation registry training boundary changed")
    labels = load_canonical_jsonl(run_dir / "labels.jsonl")
    if len(labels) != protocol["budget"]["validation_exact_candidate_labels"]:
        raise ValueError("validation label count changed")
    return protocol, launch, completion, registry, labels


def load_equality_ensemble(
    repo_root: Path,
    protocol: Mapping[str, Any],
    equality: Any,
) -> tuple[Any, dict[str, Any], Path]:
    frozen = protocol["source_evidence"]["frozen_equality_model"]
    package_path = repo_root / frozen["package"]["path"]
    binding_path = repo_root / frozen["binding"]["path"]
    if (
        file_sha256(package_path) != frozen["package"]["sha256"]
        or file_sha256(binding_path) != frozen["binding"]["sha256"]
        or package_path != repo_root / EQUALITY_PACKAGE
        or binding_path != repo_root / EQUALITY_BINDING
    ):
        raise ValueError("frozen equality package binding changed")
    package = load_canonical_json(package_path)
    binding = load_canonical_json(binding_path)
    ensemble_relative = binding["ensemble"]["path"]
    ensemble_path = package_path.parent / ensemble_relative
    if (
        file_sha256(ensemble_path) != frozen["checkpoint_sha256"]
        or binding["ensemble"]["model_id"] != frozen["model_id"]
    ):
        raise ValueError("frozen equality checkpoint changed")
    record = load_json_object(ensemble_path)
    model = equality.LogitEnsemble.from_record(record)
    if record.get("model_id") != frozen["model_id"]:
        raise ValueError("equality model identity changed")
    return model, record, ensemble_path


def validation_arrays(
    rows: Sequence[Mapping[str, Any]],
    equality: Any,
    diversity: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nodes = []
    adjacency = []
    target_indices = []
    for index, row in enumerate(rows):
        if row.get("global_label_index") != index:
            raise ValueError("validation label order changed")
        node_values, adjacency_values = diversity._candidate_arrays(row["candidate"])
        nodes.append(node_values)
        adjacency.append(adjacency_values)
        target_indices.append(equality.TARGETS.index(row["target"]))
    return (
        np.stack(nodes),
        np.stack(adjacency),
        np.asarray(target_indices, dtype=np.int64),
    )


def stage0_rows(prior: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    controls = {}
    for target in TARGETS:
        matches = [
            row
            for row in prior["validation_parents"][target]
            if row.get("source") == "stage0_control"
        ]
        if len(matches) != 1:
            raise ValueError(f"target {target} lacks one Stage-0 control")
        controls[target] = matches[0]
    return controls


def embed_in_batches(
    model: Any,
    nodes: np.ndarray,
    adjacency: np.ndarray,
) -> np.ndarray:
    batches = []
    for start in range(0, len(nodes), EMBED_BATCH):
        stop = min(start + EMBED_BATCH, len(nodes))
        batches.append(model.embed(nodes[start:stop], adjacency[start:stop]))
    result = np.concatenate(batches)
    if not np.isfinite(result).all():
        raise ValueError("novelty embedding contains a nonfinite value")
    return result


def pool_streams(
    rows: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> list[tuple[str, int, list[list[int]]]]:
    grouped: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["target"], row["pair_seed"], row["group_index"])].append(index)
    streams = []
    seeds = protocol["splits"]["validation"]["pair_seeds"]
    groups_per_pair = protocol["splits"]["validation"]["groups_per_pair"]
    for target in TARGETS:
        for pair_seed in seeds:
            pools = []
            for group_index in range(groups_per_pair):
                indices = sorted(
                    grouped[(target, pair_seed, group_index)],
                    key=lambda index: rows[index]["slot_index"],
                )
                if len(indices) != 16:
                    raise ValueError("validation stream has an incomplete pool")
                pools.append(indices)
            streams.append((target, pair_seed, pools))
    if sum(len(pools) for _target, _seed, pools in streams) * 16 != len(rows):
        raise ValueError("validation pool projection changed")
    return streams


def first_nonempty_tier(
    rows: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
    live_candidates: set[str],
) -> tuple[int, list[int]]:
    for tier_index in range(4):
        selected = []
        for index in indices:
            row = rows[index]
            conditions = (
                row["weakly_connected"],
                not row["prior_split_candidate_collision"],
                row["candidate_sha256"] not in live_candidates,
            )
            if tier_index == 0 and all(conditions):
                selected.append(index)
            elif tier_index == 1 and all(conditions[:2]):
                selected.append(index)
            elif tier_index == 2 and conditions[1]:
                selected.append(index)
            elif tier_index == 3:
                selected.append(index)
        if selected:
            return tier_index, selected
    raise AssertionError("all-candidate structural tier cannot be empty")


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


def discovery_identity(
    row: Mapping[str, Any],
) -> tuple[str, str] | None:
    decision = row["exact_decision"]
    quotient = row["structural_quotient"]
    if (
        not isinstance(decision, Mapping)
        or decision.get("equal") is not True
        or not isinstance(quotient, Mapping)
        or row["prior_split_candidate_collision"]
        or row["prior_split_quotient_collision"]
    ):
        return None
    return (
        quotient["quotient_sha256"],
        decision["candidate_root_game_sha256"],
    )


def summarize_streams(stream_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_target: dict[str, list[Mapping[str, Any]]] = {target: [] for target in TARGETS}
    for row in stream_rows:
        by_target[row["target"]].append(row)
    target_means = {
        target: {
            metric: float(np.mean([row[metric] for row in by_target[target]]))
            for metric in ("quotient_unique", "literal_unique")
        }
        for target in TARGETS
    }
    return {
        "stream_count": len(stream_rows),
        "total_quotient_unique": sum(row["quotient_unique"] for row in stream_rows),
        "total_literal_unique": sum(row["literal_unique"] for row in stream_rows),
        "target_mean": target_means,
        "target_macro_quotient_unique": float(
            np.mean([target_means[target]["quotient_unique"] for target in TARGETS])
        ),
        "target_macro_literal_unique": float(
            np.mean([target_means[target]["literal_unique"] for target in TARGETS])
        ),
        "streams": list(stream_rows),
    }


def simulate_baseline(
    *,
    arm: str,
    rows: Sequence[Mapping[str, Any]],
    streams: Sequence[tuple[str, int, list[list[int]]]],
    controls: Mapping[str, Mapping[str, Any]],
    equality_logits: np.ndarray,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if arm not in ("random", "equality"):
        raise ValueError("unknown baseline arm")
    output = []
    prefix = protocol["splits"]["seed_derivation"]["prefix"]
    for target, pair_seed, pools in streams:
        live = {controls[target]["candidate_sha256"]}
        quotient_discoveries: set[str] = set()
        literal_discoveries: set[str] = set()
        tier_counts: dict[int, int] = defaultdict(int)
        selected: list[str] = []
        for group_index, indices in enumerate(pools):
            tier, eligible = first_nonempty_tier(rows, indices, live)
            tier_counts[tier] += 1
            if arm == "random":
                offset = counter_randbelow(
                    len(eligible),
                    prefix=prefix,
                    phase="validation",
                    target=target,
                    pair_seed=pair_seed,
                    unit_index=group_index,
                    draw_name="random_selection",
                )
                selected_index = eligible[offset]
            else:
                selected_index = min(
                    eligible,
                    key=lambda index: (
                        -float(equality_logits[index]),
                        rows[index]["candidate_sha256"],
                    ),
                )
            row = rows[selected_index]
            selected.append(row["candidate_sha256"])
            identity = discovery_identity(row)
            if identity is not None:
                quotient_sha, literal_sha = identity
                quotient_discoveries.add(quotient_sha)
                literal_discoveries.add(literal_sha)
                live.add(row["candidate_sha256"])
        output.append(
            {
                "target": target,
                "pair_seed": pair_seed,
                "quotient_unique": len(quotient_discoveries),
                "literal_unique": len(literal_discoveries),
                "tier_counts": {
                    str(key): tier_counts[key] for key in sorted(tier_counts)
                },
                "selected_candidate_sha256": selected,
            }
        )
    result = summarize_streams(output)
    result["arm"] = arm
    return result


def simulate_novelty(
    *,
    rows: Sequence[Mapping[str, Any]],
    streams: Sequence[tuple[str, int, list[list[int]]]],
    controls: Mapping[str, Mapping[str, Any]],
    equality_logits: np.ndarray,
    member_embeddings: Sequence[np.ndarray],
    lambda_weight: float,
    diversity: Any,
) -> dict[str, Any]:
    row_count = len(rows)
    stage_index = {target: row_count + index for index, target in enumerate(TARGETS)}
    output = []
    for target, pair_seed, pools in streams:
        live = {controls[target]["candidate_sha256"]}
        memory = [stage_index[target]]
        quotient_discoveries: set[str] = set()
        literal_discoveries: set[str] = set()
        tier_counts: dict[int, int] = defaultdict(int)
        selected: list[str] = []
        selected_scores: list[dict[str, float]] = []
        for indices in pools:
            tier, eligible = first_nonempty_tier(rows, indices, live)
            tier_counts[tier] += 1
            equality_values = [float(equality_logits[index]) for index in eligible]
            novelty_values = []
            for candidate_index in eligible:
                member_minima = []
                for embeddings in member_embeddings:
                    similarities = np.clip(
                        embeddings[memory] @ embeddings[candidate_index],
                        -1.0,
                        1.0,
                    )
                    member_minima.append(float(np.min(1.0 - similarities)))
                novelty_values.append(float(np.mean(member_minima)))
            equality_rank = diversity.midrank_fraction(equality_values)
            novelty_rank = diversity.midrank_fraction(novelty_values)
            fused = equality_rank + lambda_weight * novelty_rank
            selected_offset = min(
                range(len(eligible)),
                key=lambda offset: (
                    -float(fused[offset]),
                    rows[eligible[offset]]["candidate_sha256"],
                ),
            )
            selected_index = eligible[selected_offset]
            row = rows[selected_index]
            selected.append(row["candidate_sha256"])
            selected_scores.append(
                {
                    "equality_logit": equality_values[selected_offset],
                    "novelty_score": novelty_values[selected_offset],
                    "rank_fusion_score": float(fused[selected_offset]),
                }
            )
            identity = discovery_identity(row)
            if identity is not None:
                quotient_sha, literal_sha = identity
                quotient_discoveries.add(quotient_sha)
                literal_discoveries.add(literal_sha)
                live.add(row["candidate_sha256"])
                memory.append(selected_index)
        output.append(
            {
                "target": target,
                "pair_seed": pair_seed,
                "quotient_unique": len(quotient_discoveries),
                "literal_unique": len(literal_discoveries),
                "tier_counts": {
                    str(key): tier_counts[key] for key in sorted(tier_counts)
                },
                "memory_size_final": len(memory),
                "selected_candidate_sha256": selected,
                "selected_scores": selected_scores,
            }
        )
    result = summarize_streams(output)
    result["arm"] = "equality_novelty"
    return result


def ratio(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return math.inf if numerator > 0.0 else 1.0
    return numerator / denominator


def metric_projection(
    result: Mapping[str, Any],
    *,
    include_streams: bool,
) -> dict[str, Any]:
    fields = (
        "stream_count",
        "total_quotient_unique",
        "total_literal_unique",
        "target_mean",
        "target_macro_quotient_unique",
        "target_macro_literal_unique",
    )
    projection = {field: result[field] for field in fields}
    if include_streams:
        projection["streams"] = result["streams"]
    return projection


def model_selection(
    *,
    repo_root: Path,
    protocol: Mapping[str, Any],
    launch: Mapping[str, Any],
    registry: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    equality: Any,
    diversity: Any,
    equality_model: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[Any] | None]:
    training_path = repo_root / TRAINING_EVENTS
    expected_training = protocol["source_evidence"]["historical_training"]["events"]
    if file_sha256(training_path) != expected_training["sha256"]:
        raise ValueError("historical novelty training source changed")
    corpus = diversity.load_contrastive_corpus(training_path)
    expected_counts = (
        expected_training["all_rows"],
        expected_training["nonnull_exact_decision_rows"],
        expected_training["literal_digest_groups"],
        expected_training["contrastive_eligible_groups"],
        expected_training["contrastive_eligible_rows"],
    )
    observed_counts = (
        corpus.row_count,
        corpus.labeled_row_count,
        corpus.literal_digest_group_count,
        corpus.eligible_group_count,
        corpus.eligible_row_count,
    )
    if observed_counts != expected_counts:
        raise ValueError("novelty training label projection changed")

    nodes, adjacency, target_indices = validation_arrays(
        rows,
        equality,
        diversity,
    )
    equality_logits = equality_model.predict_logits(
        nodes,
        adjacency,
        target_indices,
    )
    if not np.isfinite(equality_logits).all():
        raise ValueError("frozen equality model produced nonfinite logits")
    prior = load_canonical_json(
        repo_root / launch["output_directory"] / "prior_split_identity_registry.json"
    )
    verify_self_hash(prior, "registry_sha256", label="prior registry")
    controls = stage0_rows(prior)
    control_nodes = []
    control_adjacency = []
    for target in TARGETS:
        node_values, adjacency_values = diversity._candidate_arrays(
            controls[target]["candidate"]
        )
        control_nodes.append(node_values)
        control_adjacency.append(adjacency_values)
    all_nodes = np.concatenate((nodes, np.stack(control_nodes)))
    all_adjacency = np.concatenate((adjacency, np.stack(control_adjacency)))
    streams = pool_streams(rows, protocol)
    random_result = simulate_baseline(
        arm="random",
        rows=rows,
        streams=streams,
        controls=controls,
        equality_logits=equality_logits,
        protocol=protocol,
    )
    equality_result = simulate_baseline(
        arm="equality",
        rows=rows,
        streams=streams,
        controls=controls,
        equality_logits=equality_logits,
        protocol=protocol,
    )
    print(
        json.dumps(
            {
                "phase": "validation_baselines",
                "random_literal": random_result["total_literal_unique"],
                "equality_literal": equality_result["total_literal_unique"],
                "random_quotient": random_result["total_quotient_unique"],
                "equality_quotient": equality_result["total_quotient_unique"],
            },
            sort_keys=True,
        ),
        flush=True,
    )

    grid = protocol["novelty_model"]["finite_grid"]
    lambda_grid = protocol["acquisition"]["lambda_grid"]
    selection_rule = protocol["validation_selection"]["selection_rule"]
    candidate_records = []
    selected_key: tuple[Any, ...] | None = None
    selected_record: dict[str, Any] | None = None
    selected_parameters: list[dict[str, np.ndarray]] | None = None
    selected_models: list[Any] | None = None

    for embedding_width in grid["embedding_width"]:
        for temperature in grid["contrastive_temperature"]:
            checkpoint_sets = []
            trained_models = []
            for seed in grid["training_seeds"]:
                model = diversity.DirectedMPNNDiversityEncoder(
                    embedding_width=embedding_width,
                    dropout=protocol["novelty_model"]["architecture"]["dropout"],
                    random_seed=seed,
                )
                checkpoints = model.fit(
                    corpus,
                    temperature=temperature,
                    epochs=grid["maximum_epochs"],
                    learning_rate=grid["learning_rate"][0],
                    weight_decay=grid["weight_decay"][0],
                    random_seed=seed,
                    capture_checkpoints=True,
                )
                checkpoint_sets.append(checkpoints)
                trained_models.append(model)
            for epoch in range(1, grid["maximum_epochs"] + 1):
                epoch_models = []
                checkpoint_digests = []
                member_embeddings = []
                for member_index, seed in enumerate(grid["training_seeds"]):
                    model = diversity.DirectedMPNNDiversityEncoder(
                        embedding_width=embedding_width,
                        dropout=protocol["novelty_model"]["architecture"]["dropout"],
                        random_seed=seed,
                    )
                    model.parameters = {
                        name: value.copy()
                        for name, value in checkpoint_sets[member_index][
                            epoch - 1
                        ].items()
                    }
                    model.training_summary = {
                        "training_only": True,
                        "validated": False,
                        "epochs_completed": epoch,
                        "source_rows": corpus.row_count,
                        "nonnull_exact_decision_rows": corpus.labeled_row_count,
                        "literal_digest_groups": corpus.literal_digest_group_count,
                        "eligible_digest_groups": corpus.eligible_group_count,
                        "eligible_rows": corpus.eligible_row_count,
                        "groups_per_batch": diversity.GROUPS_PER_BATCH,
                        "rows_per_group_per_epoch": diversity.ROWS_PER_GROUP,
                    }
                    epoch_models.append(model)
                    checkpoint_digests.append(
                        diversity._parameters_digest(model.parameters)
                    )
                    member_embeddings.append(
                        embed_in_batches(model, all_nodes, all_adjacency)
                    )
                for lambda_weight in lambda_grid:
                    result = simulate_novelty(
                        rows=rows,
                        streams=streams,
                        controls=controls,
                        equality_logits=equality_logits,
                        member_embeddings=member_embeddings,
                        lambda_weight=lambda_weight,
                        diversity=diversity,
                    )
                    quotient_ratio = ratio(
                        result["total_quotient_unique"],
                        equality_result["total_quotient_unique"],
                    )
                    literal_ratio = ratio(
                        result["total_literal_unique"],
                        random_result["total_literal_unique"],
                    )
                    literal_difference = (
                        result["target_macro_literal_unique"]
                        - equality_result["target_macro_literal_unique"]
                    )
                    quotient_difference = (
                        result["target_macro_quotient_unique"]
                        - equality_result["target_macro_quotient_unique"]
                    )
                    feasible = quotient_ratio >= 0.95 and literal_ratio >= 0.95
                    record = {
                        "embedding_width": embedding_width,
                        "contrastive_temperature": temperature,
                        "epoch": epoch,
                        "lambda": lambda_weight,
                        "member_checkpoint_sha256": checkpoint_digests,
                        "metrics": metric_projection(
                            result,
                            include_streams=False,
                        ),
                        "quotient_ratio_to_equality": quotient_ratio,
                        "literal_ratio_to_random": literal_ratio,
                        "target_macro_literal_difference_vs_equality": (
                            literal_difference
                        ),
                        "target_macro_quotient_difference_vs_equality": (
                            quotient_difference
                        ),
                        "feasible": feasible,
                    }
                    candidate_records.append(record)
                    if feasible:
                        key = (
                            -literal_difference,
                            -quotient_difference,
                            embedding_width,
                            temperature,
                            epoch,
                            lambda_weight,
                        )
                        if selected_key is None or key < selected_key:
                            selected_key = key
                            selected_record = copy.deepcopy(record)
                            selected_parameters = [
                                {
                                    name: value.copy()
                                    for name, value in model.parameters.items()
                                }
                                for model in epoch_models
                            ]
                            selected_models = epoch_models
            print(
                json.dumps(
                    {
                        "phase": "grid_configuration_complete",
                        "embedding_width": embedding_width,
                        "contrastive_temperature": temperature,
                        "candidate_records": len(candidate_records),
                        "feasible_records": sum(
                            record["feasible"] for record in candidate_records
                        ),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    selected_trace = None
    if selected_record is not None and selected_parameters is not None:
        selected_models = []
        for member_index, seed in enumerate(grid["training_seeds"]):
            model = diversity.DirectedMPNNDiversityEncoder(
                embedding_width=selected_record["embedding_width"],
                dropout=protocol["novelty_model"]["architecture"]["dropout"],
                random_seed=seed,
            )
            model.parameters = selected_parameters[member_index]
            model.training_summary = {
                "training_only": True,
                "validated": False,
                "epochs_completed": selected_record["epoch"],
                "source_rows": corpus.row_count,
                "nonnull_exact_decision_rows": corpus.labeled_row_count,
                "literal_digest_groups": corpus.literal_digest_group_count,
                "eligible_digest_groups": corpus.eligible_group_count,
                "eligible_rows": corpus.eligible_row_count,
                "groups_per_batch": diversity.GROUPS_PER_BATCH,
                "rows_per_group_per_epoch": diversity.ROWS_PER_GROUP,
            }
            selected_models.append(model)
        embeddings = [
            embed_in_batches(model, all_nodes, all_adjacency)
            for model in selected_models
        ]
        selected_trace = simulate_novelty(
            rows=rows,
            streams=streams,
            controls=controls,
            equality_logits=equality_logits,
            member_embeddings=embeddings,
            lambda_weight=selected_record["lambda"],
            diversity=diversity,
        )
        if (
            metric_projection(selected_trace, include_streams=False)
            != selected_record["metrics"]
        ):
            raise ValueError("selected validation simulation does not replay")

    report_payload = {
        "schema_version": GRID_SCHEMA,
        "status": (
            "FEASIBLE_CONFIGURATION_SELECTED"
            if selected_record is not None
            else "NO_FEASIBLE_CONFIGURATION_NO_LAUNCH"
        ),
        "protocol": {
            "path": PROTOCOL_PATH.as_posix(),
            "sha256": file_sha256(repo_root / PROTOCOL_PATH),
        },
        "training_source": {
            "path": TRAINING_EVENTS.as_posix(),
            "sha256": corpus.source_sha256,
            "source_rows": corpus.row_count,
            "nonnull_exact_decision_rows": corpus.labeled_row_count,
            "literal_digest_groups": corpus.literal_digest_group_count,
            "eligible_digest_groups": corpus.eligible_group_count,
            "eligible_rows": corpus.eligible_row_count,
            "validation_rows_used_for_gradient_updates": 0,
        },
        "validation_source": {
            "directory": launch["output_directory"],
            "completion_sha256": load_canonical_json(
                repo_root / launch["output_directory"] / "VALIDATION_COMPLETE.json"
            )["completion_sha256"],
            "registry_sha256": registry["registry_sha256"],
            "label_count": len(rows),
            "test_data_generated": False,
        },
        "grid": {
            "embedding_width": grid["embedding_width"],
            "contrastive_temperature": grid["contrastive_temperature"],
            "epochs": list(range(1, grid["maximum_epochs"] + 1)),
            "lambda": lambda_grid,
            "training_seeds": grid["training_seeds"],
            "candidate_record_count": len(candidate_records),
        },
        "baselines": {
            "structural_random": metric_projection(
                random_result,
                include_streams=True,
            ),
            "frozen_equality": metric_projection(
                equality_result,
                include_streams=True,
            ),
        },
        "candidates": candidate_records,
        "selection_rule": selection_rule,
        "selected": selected_record,
        "selected_validation_trace": (
            metric_projection(selected_trace, include_streams=True)
            if selected_trace is not None
            else None
        ),
        "no_feasible_configuration_policy": "NO_LAUNCH",
        "test_data_generated": False,
        "paper_evidence": False,
    }
    report = dict(report_payload)
    report["grid_report_id"] = (
        "grid-report-sha256:"
        + hashlib.sha256(canonical_json_bytes(report_payload)).hexdigest()
    )
    return report, selected_record, selected_models


def freeze(
    *,
    repo_root: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    protocol, launch, completion, registry, rows = validation_sources(repo_root)
    completion_file_sha = file_sha256(
        repo_root / launch["output_directory"] / "VALIDATION_COMPLETE.json"
    )
    if output_dir is None:
        output_dir = (
            repo_root
            / "output/research"
            / f"digraph-order7-diversity-model-v2-{completion_file_sha[:12]}"
        )
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        equality, diversity = load_frozen_rankers(repo_root, launch)
        equality_model, equality_record, equality_path = load_equality_ensemble(
            repo_root,
            protocol,
            equality,
        )
        report, selected, selected_models = model_selection(
            repo_root=repo_root,
            protocol=protocol,
            launch=launch,
            registry=registry,
            rows=rows,
            equality=equality,
            diversity=diversity,
            equality_model=equality_model,
        )
        report_reference = write_content_addressed(
            output_dir,
            "selection",
            report,
        )
        if selected is None or selected_models is None:
            package_payload = {
                "schema_version": PACKAGE_SCHEMA,
                "status": "NO_LAUNCH",
                "selection_report": report_reference,
                "validation_completion_file_sha256": completion_file_sha,
                "test_data_generated": False,
                "paper_evidence": False,
                "rerun_allowed": False,
                "overwrite_allowed": False,
            }
            package = dict(package_payload)
            package["package_sha256"] = object_sha256(package_payload)
            write_json_exclusive(output_dir / "MODEL_PACKAGE.json", package)
            return package

        training_path = repo_root / TRAINING_EVENTS
        corpus = diversity.load_contrastive_corpus(training_path)
        ensemble = diversity.DiversityEnsemble(selected_models)
        selection_binding = {
            "grid_report_id": report["grid_report_id"],
            "embedding_width": selected["embedding_width"],
            "contrastive_temperature": selected["contrastive_temperature"],
            "epoch": selected["epoch"],
            "lambda": selected["lambda"],
            "member_checkpoint_sha256": selected["member_checkpoint_sha256"],
        }
        ensemble_record = ensemble.to_record(
            corpus=corpus,
            selection=selection_binding,
        )
        ensemble_reference = write_content_addressed(
            output_dir,
            "ensemble",
            ensemble_record,
        )
        model_card = {
            "schema_version": MODEL_CARD_SCHEMA,
            "status": "FROZEN_VALIDATED_NOVELTY_ENSEMBLE",
            "model_id": ensemble_record["model_id"],
            "purpose": ("target-free graph-novelty component for frozen rank fusion"),
            "selected": selection_binding,
            "training_labels": (
                "historical training-only complete literal-game digest " "equivalence"
            ),
            "training_source_sha256": corpus.source_sha256,
            "validation_use": "checkpoint_and_lambda_selection_only",
            "validation_rows_used_for_gradient_updates": 0,
            "exact_verifier_authority": True,
            "human_preference_measured": False,
            "aesthetic_quality_measured": False,
            "known_scope": "order-7 Digraph Placement frozen grammar",
            "checkpoint_sha256": ensemble_reference["sha256"],
            "selection_report_sha256": report_reference["sha256"],
            "frozen_equality_model_id": equality_record["model_id"],
            "frozen_equality_checkpoint_sha256": file_sha256(equality_path),
            "test_data_generated": False,
            "paper_evidence": False,
        }
        model_card_reference = write_content_addressed(
            output_dir,
            "model_card",
            model_card,
        )
        model_snapshot = launch["model_implementation"]
        source_hashes = {
            entry["repo_relative_path"]: entry["sha256"]
            for entry in model_snapshot["snapshot_files"]
        }
        binding_payload = {
            "schema_version": BINDING_SCHEMA,
            "status": "FROZEN",
            "ensemble": {
                **ensemble_reference,
                "model_id": ensemble_record["model_id"],
            },
            "selection_report": {
                **report_reference,
                "grid_report_id": report["grid_report_id"],
            },
            "protocol_model_bindings": {
                "model_card_sha256": model_card_reference["sha256"],
                "checkpoint_sha256": ensemble_reference["sha256"],
                "feature_source_sha256": source_hashes[
                    "python/partizan/digraph_diversity_ranker.py"
                ],
                "training_registry_sha256": load_canonical_json(
                    repo_root
                    / launch["output_directory"]
                    / "prior_split_identity_registry.json"
                )["historical_training_registry"]["registry_sha256"],
                "validation_registry_sha256": registry["registry_sha256"],
                "package_lock_sha256": source_hashes["pyproject.toml"],
                "training_seeds": protocol["novelty_model"]["finite_grid"][
                    "training_seeds"
                ],
                "checkpoint_selection_rule": protocol["validation_selection"][
                    "selection_rule"
                ],
            },
            "ranker": {
                "kind": "frozen_dual_model_adapter",
                "factory_callable": "build_resource_preflight_diversity_ranker",
                "partizan_commit": model_snapshot["pushed_commit_sha"],
                "source_sha256": source_hashes[
                    "python/partizan/digraph_diversity_ranker.py"
                ],
            },
            "frozen_equality": {
                "model_id": equality_record["model_id"],
                "checkpoint_sha256": file_sha256(equality_path),
            },
            "protocol_sha256": file_sha256(repo_root / PROTOCOL_PATH),
            "validation_completion_file_sha256": completion_file_sha,
            "test_data_generated": False,
        }
        binding = dict(binding_payload)
        binding["binding_sha256"] = object_sha256(binding_payload)
        write_json_exclusive(output_dir / "model_binding.json", binding)
        package_payload = {
            "schema_version": PACKAGE_SCHEMA,
            "status": "FROZEN_VALIDATED_DIVERSITY_MODEL_PACKAGE",
            "model_id": ensemble_record["model_id"],
            "grid_report_id": report["grid_report_id"],
            "selected": selection_binding,
            "partizan_commit": model_snapshot["pushed_commit_sha"],
            "validation_completion_file_sha256": completion_file_sha,
            "validation_completion_sha256": completion["completion_sha256"],
            "artifacts": {
                "selection_report": report_reference,
                "ensemble": ensemble_reference,
                "model_card": model_card_reference,
                "model_binding": {
                    "path": "model_binding.json",
                    "sha256": file_sha256(output_dir / "model_binding.json"),
                },
            },
            "validation_authorized_for_model_selection": True,
            "test_data_generated": False,
            "paper_evidence": False,
            "rerun_allowed": False,
            "overwrite_allowed": False,
        }
        package = dict(package_payload)
        package["package_sha256"] = object_sha256(package_payload)
        write_json_exclusive(output_dir / "MODEL_PACKAGE.json", package)
        return package
    except BaseException as error:
        failure_payload = {
            "schema_version": FAILURE_SCHEMA,
            "status": "FAILED_CLOSED",
            "error_type": type(error).__name__,
            "error": str(error),
            "resume_allowed": False,
            "test_data_generated": False,
            "paper_evidence": False,
        }
        failure = dict(failure_payload)
        failure["failure_sha256"] = object_sha256(failure_payload)
        try:
            write_json_exclusive(output_dir / "FAILURE.json", failure)
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = None
    if args.output is not None:
        output = (
            args.output if args.output.is_absolute() else (repo_root / args.output)
        ).resolve()
    package = freeze(repo_root=repo_root, output_dir=output)
    print(json.dumps(package, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
