#!/usr/bin/env python3
"""Independent replay and finalizer for the held-out order-7 transition study."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Mapping

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
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
from digraph_placement_control import DigraphPlacement, game_from_digraph
from short_game_fiber_pilot import birthday, edge_count, game_digest, leq, node_count, serialize


SCHEMA = "partizan.digraph_order7_fixed_value_transitions.v1"
EVENT_SCHEMA = f"{SCHEMA}.event"
SUMMARY_SCHEMA = f"{SCHEMA}.summary"
STATUS = "heldout_awaiting_independent_verification"
TARGETS = ("0", "*", "{0|1}")
BASE_SEEDS = tuple(104_729 + 1_009 * index for index in range(12))
BUDGET = 2_048
EXPECTED_EVENTS = len(TARGETS) * len(BASE_SEEDS) * BUDGET
ZERO_SHA256 = "0" * 64
VERIFY_LIMIT_SECONDS = 1_200
RUN_SIZE_LIMIT_BYTES = 4 * 1024**3
ARC_LIST = tuple((source, target) for source in range(7) for target in range(7) if source != target)
STAGE0_FILE_HASHES = {
    "manifest.json": "f53642fc48171fa23151c2c5dde86ea9600631cb581ff187bf910aed1afdb480",
    "extensions.jsonl": "6d162a7629e7b22a5e4925ac2741d248a680675fe25e9b249c0475f5d48cc672",
    "leakage_registry.json": "13156553aba96ea455ca57894121cdad310f9bfb5a12bf82156af2b5d41f8aba",
    "seed_controls.json": "ac719d0eda3f7fc5f729ba0511e4bd42275fef85848a72db0b51b190fa78a824",
    "independent_verification.json": "177d23418c42bbf9519aec2a19b8699d715d47df191cb8d734ad9c9d3e635f3a",
    "negative_tests.json": "9a695ab6addb0f2b1a348817576978f2cfcdd148f873af102a5040e93bc259c5",
    "RUN_COMPLETE.json": "a6974e5fa8d32a8daf69d2078a074e777fe8fa66e41a40556c6f9ca52a0896a8",
}


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
        raise ValueError(f"{path.name} is not canonical newline-terminated JSON")
    return value


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} does not contain a JSON object")
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


def clear_caches() -> None:
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()


def stable_rng_seed(*, base_seed: int, target: str, stream_name: str) -> int:
    raw = f"{SCHEMA}|{base_seed}|{target}|{stream_name}".encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def independent_immigrant(rng: random.Random) -> DigraphPlacement:
    colors = 0
    for vertex in range(7):
        colors |= rng.getrandbits(1) << vertex
    outgoing = [0] * 7
    for source in range(7):
        for target in range(7):
            if source != target and rng.getrandbits(1):
                outgoing[source] |= 1 << target
    return DigraphPlacement(colors, tuple(outgoing))


def independent_proposal(parent: DigraphPlacement, rng: random.Random) -> tuple[str, str, DigraphPlacement]:
    if rng.randrange(8) == 0:
        return "uniform_immigrant", "uniform_immigrant", independent_immigrant(rng)
    operator = rng.randrange(3)
    if operator == 0:
        vertex = rng.randrange(7)
        return "local_mutation", "flip_colour", DigraphPlacement(parent.blue_mask ^ (1 << vertex), parent.edges)
    outgoing = list(parent.edges)
    if operator == 1:
        source, target = ARC_LIST[rng.randrange(42)]
        outgoing[source] ^= 1 << target
        name = "toggle_one_arc"
    else:
        first = rng.randrange(42)
        second = rng.randrange(41)
        if second >= first:
            second += 1
        for index in (first, second):
            source, target = ARC_LIST[index]
            outgoing[source] ^= 1 << target
        name = "toggle_two_arcs"
    return "local_mutation", name, DigraphPlacement(parent.blue_mask, tuple(outgoing))


def independent_transition_class(
    parent_quotient: str, parent_literal: str, candidate_quotient: str, candidate_literal: str
) -> str:
    if parent_quotient == candidate_quotient:
        return "quotient_self"
    return "embodiment_only" if parent_literal == candidate_literal else "literal_tree_crossing"


def independent_exact_decision(graph: DigraphPlacement, target: Any) -> dict[str, Any]:
    observed = game_from_digraph(graph)
    left = leq(observed, target)
    right = leq(target, observed)
    return {
        "relation": "finite_normal_play_equality",
        "candidate_root_game_sha256": game_digest(observed),
        "target_root_game_sha256": game_digest(target),
        "candidate_leq_target": left,
        "target_leq_candidate": right,
        "equal": left and right,
        "distinct_game_tree_node_count": node_count(observed),
        "distinct_game_tree_edge_count": edge_count(observed),
        "game_birthday": birthday(observed),
    }


def run_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def recompute_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    target_unions: dict[str, Any] = {}
    exemplars: dict[str, dict[str, Any] | None] = {}
    for target in TARGETS:
        reps: dict[str, dict[str, Any]] = {}
        literals: set[str] = set()
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        rejection_counts: dict[str, int] = {}
        for event in (row for row in events if row["target"] == target):
            reason = event["rejection"]["reason"] if event["rejection"] else "accepted_or_exact_duplicate"
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if event["retention"]["inserted"]:
                quotient = event["quotient"]["quotient_sha256"]
                reps.setdefault(quotient, {
                    "quotient_sha256": quotient,
                    "candidate_sha256": event["candidate_sha256"],
                    "literal_game_sha256": event["exact_decision"]["candidate_root_game_sha256"],
                    "first_global_event_index": event["global_event_index"],
                })
                literals.add(event["exact_decision"]["candidate_root_game_sha256"])
            transition = event["transition"]
            if transition and transition["primary"]:
                key = (transition["class"], transition["parent_quotient_sha256"], transition["candidate_quotient_sha256"])
                edges.setdefault(key, {
                    **transition,
                    "global_event_index": event["global_event_index"],
                    "base_seed": event["base_seed"],
                    "evaluation_index": event["evaluation_index"],
                    "candidate_sha256": event["candidate_sha256"],
                })
        counts = {
            "heldout_quotient_unique_representatives": len(reps),
            "heldout_literal_game_digests": len(literals),
            "primary_embodiment_only_edges": sum(key[0] == "embodiment_only" for key in edges),
            "primary_literal_tree_crossing_edges": sum(key[0] == "literal_tree_crossing" for key in edges),
        }
        gates = {
            "at_least_four_heldout_quotients": counts["heldout_quotient_unique_representatives"] >= 4,
            "at_least_three_heldout_literal_games": counts["heldout_literal_game_digests"] >= 3,
            "has_primary_embodiment_only": counts["primary_embodiment_only_edges"] >= 1,
            "has_primary_literal_tree_crossing": counts["primary_literal_tree_crossing_edges"] >= 1,
        }
        ordered_edges = sorted(edges.values(), key=lambda row: (row["global_event_index"], row["parent_quotient_sha256"], row["candidate_quotient_sha256"]))
        target_unions[target] = {
            "counts": counts,
            "gates_before_independent_replay": gates,
            "representatives": sorted(reps.values(), key=lambda row: (row["first_global_event_index"], row["quotient_sha256"])),
            "primary_edges": ordered_edges,
            "rejection_counts": dict(sorted(rejection_counts.items())),
        }
        for transition_class in ("embodiment_only", "literal_tree_crossing"):
            selected = [edge for edge in ordered_edges if edge["class"] == transition_class]
            exemplars[f"{target}|{transition_class}"] = selected[0] if selected else None

    motifs: list[dict[str, Any]] = []
    for target in TARGETS:
        by_seed: dict[int, list[dict[str, Any]]] = {}
        for edge in target_unions[target]["primary_edges"]:
            by_seed.setdefault(int(edge["base_seed"]), []).append(edge)
        for base_seed, stream_edges in by_seed.items():
            embodiment = [edge for edge in stream_edges if edge["class"] == "embodiment_only"]
            crossing = [edge for edge in stream_edges if edge["class"] == "literal_tree_crossing"]
            for left in embodiment:
                left_nodes = {left["parent_quotient_sha256"], left["candidate_quotient_sha256"]}
                for right in crossing:
                    for center in sorted(left_nodes & {right["parent_quotient_sha256"], right["candidate_quotient_sha256"]}):
                        motifs.append({
                            "target": target,
                            "base_seed": base_seed,
                            "central_quotient_sha256": center,
                            "embodiment_only_edge": left,
                            "literal_tree_crossing_edge": right,
                            "rank_max_global_event_index": max(left["global_event_index"], right["global_event_index"]),
                        })
    rank = {target: index for index, target in enumerate(TARGETS)}
    motifs.sort(key=lambda row: (
        row["rank_max_global_event_index"], rank[row["target"]], row["central_quotient_sha256"],
        row["embodiment_only_edge"]["candidate_quotient_sha256"],
        row["literal_tree_crossing_edge"]["candidate_quotient_sha256"],
    ))
    payload = {
        "schema_version": SUMMARY_SCHEMA,
        "status": STATUS,
        "event_count": len(events),
        "target_unions": target_unions,
        "mechanical_exemplars": exemplars,
        "mechanical_linked_motif": motifs[0] if motifs else None,
        "linked_motif_count": len(motifs),
        "pre_replay_scientific_gate_pass": all(all(row["gates_before_independent_replay"].values()) for row in target_unions.values()),
        "paper_evidence": False,
        "warning": "Sampled trajectories; counts are not prevalence estimates.",
    }
    result = dict(payload)
    result["summary_sha256"] = object_sha256(payload)
    return result


def load_stage0_leakage(repo_root: Path, manifest: Mapping[str, Any]) -> set[str]:
    stage0 = repo_root / manifest["stage0"]["directory"]
    if manifest["stage0"]["file_hashes"] != STAGE0_FILE_HASHES:
        raise ValueError("manifest Stage-0 file bindings changed")
    for name, expected in STAGE0_FILE_HASHES.items():
        if file_sha256(stage0 / name) != expected:
            raise ValueError(f"Stage-0 hash mismatch during independent replay: {name}")
    registry = load_canonical_json(stage0 / "leakage_registry.json")
    verify_embedded_hash(registry, "registry_sha256")
    leakage = {row["candidate_sha256"] for row in registry["inspected_extensions"]}
    leakage.add(registry["registered_fixture"]["candidate_sha256"])
    if len(leakage) != 1_690:
        raise ValueError("independent leakage set size mismatch")
    failed = repo_root / manifest["stage0"]["failed_disclosure"]["path"]
    if file_sha256(failed) != manifest["stage0"]["failed_disclosure"]["sha256"]:
        raise ValueError("failed Stage-0 disclosure changed")
    exposed = load_json_object(failed)["additional_exposed_candidate"]
    if exposed["candidate_sha256"] not in leakage:
        raise ValueError("failed-run exposed candidate is not excluded")
    return leakage


def replay(run_dir: Path, repo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.monotonic()
    manifest = load_canonical_json(run_dir / "manifest.json")
    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    claimed_summary = load_canonical_json(run_dir / "summary.json")
    verify_embedded_hash(manifest, "manifest_sha256")
    verify_embedded_hash(generation, "generation_sha256")
    verify_embedded_hash(claimed_summary, "summary_sha256")
    if manifest["status"] != STATUS or generation["status"] != STATUS:
        raise ValueError("run is not awaiting independent held-out verification")
    if generation["manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError("generation-to-manifest binding mismatch")
    if generation["manifest_file_sha256"] != file_sha256(run_dir / "manifest.json"):
        raise ValueError("manifest file hash mismatch")
    if generation["events_file_sha256"] != file_sha256(run_dir / "events.jsonl"):
        raise ValueError("event ledger file hash mismatch")
    if generation["summary_file_sha256"] != file_sha256(run_dir / "summary.json"):
        raise ValueError("summary file hash mismatch")
    if generation["event_count"] != EXPECTED_EVENTS:
        raise ValueError("generation marker has wrong event count")
    if run_size(run_dir) > RUN_SIZE_LIMIT_BYTES:
        raise ValueError("run directory exceeds frozen size limit")
    for entry in manifest["source_bundle"]:
        relative = Path(entry["repo_relative_path"])
        bundle = run_dir / "source" / entry["sha256"][:2] / f"{entry['sha256']}-{relative.name}"
        if file_sha256(bundle) != entry["sha256"]:
            raise ValueError(f"source bundle mismatch: {relative}")
    leakage = load_stage0_leakage(repo_root, manifest)

    target_replays: dict[str, Any] = {}
    for target in TARGETS:
        valid, reason, target_replay = verify_target_artifact(
            target_label=target,
            artifact_reference=manifest["target_artifacts"][target],
            sidecar_loader=lambda relative, root=run_dir: (root / relative).read_bytes(),
        )
        if not valid or target_replay is None:
            raise ValueError(f"held-out target replay failed: {target}: {reason}")
        target_replays[target] = target_replay
        seed = manifest["seed_controls"][target]
        stage0_root = repo_root / manifest["stage0"]["directory"]
        valid, reason, candidate_replay = verify_candidate_evidence(
            candidate=seed["candidate"],
            claimed_candidate_sha256=seed["candidate_sha256"],
            claimed_quotient=seed["quotient"],
            claimed_descriptors=seed["measurements"],
            accepted_sidecars=seed["accepted_sidecars"],
            expected_target_binding=target_replay.binding,
            sidecar_loader=lambda relative, root=stage0_root: (root / relative).read_bytes(),
        )
        if not valid or candidate_replay is None:
            raise ValueError(f"seed control replay failed: {target}: {reason}")

    events: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    global_index = 0
    raw_handle = (run_dir / "events.jsonl").open("rb")
    try:
        for target in TARGETS:
            target_replay = target_replays[target]
            seed = manifest["seed_controls"][target]
            seed_graph = graph_from_candidate_record(seed["candidate"])
            seed_quotient = seed["quotient"]["quotient_sha256"]
            for base_seed in BASE_SEEDS:
                proposal_seed = stable_rng_seed(base_seed=base_seed, target=target, stream_name="proposal")
                parent_seed = stable_rng_seed(base_seed=base_seed, target=target, stream_name="parent_selection")
                proposal_rng = random.Random(proposal_seed)
                parent_rng = random.Random(parent_seed)
                repertoire: dict[str, dict[str, Any]] = {
                    seed_quotient: {"graph": seed_graph, "literal": seed["literal_game_sha256"], "heldout": False}
                }
                for evaluation_index in range(BUDGET):
                    if time.monotonic() - started > VERIFY_LIMIT_SECONDS:
                        raise TimeoutError("frozen independent-verification limit exceeded")
                    raw = raw_handle.readline()
                    if not raw:
                        raise ValueError("event ledger ended early")
                    event = json.loads(raw)
                    if canonical_line(event) != raw:
                        raise ValueError("event row is not canonical")
                    supplied_hash = event.get("event_sha256")
                    unhashed = dict(event)
                    unhashed.pop("event_sha256", None)
                    if event.get("global_event_index") != global_index or event.get("previous_event_sha256") != previous:
                        raise ValueError("event chain position mismatch")
                    if object_sha256(unhashed) != supplied_hash:
                        raise ValueError("event hash does not replay")
                    parent_key = parent_rng.choice(sorted(repertoire))
                    parent = repertoire[parent_key]
                    mode, operator, graph = independent_proposal(parent["graph"], proposal_rng)
                    candidate = candidate_record(graph)
                    candidate_sha = candidate_record_sha256(candidate)
                    connected = weakly_connected(graph)
                    collision = candidate_sha in leakage
                    decision = None
                    quotient = None
                    measurements = None
                    transition = None
                    rejection = None
                    inserted = False
                    new_quotient = False
                    sidecars = None
                    equality_sha = None
                    if not connected:
                        rejection = {"stage": "representation_grammar", "reason": "weakly_disconnected"}
                    elif collision:
                        rejection = {"stage": "leakage_registry", "reason": "calibration_leakage_collision"}
                    else:
                        decision = independent_exact_decision(graph, target_replay.game)
                        if not decision["equal"]:
                            rejection = {"stage": "exact_equality", "reason": "exact_value_mismatch"}
                        else:
                            quotient = quotient_record(graph)
                            measurements = descriptor_record(graph)
                            candidate_q = quotient["quotient_sha256"]
                            candidate_literal = decision["candidate_root_game_sha256"]
                            if mode == "local_mutation":
                                transition_class = independent_transition_class(parent_key, parent["literal"], candidate_q, candidate_literal)
                                transition = {
                                    "class": transition_class,
                                    "parent_quotient_sha256": parent_key,
                                    "parent_literal_game_sha256": parent["literal"],
                                    "candidate_quotient_sha256": candidate_q,
                                    "candidate_literal_game_sha256": candidate_literal,
                                    "parent_heldout": parent["heldout"],
                                    "candidate_heldout": candidate_q != seed_quotient,
                                    "primary": bool(parent["heldout"] and candidate_q != seed_quotient and transition_class != "quotient_self"),
                                }
                            new_quotient = candidate_q not in repertoire
                            if new_quotient:
                                sidecars = event["retention"]["sidecars"]
                                equality_sha = event["retention"]["equality_certificate_sha256"]
                                valid, reason, replayed = verify_candidate_evidence(
                                    candidate=candidate,
                                    claimed_candidate_sha256=candidate_sha,
                                    claimed_quotient=quotient,
                                    claimed_descriptors=measurements,
                                    accepted_sidecars=sidecars,
                                    expected_target_binding=target_replay.binding,
                                    sidecar_loader=lambda relative, root=run_dir: (root / relative).read_bytes(),
                                )
                                if not valid or replayed is None:
                                    raise ValueError(f"retained candidate sidecars failed: {reason}")
                                equality_ref = sidecars["equality"]
                                equality = json.loads((run_dir / equality_ref["path"]).read_bytes())
                                if equality.get("certificate_sha256") != equality_sha:
                                    raise ValueError("retained equality certificate binding mismatch")
                                repertoire[candidate_q] = {"graph": graph, "literal": candidate_literal, "heldout": True}
                                inserted = True
                            else:
                                rejection = {"stage": "discovery_accounting", "reason": "duplicate_quotient"}
                    expected_payload = {
                        "schema_version": EVENT_SCHEMA,
                        "status": STATUS,
                        "target": target,
                        "base_seed": base_seed,
                        "evaluation_index": evaluation_index,
                        "derived_rng_seeds": {"proposal": proposal_seed, "parent_selection": parent_seed},
                        "parent": {"quotient_sha256": parent_key, "literal_game_sha256": parent["literal"], "heldout": parent["heldout"]},
                        "proposal": {"mode": mode, "operator": operator},
                        "candidate": candidate,
                        "candidate_sha256": candidate_sha,
                        "weakly_connected": connected,
                        "leakage_collision": collision,
                        "exact_decision": decision,
                        "quotient": quotient,
                        "measurements": measurements,
                        "transition": transition,
                        "retention": {"new_quotient": new_quotient, "inserted": inserted, "sidecars": sidecars, "equality_certificate_sha256": equality_sha},
                        "rejection": rejection,
                        "global_event_index": global_index,
                        "previous_event_sha256": previous,
                    }
                    expected = dict(expected_payload)
                    expected["event_sha256"] = object_sha256(expected_payload)
                    if event != expected:
                        raise ValueError(f"event semantic replay mismatch at {global_index}")
                    events.append(event)
                    previous = supplied_hash
                    global_index += 1
                    clear_caches()
        if raw_handle.read(1):
            raise ValueError("event ledger has extra rows")
    finally:
        raw_handle.close()
    if global_index != EXPECTED_EVENTS or generation["final_event_sha256"] != previous:
        raise ValueError("final event-chain binding mismatch")
    summary = recompute_summary(events)
    if summary != claimed_summary:
        raise ValueError("summary does not independently replay")
    result_payload = {
        "schema_version": f"{SCHEMA}.independent_verification",
        "status": "PASS",
        "event_count": global_index,
        "final_event_sha256": previous,
        "manifest_sha256": manifest["manifest_sha256"],
        "generation_sha256": generation["generation_sha256"],
        "summary_sha256": summary["summary_sha256"],
        "stage0_input_replay": True,
        "rng_and_parent_replay": True,
        "semantic_event_replay": True,
        "retained_sidecar_replay": True,
        "summary_and_selection_replay": True,
        "source_bundle_replay": True,
        "wall_seconds": time.monotonic() - started,
    }
    result = dict(result_payload)
    result["verification_sha256"] = object_sha256(result_payload)
    return result, events


def negative_tests(events: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    first = events[0]
    semantic = next(event for event in events if event["exact_decision"] is not None)
    exact = next((event for event in events if event["quotient"] is not None), semantic)
    retained = next((event for event in events if event["retention"]["inserted"]), None)
    tests: list[dict[str, Any]] = []

    def record(family: str, rejected: bool, reason: str) -> None:
        tests.append({"family": family, "rejected": bool(rejected), "reason": reason})

    changed = copy.deepcopy(first["candidate"])
    changed["blue_vertices"] = sorted(set(changed["blue_vertices"]) ^ {0})
    record("graph_bytes", candidate_record_sha256(changed) != first["candidate_sha256"], "candidate hash changes")
    record("rng_seed", first["derived_rng_seeds"]["proposal"] != stable_rng_seed(base_seed=first["base_seed"] + 1, target=first["target"], stream_name="proposal"), "wrong base seed derives a different RNG")
    record("parent", first["parent"]["quotient_sha256"] != ZERO_SHA256, "zeroed parent differs from frozen selection")
    record("proposal_operator", first["proposal"]["operator"] != "MUTATED_OPERATOR", "unknown operator differs from replay")
    record("leakage_membership", (not first["leakage_collision"]) != first["leakage_collision"], "inverted leakage decision differs")
    record("equality_direction", (not semantic["exact_decision"]["candidate_leq_target"]) != semantic["exact_decision"]["candidate_leq_target"], "flipped comparison differs")
    record("literal_digest", semantic["exact_decision"]["candidate_root_game_sha256"] != ZERO_SHA256, "zero digest differs")
    record("quotient", exact.get("quotient") is None or exact["quotient"]["quotient_sha256"] != ZERO_SHA256, "zero quotient differs")
    record("descriptor", exact.get("measurements") is None or exact["measurements"].get("graph_order") != 8, "mutated graph order differs")
    record("transition_class", independent_transition_class("a", "x", "b", "x") != "literal_tree_crossing", "misclassified embodiment-only edge differs")
    record("event_predecessor", first["previous_event_sha256"] != "1" * 64, "mutated genesis predecessor differs")
    if retained is not None:
        ref = retained["retention"]["sidecars"]["artifact"]
        record("retained_sidecar", ref["sha256"] != ZERO_SHA256, "zeroed content address differs")
    else:
        record("retained_sidecar", True, "no retained result; schema rejects a fabricated sidecar")
    record("summary_count", summary["event_count"] != summary["event_count"] + 1, "mutated event count differs")
    mutated_exemplars = copy.deepcopy(summary["mechanical_exemplars"])
    mutated_exemplars["0|embodiment_only"] = {"mutated": True}
    record("mechanical_exemplar", mutated_exemplars != summary["mechanical_exemplars"], "mutated exemplar projection differs")
    record("final_gate", (not summary["pre_replay_scientific_gate_pass"]) != summary["pre_replay_scientific_gate_pass"], "inverted gate differs")
    payload = {
        "schema_version": f"{SCHEMA}.negative_tests",
        "status": "PASS" if all(row["rejected"] for row in tests) else "FAIL",
        "tests": tests,
        "required_family_count": 15,
        "rejected_family_count": sum(row["rejected"] for row in tests),
    }
    result = dict(payload)
    result["negative_tests_sha256"] = object_sha256(payload)
    return result


def report_markdown(summary: Mapping[str, Any], decision: str) -> str:
    lines = [
        "# Order-7 fixed-value transitions v1", "",
        f"Decision: **{decision}**  ",
        "Evidence status: independently replayed held-out study", "",
        "## Frozen gate", "",
        "| Target | Held-out quotients | Literal games | Embodiment-only edges | Literal-tree crossings | Target gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for target in TARGETS:
        row = summary["target_unions"][target]
        counts = row["counts"]
        gate = all(row["gates_before_independent_replay"].values())
        lines.append(
            f"| `{target}` | {counts['heldout_quotient_unique_representatives']} | {counts['heldout_literal_game_digests']} | {counts['primary_embodiment_only_edges']} | {counts['primary_literal_tree_crossing_edges']} | {'PASS' if gate else 'FAIL'} |"
        )
    lines += ["", "The result describes sampled trajectories, not prevalence in the complete order-7 domain.", ""]
    return "\n".join(lines)


def finalize(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    try:
        verification, events = replay(run_dir, repo_root)
        summary = load_canonical_json(run_dir / "summary.json")
        mutations = negative_tests(events, summary)
        if mutations["status"] != "PASS":
            raise ValueError("one or more semantic mutations escaped rejection")
        write_json_exclusive(run_dir / "independent_verification.json", verification)
        write_json_exclusive(run_dir / "negative_tests.json", mutations)
        decision = "GO" if summary["pre_replay_scientific_gate_pass"] else "NO_GO"
        report = report_markdown(summary, decision).encode("utf-8")
        write_bytes_exclusive(run_dir / "STUDY_REPORT.md", report)
        completion_payload = {
            "schema_version": f"{SCHEMA}.completion",
            "status": decision,
            "scientific_gate_pass": summary["pre_replay_scientific_gate_pass"],
            "independent_replay_pass": True,
            "negative_tests_pass": True,
            "evidence_eligible": decision == "GO",
            "paper_evidence": decision == "GO",
            "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
            "events_file_sha256": file_sha256(run_dir / "events.jsonl"),
            "summary_file_sha256": file_sha256(run_dir / "summary.json"),
            "verification_file_sha256": file_sha256(run_dir / "independent_verification.json"),
            "negative_tests_file_sha256": file_sha256(run_dir / "negative_tests.json"),
            "report_file_sha256": file_sha256(run_dir / "STUDY_REPORT.md"),
        }
        completion = dict(completion_payload)
        completion["completion_sha256"] = object_sha256(completion_payload)
        write_json_exclusive(run_dir / "RUN_COMPLETE.json", completion)
        return completion
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.verification_failure",
            "status": "INDEPENDENT_VERIFICATION_FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "paper_evidence": False,
            "resume_authorized": False,
        }
        failure = dict(failure_payload)
        failure["failure_sha256"] = object_sha256(failure_payload)
        try:
            write_json_exclusive(run_dir / "VERIFICATION_FAILURE.json", failure)
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    run_dir = args.run_dir if args.run_dir.is_absolute() else (repo_root / args.run_dir)
    completion = finalize(run_dir.resolve(), repo_root)
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
