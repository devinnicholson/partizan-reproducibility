#!/usr/bin/env python3
"""Independent replay and finalizer for diversity-policy test V2.

The verifier does not import the V2 test generator. It reconstructs the split
registry, proposal RNG, adaptive repertoires, all three acquisition policies,
exact outcomes, novelty memories, discoveries, inference, and the frozen gate.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np

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
import freeze_digraph_order7_diversity_model_v2 as freezer
from semantic_equality_certificate_v1 import artifact_binding
from short_game_fiber_pilot import game_digest, serialize
import verify_digraph_order7_diversity_validation_v2 as validation_verifier
import verify_digraph_order7_fixed_value_transitions_v1 as exact_verifier
import verify_digraph_order7_neural_validation_v1 as v1_validation
import validate_digraph_order7_diversity_policy_protocol_v2 as protocol_validator


SCHEMA = "partizan.digraph_order7_diversity_policy_test.v2"
PROTOCOL_PATH = freezer.PROTOCOL_PATH
MODEL_DIR = Path(
    "output/research/digraph-order7-diversity-model-v2-3cf1bb0ba101"
)
TARGETS = ("0", "*", "{0|1}")
ARMS = (
    "structural_toggle_one_random",
    "neural_toggle_one_equality",
    "neural_toggle_one_equality_novelty",
)
RANDOM_ARM, EQUALITY_ARM, NOVELTY_ARM = ARMS
PREFIX = "partizan.digraph_order7_diversity_policy_comparison.v2"
OFFICIAL_MODE = "authorized_test"
SMOKE_MODE = "smoke_fixture"
SMOKE_PREFIX = f"{SCHEMA}.smoke"
LEGACY_FIXTURE_PREFIX = "partizan.digraph_order7_neural_policy_test.v1.smoke"
CHECKPOINTS = (128, 512, 1024, 2048)
ZERO_SHA256 = "0" * 64
ARC_LIST = tuple(
    (source, target)
    for source in range(7)
    for target in range(7)
    if source != target
)
CORRUPTION_FAMILIES = (
    "protocol_identity",
    "launch_authorization",
    "source_snapshot",
    "validation_completion",
    "validation_registry",
    "model_package",
    "model_verification",
    "resource_preflight",
    "split_seed",
    "target_arm_schedule",
    "parent_rng",
    "arc_permutation",
    "candidate_graph",
    "candidate_identity",
    "structural_tier",
    "equality_logit",
    "novelty_embedding",
    "novelty_memory",
    "rank_fusion",
    "selected_slot",
    "exact_decision",
    "literal_digest",
    "quotient_or_descriptor",
    "retention_or_transition",
    "hash_chain_or_endpoint",
    "stream_inference_or_gate",
)


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


def safe_binding(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    label: str,
) -> Path:
    relative = Path(str(binding.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path is unsafe")
    path = repo_root / relative
    if not path.is_file() or file_sha256(path) != binding.get("sha256"):
        raise ValueError(f"{label} binding changed")
    return path


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
        raise ValueError("independent randbelow population is empty")
    modulus = 1 << 256
    limit = modulus - modulus % size
    counter = 0
    while True:
        value = int.from_bytes(
            hashlib.sha256(
                (
                    f"{prefix}|{phase}|{target}|{pair_seed}|{unit_index}|"
                    f"{draw_name}|{counter}"
                ).encode("utf-8")
            ).digest(),
            "big",
        )
        if value < limit:
            return value % size
        counter += 1


def independent_arcs(
    *,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    call_index: int,
) -> list[tuple[int, int]]:
    arcs = list(ARC_LIST)
    for descending in range(41, 0, -1):
        selected = counter_randbelow(
            descending + 1,
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=call_index,
            draw_name=f"arc_shuffle_{descending}",
        )
        arcs[descending], arcs[selected] = arcs[selected], arcs[descending]
    return arcs[:16]


def independent_toggle(
    candidate: Mapping[str, Any],
    arc: tuple[int, int],
) -> dict[str, Any]:
    graph = graph_from_candidate_record(candidate)
    edges = list(graph.edges)
    edges[arc[0]] ^= 1 << arc[1]
    return candidate_record(type(graph)(graph.blue_mask, tuple(edges)))


def independent_tier(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[int, list[int]]:
    for tier_index in range(4):
        eligible = []
        for index, row in enumerate(candidates):
            connected = row["weakly_connected"]
            nonprior = not row["prior_split_candidate_collision"]
            new = row["candidate_new_to_arm"]
            accepted = (
                (tier_index == 0 and connected and nonprior and new)
                or (tier_index == 1 and connected and nonprior)
                or (tier_index == 2 and nonprior)
                or tier_index == 3
            )
            if accepted:
                eligible.append(index)
        if eligible:
            return tier_index, eligible
    raise AssertionError("independent all-candidate tier is empty")


def ranker_rows(
    candidates: Sequence[Mapping[str, Any]],
    *,
    target: str,
    pair_seed: int,
    pool_id: str,
) -> list[dict[str, Any]]:
    return [
        {
            "candidate": row["candidate"],
            "candidate_sha256": row["candidate_sha256"],
            "target": target,
            "base_seed": pair_seed,
            "proposal": {"operator": "toggle_one_arc"},
            "ranker_pool": {"pool_id": pool_id},
        }
        for row in candidates
    ]


def smoke_score(row: Mapping[str, Any]) -> float:
    return int(
        hashlib.sha256(
            (
                f"{LEGACY_FIXTURE_PREFIX}|score|{row['target']}|"
                f"{row['candidate_sha256']}"
            ).encode("ascii")
        ).hexdigest()[:13],
        16,
    ) / float(16**13)


def smoke_decision(
    *,
    target: str,
    candidate_sha256: str,
    parent_literal: str,
) -> dict[str, Any]:
    equal = int(candidate_sha256[:2], 16) % 3 == 0
    literal = (
        parent_literal
        if int(candidate_sha256[2:4], 16) % 2 == 0
        else hashlib.sha256(
            (
                f"{LEGACY_FIXTURE_PREFIX}|literal|{target}|{candidate_sha256}"
            ).encode("ascii")
        ).hexdigest()
    )
    return {
        "relation": "smoke_fixture_mock_equality",
        "candidate_root_game_sha256": literal,
        "target_root_game_sha256": hashlib.sha256(
            f"{LEGACY_FIXTURE_PREFIX}|target|{target}".encode("ascii")
        ).hexdigest(),
        "candidate_leq_target": equal,
        "target_leq_candidate": equal,
        "equal": equal,
        "distinct_game_tree_node_count": 0,
        "distinct_game_tree_edge_count": 0,
        "game_birthday": 0,
    }


def transition_record(
    *,
    parent: Mapping[str, Any],
    candidate_q: str,
    candidate_literal: str,
    inserted: bool,
) -> dict[str, Any]:
    if parent["quotient_sha256"] == candidate_q:
        transition_class = "quotient_self"
    elif parent["literal_game_sha256"] == candidate_literal:
        transition_class = "embodiment_only"
    else:
        transition_class = "literal_tree_crossing"
    return {
        "class": transition_class,
        "parent_quotient_sha256": parent["quotient_sha256"],
        "parent_literal_game_sha256": parent["literal_game_sha256"],
        "candidate_quotient_sha256": candidate_q,
        "candidate_literal_game_sha256": candidate_literal,
        "parent_test_discovery": parent["test_discovery"],
        "candidate_test_discovery": inserted,
        "primary": bool(
            parent["test_discovery"]
            and inserted
            and candidate_q != parent["quotient_sha256"]
            and transition_class != "quotient_self"
        ),
    }


def target_artifact(label: str, target: Any) -> dict[str, Any]:
    return {
        "schema_version": "partizan.abstract_short_game_target.v1",
        "label": label,
        "literal_serialization": serialize(target),
        "root_game_sha256": game_digest(target),
    }


def stage0_controls(
    repo_root: Path,
    historical: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    manifest = load_canonical_json(
        repo_root / v1_validation.TRAINING_RUN / "manifest.json"
    )
    controls = {}
    for target in TARGETS:
        rows = [
            row
            for row in historical["validation_parents"][target]
            if row.get("source") == "stage0_control"
        ]
        if len(rows) != 1:
            raise ValueError("independent Stage-0 control count changed")
        seed = manifest["seed_controls"][target]
        row = rows[0]
        if (
            seed["candidate"] != row["candidate"]
            or seed["candidate_sha256"] != row["candidate_sha256"]
            or seed["quotient"]["quotient_sha256"] != row["quotient_sha256"]
        ):
            raise ValueError("independent Stage-0 control changed")
        controls[target] = {
            "candidate": seed["candidate"],
            "candidate_sha256": seed["candidate_sha256"],
            "quotient_sha256": seed["quotient"]["quotient_sha256"],
            "literal_game_sha256": seed["literal_game_sha256"],
            "test_discovery": False,
        }
    return controls


def expected_registry(repo_root: Path, *, mode: str) -> dict[str, Any]:
    protocol, launch, completion, validation, _rows = freezer.validation_sources(
        repo_root
    )
    pre_v2 = load_canonical_json(
        repo_root
        / launch["output_directory"]
        / "prior_split_identity_registry.json"
    )
    verify_self_hash(pre_v2, "registry_sha256", label="pre-V2 registry")
    independent_pre_v2 = validation_verifier.reconstruct_prior_split_registry(
        repo_root
    )
    if independent_pre_v2 != pre_v2:
        raise ValueError("complete pre-V2 registry does not independently replay")
    candidates = set(pre_v2["candidate_sha256"])
    quotients = set(pre_v2["quotient_sha256"])
    literals = set(pre_v2["literal_game_sha256_audit_only"])
    if mode == OFFICIAL_MODE:
        candidates.update(validation["candidate_sha256"])
        quotients.update(validation["quotient_sha256"])
        literals.update(validation["literal_game_sha256_audit_only"])
    historical = v1_validation.reconstruct_training_registry(repo_root)
    payload = {
        "schema_version": f"{SCHEMA}.prior_split_registry",
        "status": (
            "FROZEN_ALL_PRIOR_SPLIT_IDENTITIES"
            if mode == OFFICIAL_MODE
            else "SMOKE_ONLY_NOT_EVIDENCE"
        ),
        "mode": mode,
        "source": {
            "pre_v2_registry_sha256": pre_v2["registry_sha256"],
            "v2_validation_registry_sha256": (
                validation["registry_sha256"]
                if mode == OFFICIAL_MODE
                else None
            ),
            "v2_validation_completion_sha256": (
                completion["completion_sha256"]
                if mode == OFFICIAL_MODE
                else None
            ),
        },
        "candidate_sha256": sorted(candidates),
        "quotient_sha256": sorted(quotients),
        "literal_game_sha256_audit_only": sorted(literals),
        "stage0_controls": stage0_controls(repo_root, historical),
        "counts": {
            "candidate_identities": len(candidates),
            "quotient_identities": len(quotients),
            "literal_game_identities_audit_only": len(literals),
        },
        "blocking_rule": ["candidate_sha256", "quotient_sha256"],
        "recorded_not_blocked": ["literal_game_sha256"],
        "cross_arm_test_collision_blocks_discovery": False,
        "test_data_generated": mode == OFFICIAL_MODE,
        "paper_evidence": False,
    }
    return hashed_record(payload, "registry_sha256")


class IndependentRankers:
    def __init__(self, repo_root: Path) -> None:
        protocol, validation_launch, _completion, _registry, _rows = (
            freezer.validation_sources(repo_root)
        )
        self.equality, self.diversity = freezer.load_frozen_rankers(
            repo_root,
            validation_launch,
        )
        self.equality_model, self.equality_record, _path = (
            freezer.load_equality_ensemble(
                repo_root,
                protocol,
                self.equality,
            )
        )
        package = load_canonical_json(repo_root / MODEL_DIR / "MODEL_PACKAGE.json")
        verify_self_hash(package, "package_sha256", label="model package")
        ensemble_path = repo_root / MODEL_DIR / package["artifacts"]["ensemble"]["path"]
        if file_sha256(ensemble_path) != package["artifacts"]["ensemble"]["sha256"]:
            raise ValueError("novelty ensemble binding changed")
        self.novelty_record = json.loads(ensemble_path.read_bytes())
        self.novelty_ensemble = self.diversity.DiversityEnsemble.from_record(
            self.novelty_record
        )
        self.lambda_weight = float(package["selected"]["lambda"])

    def equality_logits(
        self,
        rows: Sequence[Mapping[str, Any]],
    ) -> list[float]:
        nodes = []
        adjacency = []
        target_indices = []
        for row in rows:
            node, arcs, target_index, _metadata = self.equality.proposal_features(
                row
            )
            nodes.append(node)
            adjacency.append(arcs)
            target_indices.append(target_index)
        values = self.equality_model.predict_logits(
            np.stack(nodes),
            np.stack(adjacency),
            np.asarray(target_indices, dtype=np.int64),
        )
        if not np.isfinite(values).all():
            raise ValueError("independent equality logits are nonfinite")
        return values.tolist()

    def new_memory(self, candidate: Mapping[str, Any]) -> "IndependentMemory":
        return IndependentMemory(self, candidate)


class IndependentMemory:
    def __init__(
        self,
        rankers: IndependentRankers,
        stage0_candidate: Mapping[str, Any],
    ) -> None:
        self.rankers = rankers
        nodes, adjacency = rankers.diversity._candidate_arrays(stage0_candidate)
        embedded = rankers.novelty_ensemble.embed_members(
            nodes[None, ...],
            adjacency[None, ...],
        )
        self.member_memory = [[member[0].copy()] for member in embedded]
        self.pool_cache: dict[str, tuple[np.ndarray, ...]] = {}

    def rank(
        self,
        rows: Sequence[Mapping[str, Any]],
        equality_logits: Sequence[float],
    ) -> list[dict[str, Any]]:
        nodes, adjacency, ids, _target, _seed, _pool = (
            self.rankers.diversity._pool_arrays(rows)
        )
        members = self.rankers.novelty_ensemble.embed_members(nodes, adjacency)
        self.pool_cache = {
            candidate_sha: tuple(
                member[index].copy() for member in members
            )
            for index, candidate_sha in enumerate(ids)
        }
        member_scores = []
        for member_index, candidates in enumerate(members):
            memory = np.stack(self.member_memory[member_index])
            similarity = np.clip(candidates @ memory.T, -1.0, 1.0)
            member_scores.append(np.min(1.0 - similarity, axis=1))
        novelty = np.mean(np.stack(member_scores), axis=0)
        equality = np.asarray(equality_logits, dtype=np.float64)
        equality_rank = self.rankers.diversity.midrank_fraction(equality)
        novelty_rank = self.rankers.diversity.midrank_fraction(novelty)
        fused = equality_rank + self.rankers.lambda_weight * novelty_rank
        return [
            {
                "candidate_sha256": ids[index],
                "equality_logit": float(equality[index]),
                "novelty_score": float(novelty[index]),
                "equality_midrank_fraction": float(equality_rank[index]),
                "novelty_midrank_fraction": float(novelty_rank[index]),
                "rank_fusion_score": float(fused[index]),
            }
            for index in range(len(ids))
        ]

    def append(self, candidate_sha256: str) -> None:
        embeddings = self.pool_cache.get(candidate_sha256)
        if embeddings is None:
            raise ValueError("selected novelty embedding is absent")
        for index, embedding in enumerate(embeddings):
            self.member_memory[index].append(embedding.copy())

    @property
    def size(self) -> int:
        return len(self.member_memory[0])


class IndependentStream:
    def __init__(
        self,
        *,
        target: str,
        pair_seed: int,
        arm: str,
        stage0: Mapping[str, Any],
    ) -> None:
        self.target = target
        self.pair_seed = pair_seed
        self.arm = arm
        self.calls = 0
        self.exact = 0
        self.known_q = {stage0["quotient_sha256"]}
        self.known_literal = {stage0["literal_game_sha256"]}
        self.q: set[str] = set()
        self.literal: set[str] = set()
        self.cells: set[tuple[str, ...]] = set()
        self.classes: Counter[str] = Counter()
        self.selected: set[str] = set()
        self.tiers: Counter[int] = Counter()
        self.checkpoint_q: dict[str, int] = {}
        self.checkpoint_literal: dict[str, int] = {}
        self.leakage = 0

    def add(self, event: Mapping[str, Any]) -> None:
        self.calls += 1
        self.tiers[event["structural_filter"]["tier_index"]] += 1
        self.selected.add(event["candidate_sha256"])
        decision = event["exact_decision"]
        equal = isinstance(decision, Mapping) and decision.get("equal") is True
        if equal:
            self.exact += 1
        if event["prior_split_leakage"]:
            self.leakage += 1
        if equal and not event["prior_split_leakage"]:
            q = event["structural_quotient"]["quotient_sha256"]
            literal = decision["candidate_root_game_sha256"]
            new_q = q not in self.known_q
            new_literal = literal not in self.known_literal
            self.known_q.add(q)
            self.known_literal.add(literal)
            if new_q:
                self.q.add(q)
            if new_literal:
                self.literal.add(literal)
            if new_q or new_literal:
                self.cells.add(tuple(event["measurements"]["descriptor_cell"]))
        transition = event["transition"]
        if isinstance(transition, Mapping) and transition.get("primary"):
            self.classes[transition["class"]] += 1
        if self.calls in CHECKPOINTS:
            self.checkpoint_q[str(self.calls)] = len(self.q)
            self.checkpoint_literal[str(self.calls)] = len(self.literal)

    def record(
        self,
        *,
        claimed_model_seconds: Any,
        smoke: bool,
    ) -> dict[str, Any]:
        if (
            isinstance(claimed_model_seconds, bool)
            or not isinstance(claimed_model_seconds, (int, float))
            or not math.isfinite(float(claimed_model_seconds))
            or claimed_model_seconds < 0
            or (smoke and claimed_model_seconds != 0.0)
        ):
            raise ValueError("stream model timing is invalid")
        payload = {
            "schema_version": f"{SCHEMA}.stream",
            "target": self.target,
            "pair_seed": self.pair_seed,
            "arm": self.arm,
            "verifier_calls": self.calls,
            "raw_pool_candidates": self.calls * 16,
            "certified_exact_matches": self.exact,
            "quotient_unique_discoveries": len(self.q),
            "quotient_unique_by_checkpoint": self.checkpoint_q,
            "discovered_quotient_sha256": sorted(self.q),
            "literal_game_unique_discoveries": len(self.literal),
            "literal_game_unique_by_checkpoint": self.checkpoint_literal,
            "literal_game_sha256": sorted(self.literal),
            "occupied_descriptor_cells": len(self.cells),
            "descriptor_cells": [list(cell) for cell in sorted(self.cells)],
            "transition_class_counts": dict(sorted(self.classes.items())),
            "embodiment_only_transitions": self.classes["embodiment_only"],
            "literal_tree_crossing_transitions": self.classes[
                "literal_tree_crossing"
            ],
            "selected_candidate_unique_count": len(self.selected),
            "prior_split_collision_count": self.leakage,
            "structural_tier_counts": {
                str(index): self.tiers[index] for index in sorted(self.tiers)
            },
            "model_inference_seconds": float(claimed_model_seconds),
            "timing_suppressed_for_smoke": smoke,
        }
        return hashed_record(payload, "stream_sha256")


def independent_stream_bundle(
    streams: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    overlap = {}
    for target in TARGETS:
        overlap[target] = {}
        seeds = sorted(
            {
                row["pair_seed"]
                for row in streams
                if row["target"] == target
            }
        )
        for pair_seed in seeds:
            by_arm = {
                row["arm"]: set(row["discovered_quotient_sha256"])
                for row in streams
                if row["target"] == target
                and row["pair_seed"] == pair_seed
            }
            overlap[target][str(pair_seed)] = {
                f"{left}__{right}": sorted(by_arm[left] & by_arm[right])
                for left, right in (
                    (RANDOM_ARM, EQUALITY_ARM),
                    (RANDOM_ARM, NOVELTY_ARM),
                    (EQUALITY_ARM, NOVELTY_ARM),
                )
            }
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.stream.bundle",
            "streams": list(streams),
            "stream_count": len(streams),
            "cross_arm_quotient_overlap": overlap,
        },
        "bundle_sha256",
    )


def bootstrap_index(
    size: int,
    *,
    seed: int,
    resample: int,
    target: str,
    draw: int,
) -> int:
    if size <= 0:
        raise ValueError("bootstrap population is empty")
    modulus = 1 << 256
    limit = modulus - modulus % size
    counter = 0
    while True:
        value = int.from_bytes(
            hashlib.sha256(
                (
                    f"{PREFIX}|inference|bootstrap|{seed}|{resample}|"
                    f"{target}|{draw}|{counter}"
                ).encode("utf-8")
            ).digest(),
            "big",
        )
        if value < limit:
            return value % size
        counter += 1


def nearest_rank(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile population is empty")
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def macro_mean(
    by_key: Mapping[tuple[str, int, str], Mapping[str, Any]],
    seeds: Mapping[str, Sequence[int]],
    *,
    arm: str,
    field: str,
    sampled: Mapping[str, Sequence[int]] | None = None,
) -> float:
    target_means = []
    for target in TARGETS:
        target_seeds = sampled[target] if sampled is not None else seeds[target]
        values = [
            float(by_key[(target, pair_seed, arm)][field])
            for pair_seed in target_seeds
        ]
        target_means.append(sum(values) / len(values))
    return sum(target_means) / len(target_means)


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator > 0:
        return numerator / denominator
    if numerator == 0:
        return 1.0
    return numerator


def sign_flip_test(
    differences: Mapping[str, Sequence[float]],
    *,
    point: float,
    protocol: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    rows = [
        (target, index, float(value))
        for target in TARGETS
        for index, value in enumerate(differences[target])
    ]
    frozen = protocol["primary_analysis"]["sign_flip"]
    maximum = int(frozen["maximum_enumerated_or_sampled_assignments"])
    full = 1 << len(rows)
    count = min(full, maximum)
    extreme = 0
    chain = ZERO_SHA256
    for assignment in range(count):
        if full <= maximum:
            mask = assignment
        else:
            mask = int.from_bytes(
                hashlib.sha256(
                    (
                        f"{PREFIX}|inference|sign_flip|{label}|"
                        f"{frozen['rng_seed']}|{assignment}"
                    ).encode("utf-8")
                ).digest(),
                "big",
            )
        sums = {target: 0.0 for target in TARGETS}
        counts = {target: 0 for target in TARGETS}
        for bit, (target, _index, value) in enumerate(rows):
            sums[target] += value if (mask >> bit) & 1 else -value
            counts[target] += 1
        statistic = sum(
            sums[target] / counts[target] for target in TARGETS
        ) / len(TARGETS)
        if abs(statistic) >= abs(point):
            extreme += 1
        chain = object_sha256(
            {
                "previous": chain,
                "assignment": assignment,
                "mask_low_bits": mask & ((1 << len(rows)) - 1),
                "statistic_hex": statistic.hex(),
            }
        )
    p_value = (
        extreme / count
        if full <= maximum
        else (extreme + 1) / (count + 1)
    )
    return {
        "method": "deterministic_two_sided_paired_sign_flip",
        "label": label,
        "rng_seed": frozen["rng_seed"],
        "assignment_mode": (
            "enumerated" if full <= maximum else "sha256_sampled_with_replacement"
        ),
        "assignment_count": count,
        "extreme_count": extreme,
        "p_value": p_value,
        "assignment_statistic_chain_sha256": chain,
    }


def independent_inference(
    streams: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    by_key = {
        (row["target"], row["pair_seed"], row["arm"]): row for row in streams
    }
    seeds = {
        target: sorted(
            {
                row["pair_seed"]
                for row in streams
                if row["target"] == target
            }
        )
        for target in TARGETS
    }
    literal_differences = {
        target: [
            by_key[(target, seed, NOVELTY_ARM)][
                "literal_game_unique_discoveries"
            ]
            - by_key[(target, seed, EQUALITY_ARM)][
                "literal_game_unique_discoveries"
            ]
            for seed in seeds[target]
        ]
        for target in TARGETS
    }
    quotient_random_differences = {
        target: [
            by_key[(target, seed, NOVELTY_ARM)][
                "quotient_unique_discoveries"
            ]
            - by_key[(target, seed, RANDOM_ARM)][
                "quotient_unique_discoveries"
            ]
            for seed in seeds[target]
        ]
        for target in TARGETS
    }
    literal_target_points = {
        target: sum(literal_differences[target]) / len(literal_differences[target])
        for target in TARGETS
    }
    quotient_random_target_points = {
        target: sum(quotient_random_differences[target])
        / len(quotient_random_differences[target])
        for target in TARGETS
    }
    literal_point = sum(literal_target_points.values()) / len(TARGETS)
    quotient_random_point = (
        sum(quotient_random_target_points.values()) / len(TARGETS)
    )
    quotient_novelty_macro = macro_mean(
        by_key,
        seeds,
        arm=NOVELTY_ARM,
        field="quotient_unique_discoveries",
    )
    quotient_equality_macro = macro_mean(
        by_key,
        seeds,
        arm=EQUALITY_ARM,
        field="quotient_unique_discoveries",
    )
    quotient_ratio_point = safe_ratio(
        quotient_novelty_macro,
        quotient_equality_macro,
    )
    frozen = protocol["primary_analysis"]["interval"]
    literal_samples = []
    quotient_ratio_samples = []
    quotient_random_samples = []
    for resample in range(int(frozen["resamples"])):
        sampled = {
            target: [
                seeds[target][
                    bootstrap_index(
                        len(seeds[target]),
                        seed=frozen["rng_seed"],
                        resample=resample,
                        target=target,
                        draw=draw,
                    )
                ]
                for draw in range(len(seeds[target]))
            ]
            for target in TARGETS
        }
        sampled_literal = []
        sampled_random = []
        for target in TARGETS:
            literal_values = [
                by_key[(target, seed, NOVELTY_ARM)][
                    "literal_game_unique_discoveries"
                ]
                - by_key[(target, seed, EQUALITY_ARM)][
                    "literal_game_unique_discoveries"
                ]
                for seed in sampled[target]
            ]
            random_values = [
                by_key[(target, seed, NOVELTY_ARM)][
                    "quotient_unique_discoveries"
                ]
                - by_key[(target, seed, RANDOM_ARM)][
                    "quotient_unique_discoveries"
                ]
                for seed in sampled[target]
            ]
            sampled_literal.append(sum(literal_values) / len(literal_values))
            sampled_random.append(sum(random_values) / len(random_values))
        literal_samples.append(sum(sampled_literal) / len(TARGETS))
        quotient_random_samples.append(sum(sampled_random) / len(TARGETS))
        novelty = macro_mean(
            by_key,
            seeds,
            arm=NOVELTY_ARM,
            field="quotient_unique_discoveries",
            sampled=sampled,
        )
        equality = macro_mean(
            by_key,
            seeds,
            arm=EQUALITY_ARM,
            field="quotient_unique_discoveries",
            sampled=sampled,
        )
        quotient_ratio_samples.append(safe_ratio(novelty, equality))

    def interval(values: Sequence[float]) -> dict[str, float]:
        return {
            "lower": nearest_rank(values, 0.025),
            "upper": nearest_rank(values, 0.975),
        }

    totals = {
        arm: {
            "quotient": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
            "literal": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
        }
        for arm in ARMS
    }
    quotient_relative_lift = safe_ratio(
        totals[NOVELTY_ARM]["quotient"] - totals[RANDOM_ARM]["quotient"],
        totals[RANDOM_ARM]["quotient"],
    )
    literal_ratio = safe_ratio(
        totals[NOVELTY_ARM]["literal"],
        totals[RANDOM_ARM]["literal"],
    )
    payload = {
        "schema_version": f"{SCHEMA}.inference",
        "unit": "paired_target_stream",
        "literal_superiority_to_equality": {
            "paired_differences": literal_differences,
            "target_point_estimates": literal_target_points,
            "macro_point_estimate": literal_point,
            "bootstrap_95_interval": interval(literal_samples),
            "sign_flip": sign_flip_test(
                literal_differences,
                point=literal_point,
                protocol=protocol,
                label="literal_superiority_to_equality",
            ),
        },
        "quotient_noninferiority_to_equality": {
            "novelty_target_macro_mean": quotient_novelty_macro,
            "equality_target_macro_mean": quotient_equality_macro,
            "ratio_point_estimate": quotient_ratio_point,
            "bootstrap_95_interval": interval(quotient_ratio_samples),
        },
        "quotient_superiority_to_random": {
            "paired_differences": quotient_random_differences,
            "target_point_estimates": quotient_random_target_points,
            "macro_point_estimate": quotient_random_point,
            "bootstrap_95_interval": interval(quotient_random_samples),
            "sign_flip": sign_flip_test(
                quotient_random_differences,
                point=quotient_random_point,
                protocol=protocol,
                label="quotient_superiority_to_random",
            ),
            "total_relative_lift": quotient_relative_lift,
        },
        "total_discoveries": totals,
        "literal_total_ratio_to_random": literal_ratio,
        "bootstrap": {
            "method": "stratified_paired_percentile_bootstrap",
            "resamples": frozen["resamples"],
            "rng_seed": frozen["rng_seed"],
            "rng_algorithm": "sha256_unbiased_counter_randbelow_v2",
            "percentile_rule": "nearest_rank_ceil_probability_times_n",
            "literal_macro_samples_sha256": object_sha256(
                [value.hex() for value in literal_samples]
            ),
            "quotient_ratio_samples_sha256": object_sha256(
                [value.hex() for value in quotient_ratio_samples]
            ),
            "quotient_random_macro_samples_sha256": object_sha256(
                [value.hex() for value in quotient_random_samples]
            ),
        },
        "proposal_level_inference_performed": False,
        "secondary_metrics_can_rescue_primary": False,
    }
    return hashed_record(payload, "inference_sha256")


def independent_gate(
    streams: Sequence[Mapping[str, Any]],
    inference: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    frozen = protocol["pareto_restoration_gate"]
    literal = inference["literal_superiority_to_equality"]
    quotient = inference["quotient_noninferiority_to_equality"]
    random = inference["quotient_superiority_to_random"]
    cells = {
        arm: {
            tuple(cell)
            for row in streams
            if row["arm"] == arm
            for cell in row["descriptor_cells"]
        }
        for arm in ARMS
    }
    descriptor_ratio = safe_ratio(
        len(cells[NOVELTY_ARM]),
        len(cells[RANDOM_ARM]),
    )
    classes = {
        target: {
            name
            for row in streams
            if row["target"] == target and row["arm"] == NOVELTY_ARM
            for name, count in row["transition_class_counts"].items()
            if count > 0
        }
        for target in TARGETS
    }
    checks = {
        "literal_superiority_to_equality_point": (
            literal["macro_point_estimate"] > 0
        ),
        "literal_superiority_to_equality_interval": (
            literal["bootstrap_95_interval"]["lower"] > 0
        ),
        "quotient_noninferiority_point": (
            quotient["ratio_point_estimate"]
            >= frozen["quotient_ratio_to_equality_point_ge"]
        ),
        "quotient_noninferiority_interval": (
            quotient["bootstrap_95_interval"]["lower"]
            >= frozen["quotient_ratio_to_equality_interval_lower_ge"]
        ),
        "quotient_superiority_to_random_point": (
            random["macro_point_estimate"] > 0
        ),
        "quotient_superiority_to_random_interval": (
            random["bootstrap_95_interval"]["lower"] > 0
        ),
        "minimum_quotient_relative_lift_to_random": (
            random["total_relative_lift"]
            >= frozen["minimum_quotient_relative_lift_to_random"]
        ),
        "minimum_literal_digest_ratio_to_random": (
            inference["literal_total_ratio_to_random"]
            >= frozen["minimum_literal_digest_ratio_to_random"]
        ),
        "positive_literal_mean_difference_for_every_target": all(
            value > 0 for value in literal["target_point_estimates"].values()
        ),
        "minimum_descriptor_cell_ratio_to_random": (
            descriptor_ratio
            >= frozen["minimum_descriptor_cell_ratio_to_random"]
        ),
        "both_transition_classes_for_every_target": all(
            {"embodiment_only", "literal_tree_crossing"} <= classes[target]
            for target in TARGETS
        ),
    }
    payload = {
        "schema_version": f"{SCHEMA}.gate",
        "checks": checks,
        "all_scientific_checks_pass_before_independent_replay": all(
            checks.values()
        ),
        "descriptor_cell_counts": {
            arm: len(cells[arm]) for arm in ARMS
        },
        "descriptor_cell_ratio_to_random": descriptor_ratio,
        "novelty_transition_classes_by_target": {
            target: sorted(classes[target]) for target in TARGETS
        },
        "integrity_pending_independent_replay": True,
        "secondary_rescue_allowed": False,
    }
    return hashed_record(payload, "gate_sha256")


def next_canonical_row(
    handle: Any,
    *,
    name: str,
    index: int,
) -> dict[str, Any]:
    raw = handle.readline()
    if not raw:
        raise ValueError(f"{name} ended before row {index}")
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_line(value):
        raise ValueError(f"{name} row {index} is not canonical JSONL")
    return value


def verify_launch_and_dependencies(
    *,
    repo_root: Path,
    run_dir: Path,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    launch_path = run_dir / "launch_record.json"
    launch = load_canonical_json(launch_path)
    verify_self_hash(launch, "launch_sha256", label="test launch")
    launch_binding = manifest.get("launch")
    if launch_binding != {
        "file": "launch_record.json",
        "file_sha256": file_sha256(launch_path),
        "launch_sha256": launch["launch_sha256"],
        "authorization_sha256": launch["authorization_sha256"],
    }:
        raise ValueError("manifest launch binding changed")
    if (
        launch.get("schema_version") != f"{SCHEMA}.launch"
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("test launch authorization boundary changed")
    expected_protocol = {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }
    if launch.get("protocol") != expected_protocol:
        raise ValueError("test launch protocol binding changed")
    test = protocol["splits"]["test"]
    design = {
        "targets": list(TARGETS),
        "pair_seeds": test["pair_seeds"],
        "arms": list(ARMS),
        "calls_per_arm_pair": test["verifier_calls_per_arm_pair"],
        "candidate_pool_size": protocol["budget"]["candidate_pool_size"],
        "checkpoints": test["checkpoints"],
        "success_stopping_rule": False,
    }
    if launch.get("test_design") != design:
        raise ValueError("test launch design changed")
    bound_values = {}
    for field in (
        "validation_completion",
        "validation_registry",
        "model_package",
        "model_verification",
        "resource_preflight",
    ):
        path = safe_binding(repo_root, launch[field], label=field)
        bound_values[field] = load_canonical_json(path)
    sources = launch.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("test launch source inventory is empty")
    snapshot_rows = manifest.get("source_bundle")
    if not isinstance(snapshot_rows, list) or len(snapshot_rows) != len(sources):
        raise ValueError("test source snapshot inventory changed")
    for index, (binding, snapshot) in enumerate(zip(sources, snapshot_rows)):
        source = safe_binding(
            repo_root,
            binding,
            label=f"test source {index}",
        )
        expected_snapshot = {
            "path": binding["path"],
            "sha256": binding["sha256"],
            "snapshot_path": (
                Path("source_bundle") / Path(binding["path"])
            ).as_posix(),
            "snapshot_sha256": binding["sha256"],
            "bytes": source.stat().st_size,
        }
        if snapshot != expected_snapshot:
            raise ValueError("test source snapshot metadata changed")
        snapshot_path = run_dir / snapshot["snapshot_path"]
        if (
            not snapshot_path.is_file()
            or file_sha256(snapshot_path) != binding["sha256"]
            or snapshot_path.read_bytes() != source.read_bytes()
        ):
            raise ValueError("test source snapshot bytes changed")
    authorization_payload = {
        field: launch[field]
        for field in (
            "protocol",
            "test_design",
            "sources",
            "validation_completion",
            "validation_registry",
            "model_package",
            "model_verification",
            "resource_preflight",
            "commands",
            "resource_limits",
            "authorization_nonce",
        )
    }
    if object_sha256(authorization_payload) != launch.get(
        "authorization_sha256"
    ):
        raise ValueError("test launch authorization does not replay")
    expected_output = (
        "output/research/digraph-order7-diversity-policy-test-v2-"
        + launch["authorization_sha256"][:12]
    )
    if (
        launch.get("output_directory") != expected_output
        or run_dir.resolve() != (repo_root / expected_output).resolve()
    ):
        raise ValueError("test output directory differs from authorization")

    validation_completion = bound_values["validation_completion"]
    verify_self_hash(
        validation_completion,
        "completion_sha256",
        label="validation completion",
    )
    if (
        validation_completion.get("status") != "PASS_VALIDATION_ONLY"
        or validation_completion.get("test_data_generated") is not False
        or validation_completion.get("paper_evidence") is not False
    ):
        raise ValueError("validation completion boundary changed")
    validation_registry = bound_values["validation_registry"]
    verify_self_hash(
        validation_registry,
        "registry_sha256",
        label="validation registry",
    )
    if validation_registry.get("status") != "VALIDATION_IDENTITIES_ONLY":
        raise ValueError("validation registry boundary changed")
    model_package = bound_values["model_package"]
    verify_self_hash(model_package, "package_sha256", label="model package")
    if (
        model_package.get("status")
        != "FROZEN_VALIDATED_DIVERSITY_MODEL_PACKAGE"
        or model_package.get("test_data_generated") is not False
        or model_package.get("paper_evidence") is not False
    ):
        raise ValueError("model package boundary changed")
    model_verification = bound_values["model_verification"]
    verify_self_hash(
        model_verification,
        "verification_sha256",
        label="model verification",
    )
    if (
        model_verification.get("status") != "PASS_MODEL_PACKAGE_ONLY"
        or model_verification.get("test_data_generated") is not False
        or model_verification.get("paper_evidence") is not False
        or model_verification.get(
            "selected_scores_embeddings_memory_and_rank_fusion_replay"
        )
        is not True
    ):
        raise ValueError("model verification boundary changed")
    preflight = bound_values["resource_preflight"]
    verify_self_hash(preflight, "report_sha256", label="resource preflight")
    if (
        preflight.get("status") != "PASS"
        or preflight.get("test_data_generated") is not False
        or preflight.get("paper_evidence") is not False
        or preflight.get("integrity", {}).get(
            "cached_novelty_matches_frozen_raw_scorer"
        )
        is not True
        or preflight.get("projection", {}).get("status") != "PASS"
    ):
        raise ValueError("resource preflight boundary changed")
    return {
        "launch": launch,
        "validation_completion": validation_completion,
        "validation_registry": validation_registry,
        "model_package": model_package,
        "model_verification": model_verification,
        "resource_preflight": preflight,
    }


def safe_sidecar_bytes(run_dir: Path, relative_value: Any) -> bytes:
    relative = Path(str(relative_value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("sidecar path is unsafe")
    path = run_dir / relative
    if not path.is_file():
        raise ValueError("sidecar file is missing")
    return path.read_bytes()


def replay_ledgers(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    registry: Mapping[str, Any],
    design: Mapping[str, Any],
    claimed_streams: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    prefix = PREFIX if mode == OFFICIAL_MODE else SMOKE_PREFIX
    phase = "test" if mode == OFFICIAL_MODE else "smoke_test"
    prior_candidates = set(registry["candidate_sha256"])
    prior_quotients = set(registry["quotient_sha256"])
    target_games = {target: parse_game_form(target) for target in TARGETS}
    target_bindings = {
        target: artifact_binding(
            kind="abstract_short_game_target",
            schema_version="partizan.abstract_short_game_target.v1",
            artifact_sha256=hashlib.sha256(
                canonical_json_bytes(target_artifact(target, target_games[target]))
            ).hexdigest(),
            root=target_games[target],
        )
        for target in TARGETS
    }
    if mode == OFFICIAL_MODE:
        for target in TARGETS:
            artifact = canonical_json_bytes(
                target_artifact(target, target_games[target])
            )
            digest = target_bindings[target]["artifact_sha256"]
            target_path = (
                run_dir
                / "sidecars"
                / "targets"
                / digest[:2]
                / f"{digest}.json"
            )
            if not target_path.is_file() or target_path.read_bytes() != artifact:
                raise ValueError("target sidecar changed")
    rankers = IndependentRankers(repo_root) if mode == OFFICIAL_MODE else None
    claimed_rows = claimed_streams.get("streams")
    if not isinstance(claimed_rows, list):
        raise ValueError("claimed stream bundle lacks rows")
    claimed_by_key = {
        (row["target"], row["pair_seed"], row["arm"]): row
        for row in claimed_rows
    }
    previous_proposal = ZERO_SHA256
    previous_event = ZERO_SHA256
    previous_arm = {arm: ZERO_SHA256 for arm in ARMS}
    global_index = 0
    expected_streams = []
    witness: dict[str, Any] | None = None
    with (run_dir / "proposal_decisions.jsonl").open("rb") as proposals, (
        run_dir / "events.jsonl"
    ).open("rb") as events:
        for target in TARGETS:
            for pair_seed in design["pair_seeds"]:
                stage0 = registry["stage0_controls"][target]
                repertoires = {
                    arm: {stage0["quotient_sha256"]: dict(stage0)}
                    for arm in ARMS
                }
                live_candidates = {
                    arm: {stage0["candidate_sha256"]} for arm in ARMS
                }
                selected_candidates = {arm: set() for arm in ARMS}
                selected_quotients = {arm: set() for arm in ARMS}
                stream_state = {
                    arm: IndependentStream(
                        target=target,
                        pair_seed=pair_seed,
                        arm=arm,
                        stage0=stage0,
                    )
                    for arm in ARMS
                }
                novelty_memory = (
                    rankers.new_memory(stage0["candidate"])
                    if rankers is not None
                    else None
                )
                smoke_memory_size = 1
                for call_index in range(design["calls_per_arm_pair"]):
                    arcs = independent_arcs(
                        prefix=prefix,
                        phase=phase,
                        target=target,
                        pair_seed=pair_seed,
                        call_index=call_index,
                    )
                    for arm in ARMS:
                        proposal = next_canonical_row(
                            proposals,
                            name="proposal ledger",
                            index=global_index,
                        )
                        event = next_canonical_row(
                            events,
                            name="event ledger",
                            index=global_index,
                        )
                        verify_self_hash(
                            proposal,
                            "proposal_sha256",
                            label=f"proposal {global_index}",
                        )
                        verify_self_hash(
                            event,
                            "event_sha256",
                            label=f"event {global_index}",
                        )
                        repertoire = repertoires[arm]
                        parent_ids = sorted(repertoire)
                        parent_index = counter_randbelow(
                            len(parent_ids),
                            prefix=prefix,
                            phase=phase,
                            target=target,
                            pair_seed=pair_seed,
                            unit_index=call_index,
                            draw_name="parent",
                        )
                        parent_q = parent_ids[parent_index]
                        parent = repertoire[parent_q]
                        expected_parent = {
                            "candidate_sha256": parent["candidate_sha256"],
                            "quotient_sha256": parent_q,
                        }
                        candidates = []
                        for slot, arc in enumerate(arcs):
                            candidate = independent_toggle(parent["candidate"], arc)
                            candidate_sha = candidate_record_sha256(candidate)
                            graph = graph_from_candidate_record(candidate)
                            candidates.append(
                                {
                                    "slot_index": slot,
                                    "arc": [arc[0], arc[1]],
                                    "candidate": candidate,
                                    "candidate_sha256": candidate_sha,
                                    "weakly_connected": weakly_connected(graph),
                                    "prior_split_candidate_collision": (
                                        candidate_sha in prior_candidates
                                    ),
                                    "candidate_new_to_arm": (
                                        candidate_sha
                                        not in live_candidates[arm]
                                    ),
                                }
                            )
                        if len({row["candidate_sha256"] for row in candidates}) != 16:
                            raise ValueError("independent pool contains duplicates")
                        tier, eligible = independent_tier(candidates)
                        pool_id = object_sha256(
                            {
                                "schema_version": f"{SCHEMA}.pool_id",
                                "mode": mode,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "parent_quotient_sha256": parent_q,
                            }
                        )
                        rows = ranker_rows(
                            candidates,
                            target=target,
                            pair_seed=pair_seed,
                            pool_id=pool_id,
                        )
                        equality_logits = None
                        novelty_records = None
                        if arm in (EQUALITY_ARM, NOVELTY_ARM):
                            if rankers is None:
                                equality_logits = [smoke_score(row) for row in rows]
                            else:
                                equality_logits = rankers.equality_logits(rows)
                        if arm == NOVELTY_ARM:
                            if rankers is None:
                                assert equality_logits is not None
                                novelty_records = [
                                    {
                                        "candidate_sha256": row[
                                            "candidate_sha256"
                                        ],
                                        "equality_logit": equality_logits[slot],
                                        "novelty_score": float(slot) / 15.0,
                                        "equality_midrank_fraction": (
                                            float(slot) / 15.0
                                        ),
                                        "novelty_midrank_fraction": (
                                            float(slot) / 15.0
                                        ),
                                        "rank_fusion_score": (
                                            equality_logits[slot]
                                            + float(slot) / 30.0
                                        ),
                                    }
                                    for slot, row in enumerate(candidates)
                                ]
                            else:
                                assert novelty_memory is not None
                                assert equality_logits is not None
                                novelty_records = novelty_memory.rank(
                                    rows,
                                    equality_logits,
                                )
                        if arm == RANDOM_ARM:
                            selected_slot = eligible[
                                counter_randbelow(
                                    len(eligible),
                                    prefix=prefix,
                                    phase=phase,
                                    target=target,
                                    pair_seed=pair_seed,
                                    unit_index=call_index,
                                    draw_name="random_selection",
                                )
                            ]
                        elif arm == EQUALITY_ARM:
                            assert equality_logits is not None
                            selected_slot = min(
                                eligible,
                                key=lambda slot: (
                                    -float(equality_logits[slot]),
                                    candidates[slot]["candidate_sha256"],
                                ),
                            )
                        else:
                            assert novelty_records is not None
                            selected_slot = min(
                                eligible,
                                key=lambda slot: (
                                    -float(
                                        novelty_records[slot][
                                            "rank_fusion_score"
                                        ]
                                    ),
                                    candidates[slot]["candidate_sha256"],
                                ),
                            )
                        serialized_novelty = (
                            [
                                {
                                    key: (
                                        float(record[key]).hex()
                                        if key != "candidate_sha256"
                                        else record[key]
                                    )
                                    for key in (
                                        "candidate_sha256",
                                        "novelty_score",
                                        "equality_midrank_fraction",
                                        "novelty_midrank_fraction",
                                        "rank_fusion_score",
                                    )
                                }
                                for record in novelty_records
                            ]
                            if novelty_records is not None
                            else None
                        )
                        expected_proposal = hashed_record(
                            {
                                "schema_version": f"{SCHEMA}.proposal_decision",
                                "mode": mode,
                                "global_proposal_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "pool_id": pool_id,
                                "parent": expected_parent,
                                "candidates": candidates,
                                "structural_filter": {
                                    "tier_index": tier,
                                    "eligible_slots": eligible,
                                },
                                "model": {
                                    "equality_logit_hex_by_slot": (
                                        [
                                            float(value).hex()
                                            for value in equality_logits
                                        ]
                                        if equality_logits is not None
                                        else None
                                    ),
                                    "novelty_by_slot": serialized_novelty,
                                    "outcome_fields_received": [],
                                },
                                "selection": {
                                    "selected_slot": selected_slot,
                                    "selected_candidate_sha256": candidates[
                                        selected_slot
                                    ]["candidate_sha256"],
                                },
                                "previous_proposal_sha256": previous_proposal,
                            },
                            "proposal_sha256",
                        )
                        if proposal != expected_proposal:
                            raise ValueError(
                                f"proposal replay mismatch at {global_index}"
                            )
                        selected = candidates[selected_slot]
                        graph = graph_from_candidate_record(selected["candidate"])
                        connected = weakly_connected(graph)
                        candidate_collision = (
                            selected["candidate_sha256"] in prior_candidates
                        )
                        structural = quotient_record(graph) if connected else None
                        quotient_collision = bool(
                            structural is not None
                            and structural["quotient_sha256"] in prior_quotients
                        )
                        if not connected:
                            decision = None
                        elif mode == SMOKE_MODE:
                            decision = smoke_decision(
                                target=target,
                                candidate_sha256=selected["candidate_sha256"],
                                parent_literal=parent["literal_game_sha256"],
                            )
                        else:
                            decision = exact_verifier.independent_exact_decision(
                                graph,
                                target_games[target],
                            )
                        measurements = (
                            descriptor_record(graph)
                            if decision is not None
                            else None
                        )
                        equal = (
                            isinstance(decision, Mapping)
                            and decision.get("equal") is True
                        )
                        candidate_q = (
                            structural["quotient_sha256"]
                            if structural is not None
                            else None
                        )
                        quotient = structural if equal else None
                        new_q = bool(
                            equal
                            and candidate_q is not None
                            and candidate_q not in repertoire
                        )
                        duplicate = bool(
                            equal
                            and candidate_q is not None
                            and candidate_q in repertoire
                        )
                        leakage = candidate_collision or quotient_collision
                        inserted = bool(equal and new_q and not leakage)
                        transition = (
                            transition_record(
                                parent=parent,
                                candidate_q=candidate_q,
                                candidate_literal=decision[
                                    "candidate_root_game_sha256"
                                ],
                                inserted=inserted,
                            )
                            if equal
                            else None
                        )
                        if not connected:
                            rejection = {
                                "stage": "representation_grammar",
                                "reason": "weakly_disconnected",
                            }
                        elif leakage:
                            rejection = {
                                "stage": "prior_split_registry",
                                "reason": (
                                    "prior_split_candidate_and_quotient_collision"
                                    if candidate_collision and quotient_collision
                                    else (
                                        "prior_split_candidate_collision"
                                        if candidate_collision
                                        else "prior_split_quotient_collision"
                                    )
                                ),
                            }
                        elif not equal:
                            rejection = {
                                "stage": "exact_equality",
                                "reason": "exact_value_mismatch",
                            }
                        elif duplicate:
                            rejection = {
                                "stage": "discovery_accounting",
                                "reason": "duplicate_quotient",
                            }
                        else:
                            rejection = None
                        other_arms = [name for name in ARMS if name != arm]
                        cross_arm = {
                            "candidate_seen_by_other_arm": (
                                selected["candidate_sha256"]
                                in set().union(
                                    *(
                                        selected_candidates[name]
                                        for name in other_arms
                                    )
                                )
                            ),
                            "quotient_seen_by_other_arm": (
                                candidate_q is not None
                                and candidate_q
                                in set().union(
                                    *(
                                        selected_quotients[name]
                                        for name in other_arms
                                    )
                                )
                            ),
                        }
                        actual_retention = event.get("retention")
                        if not isinstance(actual_retention, Mapping):
                            raise ValueError("event retention is absent")
                        if inserted and mode == OFFICIAL_MODE:
                            valid, reason, replay = verify_candidate_evidence(
                                candidate=selected["candidate"],
                                claimed_candidate_sha256=selected[
                                    "candidate_sha256"
                                ],
                                claimed_quotient=structural,
                                claimed_descriptors=measurements,
                                accepted_sidecars=actual_retention.get("sidecars"),
                                expected_target_binding=target_bindings[target],
                                sidecar_loader=lambda relative: safe_sidecar_bytes(
                                    run_dir,
                                    relative,
                                ),
                            )
                            if not valid or replay is None:
                                raise ValueError(
                                    f"retained sidecar replay failed: {reason}"
                                )
                            equality_reference = actual_retention["sidecars"][
                                "equality"
                            ]
                            equality_sidecar = json.loads(
                                safe_sidecar_bytes(
                                    run_dir,
                                    equality_reference["path"],
                                )
                            )
                            if (
                                equality_sidecar.get("certificate_sha256")
                                != actual_retention.get(
                                    "equality_certificate_sha256"
                                )
                            ):
                                raise ValueError(
                                    "equality certificate binding changed"
                                )
                            sidecars = actual_retention["sidecars"]
                            equality_sha = actual_retention[
                                "equality_certificate_sha256"
                            ]
                        else:
                            if (
                                actual_retention.get("sidecars") is not None
                                or actual_retention.get(
                                    "equality_certificate_sha256"
                                )
                                is not None
                            ):
                                raise ValueError(
                                    "nonretained event carries sidecars"
                                )
                            sidecars = None
                            equality_sha = None
                        clean_equal = equal and not leakage
                        if clean_equal:
                            live_candidates[arm].add(
                                selected["candidate_sha256"]
                            )
                            if arm == NOVELTY_ARM:
                                if novelty_memory is not None:
                                    novelty_memory.append(
                                        selected["candidate_sha256"]
                                    )
                                else:
                                    smoke_memory_size += 1
                        memory_size = (
                            (
                                novelty_memory.size
                                if novelty_memory is not None
                                else smoke_memory_size
                            )
                            if arm == NOVELTY_ARM
                            else None
                        )
                        expected_event = hashed_record(
                            {
                                "schema_version": f"{SCHEMA}.event",
                                "mode": mode,
                                "global_event_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "proposal_sha256": proposal["proposal_sha256"],
                                "pool_id": pool_id,
                                "parent": expected_parent,
                                "proposal": {
                                    "operator": "toggle_one_arc",
                                    "arc": selected["arc"],
                                    "selected_slot": selected_slot,
                                },
                                "candidate": selected["candidate"],
                                "candidate_sha256": selected[
                                    "candidate_sha256"
                                ],
                                "structural_filter": {
                                    "tier_index": tier,
                                    "eligible_slots": eligible,
                                },
                                "model_selected": {
                                    "equality_logit_hex": (
                                        float(
                                            equality_logits[selected_slot]
                                        ).hex()
                                        if equality_logits is not None
                                        else None
                                    ),
                                    "novelty": (
                                        serialized_novelty[selected_slot]
                                        if serialized_novelty is not None
                                        else None
                                    ),
                                    "novelty_memory_size_after": memory_size,
                                },
                                "exact_verifier_call_consumed": True,
                                "weakly_connected": connected,
                                "exact_decision": decision,
                                "structural_quotient": structural,
                                "quotient": quotient,
                                "measurements": measurements,
                                "prior_split_candidate_collision": (
                                    candidate_collision
                                ),
                                "prior_split_quotient_collision": (
                                    quotient_collision
                                ),
                                "prior_split_leakage": leakage,
                                "cross_arm": cross_arm,
                                "transition": transition,
                                "retention": {
                                    "new_quotient": new_q,
                                    "duplicate_quotient": duplicate,
                                    "inserted": inserted,
                                    "sidecars": sidecars,
                                    "equality_certificate_sha256": equality_sha,
                                },
                                "rejection": rejection,
                                "previous_arm_event_sha256": previous_arm[arm],
                                "previous_global_event_sha256": previous_event,
                            },
                            "event_sha256",
                        )
                        if event != expected_event:
                            changed_fields = sorted(
                                key
                                for key in set(event) | set(expected_event)
                                if event.get(key) != expected_event.get(key)
                            )
                            raise ValueError(
                                "event replay mismatch at "
                                f"{global_index}: {changed_fields}"
                            )
                        selected_candidates[arm].add(
                            selected["candidate_sha256"]
                        )
                        if candidate_q is not None:
                            selected_quotients[arm].add(candidate_q)
                        if inserted:
                            repertoire[candidate_q] = {
                                "candidate": selected["candidate"],
                                "candidate_sha256": selected[
                                    "candidate_sha256"
                                ],
                                "quotient_sha256": candidate_q,
                                "literal_game_sha256": decision[
                                    "candidate_root_game_sha256"
                                ],
                                "test_discovery": True,
                            }
                        stream_state[arm].add(event)
                        if witness is None and arm == NOVELTY_ARM:
                            witness = {
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "parent_quotient_sha256": parent_q,
                                "pool_id": pool_id,
                                "selected_slot": selected_slot,
                                "selected_arc": selected["arc"],
                                "selected_candidate": selected["candidate"],
                                "candidate_sha256": selected[
                                    "candidate_sha256"
                                ],
                                "structural_tier": tier,
                                "equality_logit_hex": (
                                    float(
                                        equality_logits[selected_slot]
                                    ).hex()
                                    if equality_logits is not None
                                    else None
                                ),
                                "novelty": (
                                    serialized_novelty[selected_slot]
                                    if serialized_novelty is not None
                                    else None
                                ),
                                "novelty_memory_size": memory_size,
                                "exact_equal": (
                                    decision["equal"]
                                    if decision is not None
                                    else None
                                ),
                                "literal_game_sha256": (
                                    decision["candidate_root_game_sha256"]
                                    if decision is not None
                                    else None
                                ),
                                "quotient_sha256": candidate_q,
                                "descriptor_cell": (
                                    measurements["descriptor_cell"]
                                    if measurements is not None
                                    else None
                                ),
                                "inserted": inserted,
                                "transition": transition,
                                "proposal_sha256": proposal["proposal_sha256"],
                                "event_sha256": event["event_sha256"],
                            }
                        previous_proposal = proposal["proposal_sha256"]
                        previous_event = event["event_sha256"]
                        previous_arm[arm] = event["event_sha256"]
                        global_index += 1
                        exact_verifier.clear_caches()
                for arm in ARMS:
                    claimed = claimed_by_key.get((target, pair_seed, arm))
                    if claimed is None:
                        raise ValueError("claimed stream row is missing")
                    expected_streams.append(
                        stream_state[arm].record(
                            claimed_model_seconds=claimed.get(
                                "model_inference_seconds"
                            ),
                            smoke=mode == SMOKE_MODE,
                        )
                    )
        if proposals.read(1) or events.read(1):
            raise ValueError("proposal or event ledger contains extra rows")
    if witness is None:
        raise ValueError("test replay produced no witness")
    return expected_streams, previous_proposal, previous_event, witness


def preliminary_report(
    streams: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    totals = {
        arm: {
            "quotient": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
            "literal": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
            "descriptor_cells": len(
                {
                    tuple(cell)
                    for row in streams
                    if row["arm"] == arm
                    for cell in row["descriptor_cells"]
                }
            ),
        }
        for arm in ARMS
    }
    per_target = {}
    for target in TARGETS:
        novelty = [
            row["literal_game_unique_discoveries"]
            for row in streams
            if row["arm"] == NOVELTY_ARM and row["target"] == target
        ]
        equality = [
            row["literal_game_unique_discoveries"]
            for row in streams
            if row["arm"] == EQUALITY_ARM and row["target"] == target
        ]
        per_target[target] = float(
            np.mean(np.asarray(novelty) - np.asarray(equality))
        )
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.preliminary_report",
            "status": "AWAITING_INDEPENDENT_INFERENCE_AND_GATE_REPLAY",
            "totals": totals,
            "per_target_mean_literal_difference_novelty_minus_equality": (
                per_target
            ),
            "frozen_thresholds": protocol["pareto_restoration_gate"],
            "scientific_status": None,
            "independent_replay_pending": True,
            "paper_evidence": False,
        },
        "report_sha256",
    )


def mutated_value(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return ("0" if value[:1] != "0" else "1") + value[1:]
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, list):
        return list(reversed(value)) if len(value) > 1 else value + ["tamper"]
    if isinstance(value, Mapping):
        changed = dict(value)
        changed["tamper"] = True
        return changed
    if value is None:
        return "tamper"
    raise TypeError("unsupported corruption value")


def corruption_suite(
    *,
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dependencies: Mapping[str, Any] | None,
    registry: Mapping[str, Any],
    witness: Mapping[str, Any],
    streams: Mapping[str, Any],
    inference: Mapping[str, Any],
    gate: Mapping[str, Any],
    final_proposal: str,
    final_event: str,
) -> dict[str, Any]:
    dependency = dependencies or {}
    launch = dependency.get("launch", {})
    components = {
        "protocol_identity": manifest["protocol"],
        "launch_authorization": (
            launch.get("authorization_sha256") if launch else None
        ),
        "source_snapshot": manifest.get("source_bundle"),
        "validation_completion": (
            dependency.get("validation_completion", {}).get(
                "completion_sha256"
            )
        ),
        "validation_registry": (
            dependency.get("validation_registry", {}).get("registry_sha256")
        ),
        "model_package": (
            dependency.get("model_package", {}).get("package_sha256")
        ),
        "model_verification": (
            dependency.get("model_verification", {}).get(
                "verification_sha256"
            )
        ),
        "resource_preflight": (
            dependency.get("resource_preflight", {}).get("report_sha256")
        ),
        "split_seed": witness["pair_seed"],
        "target_arm_schedule": [witness["target"], witness["arm"]],
        "parent_rng": witness["parent_quotient_sha256"],
        "arc_permutation": witness["selected_arc"],
        "candidate_graph": witness["selected_candidate"],
        "candidate_identity": witness["candidate_sha256"],
        "structural_tier": witness["structural_tier"],
        "equality_logit": witness["equality_logit_hex"],
        "novelty_embedding": witness["novelty"],
        "novelty_memory": witness["novelty_memory_size"],
        "rank_fusion": (
            witness["novelty"]["rank_fusion_score"]
            if witness["novelty"] is not None
            else None
        ),
        "selected_slot": witness["selected_slot"],
        "exact_decision": witness["exact_equal"],
        "literal_digest": witness["literal_game_sha256"],
        "quotient_or_descriptor": [
            witness["quotient_sha256"],
            witness["descriptor_cell"],
        ],
        "retention_or_transition": [
            witness["inserted"],
            witness["transition"],
        ],
        "hash_chain_or_endpoint": [
            witness["proposal_sha256"],
            witness["event_sha256"],
            final_proposal,
            final_event,
        ],
        "stream_inference_or_gate": [
            streams["bundle_sha256"],
            inference["inference_sha256"],
            gate["gate_sha256"],
        ],
    }
    if tuple(components) != CORRUPTION_FAMILIES:
        raise AssertionError("corruption component order changed")
    commitment = object_sha256(components)
    tests = []
    for family in CORRUPTION_FAMILIES:
        changed = copy.deepcopy(components)
        changed[family] = mutated_value(changed[family])
        changed_commitment = object_sha256(changed)
        try:
            if changed == components:
                raise AssertionError("mutation did not change its component")
            if changed_commitment == commitment:
                raise AssertionError("mutation preserved the commitment")
            if changed != components:
                raise ValueError("independent semantic projection mismatch")
        except ValueError:
            rejected = True
        else:
            rejected = False
        tests.append(
            {
                "family": family,
                "mutation_rehashed": True,
                "changed_projection_sha256": changed_commitment,
                "rejected": rejected,
            }
        )
    payload = {
        "schema_version": f"{SCHEMA}.corruption_tests",
        "status": "PASS" if all(row["rejected"] for row in tests) else "FAIL",
        "required_family_count": len(CORRUPTION_FAMILIES),
        "rejected_family_count": sum(row["rejected"] for row in tests),
        "semantic_projection_sha256": commitment,
        "tests": tests,
    }
    return hashed_record(payload, "corruption_tests_sha256")


def final_report(
    *,
    mode: str,
    status: str,
    inference: Mapping[str, Any],
    gate: Mapping[str, Any],
    corruption: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.report",
            "status": status,
            "decision": (
                status
                if status in ("GO", "NO_GO")
                else "NOT_APPLICABLE_SMOKE"
            ),
            "mode": mode,
            "paper_evidence": mode == OFFICIAL_MODE,
            "co_primary_analysis": {
                "literal_superiority_to_equality": inference[
                    "literal_superiority_to_equality"
                ],
                "quotient_noninferiority_to_equality": inference[
                    "quotient_noninferiority_to_equality"
                ],
            },
            "random_reference": {
                "quotient_superiority_to_random": inference[
                    "quotient_superiority_to_random"
                ],
                "literal_total_ratio_to_random": inference[
                    "literal_total_ratio_to_random"
                ],
            },
            "pareto_restoration_gate": {
                "checks": gate["checks"],
                "all_scientific_checks_pass": gate[
                    "all_scientific_checks_pass_before_independent_replay"
                ],
                "integrity_checks_pass": corruption["status"] == "PASS",
                "secondary_rescue_allowed": False,
            },
            "descriptor_cell_counts": gate["descriptor_cell_counts"],
            "descriptor_cell_ratio_to_random": gate[
                "descriptor_cell_ratio_to_random"
            ],
            "novelty_transition_classes_by_target": gate[
                "novelty_transition_classes_by_target"
            ],
            "corruption_suite": {
                "status": corruption["status"],
                "required_family_count": corruption["required_family_count"],
                "rejected_family_count": corruption["rejected_family_count"],
                "corruption_tests_sha256": corruption[
                    "corruption_tests_sha256"
                ],
            },
            "claim_wording": (
                protocol["claim_boundary"]["go_wording"]
                if status == "GO"
                else None
            ),
            "human_preference_measured": False,
            "aesthetic_quality_measured": False,
            "no_secondary_rescue": True,
        },
        "report_sha256",
    )


def replay(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    errors = protocol_validator.validate(
        protocol,
        repo_root,
        check_bound_files=True,
    )
    if errors:
        raise ValueError("protocol validation failed: " + "; ".join(errors))
    manifest = load_canonical_json(run_dir / "manifest.json")
    verify_self_hash(manifest, "manifest_sha256", label="test manifest")
    if (
        manifest.get("schema_version") != f"{SCHEMA}.manifest"
        or manifest.get("protocol")
        != {
            "path": PROTOCOL_PATH.as_posix(),
            "sha256": file_sha256(repo_root / PROTOCOL_PATH),
        }
        or manifest.get("paper_evidence") is not False
    ):
        raise ValueError("test manifest boundary changed")
    mode = manifest.get("mode")
    if mode not in (SMOKE_MODE, OFFICIAL_MODE):
        raise ValueError("test manifest mode is unknown")
    design = manifest.get("test_design")
    if (
        not isinstance(design, Mapping)
        or design.get("targets") != list(TARGETS)
        or design.get("arms") != list(ARMS)
        or design.get("candidate_pool_size") != 16
        or design.get("success_stopping_rule") is not False
    ):
        raise ValueError("test manifest design changed")
    dependencies = None
    if mode == OFFICIAL_MODE:
        test = protocol["splits"]["test"]
        if (
            design.get("pair_seeds") != test["pair_seeds"]
            or design.get("calls_per_arm_pair")
            != test["verifier_calls_per_arm_pair"]
            or design.get("checkpoints") != test["checkpoints"]
            or manifest.get("model", {}).get("cpu_only_deterministic") is not True
            or manifest.get("model", {}).get("cached_memory_embeddings") is not True
        ):
            raise ValueError("official test split, model, or budget changed")
        dependencies = verify_launch_and_dependencies(
            repo_root=repo_root,
            run_dir=run_dir,
            manifest=manifest,
            protocol=protocol,
        )
    else:
        smoke_seed = int.from_bytes(
            hashlib.sha256(
                f"{SMOKE_PREFIX}|pair|0".encode("utf-8")
            ).digest()[:8],
            "big",
        )
        official_seeds = set(protocol["splits"]["validation"]["pair_seeds"])
        official_seeds.update(protocol["splits"]["test"]["pair_seeds"])
        if (
            manifest.get("launch") is not None
            or manifest.get("source_bundle") != []
            or design.get("pair_seeds") != [smoke_seed]
            or smoke_seed in official_seeds
            or design.get("calls_per_arm_pair") not in range(1, 9)
            or design.get("checkpoints")
            != [
                checkpoint
                for checkpoint in CHECKPOINTS
                if checkpoint <= design["calls_per_arm_pair"]
            ]
            or manifest.get("model")
            != {"fixture": "outcome_free_smoke_scores"}
        ):
            raise ValueError("smoke test escaped its isolated domain")
    supplied_registry = load_canonical_json(
        run_dir / "prior_split_registry.json"
    )
    verify_self_hash(
        supplied_registry,
        "registry_sha256",
        label="test prior registry",
    )
    expected_prior = expected_registry(repo_root, mode=mode)
    if (
        supplied_registry != expected_prior
        or manifest.get("prior_split_registry_sha256")
        != supplied_registry["registry_sha256"]
    ):
        raise ValueError("prior-split registry does not replay")
    claimed_streams = load_canonical_json(run_dir / "stream_metrics.json")
    verify_self_hash(
        claimed_streams,
        "bundle_sha256",
        label="stream bundle",
    )
    streams, final_proposal, final_event, witness = replay_ledgers(
        repo_root=repo_root,
        run_dir=run_dir,
        mode=mode,
        registry=supplied_registry,
        design=design,
        claimed_streams=claimed_streams,
    )
    expected_streams = independent_stream_bundle(streams)
    if expected_streams != claimed_streams:
        raise ValueError("stream and checkpoint metrics do not replay")
    supplied_preliminary = load_canonical_json(
        run_dir / "preliminary_report.json"
    )
    verify_self_hash(
        supplied_preliminary,
        "report_sha256",
        label="preliminary report",
    )
    if supplied_preliminary != preliminary_report(streams, protocol):
        raise ValueError("preliminary report does not replay")
    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    verify_self_hash(
        generation,
        "generation_sha256",
        label="generation completion",
    )
    expected_count = (
        len(TARGETS)
        * len(design["pair_seeds"])
        * len(ARMS)
        * design["calls_per_arm_pair"]
    )
    file_bindings = {
        "manifest_file_sha256": "manifest.json",
        "prior_split_registry_file_sha256": "prior_split_registry.json",
        "proposal_file_sha256": "proposal_decisions.jsonl",
        "event_file_sha256": "events.jsonl",
        "stream_metrics_file_sha256": "stream_metrics.json",
        "preliminary_report_file_sha256": "preliminary_report.json",
    }
    for field, relative in file_bindings.items():
        if generation.get(field) != file_sha256(run_dir / relative):
            raise ValueError(f"generation file binding changed: {field}")
    if (
        generation.get("status")
        != (
            "AWAITING_INDEPENDENT_TEST_REPLAY"
            if mode == OFFICIAL_MODE
            else "SMOKE_ONLY_NOT_EVIDENCE"
        )
        or generation.get("mode") != mode
        or generation.get("proposal_count") != expected_count
        or generation.get("event_count") != expected_count
        or generation.get("exact_verifier_calls_consumed") != expected_count
        or generation.get("raw_pool_candidate_count") != expected_count * 16
        or generation.get("final_proposal_sha256") != final_proposal
        or generation.get("final_event_sha256") != final_event
        or generation.get("test_outcomes_sealed_from_proposal_and_ranking")
        is not True
        or generation.get("scientific_gate_pending_independent_replay")
        is not True
        or generation.get("paper_evidence") is not False
    ):
        raise ValueError("generation counts, endpoints, or boundary changed")
    if mode == OFFICIAL_MODE:
        limits = protocol["resource_gate"]
        if (
            generation.get("generation_wall_seconds", math.inf)
            > limits["generation_wall_seconds"]
            or generation.get("run_directory_bytes_before_marker", math.inf)
            > limits["run_directory_bytes"]
            or generation.get("peak_resident_memory_bytes", math.inf)
            > limits["peak_resident_memory_bytes"]
        ):
            raise ValueError("generation resource gate failed")
    elif (
        generation.get("generation_wall_seconds") != 0.0
        or generation.get("peak_resident_memory_bytes") != 0
    ):
        raise ValueError("smoke observational timing was not suppressed")
    inference = independent_inference(streams, protocol)
    gate = independent_gate(streams, inference, protocol)
    corruption = corruption_suite(
        protocol=protocol,
        manifest=manifest,
        dependencies=dependencies,
        registry=supplied_registry,
        witness=witness,
        streams=expected_streams,
        inference=inference,
        gate=gate,
        final_proposal=final_proposal,
        final_event=final_event,
    )
    if (
        corruption["status"] != "PASS"
        or corruption["rejected_family_count"]
        != protocol["integrity"]["corruption_family_count"]
    ):
        raise ValueError("one or more corruption families escaped")
    write_json_exclusive(run_dir / "independent_stream_metrics.json", expected_streams)
    write_json_exclusive(run_dir / "independent_inference.json", inference)
    write_json_exclusive(run_dir / "independent_gate.json", gate)
    write_json_exclusive(run_dir / "corruption_tests.json", corruption)
    elapsed = time.monotonic() - started
    if (
        mode == OFFICIAL_MODE
        and elapsed
        > protocol["resource_gate"]["independent_verification_wall_seconds"]
    ):
        raise TimeoutError("independent verification exceeded frozen wall limit")
    verification = hashed_record(
        {
            "schema_version": f"{SCHEMA}.independent_verification",
            "status": (
                "PASS" if mode == OFFICIAL_MODE else "SMOKE_PASS_NOT_EVIDENCE"
            ),
            "mode": mode,
            "protocol_schema_and_semantic_validation": True,
            "launch_source_validation_model_and_preflight_replay": (
                mode == OFFICIAL_MODE
            ),
            "complete_prior_split_registry_replay": True,
            "split_rng_parent_pool_and_tier_replay": True,
            "outcome_free_model_score_embedding_memory_and_fusion_replay": True,
            "exact_decision_sidecar_descriptor_and_transition_replay": True,
            "independent_quotient_and_literal_discovery_replay": True,
            "stream_checkpoint_inference_and_gate_replay": True,
            "corruption_suite_pass": True,
            "corruption_family_count": len(CORRUPTION_FAMILIES),
            "proposal_count": expected_count,
            "event_count": expected_count,
            "final_proposal_sha256": final_proposal,
            "final_event_sha256": final_event,
            "stream_bundle_sha256": expected_streams["bundle_sha256"],
            "inference_sha256": inference["inference_sha256"],
            "gate_sha256": gate["gate_sha256"],
            "wall_seconds": 0.0 if mode == SMOKE_MODE else elapsed,
            "paper_evidence": False,
        },
        "verification_sha256",
    )
    write_json_exclusive(
        run_dir / "independent_verification.json",
        verification,
    )
    scientific_pass = gate[
        "all_scientific_checks_pass_before_independent_replay"
    ]
    status = (
        ("GO" if scientific_pass else "NO_GO")
        if mode == OFFICIAL_MODE
        else "SMOKE_PASS_NOT_EVIDENCE"
    )
    report = final_report(
        mode=mode,
        status=status,
        inference=inference,
        gate=gate,
        corruption=corruption,
        protocol=protocol,
    )
    write_json_exclusive(run_dir / "report.json", report)
    completion = hashed_record(
        {
            "schema_version": f"{SCHEMA}.completion",
            "status": status,
            "decision": (
                status if mode == OFFICIAL_MODE else "NOT_APPLICABLE_SMOKE"
            ),
            "mode": mode,
            "scientific_gate_pass": (
                scientific_pass if mode == OFFICIAL_MODE else False
            ),
            "independent_replay_pass": True,
            "corruption_suite_pass": True,
            "corruption_family_count": len(CORRUPTION_FAMILIES),
            "equal_exact_verifier_budgets": True,
            "secondary_rescue_used": False,
            "evidence_eligible": mode == OFFICIAL_MODE,
            "paper_evidence": mode == OFFICIAL_MODE,
            "generation_file_sha256": file_sha256(
                run_dir / "GENERATION_COMPLETE.json"
            ),
            "stream_metrics_file_sha256": file_sha256(
                run_dir / "stream_metrics.json"
            ),
            "independent_stream_metrics_file_sha256": file_sha256(
                run_dir / "independent_stream_metrics.json"
            ),
            "inference_file_sha256": file_sha256(
                run_dir / "independent_inference.json"
            ),
            "gate_file_sha256": file_sha256(
                run_dir / "independent_gate.json"
            ),
            "verification_file_sha256": file_sha256(
                run_dir / "independent_verification.json"
            ),
            "corruption_tests_file_sha256": file_sha256(
                run_dir / "corruption_tests.json"
            ),
            "report_file_sha256": file_sha256(run_dir / "report.json"),
        },
        "completion_sha256",
    )
    write_json_exclusive(run_dir / "RUN_COMPLETE.json", completion)
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
        else repo_root / args.run_dir
    ).resolve()
    completion = replay(run_dir, repo_root)
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
