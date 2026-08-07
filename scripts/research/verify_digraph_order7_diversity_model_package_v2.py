#!/usr/bin/env python3
"""Independently verify the frozen diversity-policy V2 model package."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import freeze_digraph_order7_diversity_model_v2 as freezer


SCHEMA = "partizan.digraph_order7_diversity_model_verification.v2"
DEFAULT_MODEL_DIR = Path(
    "output/research/digraph-order7-diversity-model-v2-3cf1bb0ba101"
)
VERIFICATION_NAME = "MODEL_PACKAGE_VERIFICATION.json"
TARGETS = ("0", "*", "{0|1}")


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
        raise ValueError(f"{path}: expected canonical newline JSON")
    return value


def verify_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


def safe_artifact(model_dir: Path, reference: Mapping[str, Any]) -> Path:
    relative = Path(str(reference.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("model artifact path is unsafe")
    path = model_dir / relative
    if (
        not path.is_file()
        or file_sha256(path) != reference.get("sha256")
        or path.stat().st_size != reference.get("bytes")
    ):
        raise ValueError("model artifact binding changed")
    return path


def verify_grid(
    report: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        report.get("schema_version") != freezer.GRID_SCHEMA
        or report.get("status") != "FEASIBLE_CONFIGURATION_SELECTED"
        or report.get("test_data_generated") is not False
        or report.get("paper_evidence") is not False
    ):
        raise ValueError("grid report boundary changed")
    payload = dict(report)
    supplied_id = payload.pop("grid_report_id", None)
    expected_id = (
        "grid-report-sha256:"
        + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    )
    if supplied_id != expected_id:
        raise ValueError("grid report id does not replay")
    frozen = protocol["novelty_model"]["finite_grid"]
    lambdas = protocol["acquisition"]["lambda_grid"]
    expected_keys = {
        (width, temperature, epoch, lambda_weight)
        for width in frozen["embedding_width"]
        for temperature in frozen["contrastive_temperature"]
        for epoch in range(1, frozen["maximum_epochs"] + 1)
        for lambda_weight in lambdas
    }
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(expected_keys):
        raise ValueError("grid candidate count changed")
    observed_keys = set()
    feasible = []
    checkpoint_by_epoch: dict[tuple[int, float, int], list[str]] = {}
    equality = report["baselines"]["frozen_equality"]
    random = report["baselines"]["structural_random"]
    for record in candidates:
        key = (
            record["embedding_width"],
            record["contrastive_temperature"],
            record["epoch"],
            record["lambda"],
        )
        if key in observed_keys:
            raise ValueError("grid contains a duplicate configuration")
        observed_keys.add(key)
        epoch_key = key[:3]
        checkpoints = record["member_checkpoint_sha256"]
        if (
            not isinstance(checkpoints, list)
            or len(checkpoints) != 3
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in checkpoints
            )
        ):
            raise ValueError("grid checkpoint digest changed")
        if epoch_key in checkpoint_by_epoch:
            if checkpoint_by_epoch[epoch_key] != checkpoints:
                raise ValueError("lambda changed an epoch checkpoint")
        else:
            checkpoint_by_epoch[epoch_key] = checkpoints
        metrics = record["metrics"]
        quotient_ratio = freezer.ratio(
            metrics["total_quotient_unique"],
            equality["total_quotient_unique"],
        )
        literal_ratio = freezer.ratio(
            metrics["total_literal_unique"],
            random["total_literal_unique"],
        )
        literal_difference = (
            metrics["target_macro_literal_unique"]
            - equality["target_macro_literal_unique"]
        )
        quotient_difference = (
            metrics["target_macro_quotient_unique"]
            - equality["target_macro_quotient_unique"]
        )
        expected_feasible = quotient_ratio >= 0.95 and literal_ratio >= 0.95
        if (
            record["quotient_ratio_to_equality"] != quotient_ratio
            or record["literal_ratio_to_random"] != literal_ratio
            or record["target_macro_literal_difference_vs_equality"]
            != literal_difference
            or record["target_macro_quotient_difference_vs_equality"]
            != quotient_difference
            or record["feasible"] is not expected_feasible
        ):
            raise ValueError("grid feasibility or selector metric changed")
        if expected_feasible:
            feasible.append(record)
    if observed_keys != expected_keys:
        raise ValueError("grid is not the complete frozen Cartesian product")
    if not feasible:
        raise ValueError("grid has no feasible configuration")
    selected = min(
        feasible,
        key=lambda record: (
            -record["target_macro_literal_difference_vs_equality"],
            -record["target_macro_quotient_difference_vs_equality"],
            record["embedding_width"],
            record["contrastive_temperature"],
            record["epoch"],
            record["lambda"],
        ),
    )
    if report.get("selected") != selected:
        raise ValueError("grid selected record does not follow frozen ordering")
    if (
        report.get("selection_rule")
        != protocol["validation_selection"]["selection_rule"]
    ):
        raise ValueError("grid selection rule changed")
    return {
        "grid_report_id": supplied_id,
        "candidate_count": len(candidates),
        "feasible_count": len(feasible),
        "selected": selected,
    }


def midrank(values: list[float]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    order = np.argsort(array, kind="mergesort")
    output = np.empty(len(array), dtype=np.float64)
    start = 0
    while start < len(array):
        end = start + 1
        while end < len(array) and array[order[end]] == array[order[start]]:
            end += 1
        output[order[start:end]] = (
            (start + end - 1) / 2.0 / (len(array) - 1) if len(array) > 1 else 0.5
        )
        start = end
    return output


def structural_tier(
    rows: list[dict[str, Any]],
    indices: list[int],
    live: set[str],
) -> tuple[int, list[int]]:
    for tier in range(4):
        eligible = []
        for index in indices:
            row = rows[index]
            conditions = (
                row["weakly_connected"],
                not row["prior_split_candidate_collision"],
                row["candidate_sha256"] not in live,
            )
            if (
                (tier == 0 and all(conditions))
                or (tier == 1 and all(conditions[:2]))
                or (tier == 2 and conditions[1])
                or tier == 3
            ):
                eligible.append(index)
        if eligible:
            return tier, eligible
    raise AssertionError("structural tiers are exhaustive")


def independent_selected_replay(
    *,
    rows: list[dict[str, Any]],
    streams: list[tuple[str, int, list[list[int]]]],
    controls: Mapping[str, Mapping[str, Any]],
    equality_logits: np.ndarray,
    embeddings: list[np.ndarray],
    lambda_weight: float,
) -> dict[str, Any]:
    row_count = len(rows)
    stage_indices = {target: row_count + index for index, target in enumerate(TARGETS)}
    results = []
    for target, pair_seed, pools in streams:
        live = {controls[target]["candidate_sha256"]}
        memory = [stage_indices[target]]
        quotients: set[str] = set()
        literals: set[str] = set()
        tier_counts: dict[int, int] = {}
        selected = []
        selected_scores = []
        for indices in pools:
            tier, eligible = structural_tier(rows, indices, live)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            equality_values = [float(equality_logits[index]) for index in eligible]
            novelty_values = []
            for index in eligible:
                distances = []
                for member in embeddings:
                    cosine = np.clip(member[memory] @ member[index], -1.0, 1.0)
                    distances.append(float(np.min(1.0 - cosine)))
                novelty_values.append(float(np.mean(distances)))
            fused = midrank(equality_values) + lambda_weight * midrank(novelty_values)
            offset = min(
                range(len(eligible)),
                key=lambda position: (
                    -float(fused[position]),
                    rows[eligible[position]]["candidate_sha256"],
                ),
            )
            selected_index = eligible[offset]
            row = rows[selected_index]
            selected.append(row["candidate_sha256"])
            selected_scores.append(
                {
                    "equality_logit": equality_values[offset],
                    "novelty_score": novelty_values[offset],
                    "rank_fusion_score": float(fused[offset]),
                }
            )
            identity = freezer.discovery_identity(row)
            if identity is not None:
                quotient, literal = identity
                quotients.add(quotient)
                literals.add(literal)
                live.add(row["candidate_sha256"])
                memory.append(selected_index)
        results.append(
            {
                "target": target,
                "pair_seed": pair_seed,
                "quotient_unique": len(quotients),
                "literal_unique": len(literals),
                "tier_counts": {
                    str(key): tier_counts[key] for key in sorted(tier_counts)
                },
                "memory_size_final": len(memory),
                "selected_candidate_sha256": selected,
                "selected_scores": selected_scores,
            }
        )
    return freezer.summarize_streams(results)


def verify_package(
    *,
    repo_root: Path,
    model_dir: Path,
) -> dict[str, Any]:
    protocol, launch, completion, registry, rows = freezer.validation_sources(repo_root)
    package = load_canonical_json(model_dir / "MODEL_PACKAGE.json")
    verify_self_hash(package, "package_sha256", label="model package")
    if (
        package.get("schema_version") != freezer.PACKAGE_SCHEMA
        or package.get("status") != "FROZEN_VALIDATED_DIVERSITY_MODEL_PACKAGE"
        or package.get("test_data_generated") is not False
        or package.get("paper_evidence") is not False
        or package.get("rerun_allowed") is not False
        or package.get("overwrite_allowed") is not False
    ):
        raise ValueError("model package boundary changed")
    artifacts = package["artifacts"]
    report_path = safe_artifact(model_dir, artifacts["selection_report"])
    ensemble_path = safe_artifact(model_dir, artifacts["ensemble"])
    model_card_path = safe_artifact(model_dir, artifacts["model_card"])
    binding_path = model_dir / artifacts["model_binding"]["path"]
    if file_sha256(binding_path) != artifacts["model_binding"]["sha256"]:
        raise ValueError("model binding artifact changed")

    report = load_canonical_json(report_path)
    grid = verify_grid(report, protocol)
    if package["grid_report_id"] != grid["grid_report_id"] or package["selected"] != {
        "grid_report_id": grid["grid_report_id"],
        "embedding_width": grid["selected"]["embedding_width"],
        "contrastive_temperature": grid["selected"]["contrastive_temperature"],
        "epoch": grid["selected"]["epoch"],
        "lambda": grid["selected"]["lambda"],
        "member_checkpoint_sha256": grid["selected"]["member_checkpoint_sha256"],
    }:
        raise ValueError("package selection binding changed")

    equality, diversity = freezer.load_frozen_rankers(repo_root, launch)
    ensemble_record = load_canonical_json(ensemble_path)
    ensemble = diversity.DiversityEnsemble.from_record(ensemble_record)
    if (
        ensemble_record["model_id"] != package["model_id"]
        or ensemble_record["selection"] != package["selected"]
    ):
        raise ValueError("ensemble identity or selection changed")

    model_card = load_canonical_json(model_card_path)
    if (
        model_card.get("schema_version") != freezer.MODEL_CARD_SCHEMA
        or model_card.get("checkpoint_sha256") != artifacts["ensemble"]["sha256"]
        or model_card.get("selection_report_sha256")
        != artifacts["selection_report"]["sha256"]
        or model_card.get("validation_rows_used_for_gradient_updates") != 0
        or model_card.get("test_data_generated") is not False
        or model_card.get("paper_evidence") is not False
    ):
        raise ValueError("model card boundary changed")
    binding = load_canonical_json(binding_path)
    verify_self_hash(binding, "binding_sha256", label="model binding")
    required = protocol["novelty_model"]["required_binding_fields"]
    if set(binding["protocol_model_bindings"]) != set(required):
        raise ValueError("protocol model binding fields changed")
    if (
        binding["protocol_model_bindings"]["validation_registry_sha256"]
        != registry["registry_sha256"]
        or binding["test_data_generated"] is not False
    ):
        raise ValueError("model binding validation boundary changed")

    equality_model, _record, _path = freezer.load_equality_ensemble(
        repo_root,
        protocol,
        equality,
    )
    nodes, adjacency, target_indices = freezer.validation_arrays(
        rows,
        equality,
        diversity,
    )
    equality_logits = equality_model.predict_logits(
        nodes,
        adjacency,
        target_indices,
    )
    prior = load_canonical_json(
        repo_root / launch["output_directory"] / "prior_split_identity_registry.json"
    )
    controls = freezer.stage0_rows(prior)
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
    member_embeddings = [
        freezer.embed_in_batches(member, all_nodes, all_adjacency)
        for member in ensemble.members
    ]
    selected_replay = independent_selected_replay(
        rows=rows,
        streams=freezer.pool_streams(rows, protocol),
        controls=controls,
        equality_logits=equality_logits,
        embeddings=member_embeddings,
        lambda_weight=package["selected"]["lambda"],
    )
    expected_trace = report["selected_validation_trace"]
    for field in (
        "stream_count",
        "total_quotient_unique",
        "total_literal_unique",
        "target_mean",
        "target_macro_quotient_unique",
        "target_macro_literal_unique",
        "streams",
    ):
        if selected_replay[field] != expected_trace[field]:
            raise ValueError(f"selected validation replay changed: {field}")
    if (
        freezer.metric_projection(selected_replay, include_streams=False)
        != grid["selected"]["metrics"]
    ):
        raise ValueError("selected validation metric projection changed")
    return {
        "schema_version": SCHEMA,
        "status": "PASS_MODEL_PACKAGE_ONLY",
        "model_package_sha256": package["package_sha256"],
        "model_id": package["model_id"],
        "grid_report_id": package["grid_report_id"],
        "complete_grid_replay": True,
        "selection_rule_replay": True,
        "ensemble_checkpoint_digest_replay": True,
        "model_card_and_binding_replay": True,
        "selected_scores_embeddings_memory_and_rank_fusion_replay": True,
        "grid_candidate_count": grid["candidate_count"],
        "feasible_candidate_count": grid["feasible_count"],
        "selected_validation": {
            "total_quotient_unique": selected_replay["total_quotient_unique"],
            "total_literal_unique": selected_replay["total_literal_unique"],
            "target_macro_quotient_unique": selected_replay[
                "target_macro_quotient_unique"
            ],
            "target_macro_literal_unique": selected_replay[
                "target_macro_literal_unique"
            ],
        },
        "validation_rows_used_for_gradient_updates": 0,
        "test_data_generated": False,
        "paper_evidence": False,
    }


def write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = dict(value)
    payload["verification_sha256"] = object_sha256(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_line(payload))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    model_dir = (
        args.model_dir if args.model_dir.is_absolute() else repo_root / args.model_dir
    ).resolve()
    verification = verify_package(repo_root=repo_root, model_dir=model_dir)
    write_exclusive(model_dir / VERIFICATION_NAME, verification)
    print(json.dumps(verification, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
