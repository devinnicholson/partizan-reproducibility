#!/usr/bin/env python3
"""Generate the one-time three-arm diversity-policy V2 held-out test."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np

import digraph_order7_neural_policy_test_v1 as prior_test
from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    graph_from_candidate_record,
    weakly_connected,
)
from digraph_placement_control import parse_game_form
import freeze_digraph_order7_diversity_model_v2 as freezer
from semantic_equality_certificate_v1 import artifact_binding
import verify_digraph_order7_diversity_model_package_v2 as model_verifier


SCHEMA = "partizan.digraph_order7_diversity_policy_test.v2"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
REGISTRY_SCHEMA = f"{SCHEMA}.prior_split_registry"
PROPOSAL_SCHEMA = f"{SCHEMA}.proposal_decision"
EVENT_SCHEMA = f"{SCHEMA}.event"
STREAM_SCHEMA = f"{SCHEMA}.stream"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
PROTOCOL_PATH = freezer.PROTOCOL_PATH
MODEL_DIR = model_verifier.DEFAULT_MODEL_DIR
RESOURCE_PREFLIGHT = Path(
    "output/research/DIGRAPH_ORDER7_DIVERSITY_RESOURCE_PREFLIGHT_V2.json"
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
ZERO_SHA256 = "0" * 64
CHECKPOINTS = (128, 512, 1024, 2048)


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


def verify_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
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


def peak_rss_bytes() -> int:
    observed = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return observed if sys.platform == "darwin" else observed * 1024


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def safe_bound_path(
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


def snapshot_bound_sources(
    *,
    repo_root: Path,
    run_dir: Path,
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    snapshots = []
    for index, binding in enumerate(sources):
        source = safe_bound_path(
            repo_root,
            binding,
            label=f"test source {index}",
        )
        relative = Path(binding["path"])
        snapshot_relative = Path("source_bundle") / relative
        data = source.read_bytes()
        write_bytes_exclusive(run_dir / snapshot_relative, data)
        snapshots.append(
            {
                "path": relative.as_posix(),
                "sha256": binding["sha256"],
                "snapshot_path": snapshot_relative.as_posix(),
                "snapshot_sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return snapshots


def prior_split_registry(
    repo_root: Path,
    *,
    mode: str,
) -> dict[str, Any]:
    protocol, launch, completion, validation, _rows = freezer.validation_sources(
        repo_root
    )
    pre_v2 = load_canonical_json(
        repo_root
        / launch["output_directory"]
        / "prior_split_identity_registry.json"
    )
    verify_self_hash(pre_v2, "registry_sha256", label="pre-V2 registry")
    candidates = set(pre_v2["candidate_sha256"])
    quotients = set(pre_v2["quotient_sha256"])
    literals = set(pre_v2["literal_game_sha256_audit_only"])
    if mode == OFFICIAL_MODE:
        candidates.update(validation["candidate_sha256"])
        quotients.update(validation["quotient_sha256"])
        literals.update(validation["literal_game_sha256_audit_only"])
    training = prior_test.validation_builder.training_identity_registry(repo_root)
    controls = prior_test.stage0_controls(repo_root, training)
    payload = {
        "schema_version": REGISTRY_SCHEMA,
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
        "stage0_controls": controls,
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


def first_nonempty_tier(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[int, list[int]]:
    for tier_index in range(4):
        eligible = []
        for slot, candidate in enumerate(candidates):
            conditions = (
                candidate["weakly_connected"],
                not candidate["prior_split_candidate_collision"],
                candidate["candidate_new_to_arm"],
            )
            if (
                (tier_index == 0 and all(conditions))
                or (tier_index == 1 and all(conditions[:2]))
                or (tier_index == 2 and conditions[1])
                or tier_index == 3
            ):
                eligible.append(slot)
        if eligible:
            return tier_index, eligible
    raise AssertionError("all-candidate tier cannot be empty")


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


class FrozenRankers:
    def __init__(self, repo_root: Path) -> None:
        (
            self.protocol,
            self.validation_launch,
            _completion,
            _registry,
            _rows,
        ) = freezer.validation_sources(repo_root)
        self.equality, self.diversity = freezer.load_frozen_rankers(
            repo_root,
            self.validation_launch,
        )
        (
            self.equality_model,
            self.equality_record,
            self.equality_path,
        ) = freezer.load_equality_ensemble(
            repo_root,
            self.protocol,
            self.equality,
        )
        self.model_dir = repo_root / MODEL_DIR
        self.package = load_canonical_json(self.model_dir / "MODEL_PACKAGE.json")
        ensemble_path = (
            self.model_dir / self.package["artifacts"]["ensemble"]["path"]
        )
        self.novelty_record = json.loads(ensemble_path.read_bytes())
        self.novelty_ensemble = self.diversity.DiversityEnsemble.from_record(
            self.novelty_record
        )
        self.lambda_weight = self.package["selected"]["lambda"]

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
            raise ValueError("equality model produced nonfinite logits")
        return values.tolist()

    def new_memory(self, candidate: Mapping[str, Any]) -> "NoveltyMemory":
        return NoveltyMemory(self, candidate)


class NoveltyMemory:
    def __init__(
        self,
        rankers: FrozenRankers,
        stage0_candidate: Mapping[str, Any],
    ) -> None:
        self.rankers = rankers
        nodes, adjacency = rankers.diversity._candidate_arrays(stage0_candidate)
        embedded = rankers.novelty_ensemble.embed_members(
            nodes[None, ...],
            adjacency[None, ...],
        )
        self.member_memory = [
            [member[0].copy()] for member in embedded
        ]
        self.last_pool_embeddings: dict[str, tuple[np.ndarray, ...]] = {}

    def rank(
        self,
        rows: Sequence[Mapping[str, Any]],
        equality_logits: Sequence[float],
    ) -> list[dict[str, Any]]:
        (
            nodes,
            adjacency,
            candidate_ids,
            _target,
            _base_seed,
            _pool_id,
        ) = self.rankers.diversity._pool_arrays(rows)
        candidate_members = self.rankers.novelty_ensemble.embed_members(
            nodes,
            adjacency,
        )
        self.last_pool_embeddings = {
            candidate_sha: tuple(
                member[index].copy() for member in candidate_members
            )
            for index, candidate_sha in enumerate(candidate_ids)
        }
        member_scores = []
        for member_index, candidate_embeddings in enumerate(candidate_members):
            memory = np.stack(self.member_memory[member_index])
            similarities = np.clip(
                candidate_embeddings @ memory.T,
                -1.0,
                1.0,
            )
            member_scores.append(np.min(1.0 - similarities, axis=1))
        novelty = np.mean(np.stack(member_scores), axis=0)
        equality_values = np.asarray(equality_logits, dtype=np.float64)
        equality_rank = self.rankers.diversity.midrank_fraction(equality_values)
        novelty_rank = self.rankers.diversity.midrank_fraction(novelty)
        fused = (
            equality_rank
            + self.rankers.lambda_weight * novelty_rank
        )
        return [
            {
                "candidate_sha256": candidate_ids[index],
                "equality_logit": float(equality_values[index]),
                "novelty_score": float(novelty[index]),
                "equality_midrank_fraction": float(equality_rank[index]),
                "novelty_midrank_fraction": float(novelty_rank[index]),
                "rank_fusion_score": float(fused[index]),
            }
            for index in range(len(candidate_ids))
        ]

    def append_selected(self, candidate_sha256: str) -> None:
        embeddings = self.last_pool_embeddings.get(candidate_sha256)
        if embeddings is None:
            raise ValueError("selected graph is absent from novelty pool cache")
        for member_index, embedding in enumerate(embeddings):
            self.member_memory[member_index].append(embedding.copy())

    @property
    def size(self) -> int:
        return len(self.member_memory[0])


class SmokeNoveltyMemory:
    """Count fixture updates without loading or exercising a frozen model."""

    def __init__(self) -> None:
        self._size = 1

    def append_selected(self, _candidate_sha256: str) -> None:
        self._size += 1

    @property
    def size(self) -> int:
        return self._size


class StreamAccumulator:
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
        self.exact_matches = 0
        self.known_quotients = {stage0["quotient_sha256"]}
        self.known_literals = {stage0["literal_game_sha256"]}
        self.quotient_discoveries: set[str] = set()
        self.literal_discoveries: set[str] = set()
        self.descriptor_cells: set[tuple[str, ...]] = set()
        self.transition_classes: Counter[str] = Counter()
        self.selected_candidates: set[str] = set()
        self.tier_counts: Counter[int] = Counter()
        self.checkpoint_quotients: dict[str, int] = {}
        self.checkpoint_literals: dict[str, int] = {}
        self.prior_collisions = 0
        self.model_inference_seconds = 0.0

    def update(self, event: Mapping[str, Any]) -> None:
        self.calls += 1
        self.tier_counts[event["structural_filter"]["tier_index"]] += 1
        self.selected_candidates.add(event["candidate_sha256"])
        decision = event["exact_decision"]
        equal = isinstance(decision, Mapping) and decision.get("equal") is True
        if equal:
            self.exact_matches += 1
        if event["prior_split_leakage"]:
            self.prior_collisions += 1
        clean_equal = equal and not event["prior_split_leakage"]
        if clean_equal:
            quotient_sha = event["structural_quotient"]["quotient_sha256"]
            literal_sha = decision["candidate_root_game_sha256"]
            new_quotient = quotient_sha not in self.known_quotients
            new_literal = literal_sha not in self.known_literals
            self.known_quotients.add(quotient_sha)
            self.known_literals.add(literal_sha)
            if new_quotient:
                self.quotient_discoveries.add(quotient_sha)
            if new_literal:
                self.literal_discoveries.add(literal_sha)
            if new_quotient or new_literal:
                self.descriptor_cells.add(
                    tuple(event["measurements"]["descriptor_cell"])
                )
        transition = event["transition"]
        if isinstance(transition, Mapping) and transition.get("primary"):
            self.transition_classes[transition["class"]] += 1
        if self.calls in CHECKPOINTS:
            self.checkpoint_quotients[str(self.calls)] = len(
                self.quotient_discoveries
            )
            self.checkpoint_literals[str(self.calls)] = len(
                self.literal_discoveries
            )

    def record(self, *, suppress_timing: bool) -> dict[str, Any]:
        payload = {
            "schema_version": STREAM_SCHEMA,
            "target": self.target,
            "pair_seed": self.pair_seed,
            "arm": self.arm,
            "verifier_calls": self.calls,
            "raw_pool_candidates": self.calls * 16,
            "certified_exact_matches": self.exact_matches,
            "quotient_unique_discoveries": len(self.quotient_discoveries),
            "quotient_unique_by_checkpoint": self.checkpoint_quotients,
            "discovered_quotient_sha256": sorted(
                self.quotient_discoveries
            ),
            "literal_game_unique_discoveries": len(
                self.literal_discoveries
            ),
            "literal_game_unique_by_checkpoint": self.checkpoint_literals,
            "literal_game_sha256": sorted(self.literal_discoveries),
            "occupied_descriptor_cells": len(self.descriptor_cells),
            "descriptor_cells": [
                list(cell) for cell in sorted(self.descriptor_cells)
            ],
            "transition_class_counts": dict(
                sorted(self.transition_classes.items())
            ),
            "embodiment_only_transitions": self.transition_classes[
                "embodiment_only"
            ],
            "literal_tree_crossing_transitions": self.transition_classes[
                "literal_tree_crossing"
            ],
            "selected_candidate_unique_count": len(
                self.selected_candidates
            ),
            "prior_split_collision_count": self.prior_collisions,
            "structural_tier_counts": {
                str(key): self.tier_counts[key]
                for key in sorted(self.tier_counts)
            },
            "model_inference_seconds": (
                0.0 if suppress_timing else self.model_inference_seconds
            ),
            "timing_suppressed_for_smoke": suppress_timing,
        }
        return hashed_record(payload, "stream_sha256")


def stream_bundle(streams: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    overlap = {}
    for target in TARGETS:
        overlap[target] = {}
        for pair_seed in sorted(
            {
                row["pair_seed"]
                for row in streams
                if row["target"] == target
            }
        ):
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
    payload = {
        "schema_version": f"{STREAM_SCHEMA}.bundle",
        "streams": list(streams),
        "stream_count": len(streams),
        "cross_arm_quotient_overlap": overlap,
    }
    return hashed_record(payload, "bundle_sha256")


def select_slot(
    *,
    arm: str,
    eligible: Sequence[int],
    candidates: Sequence[Mapping[str, Any]],
    equality_logits: Sequence[float] | None,
    novelty_records: Sequence[Mapping[str, Any]] | None,
    target: str,
    pair_seed: int,
    call_index: int,
    prefix: str,
    phase: str,
) -> int:
    if arm == RANDOM_ARM:
        offset = prior_test.counter_randbelow(
            len(eligible),
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=call_index,
            draw_name="random_selection",
        )
        return eligible[offset]
    if arm == EQUALITY_ARM and equality_logits is not None:
        return min(
            eligible,
            key=lambda slot: (
                -float(equality_logits[slot]),
                candidates[slot]["candidate_sha256"],
            ),
        )
    if arm == NOVELTY_ARM and novelty_records is not None:
        return min(
            eligible,
            key=lambda slot: (
                -float(novelty_records[slot]["rank_fusion_score"]),
                candidates[slot]["candidate_sha256"],
            ),
        )
    raise ValueError("arm selection lacks frozen model scores")


def generate_ledgers(
    *,
    run_dir: Path,
    mode: str,
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    registry: Mapping[str, Any],
    rankers: FrozenRankers | None,
) -> tuple[dict[str, Any], str, str]:
    prefix = PREFIX if mode == OFFICIAL_MODE else SMOKE_PREFIX
    phase = "test" if mode == OFFICIAL_MODE else "smoke_test"
    prior_candidates = set(registry["candidate_sha256"])
    prior_quotients = set(registry["quotient_sha256"])
    target_games = {target: parse_game_form(target) for target in TARGETS}
    target_bindings = {}
    if mode == OFFICIAL_MODE:
        for target in TARGETS:
            artifact = prior_test.fixed_value.target_artifact(
                target,
                target_games[target],
            )
            reference = prior_test.fixed_value.write_content_addressed(
                run_dir,
                "targets",
                artifact,
            )
            target_bindings[target] = artifact_binding(
                kind="abstract_short_game_target",
                schema_version=artifact["schema_version"],
                artifact_sha256=reference["sha256"],
                root=target_games[target],
            )
    proposal_path = run_dir / "proposal_decisions.jsonl"
    event_path = run_dir / "events.jsonl"
    proposal_fd = os.open(
        proposal_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    event_fd = os.open(
        event_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    previous_proposal = ZERO_SHA256
    previous_event = ZERO_SHA256
    previous_arm = {arm: ZERO_SHA256 for arm in ARMS}
    global_index = 0
    streams = []
    try:
        with os.fdopen(proposal_fd, "wb") as proposal_handle, os.fdopen(
            event_fd,
            "wb",
        ) as event_handle:
            for target in TARGETS:
                for pair_seed in pair_seeds:
                    control = registry["stage0_controls"][target]
                    repertoires = {
                        arm: {
                            control["quotient_sha256"]: dict(control)
                        }
                        for arm in ARMS
                    }
                    live_candidates = {
                        arm: {control["candidate_sha256"]} for arm in ARMS
                    }
                    selected_candidates = {arm: set() for arm in ARMS}
                    selected_quotients = {arm: set() for arm in ARMS}
                    accumulators = {
                        arm: StreamAccumulator(
                            target=target,
                            pair_seed=pair_seed,
                            arm=arm,
                            stage0=control,
                        )
                        for arm in ARMS
                    }
                    novelty_memory = (
                        rankers.new_memory(control["candidate"])
                        if rankers is not None
                        else SmokeNoveltyMemory()
                    )
                    for call_index in range(calls_per_arm_pair):
                        arcs = prior_test.selected_arcs(
                            prefix=prefix,
                            phase=phase,
                            target=target,
                            pair_seed=pair_seed,
                            call_index=call_index,
                        )
                        for arm in ARMS:
                            repertoire = repertoires[arm]
                            parent_ids = sorted(repertoire)
                            parent_index = prior_test.counter_randbelow(
                                len(parent_ids),
                                prefix=prefix,
                                phase=phase,
                                target=target,
                                pair_seed=pair_seed,
                                unit_index=call_index,
                                draw_name="parent",
                            )
                            parent = repertoire[parent_ids[parent_index]]
                            parent_graph = graph_from_candidate_record(
                                parent["candidate"]
                            )
                            candidates = []
                            for slot, arc in enumerate(arcs):
                                graph = prior_test.toggle_arc(parent_graph, arc)
                                candidate = candidate_record(graph)
                                candidate_sha = candidate_record_sha256(candidate)
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
                            if len(
                                {
                                    row["candidate_sha256"]
                                    for row in candidates
                                }
                            ) != 16:
                                raise ValueError("test pool has duplicate candidates")
                            tier_index, eligible = first_nonempty_tier(candidates)
                            pool_id = object_sha256(
                                {
                                    "schema_version": f"{SCHEMA}.pool_id",
                                    "mode": mode,
                                    "target": target,
                                    "pair_seed": pair_seed,
                                    "call_index": call_index,
                                    "arm": arm,
                                    "parent_quotient_sha256": parent_ids[
                                        parent_index
                                    ],
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
                            inference_started = time.perf_counter()
                            if rankers is not None and arm in (
                                EQUALITY_ARM,
                                NOVELTY_ARM,
                            ):
                                equality_logits = rankers.equality_logits(rows)
                            if rankers is not None and arm == NOVELTY_ARM:
                                assert novelty_memory is not None
                                novelty_records = novelty_memory.rank(
                                    rows,
                                    equality_logits,
                                )
                            inference_seconds = (
                                time.perf_counter() - inference_started
                            )
                            if mode == SMOKE_MODE and arm != RANDOM_ARM:
                                equality_logits = [
                                    prior_test.smoke_ranker([row])[0]
                                    for row in rows
                                ]
                                if arm == NOVELTY_ARM:
                                    novelty_records = [
                                        {
                                            "candidate_sha256": row[
                                                "candidate_sha256"
                                            ],
                                            "equality_logit": equality_logits[
                                                slot
                                            ],
                                            "novelty_score": float(slot) / 15.0,
                                            "equality_midrank_fraction": float(
                                                slot
                                            )
                                            / 15.0,
                                            "novelty_midrank_fraction": float(
                                                slot
                                            )
                                            / 15.0,
                                            "rank_fusion_score": (
                                                equality_logits[slot]
                                                + float(slot) / 30.0
                                            ),
                                        }
                                        for slot, row in enumerate(candidates)
                                    ]
                            selected_slot = select_slot(
                                arm=arm,
                                eligible=eligible,
                                candidates=candidates,
                                equality_logits=equality_logits,
                                novelty_records=novelty_records,
                                target=target,
                                pair_seed=pair_seed,
                                call_index=call_index,
                                prefix=prefix,
                                phase=phase,
                            )
                            proposal_payload = {
                                "schema_version": PROPOSAL_SCHEMA,
                                "mode": mode,
                                "global_proposal_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "pool_id": pool_id,
                                "parent": {
                                    "candidate_sha256": parent[
                                        "candidate_sha256"
                                    ],
                                    "quotient_sha256": parent[
                                        "quotient_sha256"
                                    ],
                                },
                                "candidates": candidates,
                                "structural_filter": {
                                    "tier_index": tier_index,
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
                                    "novelty_by_slot": (
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
                                    ),
                                    "outcome_fields_received": [],
                                },
                                "selection": {
                                    "selected_slot": selected_slot,
                                    "selected_candidate_sha256": candidates[
                                        selected_slot
                                    ]["candidate_sha256"],
                                },
                                "previous_proposal_sha256": previous_proposal,
                            }
                            proposal = hashed_record(
                                proposal_payload,
                                "proposal_sha256",
                            )
                            proposal_handle.write(canonical_line(proposal))
                            proposal_handle.flush()
                            previous_proposal = proposal["proposal_sha256"]

                            selected = candidates[selected_slot]
                            graph = graph_from_candidate_record(
                                selected["candidate"]
                            )
                            other_arms = [name for name in ARMS if name != arm]
                            semantic, inserted = prior_test.evaluate_selected(
                                graph=graph,
                                candidate=selected["candidate"],
                                candidate_sha=selected["candidate_sha256"],
                                target=target,
                                parent=parent,
                                mode=mode,
                                target_games=target_games,
                                target_bindings=target_bindings,
                                prior_candidates=prior_candidates,
                                prior_quotients=prior_quotients,
                                repertoire=repertoire,
                                other_candidates=set().union(
                                    *(
                                        selected_candidates[name]
                                        for name in other_arms
                                    )
                                ),
                                other_quotients=set().union(
                                    *(
                                        selected_quotients[name]
                                        for name in other_arms
                                    )
                                ),
                                run_dir=run_dir,
                            )
                            selected_candidates[arm].add(
                                selected["candidate_sha256"]
                            )
                            structural = semantic["structural_quotient"]
                            if structural is not None:
                                selected_quotients[arm].add(
                                    structural["quotient_sha256"]
                                )
                            decision = semantic["exact_decision"]
                            clean_equal = (
                                isinstance(decision, Mapping)
                                and decision.get("equal") is True
                                and not semantic["prior_split_leakage"]
                            )
                            if clean_equal:
                                live_candidates[arm].add(
                                    selected["candidate_sha256"]
                                )
                                if arm == NOVELTY_ARM:
                                    assert novelty_memory is not None
                                    novelty_memory.append_selected(
                                        selected["candidate_sha256"]
                                    )
                            event_payload = {
                                "schema_version": EVENT_SCHEMA,
                                "mode": mode,
                                "global_event_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "proposal_sha256": proposal[
                                    "proposal_sha256"
                                ],
                                "pool_id": pool_id,
                                "parent": proposal["parent"],
                                "proposal": {
                                    "operator": "toggle_one_arc",
                                    "arc": selected["arc"],
                                    "selected_slot": selected_slot,
                                },
                                "candidate": selected["candidate"],
                                "candidate_sha256": selected[
                                    "candidate_sha256"
                                ],
                                "structural_filter": proposal[
                                    "structural_filter"
                                ],
                                "model_selected": {
                                    "equality_logit_hex": (
                                        float(
                                            equality_logits[selected_slot]
                                        ).hex()
                                        if equality_logits is not None
                                        else None
                                    ),
                                    "novelty": (
                                        proposal["model"]["novelty_by_slot"][
                                            selected_slot
                                        ]
                                        if novelty_records is not None
                                        else None
                                    ),
                                    "novelty_memory_size_after": (
                                        novelty_memory.size
                                        if arm == NOVELTY_ARM
                                        and novelty_memory is not None
                                        else None
                                    ),
                                },
                                "exact_verifier_call_consumed": True,
                                **semantic,
                                "previous_arm_event_sha256": previous_arm[arm],
                                "previous_global_event_sha256": previous_event,
                            }
                            event = hashed_record(
                                event_payload,
                                "event_sha256",
                            )
                            event_handle.write(canonical_line(event))
                            event_handle.flush()
                            previous_arm[arm] = event["event_sha256"]
                            previous_event = event["event_sha256"]
                            accumulators[arm].model_inference_seconds += (
                                inference_seconds
                            )
                            accumulators[arm].update(event)
                            global_index += 1
                            prior_test.fixed_value.clear_caches()
                        if call_index + 1 in CHECKPOINTS:
                            os.fsync(proposal_handle.fileno())
                            os.fsync(event_handle.fileno())
                    for arm in ARMS:
                        streams.append(
                            accumulators[arm].record(
                                suppress_timing=mode == SMOKE_MODE
                            )
                        )
            proposal_handle.flush()
            event_handle.flush()
            os.fsync(proposal_handle.fileno())
            os.fsync(event_handle.fileno())
    except BaseException:
        raise
    return stream_bundle(streams), previous_proposal, previous_event


def preliminary_report(
    streams_bundle: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    streams = streams_bundle["streams"]
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
    per_target_literal_difference = {}
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
        per_target_literal_difference[target] = float(
            np.mean(np.asarray(novelty) - np.asarray(equality))
        )
    payload = {
        "schema_version": f"{SCHEMA}.preliminary_report",
        "status": "AWAITING_INDEPENDENT_INFERENCE_AND_GATE_REPLAY",
        "totals": totals,
        "per_target_mean_literal_difference_novelty_minus_equality": (
            per_target_literal_difference
        ),
        "frozen_thresholds": protocol["pareto_restoration_gate"],
        "scientific_status": None,
        "independent_replay_pending": True,
        "paper_evidence": False,
    }
    return hashed_record(payload, "report_sha256")


def verify_launch(
    *,
    repo_root: Path,
    launch: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    verify_self_hash(launch, "launch_sha256", label="test launch")
    if (
        launch.get("schema_version") != LAUNCH_SCHEMA
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("test launch boundary changed")
    if launch.get("protocol") != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("test launch protocol binding changed")
    test = protocol["splits"]["test"]
    expected_design = {
        "targets": list(TARGETS),
        "pair_seeds": test["pair_seeds"],
        "arms": list(ARMS),
        "calls_per_arm_pair": test["verifier_calls_per_arm_pair"],
        "candidate_pool_size": protocol["budget"]["candidate_pool_size"],
        "checkpoints": test["checkpoints"],
        "success_stopping_rule": False,
    }
    if launch.get("test_design") != expected_design:
        raise ValueError("test launch design changed")
    for section in (
        "validation_completion",
        "validation_registry",
        "model_package",
        "model_verification",
        "resource_preflight",
    ):
        safe_bound_path(repo_root, launch[section], label=section)
    sources = launch.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("test launch source inventory is empty")
    for entry in sources:
        safe_bound_path(repo_root, entry, label="test source")
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
    if launch.get("output_directory") != expected_output:
        raise ValueError("test launch output is not authorization-derived")


def build_run(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    launch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    test = protocol["splits"]["test"]
    if mode == OFFICIAL_MODE:
        if launch is None:
            raise ValueError("official test requires its one-time launch")
        verify_launch(repo_root=repo_root, launch=launch, protocol=protocol)
        if (
            list(pair_seeds) != test["pair_seeds"]
            or calls_per_arm_pair != test["verifier_calls_per_arm_pair"]
            or run_dir.resolve()
            != (repo_root / launch["output_directory"]).resolve()
        ):
            raise ValueError("official test design changed")
    elif mode == SMOKE_MODE:
        if launch is not None or len(pair_seeds) != 1:
            raise ValueError("smoke test launch boundary changed")
        if not 1 <= calls_per_arm_pair <= 8:
            raise ValueError("smoke calls must be between one and eight")
    else:
        raise ValueError("unknown test mode")
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        launch_binding = None
        if launch is not None:
            write_json_exclusive(run_dir / "launch_record.json", launch)
            launch_binding = {
                "file": "launch_record.json",
                "file_sha256": file_sha256(run_dir / "launch_record.json"),
                "launch_sha256": launch["launch_sha256"],
                "authorization_sha256": launch["authorization_sha256"],
            }
        source_bundle = (
            snapshot_bound_sources(
                repo_root=repo_root,
                run_dir=run_dir,
                sources=launch["sources"],
            )
            if launch is not None
            else []
        )
        registry = prior_split_registry(repo_root, mode=mode)
        write_json_exclusive(run_dir / "prior_split_registry.json", registry)
        manifest = hashed_record(
            {
                "schema_version": MANIFEST_SCHEMA,
                "status": (
                    "AWAITING_INDEPENDENT_TEST_REPLAY"
                    if mode == OFFICIAL_MODE
                    else "SMOKE_ONLY_NOT_EVIDENCE"
                ),
                "mode": mode,
                "protocol": {
                    "path": PROTOCOL_PATH.as_posix(),
                    "sha256": file_sha256(repo_root / PROTOCOL_PATH),
                },
                "launch": launch_binding,
                "source_bundle": source_bundle,
                "prior_split_registry_sha256": registry["registry_sha256"],
                "test_design": {
                    "targets": list(TARGETS),
                    "pair_seeds": list(pair_seeds),
                    "arms": list(ARMS),
                    "calls_per_arm_pair": calls_per_arm_pair,
                    "candidate_pool_size": 16,
                    "checkpoints": [
                        value
                        for value in CHECKPOINTS
                        if value <= calls_per_arm_pair
                    ],
                    "success_stopping_rule": False,
                },
                "model": (
                    {
                        "model_package_sha256": load_canonical_json(
                            repo_root / MODEL_DIR / "MODEL_PACKAGE.json"
                        )["package_sha256"],
                        "cpu_only_deterministic": True,
                        "cached_memory_embeddings": True,
                    }
                    if mode == OFFICIAL_MODE
                    else {"fixture": "outcome_free_smoke_scores"}
                ),
                "paper_evidence": False,
            },
            "manifest_sha256",
        )
        write_json_exclusive(run_dir / "manifest.json", manifest)
        rankers = FrozenRankers(repo_root) if mode == OFFICIAL_MODE else None
        streams, final_proposal, final_event = generate_ledgers(
            run_dir=run_dir,
            mode=mode,
            pair_seeds=pair_seeds,
            calls_per_arm_pair=calls_per_arm_pair,
            registry=registry,
            rankers=rankers,
        )
        write_json_exclusive(run_dir / "stream_metrics.json", streams)
        report = preliminary_report(streams, protocol)
        write_json_exclusive(run_dir / "preliminary_report.json", report)
        expected_events = (
            len(TARGETS)
            * len(pair_seeds)
            * len(ARMS)
            * calls_per_arm_pair
        )
        elapsed = time.monotonic() - started
        size = directory_size(run_dir)
        rss = 0 if mode == SMOKE_MODE else peak_rss_bytes()
        if mode == OFFICIAL_MODE:
            limits = protocol["resource_gate"]
            if (
                elapsed > limits["generation_wall_seconds"]
                or size > limits["run_directory_bytes"]
                or rss > limits["peak_resident_memory_bytes"]
            ):
                raise OSError("official test exceeded a frozen resource limit")
        generation_payload = {
            "schema_version": GENERATION_SCHEMA,
            "status": (
                "AWAITING_INDEPENDENT_TEST_REPLAY"
                if mode == OFFICIAL_MODE
                else "SMOKE_ONLY_NOT_EVIDENCE"
            ),
            "mode": mode,
            "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
            "prior_split_registry_file_sha256": file_sha256(
                run_dir / "prior_split_registry.json"
            ),
            "proposal_file_sha256": file_sha256(
                run_dir / "proposal_decisions.jsonl"
            ),
            "event_file_sha256": file_sha256(run_dir / "events.jsonl"),
            "stream_metrics_file_sha256": file_sha256(
                run_dir / "stream_metrics.json"
            ),
            "preliminary_report_file_sha256": file_sha256(
                run_dir / "preliminary_report.json"
            ),
            "proposal_count": expected_events,
            "event_count": expected_events,
            "exact_verifier_calls_consumed": expected_events,
            "raw_pool_candidate_count": expected_events * 16,
            "final_proposal_sha256": final_proposal,
            "final_event_sha256": final_event,
            "generation_wall_seconds": (
                0.0 if mode == SMOKE_MODE else elapsed
            ),
            "run_directory_bytes_before_marker": size,
            "peak_resident_memory_bytes": rss,
            "test_outcomes_sealed_from_proposal_and_ranking": True,
            "scientific_gate_pending_independent_replay": True,
            "paper_evidence": False,
        }
        generation = hashed_record(
            generation_payload,
            "generation_sha256",
        )
        write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
        return generation
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.generation_failure",
            "status": "INCOMPLETE_FAIL",
            "mode": mode,
            "error_type": type(error).__name__,
            "error": str(error),
            "resume_authorized": False,
            "paper_evidence": False,
        }
        try:
            write_json_exclusive(
                run_dir / "FAILURE.json",
                hashed_record(failure_payload, "failure_sha256"),
            )
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--mode",
        choices=(SMOKE_MODE, OFFICIAL_MODE),
        required=True,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--smoke-calls", type=int, default=2)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    if args.mode == SMOKE_MODE:
        if args.output is None or args.launch_record is not None:
            raise SystemExit("smoke mode requires only --output")
        run_dir = (
            args.output
            if args.output.is_absolute()
            else (repo_root / args.output)
        ).resolve()
        if not run_dir.name.startswith("smoke-"):
            raise SystemExit("smoke output basename must start with smoke-")
        official = set(protocol["splits"]["validation"]["pair_seeds"]) | set(
            protocol["splits"]["test"]["pair_seeds"]
        )
        smoke_seed = int.from_bytes(
            hashlib.sha256(
                f"{SMOKE_PREFIX}|pair|0".encode("utf-8")
            ).digest()[:8],
            "big",
        )
        if smoke_seed in official:
            raise SystemExit("smoke seed collides with an official split")
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=SMOKE_MODE,
            pair_seeds=[smoke_seed],
            calls_per_arm_pair=args.smoke_calls,
            launch=None,
        )
    else:
        if args.launch_record is None or args.output is not None:
            raise SystemExit("official mode requires only --launch-record")
        launch_path = (
            args.launch_record
            if args.launch_record.is_absolute()
            else (repo_root / args.launch_record)
        ).resolve()
        launch = load_canonical_json(launch_path)
        verify_launch(repo_root=repo_root, launch=launch, protocol=protocol)
        generation = build_run(
            repo_root=repo_root,
            run_dir=(repo_root / launch["output_directory"]).resolve(),
            mode=OFFICIAL_MODE,
            pair_seeds=protocol["splits"]["test"]["pair_seeds"],
            calls_per_arm_pair=protocol["splits"]["test"][
                "verifier_calls_per_arm_pair"
            ],
            launch=launch,
        )
    print(json.dumps(generation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
