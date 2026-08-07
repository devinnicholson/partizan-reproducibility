#!/usr/bin/env python3
"""Generate the preregistered held-out order-7 fixed-value transition ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from digraph_derivation_certificate_v3 import (
    ARTIFACT_SCHEMA,
    build_derivation_certificate,
    build_graph_artifact,
    bytes_sha256,
    canonical_artifact_bytes,
    canonical_json_bytes,
    game_from_verified_derivation,
    object_sha256,
    schema_contract,
    verify_derivation_certificate,
)
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    descriptor_record,
    graph_from_candidate_record,
    quotient_record,
    verify_candidate_evidence,
    verify_target_artifact,
    weakly_connected,
)
from digraph_placement_control import DigraphPlacement, game_from_digraph, parse_game_form
from semantic_equality_certificate_v1 import (
    artifact_binding,
    build_certificate as build_equality_certificate,
    verify_certificate as verify_equality_certificate,
)
from short_game_fiber_pilot import (
    Game,
    birthday,
    edge_count,
    game_digest,
    leq,
    node_count,
    serialize,
)


SCHEMA = "partizan.digraph_order7_fixed_value_transitions.v1"
EVENT_SCHEMA = f"{SCHEMA}.event"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
SUMMARY_SCHEMA = f"{SCHEMA}.summary"
STATUS = "heldout_awaiting_independent_verification"
PREREGISTRATION = Path(
    "docs/research/DIGRAPH_ORDER7_FIXED_VALUE_TRANSITIONS_V1_PREREGISTRATION.md"
)
PREREGISTRATION_SHA256 = (
    "4a9328e40d53ee4ffe9626b51a40ed4b97741ee9f75ac8e9e798a02cd9f444a9"
)
STAGE0 = Path("output/research/digraph-order7-seed-calibration-v1-eb6feb7bdd84")
STAGE0_FAILED = Path(
    "output/research/digraph-order7-seed-calibration-v1-c4b2bb2ec334/FAILURE.json"
)
STAGE0_FILE_HASHES = {
    "manifest.json": "f53642fc48171fa23151c2c5dde86ea9600631cb581ff187bf910aed1afdb480",
    "extensions.jsonl": "6d162a7629e7b22a5e4925ac2741d248a680675fe25e9b249c0475f5d48cc672",
    "leakage_registry.json": "13156553aba96ea455ca57894121cdad310f9bfb5a12bf82156af2b5d41f8aba",
    "seed_controls.json": "ac719d0eda3f7fc5f729ba0511e4bd42275fef85848a72db0b51b190fa78a824",
    "independent_verification.json": "177d23418c42bbf9519aec2a19b8699d715d47df191cb8d734ad9c9d3e635f3a",
    "negative_tests.json": "9a695ab6addb0f2b1a348817576978f2cfcdd148f873af102a5040e93bc259c5",
    "RUN_COMPLETE.json": "a6974e5fa8d32a8daf69d2078a074e777fe8fa66e41a40556c6f9ca52a0896a8",
}
STAGE0_INTERNAL_HASHES = {
    "manifest_sha256": "eb6feb7bdd848613c5bf3752ab0a91f08d9b3f6cda61e4b0fbf3b482cb56d04c",
    "registry_sha256": "dd42ea0518d077cf576bfac062f0329af04de80f97a44fe3bf8c3e26da5d0501",
    "seed_controls_sha256": "ae9749d984c6047db29d3788f3fa9a8432a5d93de0355e9c92cb1539f78d98f7",
    "verification_sha256": "13ef0264afaeed49896992aead62d35fa7f9c3842d22d16e096edbc8c0a75467",
    "completion_sha256": "affea5aed0a606f16ec8a28318fab217cfad908cfcbc89433bca4e707dba4949",
}
STAGE0_FAILED_SHA256 = (
    "3a43b283b8bc278007d23a3efac33d4d809b499e1588d089f6a0a6533e109029"
)
TARGETS = ("0", "*", "{0|1}")
BASE_SEEDS = tuple(104_729 + 1_009 * index for index in range(12))
BUDGET = 2_048
CHECKPOINTS = (128, 512, 1_024, 2_048)
GENERATION_LIMIT_SECONDS = 900
VERIFICATION_LIMIT_SECONDS = 1_200
RUN_SIZE_LIMIT_BYTES = 4 * 1024**3
ZERO_SHA256 = "0" * 64
ARC_LIST = tuple((source, target) for source in range(7) for target in range(7) if source != target)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


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


def verify_embedded_hash(value: Mapping[str, Any], field: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if not isinstance(supplied, str) or object_sha256(payload) != supplied:
        raise ValueError(f"embedded hash {field} does not replay")


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


def content_path(role: str, digest: str) -> PurePosixPath:
    return PurePosixPath("sidecars") / role / digest[:2] / f"{digest}.json"


def write_content_addressed(
    run_dir: Path, role: str, value: Mapping[str, Any] | bytes
) -> dict[str, str]:
    data = value if isinstance(value, bytes) else canonical_json_bytes(value)
    digest = bytes_sha256(data)
    relative = content_path(role, digest)
    destination = run_dir / Path(relative)
    try:
        write_bytes_exclusive(destination, data)
    except FileExistsError:
        if destination.read_bytes() != data:
            raise AssertionError("content-addressed path collision")
    return {"path": relative.as_posix(), "sha256": digest}


def clear_caches() -> None:
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()


def stable_rng_seed(*, base_seed: int, target: str, stream_name: str) -> int:
    payload = f"{SCHEMA}|{base_seed}|{target}|{stream_name}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def graph_from_record(record: Mapping[str, Any]) -> DigraphPlacement:
    return graph_from_candidate_record(record)


@dataclass(frozen=True)
class Proposal:
    mode: str
    operator: str
    candidate: DigraphPlacement


def uniform_order7_immigrant(rng: random.Random) -> DigraphPlacement:
    blue_mask = sum(rng.getrandbits(1) << vertex for vertex in range(7))
    edges = [0] * 7
    for source, target in ARC_LIST:
        if rng.getrandbits(1):
            edges[source] |= 1 << target
    return DigraphPlacement(blue_mask=blue_mask, edges=tuple(edges))


def local_mutation(parent: DigraphPlacement, rng: random.Random) -> Proposal:
    if parent.order != 7:
        raise ValueError("held-out local parent is not order 7")
    operator_index = rng.randrange(3)
    if operator_index == 0:
        vertex = rng.randrange(7)
        return Proposal(
            "local_mutation",
            "flip_colour",
            DigraphPlacement(parent.blue_mask ^ (1 << vertex), parent.edges),
        )
    edges = list(parent.edges)
    if operator_index == 1:
        source, target = ARC_LIST[rng.randrange(len(ARC_LIST))]
        edges[source] ^= 1 << target
        operator = "toggle_one_arc"
    else:
        first = rng.randrange(len(ARC_LIST))
        second = rng.randrange(len(ARC_LIST) - 1)
        if second >= first:
            second += 1
        for arc_index in (first, second):
            source, target = ARC_LIST[arc_index]
            edges[source] ^= 1 << target
        operator = "toggle_two_arcs"
    return Proposal(
        "local_mutation",
        operator,
        DigraphPlacement(parent.blue_mask, tuple(edges)),
    )


def propose(parent: DigraphPlacement, rng: random.Random) -> Proposal:
    if rng.randrange(8) == 0:
        return Proposal("uniform_immigrant", "uniform_immigrant", uniform_order7_immigrant(rng))
    return local_mutation(parent, rng)


def classify_transition(
    *, parent_quotient: str, parent_literal: str, candidate_quotient: str, candidate_literal: str
) -> str:
    if parent_quotient == candidate_quotient:
        return "quotient_self"
    if parent_literal == candidate_literal:
        return "embodiment_only"
    return "literal_tree_crossing"


def exact_decision(graph: DigraphPlacement, target: Game) -> tuple[dict[str, Any], Game]:
    observed = game_from_digraph(graph)
    candidate_leq_target = leq(observed, target)
    target_leq_candidate = leq(target, observed)
    decision = {
        "relation": "finite_normal_play_equality",
        "candidate_root_game_sha256": game_digest(observed),
        "target_root_game_sha256": game_digest(target),
        "candidate_leq_target": candidate_leq_target,
        "target_leq_candidate": target_leq_candidate,
        "equal": candidate_leq_target and target_leq_candidate,
        "distinct_game_tree_node_count": node_count(observed),
        "distinct_game_tree_edge_count": edge_count(observed),
        "game_birthday": birthday(observed),
    }
    return decision, observed


def target_artifact(label: str, target: Game) -> dict[str, Any]:
    return {
        "schema_version": "partizan.abstract_short_game_target.v1",
        "label": label,
        "literal_serialization": serialize(target),
        "root_game_sha256": game_digest(target),
    }


def build_match_sidecars(
    *, graph: DigraphPlacement, target: Game, target_binding: Mapping[str, str], run_dir: Path
) -> tuple[dict[str, Any], str]:
    artifact = build_graph_artifact(graph)
    artifact_bytes = canonical_artifact_bytes(artifact)
    artifact_sha = bytes_sha256(artifact_bytes)
    derivation = build_derivation_certificate(artifact)
    valid, reason = verify_derivation_certificate(
        derivation,
        artifact_bytes=artifact_bytes,
        expected_artifact_sha256=artifact_sha,
    )
    if not valid:
        raise AssertionError(f"fresh derivation failed replay: {reason}")
    candidate_game = game_from_verified_derivation(derivation, artifact_bytes=artifact_bytes)
    root_digest = game_digest(candidate_game)
    equality = build_equality_certificate(
        candidate_game,
        target,
        candidate_binding=artifact_binding(
            kind="digraph_placement",
            schema_version=ARTIFACT_SCHEMA,
            artifact_sha256=artifact_sha,
            root=candidate_game,
        ),
        target_binding=dict(target_binding),
    )
    valid, reason = verify_equality_certificate(
        equality,
        expected_candidate_artifact_sha256=artifact_sha,
        expected_target_artifact_sha256=target_binding["artifact_sha256"],
        expected_candidate_root_game_sha256=root_digest,
        expected_target_root_game_sha256=target_binding["root_game_sha256"],
    )
    if not valid or not equality["verdict"]["equal"]:
        raise AssertionError(f"fresh equality proof failed replay: {reason}")
    sidecars = {
        "artifact": write_content_addressed(run_dir, "artifacts", artifact_bytes),
        "derivation": write_content_addressed(run_dir, "derivations", derivation),
        "equality": write_content_addressed(run_dir, "equality", equality),
        "candidate_root_game_sha256": root_digest,
        "target_artifact_sha256": target_binding["artifact_sha256"],
        "target_root_game_sha256": target_binding["root_game_sha256"],
    }
    return sidecars, equality["certificate_sha256"]


def verify_stage0(repo_root: Path) -> tuple[dict[str, Any], set[str]]:
    stage0 = repo_root / STAGE0
    for name, expected in STAGE0_FILE_HASHES.items():
        if file_sha256(stage0 / name) != expected:
            raise ValueError(f"Stage-0 input hash mismatch: {name}")
    if file_sha256(repo_root / STAGE0_FAILED) != STAGE0_FAILED_SHA256:
        raise ValueError("failed Stage-0 disclosure hash mismatch")
    manifest = load_canonical_json(stage0 / "manifest.json")
    registry = load_canonical_json(stage0 / "leakage_registry.json")
    seeds = load_canonical_json(stage0 / "seed_controls.json")
    verification = load_canonical_json(stage0 / "independent_verification.json")
    completion = load_canonical_json(stage0 / "RUN_COMPLETE.json")
    for value, field, expected in (
        (manifest, "manifest_sha256", STAGE0_INTERNAL_HASHES["manifest_sha256"]),
        (registry, "registry_sha256", STAGE0_INTERNAL_HASHES["registry_sha256"]),
        (seeds, "seed_controls_sha256", STAGE0_INTERNAL_HASHES["seed_controls_sha256"]),
        (verification, "verification_sha256", STAGE0_INTERNAL_HASHES["verification_sha256"]),
        (completion, "completion_sha256", STAGE0_INTERNAL_HASHES["completion_sha256"]),
    ):
        verify_embedded_hash(value, field)
        if value[field] != expected:
            raise ValueError(f"Stage-0 embedded hash mismatch: {field}")
    if completion.get("status") != "PASS_CALIBRATION_ONLY" or not completion.get(
        "heldout_search_authorized"
    ):
        raise ValueError("Stage-0 completion does not authorize held-out preparation")
    failed = load_json_object(repo_root / STAGE0_FAILED)
    exposed = failed["additional_exposed_candidate"]
    if not any(
        row["candidate_sha256"] == exposed["candidate_sha256"]
        and row["target"] == exposed["target"]
        and row["extension_index"] == exposed["extension_index"]
        for row in registry["inspected_extensions"]
    ):
        raise ValueError("failed-run exposed candidate is absent from leakage registry")
    leakage = {row["candidate_sha256"] for row in registry["inspected_extensions"]}
    leakage.add(registry["registered_fixture"]["candidate_sha256"])
    if len(leakage) != 1_690:
        raise ValueError("Stage-0 leakage registry does not contain 1,690 unique candidates")
    if set(seeds["seeds"]) != set(TARGETS):
        raise ValueError("Stage-0 seeds do not bind all targets")
    for label in TARGETS:
        target_ref = seeds["target_artifacts"][label]
        valid, reason, target_replay = verify_target_artifact(
            target_label=label,
            artifact_reference=target_ref,
            sidecar_loader=lambda relative, root=stage0: (root / relative).read_bytes(),
        )
        if not valid or target_replay is None:
            raise ValueError(f"Stage-0 target replay failed for {label}: {reason}")
        seed = seeds["seeds"][label]
        valid, reason, replay = verify_candidate_evidence(
            candidate=seed["candidate"],
            claimed_candidate_sha256=seed["candidate_sha256"],
            claimed_quotient=seed["quotient"],
            claimed_descriptors=seed["measurements"],
            accepted_sidecars=seed["accepted_sidecars"],
            expected_target_binding=target_replay.binding,
            sidecar_loader=lambda relative, root=stage0: (root / relative).read_bytes(),
        )
        if not valid or replay is None:
            raise ValueError(f"Stage-0 seed replay failed for {label}: {reason}")
    return seeds, leakage


def validate_launch(repo_root: Path, launch_path: Path) -> dict[str, Any]:
    launch = load_canonical_json(launch_path)
    verify_embedded_hash(launch, "launch_sha256")
    if launch.get("schema_version") != f"{SCHEMA}.launch" or launch.get("status") != "AUTHORIZED_ONCE":
        raise ValueError("launch record is not an authorized v1 launch")
    prereg = launch.get("preregistration", {})
    if prereg != {"path": PREREGISTRATION.as_posix(), "sha256": PREREGISTRATION_SHA256}:
        raise ValueError("launch preregistration binding mismatch")
    if file_sha256(repo_root / PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise ValueError("preregistration changed after freeze")
    if launch.get("budget") != {
        "targets": list(TARGETS),
        "base_seeds": list(BASE_SEEDS),
        "proposals_per_stream": BUDGET,
        "total_proposals": len(TARGETS) * len(BASE_SEEDS) * BUDGET,
        "checkpoints": list(CHECKPOINTS),
    }:
        raise ValueError("launch budget binding mismatch")
    if launch.get("resource_limits") != {
        "generation_wall_seconds": GENERATION_LIMIT_SECONDS,
        "verification_wall_seconds": VERIFICATION_LIMIT_SECONDS,
        "run_directory_bytes": RUN_SIZE_LIMIT_BYTES,
    }:
        raise ValueError("launch resource binding mismatch")
    if launch.get("python") != {
        "executable": sys.executable,
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
    }:
        raise ValueError("launch interpreter binding mismatch")
    for entry in launch.get("sources", []):
        relative = Path(entry["repo_relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("launch source path is not repo-relative")
        if file_sha256(repo_root / relative) != entry["sha256"]:
            raise ValueError(f"launch source hash mismatch: {relative}")
    if not launch.get("sources"):
        raise ValueError("launch record has no source bindings")
    authorization_payload = {
        field: launch[field]
        for field in (
            "preregistration",
            "budget",
            "resource_limits",
            "python",
            "sources",
            "commands",
            "authorization_nonce",
        )
    }
    if object_sha256(authorization_payload) != launch.get("authorization_sha256"):
        raise ValueError("launch authorization hash does not replay")
    expected_dir = (
        "output/research/digraph-order7-fixed-value-transitions-v1-"
        + launch["authorization_sha256"][:12]
    )
    if launch.get("output_directory") != expected_dir:
        raise ValueError("launch output directory is not self-hash derived")
    return launch


def copy_source_bundle(repo_root: Path, run_dir: Path, entries: Iterable[Mapping[str, str]]) -> None:
    for entry in entries:
        relative = Path(entry["repo_relative_path"])
        data = (repo_root / relative).read_bytes()
        if bytes_sha256(data) != entry["sha256"]:
            raise AssertionError("source changed during bundle construction")
        bundle = PurePosixPath("source") / entry["sha256"][:2] / f"{entry['sha256']}-{relative.name}"
        write_bytes_exclusive(run_dir / Path(bundle), data)


def run_directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def event_with_chain(event: dict[str, Any], *, index: int, previous: str) -> dict[str, Any]:
    chained = dict(event)
    chained["global_event_index"] = index
    chained["previous_event_sha256"] = previous
    chained["event_sha256"] = object_sha256(chained)
    return chained


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    target_union: dict[str, Any] = {}
    exemplars: dict[str, dict[str, Any] | None] = {}
    all_primary: list[dict[str, Any]] = []
    for target in TARGETS:
        target_events = [event for event in events if event["target"] == target]
        representatives: dict[str, dict[str, Any]] = {}
        literal_digests: set[str] = set()
        primary_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        rejection_counts: dict[str, int] = {}
        for event in target_events:
            reason = event["rejection"]["reason"] if event["rejection"] else "accepted_or_exact_duplicate"
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if event["retention"]["inserted"]:
                quotient = event["quotient"]["quotient_sha256"]
                representatives.setdefault(
                    quotient,
                    {
                        "quotient_sha256": quotient,
                        "candidate_sha256": event["candidate_sha256"],
                        "literal_game_sha256": event["exact_decision"]["candidate_root_game_sha256"],
                        "first_global_event_index": event["global_event_index"],
                    },
                )
                literal_digests.add(event["exact_decision"]["candidate_root_game_sha256"])
            transition = event["transition"]
            if transition and transition["primary"]:
                key = (
                    transition["class"],
                    transition["parent_quotient_sha256"],
                    transition["candidate_quotient_sha256"],
                )
                primary_edges.setdefault(key, {
                    **transition,
                    "global_event_index": event["global_event_index"],
                    "base_seed": event["base_seed"],
                    "evaluation_index": event["evaluation_index"],
                    "candidate_sha256": event["candidate_sha256"],
                })
        counts = {
            "heldout_quotient_unique_representatives": len(representatives),
            "heldout_literal_game_digests": len(literal_digests),
            "primary_embodiment_only_edges": sum(key[0] == "embodiment_only" for key in primary_edges),
            "primary_literal_tree_crossing_edges": sum(key[0] == "literal_tree_crossing" for key in primary_edges),
        }
        gates = {
            "at_least_four_heldout_quotients": counts["heldout_quotient_unique_representatives"] >= 4,
            "at_least_three_heldout_literal_games": counts["heldout_literal_game_digests"] >= 3,
            "has_primary_embodiment_only": counts["primary_embodiment_only_edges"] >= 1,
            "has_primary_literal_tree_crossing": counts["primary_literal_tree_crossing_edges"] >= 1,
        }
        target_union[target] = {
            "counts": counts,
            "gates_before_independent_replay": gates,
            "representatives": sorted(representatives.values(), key=lambda row: (row["first_global_event_index"], row["quotient_sha256"])),
            "primary_edges": sorted(primary_edges.values(), key=lambda row: (row["global_event_index"], row["parent_quotient_sha256"], row["candidate_quotient_sha256"])),
            "rejection_counts": dict(sorted(rejection_counts.items())),
        }
        all_primary.extend({"target": target, **row} for row in target_union[target]["primary_edges"])
        for transition_class in ("embodiment_only", "literal_tree_crossing"):
            candidates = [row for row in target_union[target]["primary_edges"] if row["class"] == transition_class]
            exemplars[f"{target}|{transition_class}"] = candidates[0] if candidates else None

    motifs: list[dict[str, Any]] = []
    for target in TARGETS:
        by_stream: dict[int, list[dict[str, Any]]] = {}
        for edge in target_union[target]["primary_edges"]:
            by_stream.setdefault(int(edge["base_seed"]), []).append(edge)
        for base_seed, edges in by_stream.items():
            embodiment = [edge for edge in edges if edge["class"] == "embodiment_only"]
            crossing = [edge for edge in edges if edge["class"] == "literal_tree_crossing"]
            for left in embodiment:
                left_nodes = {left["parent_quotient_sha256"], left["candidate_quotient_sha256"]}
                for right in crossing:
                    shared = left_nodes & {right["parent_quotient_sha256"], right["candidate_quotient_sha256"]}
                    for center in sorted(shared):
                        motifs.append({
                            "target": target,
                            "base_seed": base_seed,
                            "central_quotient_sha256": center,
                            "embodiment_only_edge": left,
                            "literal_tree_crossing_edge": right,
                            "rank_max_global_event_index": max(left["global_event_index"], right["global_event_index"]),
                        })
    target_rank = {target: index for index, target in enumerate(TARGETS)}
    motifs.sort(key=lambda row: (
        row["rank_max_global_event_index"],
        target_rank[row["target"]],
        row["central_quotient_sha256"],
        row["embodiment_only_edge"]["candidate_quotient_sha256"],
        row["literal_tree_crossing_edge"]["candidate_quotient_sha256"],
    ))
    pre_replay_pass = all(
        all(result["gates_before_independent_replay"].values()) for result in target_union.values()
    )
    payload = {
        "schema_version": SUMMARY_SCHEMA,
        "status": STATUS,
        "event_count": len(events),
        "target_unions": target_union,
        "mechanical_exemplars": exemplars,
        "mechanical_linked_motif": motifs[0] if motifs else None,
        "linked_motif_count": len(motifs),
        "pre_replay_scientific_gate_pass": pre_replay_pass,
        "paper_evidence": False,
        "warning": "Sampled trajectories; counts are not prevalence estimates.",
    }
    summary = dict(payload)
    summary["summary_sha256"] = object_sha256(payload)
    return summary


def generate(repo_root: Path, launch_path: Path) -> Path:
    started = time.monotonic()
    launch = validate_launch(repo_root, launch_path)
    stage0_seeds, leakage = verify_stage0(repo_root)
    run_dir = repo_root / launch["output_directory"]
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(run_dir)
    try:
        launch_ref = write_content_addressed(run_dir, "launch", launch_path.read_bytes().rstrip(b"\n"))
        copy_source_bundle(repo_root, run_dir, launch["sources"])
        games: dict[str, Game] = {}
        target_bindings: dict[str, dict[str, str]] = {}
        target_refs: dict[str, dict[str, str]] = {}
        for label in TARGETS:
            game = parse_game_form(label)
            ref = write_content_addressed(run_dir, "artifacts", target_artifact(label, game))
            games[label] = game
            target_refs[label] = ref
            target_bindings[label] = artifact_binding(
                kind="abstract_short_game_target",
                schema_version="partizan.abstract_short_game_target.v1",
                artifact_sha256=ref["sha256"],
                root=game,
            )
        manifest_payload = {
            "schema_version": MANIFEST_SCHEMA,
            "status": STATUS,
            "preregistration": {"path": PREREGISTRATION.as_posix(), "sha256": PREREGISTRATION_SHA256},
            "launch": {"path": launch_path.relative_to(repo_root).as_posix(), "file_sha256": file_sha256(launch_path), "internal_sha256": launch["launch_sha256"], "sidecar": launch_ref},
            "stage0": {"directory": STAGE0.as_posix(), "file_hashes": STAGE0_FILE_HASHES, "internal_hashes": STAGE0_INTERNAL_HASHES, "failed_disclosure": {"path": STAGE0_FAILED.as_posix(), "sha256": STAGE0_FAILED_SHA256}, "leakage_candidate_count": len(leakage)},
            "derivation_v3_contract": schema_contract(),
            "targets": list(TARGETS),
            "base_seeds": list(BASE_SEEDS),
            "budget_per_stream": BUDGET,
            "checkpoints": list(CHECKPOINTS),
            "proposal_kernel": {"immigrant_denominator": 8, "local_operators": ["flip_colour", "toggle_one_arc", "toggle_two_arcs"], "order": 7, "ordered_arc_count": len(ARC_LIST)},
            "target_artifacts": target_refs,
            "seed_controls": stage0_seeds["seeds"],
            "source_bundle": launch["sources"],
            "resource_limits": launch["resource_limits"],
            "paper_evidence": False,
        }
        manifest = dict(manifest_payload)
        manifest["manifest_sha256"] = object_sha256(manifest_payload)
        write_json_exclusive(run_dir / "manifest.json", manifest)

        events: list[dict[str, Any]] = []
        previous = ZERO_SHA256
        global_index = 0
        events_path = run_dir / "events.jsonl"
        descriptor = os.open(events_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            for label in TARGETS:
                seed = stage0_seeds["seeds"][label]
                seed_graph = graph_from_record(seed["candidate"])
                seed_quotient = seed["quotient"]["quotient_sha256"]
                seed_literal = seed["literal_game_sha256"]
                for base_seed in BASE_SEEDS:
                    proposal_seed = stable_rng_seed(base_seed=base_seed, target=label, stream_name="proposal")
                    selection_seed = stable_rng_seed(base_seed=base_seed, target=label, stream_name="parent_selection")
                    proposal_rng = random.Random(proposal_seed)
                    selection_rng = random.Random(selection_seed)
                    repertoire: dict[str, dict[str, Any]] = {
                        seed_quotient: {"graph": seed_graph, "literal": seed_literal, "heldout": False}
                    }
                    for evaluation_index in range(BUDGET):
                        if time.monotonic() - started > GENERATION_LIMIT_SECONDS:
                            raise TimeoutError("frozen generation wall-clock limit exceeded")
                        parent_key = selection_rng.choice(sorted(repertoire))
                        parent = repertoire[parent_key]
                        proposal = propose(parent["graph"], proposal_rng)
                        candidate = candidate_record(proposal.candidate)
                        candidate_sha = candidate_record_sha256(candidate)
                        connected = weakly_connected(proposal.candidate)
                        collision = candidate_sha in leakage
                        decision: dict[str, Any] | None = None
                        quotient: dict[str, Any] | None = None
                        measurements: dict[str, Any] | None = None
                        transition: dict[str, Any] | None = None
                        sidecars: dict[str, Any] | None = None
                        equality_certificate_sha256: str | None = None
                        rejection: dict[str, str] | None = None
                        inserted = False
                        new_quotient = False
                        if not connected:
                            rejection = {"stage": "representation_grammar", "reason": "weakly_disconnected"}
                        elif collision:
                            rejection = {"stage": "leakage_registry", "reason": "calibration_leakage_collision"}
                        else:
                            decision, _ = exact_decision(proposal.candidate, games[label])
                            if not decision["equal"]:
                                rejection = {"stage": "exact_equality", "reason": "exact_value_mismatch"}
                            else:
                                quotient = quotient_record(proposal.candidate)
                                measurements = descriptor_record(proposal.candidate)
                                candidate_quotient = quotient["quotient_sha256"]
                                candidate_literal = decision["candidate_root_game_sha256"]
                                if proposal.mode == "local_mutation":
                                    transition_class = classify_transition(
                                        parent_quotient=parent_key,
                                        parent_literal=parent["literal"],
                                        candidate_quotient=candidate_quotient,
                                        candidate_literal=candidate_literal,
                                    )
                                    transition = {
                                        "class": transition_class,
                                        "parent_quotient_sha256": parent_key,
                                        "parent_literal_game_sha256": parent["literal"],
                                        "candidate_quotient_sha256": candidate_quotient,
                                        "candidate_literal_game_sha256": candidate_literal,
                                        "parent_heldout": parent["heldout"],
                                        "candidate_heldout": candidate_quotient != seed_quotient,
                                        "primary": bool(parent["heldout"] and candidate_quotient != seed_quotient and transition_class != "quotient_self"),
                                    }
                                new_quotient = candidate_quotient not in repertoire
                                if new_quotient:
                                    sidecars, equality_certificate_sha256 = build_match_sidecars(
                                        graph=proposal.candidate,
                                        target=games[label],
                                        target_binding=target_bindings[label],
                                        run_dir=run_dir,
                                    )
                                    valid, reason, replay = verify_candidate_evidence(
                                        candidate=candidate,
                                        claimed_candidate_sha256=candidate_sha,
                                        claimed_quotient=quotient,
                                        claimed_descriptors=measurements,
                                        accepted_sidecars=sidecars,
                                        expected_target_binding=target_bindings[label],
                                        sidecar_loader=lambda relative, root=run_dir: (root / relative).read_bytes(),
                                    )
                                    if not valid or replay is None:
                                        raise AssertionError(f"fresh retained candidate failed replay: {reason}")
                                    repertoire[candidate_quotient] = {"graph": proposal.candidate, "literal": candidate_literal, "heldout": True}
                                    inserted = True
                                else:
                                    rejection = {"stage": "discovery_accounting", "reason": "duplicate_quotient"}
                        event_payload = {
                            "schema_version": EVENT_SCHEMA,
                            "status": STATUS,
                            "target": label,
                            "base_seed": base_seed,
                            "evaluation_index": evaluation_index,
                            "derived_rng_seeds": {"proposal": proposal_seed, "parent_selection": selection_seed},
                            "parent": {"quotient_sha256": parent_key, "literal_game_sha256": parent["literal"], "heldout": parent["heldout"]},
                            "proposal": {"mode": proposal.mode, "operator": proposal.operator},
                            "candidate": candidate,
                            "candidate_sha256": candidate_sha,
                            "weakly_connected": connected,
                            "leakage_collision": collision,
                            "exact_decision": decision,
                            "quotient": quotient,
                            "measurements": measurements,
                            "transition": transition,
                            "retention": {"new_quotient": new_quotient, "inserted": inserted, "sidecars": sidecars, "equality_certificate_sha256": equality_certificate_sha256},
                            "rejection": rejection,
                        }
                        event = event_with_chain(event_payload, index=global_index, previous=previous)
                        handle.write(canonical_line(event))
                        events.append(event)
                        previous = event["event_sha256"]
                        global_index += 1
                        clear_caches()
            handle.flush()
            os.fsync(handle.fileno())
        summary = summarize(events)
        write_json_exclusive(run_dir / "summary.json", summary)
        if run_directory_size(run_dir) > RUN_SIZE_LIMIT_BYTES:
            raise OSError("frozen run-directory size limit exceeded")
        generation_payload = {
            "schema_version": f"{SCHEMA}.generation_complete",
            "status": STATUS,
            "manifest_sha256": manifest["manifest_sha256"],
            "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
            "event_count": len(events),
            "events_file_sha256": file_sha256(events_path),
            "final_event_sha256": previous,
            "summary_sha256": summary["summary_sha256"],
            "summary_file_sha256": file_sha256(run_dir / "summary.json"),
            "generation_wall_seconds": time.monotonic() - started,
            "run_directory_bytes_before_marker": run_directory_size(run_dir),
            "paper_evidence": False,
        }
        generation = dict(generation_payload)
        generation["generation_sha256"] = object_sha256(generation_payload)
        write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
        return run_dir
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.failure",
            "status": "GENERATION_FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "elapsed_seconds": time.monotonic() - started,
            "paper_evidence": False,
            "resume_authorized": False,
        }
        failure = dict(failure_payload)
        failure["failure_sha256"] = object_sha256(failure_payload)
        try:
            write_json_exclusive(run_dir / "FAILURE.json", failure)
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--launch-record", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    launch_path = args.launch_record
    if not launch_path.is_absolute():
        launch_path = (repo_root / launch_path).resolve()
    run_dir = generate(repo_root, launch_path)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
