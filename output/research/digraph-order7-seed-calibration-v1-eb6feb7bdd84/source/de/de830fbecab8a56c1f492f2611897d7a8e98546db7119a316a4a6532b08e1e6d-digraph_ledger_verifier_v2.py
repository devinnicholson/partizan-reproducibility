#!/usr/bin/env python3
"""Read-only replay primitives for Digraph Placement search ledgers v2.

The search harness may import the pure recomputation functions in this module,
but this module never writes a run artifact.  Its evidence replay starts from
candidate graph records and exact sidecar bytes supplied by a read-only
loader.  It recomputes the graph artifact, color-isomorphism quotient,
complete-game descriptors, derivation v2, equality v1, and event hash chain.

Full summary/aggregate comparison is intentionally projection based: callers
pass the fields recorded in their manifest or summary, and replay compares
them to the deterministic projections returned here.  This keeps run I/O out
of the verifier while preventing a search implementation from defining its
own evidentiary truth.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from digraph_placement_control import (
    DigraphPlacement,
    canonical_coloured_digraph,
    parse_game_form,
)
from digraph_derivation_certificate_v2 import (
    ARTIFACT_SCHEMA,
    DerivationVerificationError,
    build_derivation_certificate,
    build_graph_artifact,
    bytes_sha256,
    canonical_artifact_bytes,
    canonical_json_bytes,
    game_from_verified_derivation,
    object_sha256,
    validate_content_addressed_relpath,
    verify_derivation_certificate,
)
from semantic_equality_certificate_v1 import (
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


SidecarLoader = Callable[[str], bytes]
ZERO_SHA256 = "0" * 64
DESCRIPTOR_CELL_COUNT = 20
CHECKPOINTS = (128, 512, 1024, 2048)


class LedgerVerificationError(ValueError):
    """Raised when candidate evidence or ledger accounting does not replay."""


@dataclass(frozen=True)
class CandidateReplay:
    """Evidence-derived facts returned only after all proof layers replay."""

    candidate_sha256: str
    artifact_sha256: str
    quotient_sha256: str
    candidate_root_game_sha256: str
    target_root_game_sha256: str
    derivation_certificate_sha256: str
    equality_certificate_sha256: str
    descriptors: dict[str, Any]


@dataclass(frozen=True)
class TargetReplay:
    """A frozen target binding reconstructed from its canonical sidecar."""

    label: str
    artifact_sha256: str
    root_game_sha256: str
    binding: dict[str, str]
    game: Game


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise LedgerVerificationError(f"{context} has unexpected or missing fields")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LedgerVerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_canonical_json_sidecar(data: bytes, context: str) -> dict[str, Any]:
    """Parse one sidecar, rejecting alternate bytes and duplicate keys."""

    if not isinstance(data, bytes):
        raise LedgerVerificationError(f"{context} loader did not return bytes")
    try:
        value = json.loads(data.decode("ascii"), object_pairs_hook=_strict_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LedgerVerificationError(f"{context} is not valid ASCII JSON") from error
    if not isinstance(value, dict):
        raise LedgerVerificationError(f"{context} must be a JSON object")
    if data != canonical_json_bytes(value):
        raise LedgerVerificationError(f"{context} bytes are not canonical")
    return value


def source_bundle_relpath(repo_relative_path: str, digest: str) -> PurePosixPath:
    """Return the frozen content-addressed path for one source snapshot."""

    source = PurePosixPath(repo_relative_path)
    if source.is_absolute() or not source.parts or ".." in source.parts:
        raise LedgerVerificationError("source path must be repo-relative")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise LedgerVerificationError("source digest must be lowercase SHA-256")
    return PurePosixPath("source_bundle") / digest[:2] / digest / source.name


def verify_source_bundle_entry(
    entry: Mapping[str, Any], *, bundle_loader: SidecarLoader
) -> tuple[bool, str]:
    """Replay a repo-relative, byte-content-addressed source snapshot."""

    try:
        if not isinstance(entry, dict):
            raise LedgerVerificationError("source bundle entry must be an object")
        _exact_keys(
            entry,
            {"repo_relative_path", "sha256", "bundle_path"},
            "source bundle entry",
        )
        repo_path = entry["repo_relative_path"]
        digest = entry["sha256"]
        bundle_path = entry["bundle_path"]
        if not all(isinstance(value, str) for value in entry.values()):
            raise LedgerVerificationError("source bundle entry is malformed")
        expected_path = str(source_bundle_relpath(repo_path, digest))
        if bundle_path != expected_path:
            raise LedgerVerificationError(
                "source snapshot path is not content-addressed"
            )
        try:
            data = bundle_loader(bundle_path)
        except Exception as error:
            raise LedgerVerificationError(
                f"cannot read source snapshot: {bundle_path}"
            ) from error
        if bytes_sha256(data) != digest:
            raise LedgerVerificationError("source snapshot byte hash mismatch")
    except (KeyError, LedgerVerificationError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "valid"


def graph_from_candidate_record(record: Mapping[str, Any]) -> DigraphPlacement:
    """Strictly parse the frozen search candidate encoding."""

    if not isinstance(record, dict):
        raise LedgerVerificationError("candidate record must be an object")
    _exact_keys(record, {"order", "blue_vertices", "arcs"}, "candidate record")
    artifact = {
        "schema_version": ARTIFACT_SCHEMA,
        "ruleset_id": "digraph_placement_normal_play.v1",
        "order": record["order"],
        "blue_vertices": record["blue_vertices"],
        "arcs": record["arcs"],
    }
    try:
        artifact_bytes = canonical_artifact_bytes(artifact)
    except (DerivationVerificationError, ValueError) as error:
        raise LedgerVerificationError(str(error)) from error
    # The canonical artifact builder is also a convenient strict decoder.
    parsed = json.loads(artifact_bytes.decode("ascii"))
    order = int(parsed["order"])
    blue_mask = sum(1 << vertex for vertex in parsed["blue_vertices"])
    edges = [0] * order
    for source, target in parsed["arcs"]:
        edges[source] |= 1 << target
    return DigraphPlacement(blue_mask=blue_mask, edges=tuple(edges))


def candidate_record(graph: DigraphPlacement) -> dict[str, Any]:
    artifact = build_graph_artifact(graph)
    return {
        "order": artifact["order"],
        "blue_vertices": artifact["blue_vertices"],
        "arcs": artifact["arcs"],
    }


def candidate_record_sha256(record: Mapping[str, Any]) -> str:
    graph = graph_from_candidate_record(record)
    canonical_record = candidate_record(graph)
    if record != canonical_record:
        raise LedgerVerificationError("candidate record is not canonical")
    return object_sha256(canonical_record)


def weakly_connected(graph: DigraphPlacement) -> bool:
    """Return whether the underlying undirected graph is connected."""

    if graph.order == 0:
        return False
    seen = {0}
    pending = [0]
    while pending:
        source = pending.pop()
        for target in range(graph.order):
            adjacent = bool(
                graph.edges[source] & (1 << target)
                or graph.edges[target] & (1 << source)
            )
            if adjacent and target not in seen:
                seen.add(target)
                pending.append(target)
    return len(seen) == graph.order


def quotient_record(graph: DigraphPlacement) -> dict[str, Any]:
    """Recompute the frozen connected color-isomorphism quotient."""

    if not weakly_connected(graph):
        raise LedgerVerificationError("candidate is not weakly connected")
    code = canonical_coloured_digraph(graph)
    return {
        "canonical_code": code,
        "quotient_sha256": hashlib.sha256(code.encode("ascii")).hexdigest(),
    }


def _root_simplification_counts(game: Game) -> tuple[int, int]:
    dominated = 0
    reversible = 0
    for index, option in enumerate(game.left):
        if any(
            index != other_index and leq(option, other)
            for other_index, other in enumerate(game.left)
        ):
            dominated += 1
        if any(leq(response, game) for response in option.right):
            reversible += 1
    for index, option in enumerate(game.right):
        if any(
            index != other_index and leq(other, option)
            for other_index, other in enumerate(game.right)
        ):
            dominated += 1
        if any(leq(game, response) for response in option.left):
            reversible += 1
    return dominated, reversible


def _simplification_bin(value: int) -> str:
    return str(value) if value <= 2 else "3+"


def _edge_bin(value: int) -> str:
    for upper, label in (
        (4, "0-4"),
        (12, "5-12"),
        (28, "13-28"),
        (60, "29-60"),
    ):
        if value <= upper:
            return label
    return "61+"


def descriptor_record(graph: DigraphPlacement) -> dict[str, Any]:
    """Recompute every frozen v2 structural measurement and descriptor."""

    artifact = build_graph_artifact(graph)
    derivation = build_derivation_certificate(artifact)
    game = game_from_verified_derivation(
        derivation, artifact_bytes=canonical_artifact_bytes(artifact)
    )
    dominated, reversible = _root_simplification_counts(game)
    simplification_count = dominated + reversible
    tree_edges = edge_count(game)
    record = {
        "graph_order": graph.order,
        "graph_arc_count": sum(mask.bit_count() for mask in graph.edges),
        "blue_vertex_count": graph.blue_mask.bit_count(),
        "red_vertex_count": graph.order - graph.blue_mask.bit_count(),
        "distinct_game_tree_node_count": node_count(game),
        "distinct_game_tree_edge_count": tree_edges,
        "game_birthday": birthday(game),
        "root_dominated_option_count": dominated,
        "root_reversible_option_count": reversible,
        "root_simplification_count": simplification_count,
        "descriptor_cell": [
            _simplification_bin(simplification_count),
            _edge_bin(tree_edges),
        ],
    }
    # Search v2 can inspect many transient candidates in one process.  These
    # process-global memo tables are derivation accelerators, not evidence;
    # retaining every rejected candidate would make memory depend on proposal
    # history without changing any descriptor.
    leq.cache_clear()
    serialize.cache_clear()
    game_digest.cache_clear()
    edge_count.cache_clear()
    node_count.cache_clear()
    birthday.cache_clear()
    return record


def _load_bound_sidecar(
    reference: Mapping[str, Any], *, role: str, loader: SidecarLoader
) -> bytes:
    if not isinstance(reference, dict):
        raise LedgerVerificationError(f"{role} sidecar reference must be an object")
    _exact_keys(reference, {"path", "sha256"}, f"{role} sidecar reference")
    path = reference["path"]
    digest = reference["sha256"]
    if not isinstance(path, str) or not isinstance(digest, str):
        raise LedgerVerificationError(f"{role} sidecar reference is malformed")
    try:
        validate_content_addressed_relpath(path, role=role, digest=digest)
    except (DerivationVerificationError, ValueError) as error:
        raise LedgerVerificationError(str(error)) from error
    try:
        data = loader(path)
    except Exception as error:
        raise LedgerVerificationError(f"cannot read {role} sidecar: {path}") from error
    if bytes_sha256(data) != digest:
        raise LedgerVerificationError(f"{role} sidecar byte hash mismatch")
    return data


def verify_target_artifact(
    *,
    target_label: str,
    artifact_reference: Mapping[str, Any],
    sidecar_loader: SidecarLoader,
) -> tuple[bool, str, TargetReplay | None]:
    """Reconstruct a frozen short-game target and its equality binding."""

    try:
        data = _load_bound_sidecar(
            artifact_reference, role="artifacts", loader=sidecar_loader
        )
        artifact = parse_canonical_json_sidecar(data, "target artifact")
        _exact_keys(
            artifact,
            {
                "schema_version",
                "label",
                "literal_serialization",
                "root_game_sha256",
            },
            "target artifact",
        )
        if artifact["schema_version"] != "partizan.abstract_short_game_target.v1":
            raise LedgerVerificationError("unsupported target artifact schema")
        if artifact["label"] != target_label:
            raise LedgerVerificationError("target label mismatch")
        literal = artifact["literal_serialization"]
        if not isinstance(literal, str):
            raise LedgerVerificationError("target serialization must be a string")
        game = parse_game_form(literal)
        root_digest = game_digest(game)
        if serialize(game) != literal:
            raise LedgerVerificationError(
                "target serialization is not literal-canonical"
            )
        if artifact["root_game_sha256"] != root_digest:
            raise LedgerVerificationError("target root-game digest mismatch")
        artifact_digest = bytes_sha256(data)
        binding = {
            "kind": "abstract_short_game_target",
            "schema_version": artifact["schema_version"],
            "artifact_sha256": artifact_digest,
            "root_game_sha256": root_digest,
        }
        replay = TargetReplay(
            label=target_label,
            artifact_sha256=artifact_digest,
            root_game_sha256=root_digest,
            binding=binding,
            game=game,
        )
    except (
        KeyError,
        LedgerVerificationError,
        TypeError,
        ValueError,
    ) as error:
        return False, str(error), None
    return True, "valid", replay


def _game_from_equality_table(equality: Mapping[str, Any], root_digest: str) -> Game:
    rows = {row["sha256"]: row for row in equality["game_table"]}
    games: dict[str, Game] = {}
    active: set[str] = set()

    def visit(digest: str) -> Game:
        if digest in games:
            return games[digest]
        if digest in active or digest not in rows:
            raise LedgerVerificationError("equality game table is not closed")
        active.add(digest)
        row = rows[digest]
        game = Game.make(
            (visit(option) for option in row["left_options"]),
            (visit(option) for option in row["right_options"]),
        )
        active.remove(digest)
        if game_digest(game) != digest or serialize(game) != row["serialization"]:
            raise LedgerVerificationError(
                "equality game table does not reconstruct the requested game"
            )
        games[digest] = game
        return game

    return visit(root_digest)


def verify_candidate_evidence(
    *,
    candidate: Mapping[str, Any],
    claimed_candidate_sha256: str,
    claimed_quotient: Mapping[str, Any],
    claimed_descriptors: Mapping[str, Any],
    accepted_sidecars: Mapping[str, Any],
    expected_target_binding: Mapping[str, str],
    sidecar_loader: SidecarLoader,
) -> tuple[bool, str, CandidateReplay | None]:
    """Replay all evidence for one retained, quotient-unique exact match."""

    try:
        if not isinstance(accepted_sidecars, dict):
            raise LedgerVerificationError("accepted_sidecars must be an object")
        _exact_keys(
            accepted_sidecars,
            {
                "artifact",
                "derivation",
                "equality",
                "candidate_root_game_sha256",
                "target_artifact_sha256",
                "target_root_game_sha256",
            },
            "accepted sidecars",
        )
        _exact_keys(
            expected_target_binding,
            {"kind", "schema_version", "artifact_sha256", "root_game_sha256"},
            "expected target binding",
        )
        if (
            accepted_sidecars["target_artifact_sha256"]
            != expected_target_binding["artifact_sha256"]
            or accepted_sidecars["target_root_game_sha256"]
            != expected_target_binding["root_game_sha256"]
        ):
            raise LedgerVerificationError("accepted target binding mismatch")

        graph = graph_from_candidate_record(candidate)
        recomputed_candidate_sha256 = candidate_record_sha256(candidate)
        if claimed_candidate_sha256 != recomputed_candidate_sha256:
            raise LedgerVerificationError("candidate record hash mismatch")
        recomputed_quotient = quotient_record(graph)
        if claimed_quotient != recomputed_quotient:
            raise LedgerVerificationError("candidate quotient mismatch")
        recomputed_descriptors = descriptor_record(graph)
        if claimed_descriptors != recomputed_descriptors:
            raise LedgerVerificationError("candidate descriptors mismatch")

        artifact_bytes = _load_bound_sidecar(
            accepted_sidecars["artifact"],
            role="artifacts",
            loader=sidecar_loader,
        )
        expected_artifact = build_graph_artifact(graph)
        expected_artifact_bytes = canonical_artifact_bytes(expected_artifact)
        if artifact_bytes != expected_artifact_bytes:
            raise LedgerVerificationError(
                "artifact sidecar is not the candidate's canonical encoding"
            )
        artifact_sha256 = bytes_sha256(artifact_bytes)

        derivation_bytes = _load_bound_sidecar(
            accepted_sidecars["derivation"],
            role="derivations",
            loader=sidecar_loader,
        )
        derivation = parse_canonical_json_sidecar(
            derivation_bytes, "derivation sidecar"
        )
        root_hash = accepted_sidecars["candidate_root_game_sha256"]
        valid, reason = verify_derivation_certificate(
            derivation,
            artifact_bytes=artifact_bytes,
            expected_artifact_sha256=artifact_sha256,
            expected_root_game_sha256=root_hash,
        )
        if not valid:
            raise LedgerVerificationError(f"derivation replay failed: {reason}")
        expected_derivation = build_derivation_certificate(expected_artifact)
        if derivation != expected_derivation:
            raise LedgerVerificationError(
                "derivation sidecar differs from deterministic reconstruction"
            )
        candidate_game = game_from_verified_derivation(
            derivation, artifact_bytes=artifact_bytes
        )

        equality_bytes = _load_bound_sidecar(
            accepted_sidecars["equality"],
            role="equality",
            loader=sidecar_loader,
        )
        equality = parse_canonical_json_sidecar(equality_bytes, "equality sidecar")
        candidate_binding = {
            "kind": "digraph_placement",
            "schema_version": ARTIFACT_SCHEMA,
            "artifact_sha256": artifact_sha256,
            "root_game_sha256": root_hash,
        }
        valid, reason = verify_equality_certificate(
            equality,
            expected_candidate_artifact_sha256=artifact_sha256,
            expected_target_artifact_sha256=expected_target_binding["artifact_sha256"],
            expected_candidate_root_game_sha256=root_hash,
            expected_target_root_game_sha256=expected_target_binding[
                "root_game_sha256"
            ],
        )
        if not valid:
            raise LedgerVerificationError(f"equality replay failed: {reason}")
        if equality["bindings"]["candidate"] != candidate_binding:
            raise LedgerVerificationError("equality candidate binding mismatch")
        if equality["bindings"]["target"] != expected_target_binding:
            raise LedgerVerificationError("equality target binding mismatch")
        target_game = _game_from_equality_table(
            equality, expected_target_binding["root_game_sha256"]
        )
        rebuilt_equality = build_equality_certificate(
            candidate_game,
            target_game,
            candidate_binding=candidate_binding,
            target_binding=dict(expected_target_binding),
        )
        if equality != rebuilt_equality:
            raise LedgerVerificationError(
                "equality sidecar differs from deterministic v1 reconstruction"
            )

        replay = CandidateReplay(
            candidate_sha256=recomputed_candidate_sha256,
            artifact_sha256=artifact_sha256,
            quotient_sha256=recomputed_quotient["quotient_sha256"],
            candidate_root_game_sha256=root_hash,
            target_root_game_sha256=expected_target_binding["root_game_sha256"],
            derivation_certificate_sha256=derivation["certificate_sha256"],
            equality_certificate_sha256=equality["certificate_sha256"],
            descriptors=recomputed_descriptors,
        )
    except (
        DerivationVerificationError,
        KeyError,
        LedgerVerificationError,
        TypeError,
        ValueError,
    ) as error:
        return False, str(error), None
    return True, "valid", replay


def chain_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a canonical global event chain without mutating its inputs."""

    previous = ZERO_SHA256
    chained: list[dict[str, Any]] = []
    for index, source in enumerate(events):
        event = copy.deepcopy(dict(source))
        forbidden = {"global_event_index", "previous_event_sha256", "event_sha256"}
        if forbidden & set(event):
            raise LedgerVerificationError("unchained event contains chain fields")
        event["global_event_index"] = index
        event["previous_event_sha256"] = previous
        event["event_sha256"] = object_sha256(event)
        previous = event["event_sha256"]
        chained.append(event)
    return chained


