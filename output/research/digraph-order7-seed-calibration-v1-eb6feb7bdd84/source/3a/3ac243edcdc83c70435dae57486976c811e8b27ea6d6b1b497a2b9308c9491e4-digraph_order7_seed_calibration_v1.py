#!/usr/bin/env python3
"""Deterministically construct registered order-7 launch seeds.

This is Stage 0 calibration only.  It visits one-vertex extensions in the
contract's exact order and stops at the first exact target match.  A separate
process must independently verify the closed bundle before it can be used by
any held-out study.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from digraph_derivation_certificate_v3 import (
    ARTIFACT_SCHEMA,
    build_derivation_certificate,
    build_graph_artifact,
    bytes_sha256,
    canonical_artifact_bytes,
    canonical_json_bytes,
    game_from_verified_derivation,
    schema_contract,
    verify_derivation_certificate,
)
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    descriptor_record,
    graph_from_candidate_record,
    object_sha256,
    quotient_record,
    weakly_connected,
)
from digraph_placement_control import DigraphPlacement, parse_game_form
from semantic_equality_certificate_v1 import (
    artifact_binding,
    build_certificate as build_equality_certificate,
    verify_certificate as verify_equality_certificate,
)
from short_game_fiber_pilot import (
    birthday,
    edge_count,
    game_digest,
    leq,
    node_count,
    serialize,
)


SCHEMA = "partizan.digraph_order7_seed_calibration.v1"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
ROW_SCHEMA = f"{SCHEMA}.extension"
REGISTRY_SCHEMA = f"{SCHEMA}.leakage_registry"
SEED_SCHEMA = f"{SCHEMA}.seed_controls"
GENERATION_SCHEMA = f"{SCHEMA}.generation_complete"
STATUS = "calibration_only_not_paper_evidence"
CONTRACT = Path("docs/research/DIGRAPH_ORDER7_SEED_CALIBRATION_V1_CONTRACT.md")
CONTRACT_SHA256 = (
    "25792dfcefd0bc31d02659d952c02667c0df7929b948b3ee3e4dc2361381d53c"
)
V2_RUN = Path("output/research/digraph-fiber-calibration-v2-9e8d78ec958a")
TARGETS = ("0", "*", "{0|1}")
MAX_EXTENSIONS = 8192
ZERO_SHA256 = "0" * 64

REGISTERED_FIXTURE = {
    "order": 7,
    "blue_vertices": [0, 2, 4, 6],
    "arcs": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
}

SOURCE_PATHS = (
    CONTRACT,
    Path("scripts/research/digraph_order7_seed_calibration_v1.py"),
    Path("scripts/research/verify_digraph_order7_seed_calibration_v1.py"),
    Path("scripts/research/verify_order7_parent_controls_v1.py"),
    Path("scripts/research/digraph_derivation_certificate_v3.py"),
    Path("scripts/research/digraph_ledger_verifier_v3.py"),
    Path("scripts/research/digraph_derivation_certificate_v2.py"),
    Path("scripts/research/digraph_ledger_verifier_v2.py"),
    Path("scripts/research/digraph_placement_control.py"),
    Path("scripts/research/semantic_equality_certificate_v1.py"),
    Path("scripts/research/short_game_fiber_pilot.py"),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def content_path(role: str, digest: str) -> Path:
    return Path("sidecars") / role / digest[:2] / f"{digest}.json"


def write_content_addressed(
    run_dir: Path, role: str, value: Mapping[str, Any] | bytes
) -> dict[str, str]:
    data = value if isinstance(value, bytes) else canonical_json_bytes(value)
    digest = bytes_sha256(data)
    relative = content_path(role, digest)
    destination = run_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
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


def source_entries(repo_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for relative in SOURCE_PATHS:
        source = repo_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"missing frozen source dependency: {relative}")
        digest = file_sha256(source)
        entries.append(
            {
                "repo_relative_path": relative.as_posix(),
                "sha256": digest,
                "bundle_path": f"source/{digest[:2]}/{digest}-{relative.name}",
            }
        )
    return entries


def copy_source_bundle(
    repo_root: Path, run_dir: Path, entries: Iterable[Mapping[str, str]]
) -> None:
    for entry in entries:
        data = (repo_root / entry["repo_relative_path"]).read_bytes()
        if bytes_sha256(data) != entry["sha256"]:
            raise AssertionError("source changed during bundle construction")
        write_bytes_exclusive(run_dir / entry["bundle_path"], data)


def replay_parent_controls(repo_root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(repo_root / "scripts/research/verify_order7_parent_controls_v1.py"),
        str(repo_root / V2_RUN),
    ]
    environment = dict(os.environ)
    research_path = str(repo_root / "scripts/research")
    environment["PYTHONPATH"] = (
        research_path
        if not environment.get("PYTHONPATH")
        else research_path + os.pathsep + environment["PYTHONPATH"]
    )
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    if not result.get("passed") or set(result.get("controls", {})) != set(TARGETS):
        raise AssertionError("frozen v2 parent-control replay did not pass")
    return result


def extend_parent(parent: DigraphPlacement, extension_index: int) -> DigraphPlacement:
    if parent.order != 6:
        raise ValueError("order-7 seed parent must have order 6")
    if not 0 <= extension_index < MAX_EXTENSIONS:
        raise ValueError("extension index is outside 0..8191")
    new_colour = extension_index // 4096
    incident_mask = extension_index % 4096
    edges = list(parent.edges) + [0]
    for existing in range(6):
        if incident_mask & (1 << (2 * existing)):
            edges[existing] |= 1 << 6
        if incident_mask & (1 << (2 * existing + 1)):
            edges[6] |= 1 << existing
    blue_mask = parent.blue_mask | (new_colour << 6)
    return DigraphPlacement(blue_mask=blue_mask, edges=tuple(edges))


def target_artifact(label: str) -> tuple[Any, dict[str, Any]]:
    game = parse_game_form(label)
    artifact = {
        "schema_version": "partizan.abstract_short_game_target.v1",
        "label": label,
        "literal_serialization": serialize(game),
        "root_game_sha256": game_digest(game),
    }
    return game, artifact


def build_candidate_proof(
    graph: DigraphPlacement,
    *,
    target: Any,
    target_binding: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
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
        raise AssertionError(f"fresh order-7 derivation failed: {reason}")
    candidate_game = game_from_verified_derivation(
        derivation, artifact_bytes=artifact_bytes
    )
    equality = build_equality_certificate(
        candidate_game,
        target,
        candidate_binding=artifact_binding(
            kind="digraph_placement",
            schema_version=ARTIFACT_SCHEMA,
            artifact_sha256=artifact_sha,
            root=candidate_game,
        ),
        target_binding=target_binding,
    )
    if equality["verdict"]["equal"]:
        valid, reason = verify_equality_certificate(
            equality,
            expected_candidate_artifact_sha256=artifact_sha,
            expected_target_artifact_sha256=target_binding["artifact_sha256"],
            expected_candidate_root_game_sha256=game_digest(candidate_game),
            expected_target_root_game_sha256=target_binding["root_game_sha256"],
        )
        if not valid:
            raise AssertionError(f"fresh order-7 equality failed replay: {reason}")
    return artifact, derivation, equality, candidate_game


def add_row_hash(
    row: dict[str, Any], *, global_index: int, previous_sha256: str
) -> dict[str, Any]:
    chained = dict(row)
    chained["global_index"] = global_index
    chained["previous_row_sha256"] = previous_sha256
    chained["row_sha256"] = object_sha256(chained)
    return chained


def build_manifest(
    *, repo_root: Path, parent_replay: dict[str, Any], sources: list[dict[str, str]]
) -> dict[str, Any]:
    if file_sha256(repo_root / CONTRACT) != CONTRACT_SHA256:
        raise AssertionError("order-7 seed contract changed after freeze")
    payload = {
        "schema_version": MANIFEST_SCHEMA,
        "status": STATUS,
        "contract": {"path": CONTRACT.as_posix(), "sha256": CONTRACT_SHA256},
        "v2_parent_replay": parent_replay,
        "derivation_v3_contract": schema_contract(),
        "registered_fixture": REGISTERED_FIXTURE,
        "targets": list(TARGETS),
        "extension_order": {
            "count_per_target": MAX_EXTENSIONS,
            "formula": "new_colour_bit*4096+incident_arc_mask",
            "incident_bits": [
                direction
                for vertex in range(6)
                for direction in (f"{vertex}->6", f"6->{vertex}")
            ],
            "stop": "first connected exact match independently per target",
        },
        "source_bundle": sources,
        "output_contract": {
            "exclusive_directory": True,
            "canonical_hash_chained_extensions": True,
            "all_inspected_candidates_enter_leakage_registry": True,
            "independent_verification_required": True,
            "paper_evidence": False,
        },
    }
    manifest = dict(payload)
    manifest["manifest_sha256"] = object_sha256(payload)
    return manifest


def execute(repo_root: Path, output_root: Path) -> Path:
    repo_root = repo_root.resolve()
    parent_replay = replay_parent_controls(repo_root)
    sources = source_entries(repo_root)
    manifest = build_manifest(
        repo_root=repo_root, parent_replay=parent_replay, sources=sources
    )
    run_dir = output_root.resolve() / (
        "digraph-order7-seed-calibration-v1-" + manifest["manifest_sha256"][:12]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    copy_source_bundle(repo_root, run_dir, sources)
    write_json_exclusive(run_dir / "manifest.json", manifest)

    target_games: dict[str, Any] = {}
    target_bindings: dict[str, dict[str, str]] = {}
    target_refs: dict[str, dict[str, str]] = {}
    for label in TARGETS:
        game, artifact = target_artifact(label)
        ref = write_content_addressed(run_dir, "artifacts", artifact)
        target_games[label] = game
        target_refs[label] = ref
        target_bindings[label] = artifact_binding(
            kind="abstract_short_game_target",
            schema_version=artifact["schema_version"],
            artifact_sha256=ref["sha256"],
            root=game,
        )

    fixture_graph = graph_from_candidate_record(REGISTERED_FIXTURE)
    fixture_artifact = build_graph_artifact(fixture_graph)
    fixture_bytes = canonical_artifact_bytes(fixture_artifact)
    fixture_derivation = build_derivation_certificate(fixture_artifact)
    fixture_valid, fixture_reason = verify_derivation_certificate(
        fixture_derivation,
        artifact_bytes=fixture_bytes,
        expected_artifact_sha256=bytes_sha256(fixture_bytes),
    )
    if not fixture_valid:
        raise AssertionError(f"registered fixture replay failed: {fixture_reason}")
    fixture_registry = {
        "reason": "ORDER7_DERIVATION_V3_TEST_FIXTURE",
        "candidate": REGISTERED_FIXTURE,
        "candidate_sha256": candidate_record_sha256(REGISTERED_FIXTURE),
        "quotient": quotient_record(fixture_graph),
        "derivation_certificate_sha256": fixture_derivation[
            "certificate_sha256"
        ],
    }

    leakage_rows: list[dict[str, Any]] = []
    seed_controls: dict[str, Any] = {}
    extensions_path = run_dir / "extensions.jsonl"
    descriptor = os.open(
        extensions_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    global_index = 0
    previous_sha = ZERO_SHA256
    with os.fdopen(descriptor, "wb") as handle:
        for label in TARGETS:
            parent_record = parent_replay["controls"][label]["candidate"]
            parent = graph_from_candidate_record(parent_record)
            selected: dict[str, Any] | None = None
            for extension_index in range(MAX_EXTENSIONS):
                graph = extend_parent(parent, extension_index)
                record = candidate_record(graph)
                candidate_sha = candidate_record_sha256(record)
                connected = weakly_connected(graph)
                quotient = quotient_record(graph) if connected else None
                derivation_sha: str | None = None
                equality_sha: str | None = None
                equality_decision_sha: str | None = None
                literal_sha: str | None = None
                equality_verdict: dict[str, bool] | None = None
                artifact: dict[str, Any] | None = None
                derivation: dict[str, Any] | None = None
                equality: dict[str, Any] | None = None
                candidate_game: Any | None = None
                if connected:
                    artifact, derivation, equality, candidate_game = build_candidate_proof(
                        graph,
                        target=target_games[label],
                        target_binding=target_bindings[label],
                    )
                    derivation_sha = derivation["certificate_sha256"]
                    equality_decision_sha = equality["certificate_sha256"]
                    literal_sha = game_digest(candidate_game)
                    equality_verdict = dict(equality["verdict"])
                matched = bool(equality_verdict and equality_verdict["equal"])
                if matched:
                    equality_sha = equality_decision_sha
                row = add_row_hash(
                    {
                        "schema_version": ROW_SCHEMA,
                        "status": STATUS,
                        "target": label,
                        "extension_index": extension_index,
                        "candidate": record,
                        "candidate_sha256": candidate_sha,
                        "connected": connected,
                        "quotient": quotient,
                        "derivation_certificate_sha256": derivation_sha,
                        "literal_game_sha256": literal_sha,
                        "equality_decision_sha256": equality_decision_sha,
                        "equality_certificate_sha256": equality_sha,
                        "equality_verdict": equality_verdict,
                        "selected_first_match": matched,
                    },
                    global_index=global_index,
                    previous_sha256=previous_sha,
                )
                handle.write(canonical_json_bytes(row) + b"\n")
                leakage_rows.append(
                    {
                        "target": label,
                        "extension_index": extension_index,
                        "candidate_sha256": candidate_sha,
                        "quotient_sha256": (
                            None if quotient is None else quotient["quotient_sha256"]
                        ),
                        "row_sha256": row["row_sha256"],
                        "reason": "ORDER7_SEED_CONSTRUCTION_INSPECTED",
                    }
                )
                previous_sha = row["row_sha256"]
                global_index += 1
                if matched:
                    assert artifact is not None
                    assert derivation is not None
                    assert equality is not None
                    assert candidate_game is not None
                    artifact_ref = write_content_addressed(
                        run_dir,
                        "artifacts",
                        canonical_artifact_bytes(artifact),
                    )
                    derivation_ref = write_content_addressed(
                        run_dir, "derivations", derivation
                    )
                    equality_ref = write_content_addressed(
                        run_dir, "equality", equality
                    )
                    selected = {
                        "schema_version": f"{SEED_SCHEMA}.member",
                        "target": label,
                        "extension_index": extension_index,
                        "row_sha256": row["row_sha256"],
                        "candidate": record,
                        "candidate_sha256": candidate_sha,
                        "quotient": quotient,
                        "literal_game_sha256": literal_sha,
                        "measurements": descriptor_record(graph),
                        "accepted_sidecars": {
                            "artifact": artifact_ref,
                            "derivation": derivation_ref,
                            "equality": equality_ref,
                            "candidate_root_game_sha256": literal_sha,
                            "target_artifact_sha256": target_refs[label]["sha256"],
                            "target_root_game_sha256": target_bindings[label][
                                "root_game_sha256"
                            ],
                        },
                    }
                    seed_controls[label] = selected
                    clear_caches()
                    break
                clear_caches()
            if selected is None:
                raise RuntimeError(f"NO_GO: no order-7 seed found for {label}")
        handle.flush()
        os.fsync(handle.fileno())

    registry_payload = {
        "schema_version": REGISTRY_SCHEMA,
        "status": STATUS,
        "registered_fixture": fixture_registry,
        "inspected_extensions": leakage_rows,
        "inspected_extension_count": len(leakage_rows),
    }
    registry = dict(registry_payload)
    registry["registry_sha256"] = object_sha256(registry_payload)
    write_json_exclusive(run_dir / "leakage_registry.json", registry)

    seeds_payload = {
        "schema_version": SEED_SCHEMA,
        "status": STATUS,
        "target_artifacts": target_refs,
        "seeds": seed_controls,
    }
    seeds = dict(seeds_payload)
    seeds["seed_controls_sha256"] = object_sha256(seeds_payload)
    write_json_exclusive(run_dir / "seed_controls.json", seeds)

    generation_payload = {
        "schema_version": GENERATION_SCHEMA,
        "status": "awaiting_independent_verification",
        "manifest_sha256": manifest["manifest_sha256"],
        "extensions_file_sha256": file_sha256(extensions_path),
        "extension_row_count": global_index,
        "final_row_sha256": previous_sha,
        "leakage_registry_file_sha256": file_sha256(
            run_dir / "leakage_registry.json"
        ),
        "leakage_registry_sha256": registry["registry_sha256"],
        "seed_controls_file_sha256": file_sha256(run_dir / "seed_controls.json"),
        "seed_controls_sha256": seeds["seed_controls_sha256"],
        "selected_extension_indices": {
            label: seed_controls[label]["extension_index"] for label in TARGETS
        },
        "paper_evidence": False,
    }
    generation = dict(generation_payload)
    generation["generation_sha256"] = object_sha256(generation_payload)
    write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=Path("output/research"))
    args = parser.parse_args()
    run_dir = execute(args.repo_root, args.output_root)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
