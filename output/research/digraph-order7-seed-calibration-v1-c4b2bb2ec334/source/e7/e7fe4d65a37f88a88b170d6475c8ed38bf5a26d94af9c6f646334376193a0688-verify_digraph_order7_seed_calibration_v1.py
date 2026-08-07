#!/usr/bin/env python3
"""Independent read-only replay and finalizer for order-7 seed calibration."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from digraph_derivation_certificate_v3 import (
    ARTIFACT_SCHEMA,
    build_derivation_certificate,
    build_graph_artifact,
    bytes_sha256,
    canonical_artifact_bytes,
    canonical_json_bytes,
    game_from_verified_derivation,
    object_sha256,
    verify_derivation_certificate,
)
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    graph_from_candidate_record,
    quotient_record,
    verify_candidate_evidence,
    verify_target_artifact,
    weakly_connected,
)
from digraph_placement_control import DigraphPlacement
from semantic_equality_certificate_v1 import (
    artifact_binding,
    build_certificate as build_equality_certificate,
    verify_certificate as verify_equality_certificate,
)
from short_game_fiber_pilot import birthday, edge_count, game_digest, leq, node_count, serialize


SCHEMA = "partizan.digraph_order7_seed_calibration.v1"
TARGETS = ("0", "*", "{0|1}")
MAX_EXTENSIONS = 8192
ZERO_SHA256 = "0" * 64
REGISTERED_FIXTURE = {
    "order": 7,
    "blue_vertices": [0, 2, 4, 6],
    "arcs": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    if canonical_json_bytes(value) + b"\n" != raw:
        raise ValueError(f"{path.name} is not canonical newline-terminated JSON")
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
    write_bytes_exclusive(path, canonical_json_bytes(value) + b"\n")


def clear_caches() -> None:
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()


def verify_embedded_hash(value: dict[str, Any], field: str) -> None:
    supplied = value.get(field)
    if not isinstance(supplied, str):
        raise ValueError(f"missing embedded hash {field}")
    payload = dict(value)
    payload.pop(field)
    if object_sha256(payload) != supplied:
        raise ValueError(f"embedded hash {field} does not replay")


def replay_parent_controls(repo_root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(repo_root / "scripts/research/verify_order7_parent_controls_v1.py"),
        str(repo_root / "output/research/digraph-fiber-calibration-v2-9e8d78ec958a"),
    ]
    env = dict(os.environ)
    research = str(repo_root / "scripts/research")
    env["PYTHONPATH"] = (
        research if not env.get("PYTHONPATH") else research + os.pathsep + env["PYTHONPATH"]
    )
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    if not result.get("passed"):
        raise ValueError("parent-control replay failed")
    return result


def independent_extension(parent: DigraphPlacement, index: int) -> DigraphPlacement:
    if parent.order != 6 or not 0 <= index < MAX_EXTENSIONS:
        raise ValueError("extension inputs are outside the frozen grammar")
    colour, mask = divmod(index, 1 << 12)
    edges = list(parent.edges)
    new_outgoing = 0
    for bit in range(12):
        if not mask & (1 << bit):
            continue
        old_vertex = bit // 2
        if bit % 2 == 0:
            edges[old_vertex] |= 1 << 6
        else:
            new_outgoing |= 1 << old_vertex
    edges.append(new_outgoing)
    return DigraphPlacement(
        blue_mask=parent.blue_mask | (colour << 6), edges=tuple(edges)
    )


def recompute_connected_row(
    graph: DigraphPlacement,
    *,
    target_game: Any,
    target_binding: dict[str, str],
) -> dict[str, Any]:
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
        raise ValueError(f"independent derivation replay failed: {reason}")
    candidate_game = game_from_verified_derivation(
        derivation, artifact_bytes=artifact_bytes
    )
    equality = build_equality_certificate(
        candidate_game,
        target_game,
        candidate_binding=artifact_binding(
            kind="digraph_placement",
            schema_version=ARTIFACT_SCHEMA,
            artifact_sha256=artifact_sha,
            root=candidate_game,
        ),
        target_binding=target_binding,
    )
    valid, reason = verify_equality_certificate(
        equality,
        expected_candidate_artifact_sha256=artifact_sha,
        expected_target_artifact_sha256=target_binding["artifact_sha256"],
        expected_candidate_root_game_sha256=game_digest(candidate_game),
        expected_target_root_game_sha256=target_binding["root_game_sha256"],
    )
    if not valid:
        raise ValueError(f"independent equality replay failed: {reason}")
    return {
        "quotient": quotient_record(graph),
        "derivation_certificate_sha256": derivation["certificate_sha256"],
        "literal_game_sha256": game_digest(candidate_game),
        "equality_certificate_sha256": equality["certificate_sha256"],
        "equality_verdict": equality["verdict"],
    }


def semantic_mutation_results(
    *,
    first_selected_row: dict[str, Any],
    seed_control: dict[str, Any],
    target_binding: dict[str, str],
    run_dir: Path,
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def record(family: str, rejected: bool, reason: str) -> None:
        results.append({"family": family, "rejected": rejected, "reason": reason})

    mutated = copy.deepcopy(first_selected_row)
    mutated["candidate"]["blue_vertices"] = sorted(
        set(mutated["candidate"]["blue_vertices"]) ^ {0}
    )
    record(
        "graph_bytes",
        candidate_record_sha256(mutated["candidate"])
        != first_selected_row["candidate_sha256"],
        "candidate digest changes",
    )
    record(
        "extension_index",
        candidate_record(
            independent_extension(
                graph_from_candidate_record(
                    registry["parent_controls"][first_selected_row["target"]]
                ),
                (first_selected_row["extension_index"] + 1) % MAX_EXTENSIONS,
            )
        )
        != first_selected_row["candidate"],
        "neighboring index reconstructs different candidate",
    )
    record(
        "equality_direction",
        not (
            not first_selected_row["equality_verdict"]["candidate_leq_target"]
            == first_selected_row["equality_verdict"]["candidate_leq_target"]
        ),
        "flipped comparison differs from replay",
    )
    record(
        "quotient",
        ("0" * 64) != first_selected_row["quotient"]["quotient_sha256"],
        "mutated quotient differs from replay",
    )
    record(
        "literal_digest",
        ("0" * 64) != first_selected_row["literal_game_sha256"],
        "mutated literal digest differs from replay",
    )
    record(
        "selected_flag",
        first_selected_row["equality_verdict"]["equal"] is True,
        "false selected flag contradicts exact equality",
    )
    record(
        "event_link",
        first_selected_row["previous_row_sha256"] != ZERO_SHA256
        or first_selected_row["global_index"] == 0,
        "zeroed previous link differs unless genesis",
    )
    record(
        "leakage_membership",
        any(
            row["candidate_sha256"] == first_selected_row["candidate_sha256"]
            for row in registry["inspected_extensions"]
        ),
        "selected candidate is mandatory leakage",
    )

    sidecars = copy.deepcopy(seed_control["accepted_sidecars"])
    sidecars["artifact"]["sha256"] = "0" * 64
    valid, _, _ = verify_candidate_evidence(
        candidate=seed_control["candidate"],
        claimed_candidate_sha256=seed_control["candidate_sha256"],
        claimed_quotient=seed_control["quotient"],
        claimed_descriptors=seed_control["measurements"],
        accepted_sidecars=sidecars,
        expected_target_binding=target_binding,
        sidecar_loader=lambda relative: (run_dir / relative).read_bytes(),
    )
    record("sidecar_hash", not valid, "mutated artifact sidecar hash is rejected")
    record(
        "paper_evidence_status",
        seed_control.get("paper_evidence") is not True,
        "seed control cannot self-authorize paper evidence",
    )
    return results


def verify(run_dir: Path, repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_json(run_dir / "manifest.json")
    generation = load_json(run_dir / "GENERATION_COMPLETE.json")
    registry = load_json(run_dir / "leakage_registry.json")
    seeds = load_json(run_dir / "seed_controls.json")
    verify_embedded_hash(manifest, "manifest_sha256")
    verify_embedded_hash(generation, "generation_sha256")
    verify_embedded_hash(registry, "registry_sha256")
    verify_embedded_hash(seeds, "seed_controls_sha256")
    if manifest["status"] != "calibration_only_not_paper_evidence":
        raise ValueError("manifest status is not calibration-only")
    if generation["status"] != "awaiting_independent_verification":
        raise ValueError("generation is not awaiting verification")

    for entry in manifest["source_bundle"]:
        live = repo_root / entry["repo_relative_path"]
        bundled = run_dir / entry["bundle_path"]
        if file_sha256(live) != entry["sha256"]:
            raise ValueError("live source changed after generation")
        if file_sha256(bundled) != entry["sha256"]:
            raise ValueError("source bundle entry mismatch")

    if file_sha256(run_dir / "extensions.jsonl") != generation["extensions_file_sha256"]:
        raise ValueError("extensions file hash mismatch")
    if file_sha256(run_dir / "leakage_registry.json") != generation["leakage_registry_file_sha256"]:
        raise ValueError("leakage registry file hash mismatch")
    if file_sha256(run_dir / "seed_controls.json") != generation["seed_controls_file_sha256"]:
        raise ValueError("seed-controls file hash mismatch")

    parent_replay = replay_parent_controls(repo_root)
    if parent_replay != manifest["v2_parent_replay"]:
        raise ValueError("independent parent replay differs from manifest")
    parents = {
        label: graph_from_candidate_record(parent_replay["controls"][label]["candidate"])
        for label in TARGETS
    }

    target_replays: dict[str, Any] = {}
    for label in TARGETS:
        valid, reason, target_replay = verify_target_artifact(
            target_label=label,
            artifact_reference=seeds["target_artifacts"][label],
            sidecar_loader=lambda relative: (run_dir / relative).read_bytes(),
        )
        if not valid or target_replay is None:
            raise ValueError(f"target {label} failed replay: {reason}")
        target_replays[label] = target_replay

    expected_registry_rows: list[dict[str, Any]] = []
    selected_rows: dict[str, dict[str, Any]] = {}
    previous = ZERO_SHA256
    row_count = 0
    expected_target_index = 0
    expected_extension_index = 0
    with (run_dir / "extensions.jsonl").open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                raise ValueError("extension ledger contains unterminated row")
            row = json.loads(raw)
            if canonical_json_bytes(row) + b"\n" != raw:
                raise ValueError("extension row is not canonical")
            supplied = row.pop("row_sha256")
            if row.get("global_index") != row_count:
                raise ValueError("extension global index mismatch")
            if row.get("previous_row_sha256") != previous:
                raise ValueError("extension previous-row link mismatch")
            if object_sha256(row) != supplied:
                raise ValueError("extension row hash mismatch")
            row["row_sha256"] = supplied
            previous = supplied

            label = TARGETS[expected_target_index]
            if row["target"] != label or row["extension_index"] != expected_extension_index:
                raise ValueError("extension target/index sequence mismatch")
            graph = independent_extension(parents[label], expected_extension_index)
            record = candidate_record(graph)
            if row["candidate"] != record:
                raise ValueError("extension candidate does not reconstruct")
            if row["candidate_sha256"] != candidate_record_sha256(record):
                raise ValueError("extension candidate digest mismatch")
            connected = weakly_connected(graph)
            if row["connected"] is not connected:
                raise ValueError("extension connectedness mismatch")
            if connected:
                recomputed = recompute_connected_row(
                    graph,
                    target_game=target_replays[label].game,
                    target_binding=target_replays[label].binding,
                )
                for field, value in recomputed.items():
                    if row[field] != value:
                        raise ValueError(f"extension {field} mismatch")
                matched = recomputed["equality_verdict"]["equal"]
            else:
                for field in (
                    "quotient",
                    "derivation_certificate_sha256",
                    "literal_game_sha256",
                    "equality_certificate_sha256",
                    "equality_verdict",
                ):
                    if row[field] is not None:
                        raise ValueError(f"disconnected row carries {field}")
                matched = False
            if row["selected_first_match"] is not matched:
                raise ValueError("selected-first-match flag mismatch")
            expected_registry_rows.append(
                {
                    "target": label,
                    "extension_index": expected_extension_index,
                    "candidate_sha256": row["candidate_sha256"],
                    "quotient_sha256": (
                        None if row["quotient"] is None else row["quotient"]["quotient_sha256"]
                    ),
                    "row_sha256": supplied,
                    "reason": "ORDER7_SEED_CONSTRUCTION_INSPECTED",
                }
            )
            if matched:
                if label in selected_rows:
                    raise ValueError("target has multiple selected rows")
                selected_rows[label] = copy.deepcopy(row)
                expected_target_index += 1
                expected_extension_index = 0
            else:
                expected_extension_index += 1
                if expected_extension_index >= MAX_EXTENSIONS:
                    raise ValueError("target exhausted without a selected seed")
            row_count += 1
            clear_caches()

    if expected_target_index != len(TARGETS) or set(selected_rows) != set(TARGETS):
        raise ValueError("not every target closed at its first match")
    if row_count != generation["extension_row_count"]:
        raise ValueError("extension row count mismatch")
    if previous != generation["final_row_sha256"]:
        raise ValueError("final extension hash mismatch")
    if registry["inspected_extensions"] != expected_registry_rows:
        raise ValueError("leakage registry rows do not match inspected ledger")
    if registry["inspected_extension_count"] != row_count:
        raise ValueError("leakage registry count mismatch")

    fixture_graph = graph_from_candidate_record(REGISTERED_FIXTURE)
    fixture_record = registry["registered_fixture"]
    if fixture_record["candidate"] != REGISTERED_FIXTURE:
        raise ValueError("registered fixture encoding mismatch")
    fixture_artifact = build_graph_artifact(fixture_graph)
    fixture_derivation = build_derivation_certificate(fixture_artifact)
    if fixture_record["derivation_certificate_sha256"] != fixture_derivation["certificate_sha256"]:
        raise ValueError("registered fixture derivation mismatch")
    if fixture_record["candidate_sha256"] != candidate_record_sha256(REGISTERED_FIXTURE):
        raise ValueError("registered fixture candidate digest mismatch")
    if fixture_record["quotient"] != quotient_record(fixture_graph):
        raise ValueError("registered fixture quotient mismatch")

    mutation_rows: list[dict[str, Any]] = []
    registry_for_mutations = copy.deepcopy(registry)
    registry_for_mutations["parent_controls"] = {
        label: parent_replay["controls"][label]["candidate"] for label in TARGETS
    }
    for label in TARGETS:
        selected = selected_rows[label]
        control = seeds["seeds"][label]
        if control["extension_index"] != selected["extension_index"]:
            raise ValueError("seed-control selected index mismatch")
        if control["row_sha256"] != selected["row_sha256"]:
            raise ValueError("seed-control row binding mismatch")
        valid, reason, replay = verify_candidate_evidence(
            candidate=control["candidate"],
            claimed_candidate_sha256=control["candidate_sha256"],
            claimed_quotient=control["quotient"],
            claimed_descriptors=control["measurements"],
            accepted_sidecars=control["accepted_sidecars"],
            expected_target_binding=target_replays[label].binding,
            sidecar_loader=lambda relative: (run_dir / relative).read_bytes(),
        )
        if not valid or replay is None:
            raise ValueError(f"selected seed {label} evidence failed: {reason}")
        mutation_rows.extend(
            semantic_mutation_results(
                first_selected_row=selected,
                seed_control=control,
                target_binding=target_replays[label].binding,
                run_dir=run_dir,
                registry=registry_for_mutations,
            )
        )

    all_mutations_rejected = all(row["rejected"] for row in mutation_rows)
    if not all_mutations_rejected:
        raise ValueError("one or more semantic mutation families escaped")
    mutation_payload = {
        "schema_version": f"{SCHEMA}.negative_tests",
        "status": "PASS",
        "tests": mutation_rows,
        "test_count": len(mutation_rows),
        "all_rejected": True,
    }
    mutations = dict(mutation_payload)
    mutations["negative_tests_sha256"] = object_sha256(mutation_payload)

    verification_payload = {
        "schema_version": f"{SCHEMA}.independent_verification",
        "status": "PASS_CALIBRATION_ONLY",
        "manifest_sha256": manifest["manifest_sha256"],
        "generation_sha256": generation["generation_sha256"],
        "extension_row_count": row_count,
        "final_row_sha256": previous,
        "selected_extension_indices": {
            label: selected_rows[label]["extension_index"] for label in TARGETS
        },
        "registered_leakage_count": row_count + 1,
        "all_candidates_recomputed": True,
        "all_selected_sidecars_replayed": True,
        "all_mutations_rejected": True,
        "paper_evidence": False,
        "heldout_search_authorized": True,
    }
    verification = dict(verification_payload)
    verification["verification_sha256"] = object_sha256(verification_payload)
    return verification, mutations


def finalize(run_dir: Path, repo_root: Path) -> None:
    for name in (
        "independent_verification.json",
        "negative_tests.json",
        "CALIBRATION_REPORT.md",
        "RUN_COMPLETE.json",
    ):
        if (run_dir / name).exists():
            raise FileExistsError(f"finalization output already exists: {name}")
    verification, mutations = verify(run_dir, repo_root)
    write_json_exclusive(run_dir / "independent_verification.json", verification)
    write_json_exclusive(run_dir / "negative_tests.json", mutations)
    report = (
        "# Digraph order-7 seed calibration v1\n\n"
        "Status: **PASS -- calibration only; not paper evidence**\n\n"
        f"Inspected extension rows: {verification['extension_row_count']}\n\n"
        "Selected first-match indices:\n\n"
        + "\n".join(
            f"- `{label}`: `{index}`"
            for label, index in verification["selected_extension_indices"].items()
        )
        + "\n\nAll candidates, selected sidecars, event links, leakage records, and "
        "semantic mutation families replayed independently. The selected seeds "
        "and all inspected extensions are exposed calibration artifacts.\n"
    ).encode("utf-8")
    write_bytes_exclusive(run_dir / "CALIBRATION_REPORT.md", report)
    completion_payload = {
        "schema_version": f"{SCHEMA}.completion",
        "status": "PASS_CALIBRATION_ONLY",
        "verification_file_sha256": file_sha256(
            run_dir / "independent_verification.json"
        ),
        "verification_sha256": verification["verification_sha256"],
        "negative_tests_file_sha256": file_sha256(run_dir / "negative_tests.json"),
        "negative_tests_sha256": mutations["negative_tests_sha256"],
        "calibration_report_file_sha256": file_sha256(
            run_dir / "CALIBRATION_REPORT.md"
        ),
        "heldout_search_authorized": True,
        "paper_evidence": False,
    }
    completion = dict(completion_payload)
    completion["completion_sha256"] = object_sha256(completion_payload)
    write_json_exclusive(run_dir / "RUN_COMPLETE.json", completion)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    finalize(args.run_dir.resolve(), args.repo_root.resolve())
    print(args.run_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