def verify_event_hash_chain(
    events: Sequence[Mapping[str, Any]],
    *,
    expected_final_event_sha256: str | None = None,
) -> tuple[bool, str]:
    previous = ZERO_SHA256
    try:
        for index, source in enumerate(events):
            if not isinstance(source, dict):
                raise LedgerVerificationError("event must be an object")
            event = copy.deepcopy(source)
            event_hash = event.pop("event_sha256", None)
            if event.get("global_event_index") != index:
                raise LedgerVerificationError("global event index mismatch")
            if event.get("previous_event_sha256") != previous:
                raise LedgerVerificationError("previous event hash mismatch")
            if object_sha256(event) != event_hash:
                raise LedgerVerificationError("event hash mismatch")
            previous = event_hash
        if expected_final_event_sha256 is not None and (
            previous != expected_final_event_sha256
        ):
            raise LedgerVerificationError("final event hash mismatch")
    except (KeyError, LedgerVerificationError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "valid"


def recompute_run_projection(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute the frozen accounting projection for one policy run.

    Events must be ordered from evaluation 0 through N-1 and share one
    policy, target, and base seed.  The function derives all discovery counts
    from evidence-bearing retained events; it never trusts an aggregate flag.
    """

    if not events:
        raise LedgerVerificationError("run has no events")
    identity = tuple(events[0].get(key) for key in ("policy", "target", "base_seed"))
    discovered_quotients: set[str] = set()
    discovered_games: set[str] = set()
    discovered_cells: set[tuple[str, str]] = set()
    rejection_counts: Counter[str] = Counter()
    verifier_calls = 0
    exact_matches = 0
    retained = 0
    coverage_sum = 0.0
    checkpoints: dict[str, float] = {}

    for index, event in enumerate(events):
        if (
            tuple(event.get(key) for key in ("policy", "target", "base_seed"))
            != identity
        ):
            raise LedgerVerificationError("run mixes policy, target, or base seed")
        if event.get("evaluation_index") != index:
            raise LedgerVerificationError("evaluation index is not contiguous")
        rejection = event.get("rejection")
        verifier = event.get("verifier")
        if rejection is not None:
            if not isinstance(rejection, dict) or not isinstance(
                rejection.get("reason"), str
            ):
                raise LedgerVerificationError("typed rejection is malformed")
            rejection_counts[rejection["reason"]] += 1
        if verifier is not None:
            if (
                not isinstance(verifier, dict)
                or type(verifier.get("matched")) is not bool
            ):
                raise LedgerVerificationError("verifier summary is malformed")
            verifier_calls += 1
            exact_matches += int(verifier["matched"])

        accepted = event.get("accepted_sidecars")
        if accepted is not None:
            if not isinstance(accepted, dict):
                raise LedgerVerificationError("accepted sidecars are malformed")
            quotient = event.get("quotient")
            measurements = event.get("measurements")
            if not isinstance(quotient, dict) or not isinstance(measurements, dict):
                raise LedgerVerificationError("retained event lacks replayed structure")
            quotient_hash = quotient.get("quotient_sha256")
            root_hash = accepted.get("candidate_root_game_sha256")
            cell = measurements.get("descriptor_cell")
            if (
                not isinstance(quotient_hash, str)
                or not isinstance(root_hash, str)
                or not isinstance(cell, list)
                or len(cell) != 2
                or any(not isinstance(value, str) for value in cell)
            ):
                raise LedgerVerificationError("retained discovery key is malformed")
            if quotient_hash in discovered_quotients:
                raise LedgerVerificationError(
                    "accepted sidecars repeat an already retained quotient"
                )
            discovered_quotients.add(quotient_hash)
            discovered_games.add(root_hash)
            discovered_cells.add((cell[0], cell[1]))
            retained += 1

        coverage = 100.0 * len(discovered_cells) / DESCRIPTOR_CELL_COUNT
        coverage_sum += coverage
        evaluation_number = index + 1
        if evaluation_number in CHECKPOINTS:
            checkpoints[str(evaluation_number)] = coverage

    evaluation_count = len(events)
    return {
        "policy": identity[0],
        "target": identity[1],
        "base_seed": identity[2],
        "candidate_evaluations": evaluation_count,
        "exact_verifier_calls": verifier_calls,
        "exact_match_count": exact_matches,
        "retained_quotient_unique_count": retained,
        "generated_literal_game_unique_count": len(discovered_games),
        "generated_descriptor_cell_count": len(discovered_cells),
        "coverage_auc_percentage_points": coverage_sum / evaluation_count,
        "checkpoint_coverage_percent": checkpoints,
        "typed_rejection_counts": dict(sorted(rejection_counts.items())),
        "retained_quotient_sha256": sorted(discovered_quotients),
        "retained_literal_game_sha256": sorted(discovered_games),
        "retained_descriptor_cells": [list(cell) for cell in sorted(discovered_cells)],
    }


def recompute_aggregate_projection(
    per_run: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Recompute deterministic per-policy/target aggregate means.

    Bootstrap claims remain a separate preregistered analysis layer.  This
    projection covers the raw aggregates whose mutation must be detected by
    ledger replay.
    """

    metrics = (
        "coverage_auc_percentage_points",
        "retained_quotient_unique_count",
        "generated_literal_game_unique_count",
        "generated_descriptor_cell_count",
    )
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in per_run:
        key = (str(row["policy"]), str(row["target"]))
        groups.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for (policy, target), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda row: int(row["base_seed"]))
        for metric in metrics:
            values = [float(row[metric]) for row in rows]
            result.append(
                {
                    "policy": policy,
                    "target": target,
                    "metric": metric,
                    "values_by_seed": values,
                    "minimum": min(values),
                    "maximum": max(values),
                    "mean": sum(values) / len(values),
                }
            )
    return result


def verify_summary_projections(
    *,
    events_by_run: Sequence[Sequence[Mapping[str, Any]]],
    claimed_per_run: Sequence[Mapping[str, Any]],
    claimed_aggregates: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """Compare claimed run and aggregate projections to full recomputation."""

    try:
        recomputed_runs = [recompute_run_projection(events) for events in events_by_run]
        recomputed_runs.sort(
            key=lambda row: (
                str(row["policy"]),
                str(row["target"]),
                int(row["base_seed"]),
            )
        )
        supplied_runs = [dict(row) for row in claimed_per_run]
        supplied_runs.sort(
            key=lambda row: (
                str(row["policy"]),
                str(row["target"]),
                int(row["base_seed"]),
            )
        )
        if supplied_runs != recomputed_runs:
            raise LedgerVerificationError("per-run summary projection mismatch")
        recomputed_aggregates = recompute_aggregate_projection(recomputed_runs)
        if list(claimed_aggregates) != recomputed_aggregates:
            raise LedgerVerificationError("aggregate summary projection mismatch")
    except (KeyError, LedgerVerificationError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "valid"


__all__ = [
    "CHECKPOINTS",
    "CandidateReplay",
    "DESCRIPTOR_CELL_COUNT",
    "LedgerVerificationError",
    "TargetReplay",
    "candidate_record",
    "candidate_record_sha256",
    "chain_events",
    "descriptor_record",
    "graph_from_candidate_record",
    "parse_canonical_json_sidecar",
    "quotient_record",
    "recompute_aggregate_projection",
    "recompute_run_projection",
    "source_bundle_relpath",
    "verify_candidate_evidence",
    "verify_event_hash_chain",
    "verify_source_bundle_entry",
    "verify_summary_projections",
    "verify_target_artifact",
    "weakly_connected",
]
