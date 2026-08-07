#!/usr/bin/env python3
"""Train and freeze the Domineering equality ensemble without evaluation access."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

import numpy as np
import torch
from torch.nn import functional as F

from domineering_exact_v1 import DomineeringPosition, game_from_position
from domineering_scope_model_v1 import (
    Architecture,
    DomineeringEqualityCNN,
    candidate_arrays,
    macro_auc,
    macro_brier,
    parameter_count,
    select_equality_policy,
    select_novelty_policy,
    target_descriptor_array,
)
from fixed_value_scope_protocol_v1 import (
    artifact_sha256,
    candidate_bucket,
    canonical_json_bytes,
    load_json,
    validate_protocol,
)
from short_game_fiber_pilot import equal


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_amendments(
    protocol: dict[str, Any], amendment: dict[str, Any], clarification: dict[str, Any]
) -> None:
    if validate_protocol(protocol)["status"] != "PASS":
        raise ValueError("scope protocol does not replay")
    if amendment.get("artifact_sha256") != artifact_sha256(amendment):
        raise ValueError("scope implementation amendment hash differs")
    if clarification.get("artifact_sha256") != artifact_sha256(clarification):
        raise ValueError("scope clarification hash differs")
    if amendment.get("parent_protocol_artifact_sha256") != protocol["artifact_sha256"]:
        raise ValueError("scope amendment parent differs")
    if clarification.get("parent_amendment_artifact_sha256") != amendment["artifact_sha256"]:
        raise ValueError("scope clarification parent differs")


def target_games(protocol: dict[str, Any]) -> list[Any]:
    return [
        game_from_position(DomineeringPosition(3, 3, target["calibration_representative_mask"]))
        for target in protocol["cross_family_experiment"]["targets"]
    ]


def build_bank(
    protocol: dict[str, Any], buckets: range
) -> dict[str, Any]:
    positions = [
        DomineeringPosition(4, 4, mask)
        for mask in range(1 << 16)
        if candidate_bucket(DomineeringPosition(4, 4, mask)) in buckets
    ]
    grids, scalars, quotients, descriptor_cells = candidate_arrays(positions)
    targets = target_games(protocol)
    labels = np.zeros((len(positions), len(targets)), dtype=np.uint8)
    for candidate_index, position in enumerate(positions):
        candidate = game_from_position(position)
        for target_index, target in enumerate(targets):
            labels[candidate_index, target_index] = equal(candidate, target)
    return {
        "masks": np.asarray([position.mask for position in positions], dtype=np.uint16),
        "grids": grids,
        "scalars": scalars,
        "quotients": quotients,
        "descriptor_cells": descriptor_cells,
        "labels": labels,
    }


def predict(
    model: DomineeringEqualityCNN,
    bank: dict[str, Any],
    target_descriptors: np.ndarray,
    batch_size: int,
) -> np.ndarray:
    model.eval()
    probabilities = np.zeros(bank["labels"].shape, dtype=np.float32)
    grids = torch.from_numpy(bank["grids"])
    scalars = torch.from_numpy(bank["scalars"])
    descriptors = torch.from_numpy(target_descriptors)
    with torch.no_grad():
        for target_index in range(probabilities.shape[1]):
            for start in range(0, len(grids), batch_size):
                stop = min(start + batch_size, len(grids))
                indices = torch.full((stop - start,), target_index, dtype=torch.long)
                logits = model(
                    grids[start:stop],
                    scalars[start:stop],
                    indices,
                    descriptors[indices],
                )
                probabilities[start:stop, target_index] = torch.sigmoid(logits).numpy()
    return probabilities


def train_one(
    architecture: Architecture,
    seed: int,
    train_bank: dict[str, Any],
    tuning_bank: dict[str, Any],
    target_descriptors: np.ndarray,
    settings: dict[str, Any],
) -> tuple[DomineeringEqualityCNN, dict[str, Any]]:
    torch.manual_seed(seed)
    np.random.seed(seed % (2**32))
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    model = DomineeringEqualityCNN(architecture)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=settings["learning_rate"],
        weight_decay=settings["weight_decay"],
    )
    labels = train_bank["labels"]
    positive = labels.sum(axis=0).astype(np.float32)
    negative = len(labels) - positive
    if np.any(positive == 0) or np.any(negative == 0):
        raise ValueError("training bank lacks both classes for a target")
    positive_weight = torch.from_numpy(negative / positive)
    grids = torch.from_numpy(train_bank["grids"])
    scalars = torch.from_numpy(train_bank["scalars"])
    descriptors = torch.from_numpy(target_descriptors)
    flat_labels = torch.from_numpy(labels.reshape(-1).astype(np.float32))
    target_count = labels.shape[1]
    pair_count = len(flat_labels)
    generator = torch.Generator().manual_seed(seed)

    best: dict[str, Any] | None = None
    epochs_without_improvement = 0
    history = []
    for epoch in range(settings["maximum_epochs"]):
        model.train()
        permutation = torch.randperm(pair_count, generator=generator)
        total_loss = 0.0
        for start in range(0, pair_count, settings["batch_size"]):
            pair_indices = permutation[start : start + settings["batch_size"]]
            candidate_indices = torch.div(pair_indices, target_count, rounding_mode="floor")
            target_indices = pair_indices % target_count
            truth = flat_labels[pair_indices]
            logits = model(
                grids[candidate_indices],
                scalars[candidate_indices],
                target_indices,
                descriptors[target_indices],
            )
            losses = F.binary_cross_entropy_with_logits(logits, truth, reduction="none")
            weights = torch.where(truth > 0.5, positive_weight[target_indices], 1.0)
            loss = torch.mean(losses * weights)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), settings["gradient_clip_norm"])
            optimizer.step()
            total_loss += float(loss.detach()) * len(pair_indices)

        tuning_probabilities = predict(
            model, tuning_bank, target_descriptors, settings["batch_size"]
        )
        auc = macro_auc(tuning_bank["labels"], tuning_probabilities)
        brier = macro_brier(tuning_bank["labels"], tuning_probabilities)
        record = {
            "epoch": epoch + 1,
            "training_weighted_bce": total_loss / pair_count,
            "tuning_macro_roc_auc": auc,
            "tuning_macro_brier": brier,
        }
        history.append(record)
        key = (auc, -brier)
        if best is None or key > best["key"]:
            best = {
                "key": key,
                "epoch": epoch + 1,
                "state": copy.deepcopy(model.state_dict()),
                "probabilities": tuning_probabilities.copy(),
                "metrics": record,
            }
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
        if epochs_without_improvement >= settings["early_stopping_patience"]:
            break

    if best is None:
        raise ValueError("model training produced no checkpoint")
    model.load_state_dict(best["state"])
    return model, {
        "selected_epoch": best["epoch"],
        "tuning_macro_roc_auc": best["metrics"]["tuning_macro_roc_auc"],
        "tuning_macro_brier": best["metrics"]["tuning_macro_brier"],
        "history": history,
        "probabilities": best["probabilities"],
        "parameter_count": parameter_count(model),
        "positive_count_by_target": [int(value) for value in positive],
    }


def seeded_policy_seed(base_seed: int, target_index: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"domineering-scope-policy:{base_seed}:{target_index}".encode("ascii")).digest()[:8],
        "big",
    )


def selection_metrics(
    labels: np.ndarray,
    quotients: list[str],
    choices_by_target_seed: list[tuple[int, int, np.ndarray]],
) -> dict[str, float]:
    certified_literals = []
    certified_quotients = []
    for target_index, _, choices in choices_by_target_seed:
        exact = labels[choices, target_index].astype(bool)
        certified_literals.append(int(exact.sum()))
        certified_quotients.append(
            len({quotients[index] for index in choices[exact]})
        )
    return {
        "mean_certified_literals": float(np.mean(certified_literals)),
        "mean_certified_ruleset_quotients": float(np.mean(certified_quotients)),
    }


def tune_policy(
    protocol: dict[str, Any],
    amendment: dict[str, Any],
    tuning_bank: dict[str, Any],
    probabilities: np.ndarray,
) -> dict[str, Any]:
    contract = amendment["policy_tuning"]
    budget = contract["selection_budget_per_target_seed"]
    seeds = contract["tuning_seeds"]
    equality_rows = []
    equality_choices: dict[float, list[tuple[int, int, np.ndarray]]] = {}
    for temperature in contract["equality_temperature_grid"]:
        rows = []
        for target_index in range(probabilities.shape[1]):
            for seed in seeds:
                choices = select_equality_policy(
                    probabilities[:, target_index],
                    budget=budget,
                    temperature=temperature,
                    seed=seeded_policy_seed(seed, target_index),
                )
                rows.append((target_index, seed, choices))
        metrics = selection_metrics(
            tuning_bank["labels"], tuning_bank["quotients"], rows
        )
        equality_rows.append({"temperature": temperature, **metrics})
        equality_choices[temperature] = rows
    equality_selected = max(
        equality_rows,
        key=lambda row: (
            row["mean_certified_literals"],
            row["mean_certified_ruleset_quotients"],
            -row["temperature"],
        ),
    )

    novelty_rows = []
    temperature = equality_selected["temperature"]
    for weights in contract["novelty_weight_grid"]:
        rows = []
        for target_index in range(probabilities.shape[1]):
            for seed in seeds:
                choices = select_novelty_policy(
                    probabilities[:, target_index],
                    tuning_bank["quotients"],
                    tuning_bank["descriptor_cells"],
                    budget=budget,
                    temperature=temperature,
                    alpha=weights["alpha"],
                    beta=weights["beta"],
                    seed=seeded_policy_seed(seed, target_index),
                )
                rows.append((target_index, seed, choices))
        metrics = selection_metrics(
            tuning_bank["labels"], tuning_bank["quotients"], rows
        )
        literal_ratio = (
            metrics["mean_certified_literals"]
            / equality_selected["mean_certified_literals"]
        )
        novelty_rows.append({**weights, **metrics, "certified_literal_ratio": literal_ratio})
    eligible = [row for row in novelty_rows if row["certified_literal_ratio"] >= 0.90]
    selected = None
    if eligible:
        selected = max(
            eligible,
            key=lambda row: (
                row["mean_certified_ruleset_quotients"],
                row["mean_certified_literals"],
                -temperature,
                -row["alpha"],
                -row["beta"],
            ),
        )
    return {
        "equality_grid": equality_rows,
        "selected_equality": equality_selected,
        "novelty_grid": novelty_rows,
        "selected_novelty": selected,
        "evaluation_authorized": selected is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json"))
    parser.add_argument("--amendment", type=Path, default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_1_AMENDMENT.json"))
    parser.add_argument("--clarification", type=Path, default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_2_CLARIFICATION.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/research/fixed-value-scope-v1/training"))
    args = parser.parse_args()
    protocol = load_json(args.protocol)
    amendment = load_json(args.amendment)
    clarification = load_json(args.clarification)
    validate_amendments(protocol, amendment, clarification)
    if args.output_dir.exists():
        raise ValueError("scope training output already exists")
    args.output_dir.mkdir(parents=True)

    started = time.perf_counter()
    train_bank = build_bank(protocol, range(1, 26))
    tuning_bank = build_bank(protocol, range(26, 41))
    expected = amendment["data_contract"]
    if len(train_bank["masks"]) != expected["training_candidate_count"] or len(tuning_bank["masks"]) != expected["tuning_candidate_count"]:
        raise ValueError("scope training partition differs")
    if train_bank["labels"].size != expected["training_exact_labels"] or tuning_bank["labels"].size != expected["tuning_exact_labels"]:
        raise ValueError("scope exact-label contract differs")

    np.save(args.output_dir / "training_masks.npy", train_bank["masks"], allow_pickle=False)
    np.save(args.output_dir / "training_labels.npy", train_bank["labels"], allow_pickle=False)
    np.save(args.output_dir / "tuning_masks.npy", tuning_bank["masks"], allow_pickle=False)
    np.save(args.output_dir / "tuning_labels.npy", tuning_bank["labels"], allow_pickle=False)

    settings = amendment["model_grid"]
    target_descriptors = target_descriptor_array(protocol["cross_family_experiment"]["targets"])
    model_rows = []
    model_objects: dict[tuple[str, int], DomineeringEqualityCNN] = {}
    probability_rows: dict[tuple[str, int], np.ndarray] = {}
    for architecture_row in settings["architectures"]:
        architecture = Architecture(**architecture_row)
        for seed in settings["ensemble_seeds"]:
            model, metrics = train_one(
                architecture,
                seed,
                train_bank,
                tuning_bank,
                target_descriptors,
                settings,
            )
            checkpoint_path = args.output_dir / f"{architecture.architecture_id}-s{seed}.pt"
            torch.save(
                {
                    "schema_version": "partizan.domineering_equality_checkpoint.v1",
                    "architecture": architecture_row,
                    "seed": seed,
                    "protocol_artifact_sha256": protocol["artifact_sha256"],
                    "amendment_artifact_sha256": amendment["artifact_sha256"],
                    "clarification_artifact_sha256": clarification["artifact_sha256"],
                    "state_dict": model.state_dict(),
                },
                checkpoint_path,
            )
            row = {
                "architecture_id": architecture.architecture_id,
                "seed": seed,
                "selected_epoch": metrics["selected_epoch"],
                "tuning_macro_roc_auc": metrics["tuning_macro_roc_auc"],
                "tuning_macro_brier": metrics["tuning_macro_brier"],
                "parameter_count": metrics["parameter_count"],
                "training_positive_count_by_target": metrics["positive_count_by_target"],
                "checkpoint": {
                    "path": checkpoint_path.name,
                    "bytes": checkpoint_path.stat().st_size,
                    "file_sha256": file_sha256(checkpoint_path),
                },
                "history": metrics["history"],
            }
            model_rows.append(row)
            model_objects[(architecture.architecture_id, seed)] = model
            probability_rows[(architecture.architecture_id, seed)] = metrics["probabilities"]

    architecture_scores = []
    for architecture_row in settings["architectures"]:
        architecture_id = architecture_row["architecture_id"]
        rows = [row for row in model_rows if row["architecture_id"] == architecture_id]
        architecture_scores.append(
            {
                "architecture_id": architecture_id,
                "mean_tuning_macro_roc_auc": float(np.mean([row["tuning_macro_roc_auc"] for row in rows])),
                "mean_tuning_macro_brier": float(np.mean([row["tuning_macro_brier"] for row in rows])),
                "parameter_count": rows[0]["parameter_count"],
            }
        )
    selected_architecture = max(
        architecture_scores,
        key=lambda row: (
            row["mean_tuning_macro_roc_auc"],
            -row["mean_tuning_macro_brier"],
            -row["parameter_count"],
            row["architecture_id"],
        ),
    )
    selected_probabilities = np.mean(
        [
            probability_rows[(selected_architecture["architecture_id"], seed)]
            for seed in settings["ensemble_seeds"]
        ],
        axis=0,
    )
    policy = tune_policy(protocol, amendment, tuning_bank, selected_probabilities)
    elapsed = time.perf_counter() - started
    authority = {
        "schema_version": "partizan.domineering_scope_model_freeze.v1",
        "status": "MODEL_AND_POLICY_FROZEN_BEFORE_EVALUATION" if policy["evaluation_authorized"] else "STOP_NO_NOVELTY_POLICY_PASSED_TUNING",
        "protocol_artifact_sha256": protocol["artifact_sha256"],
        "amendment_artifact_sha256": amendment["artifact_sha256"],
        "clarification_artifact_sha256": clarification["artifact_sha256"],
        "training_candidate_count": len(train_bank["masks"]),
        "tuning_candidate_count": len(tuning_bank["masks"]),
        "training_exact_label_count": int(train_bank["labels"].size),
        "tuning_exact_label_count": int(tuning_bank["labels"].size),
        "evaluation_candidate_labels_opened": 0,
        "evaluation_exact_verifier_calls": 0,
        "model_grid": model_rows,
        "architecture_scores": architecture_scores,
        "selected_architecture": selected_architecture,
        "selected_checkpoint_files": [
            row["checkpoint"]
            for row in model_rows
            if row["architecture_id"] == selected_architecture["architecture_id"]
        ],
        "policy_freeze": policy,
        "elapsed_seconds": elapsed,
        "paper_state_changed": False,
        "v5_test_material_opened": False,
        "modal_used": False,
    }
    authority["artifact_sha256"] = artifact_sha256(authority)
    authority_path = args.output_dir / "MODEL_FREEZE_AUTHORITY_V1.json"
    authority_path.write_bytes(canonical_json_bytes(authority) + b"\n")
    print(json.dumps({key: value for key, value in authority.items() if key != "model_grid"}, indent=2, sort_keys=True))
    return 0 if policy["evaluation_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
