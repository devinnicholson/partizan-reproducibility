#!/usr/bin/env python3
"""Strict Digraph Placement artifact-to-literal-game derivation replay.

This module is the ruleset-specific layer that equality certificate v1
deliberately does not provide.  It binds canonical graph artifact bytes to a
closed, complete active-mask state graph and to one finite literal short game.

The public builder may use the move generator.  The verifier trusts neither
the certificate's state table nor its game digests: it reparses the canonical
artifact bytes, regenerates every legal move at every reachable state, and
reconstructs the literal games bottom-up.  Equality to a target is a separate
certificate and remains outside this schema.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from digraph_placement_control import DigraphPlacement
from short_game_fiber_pilot import Game, game_digest, serialize


ARTIFACT_SCHEMA = "partizan.digraph_placement_artifact.v2"
DERIVATION_SCHEMA = "partizan.digraph_placement_derivation_certificate.v2"
MAX_ORDER = 6
HEX_256 = re.compile(r"^[0-9a-f]{64}$")

RULESET = {
    "ruleset_id": "digraph_placement_normal_play.v1",
    "play_convention": "normal_play",
    "players": {"Left": "blue", "Right": "red"},
    "move_rule": (
        "play one active vertex of the moving player's colour; delete that "
        "vertex and every active out-neighbour"
    ),
    "terminal_rule": "a player with no legal move loses",
    "state_model": "monotone active-vertex bit mask",
    "game_tree": "complete; no depth cutoff",
    "option_semantics": "sets; order and duplicates removed",
}


class DerivationVerificationError(ValueError):
    """Raised when a derivation artifact or certificate fails strict replay."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the only accepted JSON byte encoding for v2 artifacts."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise DerivationVerificationError(f"{context} has unexpected or missing fields")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DerivationVerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_plain_int(value: Any, context: str) -> int:
    if type(value) is not int:
        raise DerivationVerificationError(f"{context} must be an integer")
    return value


def validate_graph(graph: DigraphPlacement) -> DigraphPlacement:
    """Validate the frozen bounded v2 graph grammar."""

    if not 0 <= graph.order <= MAX_ORDER:
        raise ValueError(f"graph order must be in 0..{MAX_ORDER}")
    allowed = (1 << graph.order) - 1
    if graph.blue_mask & ~allowed:
        raise ValueError("blue mask refers to a missing vertex")
    if len(graph.edges) != graph.order:
        raise ValueError("edge rows do not match graph order")
    for vertex, targets in enumerate(graph.edges):
        if type(targets) is not int or targets < 0:
            raise ValueError("edge masks must be nonnegative integers")
        if targets & ~allowed:
            raise ValueError("arc refers to a missing vertex")
        if targets & (1 << vertex):
            raise ValueError("self-arcs are forbidden; colour is stored separately")
    return graph


def build_graph_artifact(graph: DigraphPlacement) -> dict[str, Any]:
    """Build the canonical, bounded Digraph Placement artifact object."""

    graph = validate_graph(graph)
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "ruleset_id": RULESET["ruleset_id"],
        "order": graph.order,
        "blue_vertices": [
            vertex for vertex in range(graph.order) if graph.is_blue(vertex)
        ],
        "arcs": [
            [source, target]
            for source in range(graph.order)
            for target in range(graph.order)
            if graph.edges[source] & (1 << target)
        ],
    }


def _graph_from_artifact_object(artifact: Mapping[str, Any]) -> DigraphPlacement:
    if not isinstance(artifact, dict):
        raise DerivationVerificationError("artifact must be a JSON object")
    _exact_keys(
        artifact,
        {"schema_version", "ruleset_id", "order", "blue_vertices", "arcs"},
        "artifact",
    )
    if artifact["schema_version"] != ARTIFACT_SCHEMA:
        raise DerivationVerificationError("unsupported artifact schema")
    if artifact["ruleset_id"] != RULESET["ruleset_id"]:
        raise DerivationVerificationError("artifact ruleset mismatch")
    order = _require_plain_int(artifact["order"], "artifact order")
    if not 0 <= order <= MAX_ORDER:
        raise DerivationVerificationError(f"artifact order must be in 0..{MAX_ORDER}")

    blue_vertices = artifact["blue_vertices"]
    if not isinstance(blue_vertices, list):
        raise DerivationVerificationError("blue_vertices must be a list")
    if any(type(vertex) is not int for vertex in blue_vertices):
        raise DerivationVerificationError("blue vertex must be an integer")
    if blue_vertices != sorted(set(blue_vertices)):
        raise DerivationVerificationError(
            "blue_vertices must be sorted and duplicate-free"
        )
    if any(not 0 <= vertex < order for vertex in blue_vertices):
        raise DerivationVerificationError("blue vertex is outside graph order")

    arcs = artifact["arcs"]
    if not isinstance(arcs, list):
        raise DerivationVerificationError("arcs must be a list")
    parsed_arcs: list[tuple[int, int]] = []
    for arc in arcs:
        if (
            not isinstance(arc, list)
            or len(arc) != 2
            or any(type(vertex) is not int for vertex in arc)
        ):
            raise DerivationVerificationError(
                "each arc must be a two-integer JSON array"
            )
        source, target = arc
        if not 0 <= source < order or not 0 <= target < order:
            raise DerivationVerificationError("arc endpoint is outside graph order")
        if source == target:
            raise DerivationVerificationError("self-arcs are forbidden")
        parsed_arcs.append((source, target))
    if parsed_arcs != sorted(set(parsed_arcs)):
        raise DerivationVerificationError("arcs must be sorted and duplicate-free")

    blue_mask = sum(1 << vertex for vertex in blue_vertices)
    edges = [0] * order
    for source, target in parsed_arcs:
        edges[source] |= 1 << target
    try:
        return validate_graph(DigraphPlacement(blue_mask, tuple(edges)))
    except ValueError as error:
        raise DerivationVerificationError(str(error)) from error


def canonical_artifact_bytes(artifact: Mapping[str, Any]) -> bytes:
    """Validate an artifact object and return its unique accepted bytes."""

    graph = _graph_from_artifact_object(artifact)
    rebuilt = build_graph_artifact(graph)
    if artifact != rebuilt:
        raise DerivationVerificationError("artifact object is not canonical")
    return canonical_json_bytes(rebuilt)


def parse_canonical_artifact_bytes(artifact_bytes: bytes) -> dict[str, Any]:
    """Parse artifact bytes while rejecting duplicate keys and byte aliases."""

    if not isinstance(artifact_bytes, bytes):
        raise DerivationVerificationError("artifact bytes must be bytes")
    try:
        artifact = json.loads(
            artifact_bytes.decode("ascii"), object_pairs_hook=_strict_json_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DerivationVerificationError(
            "artifact is not valid canonical JSON"
        ) from error
    canonical = canonical_artifact_bytes(artifact)
    if artifact_bytes != canonical:
        raise DerivationVerificationError("artifact bytes are not canonical")
    return artifact


def graph_from_artifact(artifact: Mapping[str, Any]) -> DigraphPlacement:
    """Return the graph encoded by a validated canonical artifact object."""

    canonical_artifact_bytes(artifact)
    return _graph_from_artifact_object(artifact)


def content_addressed_relpath(
    role: str, digest: str, *, extension: str = "json"
) -> PurePosixPath:
    """Return the frozen repo-relative path convention for v2 sidecars."""

    if role not in {"artifacts", "derivations", "equality", "snapshots"}:
        raise ValueError("unsupported content-addressed sidecar role")
    if not HEX_256.fullmatch(digest):
        raise ValueError("content digest must be lowercase SHA-256")
    if not re.fullmatch(r"[a-z0-9]+", extension):
        raise ValueError("extension must be lowercase alphanumeric")
    return PurePosixPath("sidecars") / role / digest[:2] / f"{digest}.{extension}"


def validate_content_addressed_relpath(
    path: str, *, role: str, digest: str, extension: str = "json"
) -> None:
    """Reject absolute, escaping, or non-content-addressed reproduction paths."""

    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DerivationVerificationError("sidecar path must be repo-relative")
    if candidate != content_addressed_relpath(role, digest, extension=extension):
        raise DerivationVerificationError(
            "sidecar path does not match the content-addressed convention"
        )


def _legal_moves(
    graph: DigraphPlacement, active_mask: int, *, blue: bool
) -> list[tuple[int, int, int]]:
    moves: list[tuple[int, int, int]] = []
    for vertex in range(graph.order):
        if not active_mask & (1 << vertex) or graph.is_blue(vertex) != blue:
            continue
        deleted = active_mask & graph.move_mask(vertex)
        destination = active_mask & ~deleted
        moves.append((vertex, deleted, destination))
    return moves


def _reachable_masks(graph: DigraphPlacement) -> set[int]:
    root = graph.active_mask
    pending = [root]
    reached: set[int] = set()
    while pending:
        active = pending.pop()
        if active in reached:
            continue
        reached.add(active)
        pending.extend(
            destination
            for _, _, destination in (
                _legal_moves(graph, active, blue=True)
                + _legal_moves(graph, active, blue=False)
            )
        )
    return reached


def _derive_games(graph: DigraphPlacement, masks: set[int]) -> dict[int, Game]:
    games: dict[int, Game] = {}
    for active in sorted(masks, key=lambda mask: (mask.bit_count(), mask)):
        left = [
            games[destination]
            for _, _, destination in _legal_moves(graph, active, blue=True)
        ]
        right = [
            games[destination]
            for _, _, destination in _legal_moves(graph, active, blue=False)
        ]
        games[active] = Game.make(left, right)
    return games


def _move_rows(
    moves: list[tuple[int, int, int]], games: Mapping[int, Game]
) -> list[dict[str, Any]]:
    return [
        {
            "vertex": vertex,
            "deleted_active_mask": deleted,
            "destination_active_mask": destination,
            "destination_game_sha256": game_digest(games[destination]),
        }
        for vertex, deleted, destination in moves
    ]


def _state_row(
    graph: DigraphPlacement, active: int, games: Mapping[int, Game]
) -> dict[str, Any]:
    left_moves = _move_rows(_legal_moves(graph, active, blue=True), games)
    right_moves = _move_rows(_legal_moves(graph, active, blue=False), games)
    game = games[active]
    left_options = sorted({move["destination_game_sha256"] for move in left_moves})
    right_options = sorted({move["destination_game_sha256"] for move in right_moves})
    return {
        "active_mask": active,
        "left_no_legal_move": not left_moves,
        "right_no_legal_move": not right_moves,
        "terminal": not left_moves and not right_moves,
        "left_moves": left_moves,
        "right_moves": right_moves,
        "left_option_game_sha256": left_options,
        "right_option_game_sha256": right_options,
        "literal_game_sha256": game_digest(game),
        "literal_serialization": serialize(game),
    }


def build_derivation_certificate(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a complete derivation certificate for a canonical artifact."""

    artifact_bytes = canonical_artifact_bytes(artifact)
    graph = _graph_from_artifact_object(artifact)
    masks = _reachable_masks(graph)
    games = _derive_games(graph, masks)
    root_mask = graph.active_mask
    payload = {
        "schema_version": DERIVATION_SCHEMA,
        "ruleset": RULESET,
        "artifact_binding": {
            "kind": "canonical_digraph_placement_graph",
            "schema_version": ARTIFACT_SCHEMA,
            "artifact_sha256": bytes_sha256(artifact_bytes),
            "canonical_byte_count": len(artifact_bytes),
        },
        "root": {
            "active_mask": root_mask,
            "literal_game_sha256": game_digest(games[root_mask]),
        },
        "states": [_state_row(graph, active, games) for active in sorted(masks)],
    }
    certificate = copy.deepcopy(payload)
    certificate["certificate_sha256"] = object_sha256(payload)
    return certificate


def _replay_derivation(
    certificate: Mapping[str, Any],
    *,
    artifact_bytes: bytes,
    expected_artifact_sha256: str | None,
    expected_root_game_sha256: str | None,
) -> Game:
    if not isinstance(certificate, dict):
        raise DerivationVerificationError("certificate must be a JSON object")
    _exact_keys(
        certificate,
        {
            "schema_version",
            "ruleset",
            "artifact_binding",
            "root",
            "states",
            "certificate_sha256",
        },
        "derivation certificate",
    )
    supplied_certificate_hash = certificate["certificate_sha256"]
    if not isinstance(supplied_certificate_hash, str) or not HEX_256.fullmatch(
        supplied_certificate_hash
    ):
        raise DerivationVerificationError("certificate hash is malformed")
    payload = copy.deepcopy(certificate)
    payload.pop("certificate_sha256")
    if object_sha256(payload) != supplied_certificate_hash:
        raise DerivationVerificationError("certificate hash mismatch")
    if certificate["schema_version"] != DERIVATION_SCHEMA:
        raise DerivationVerificationError("unsupported derivation schema")
    if certificate["ruleset"] != RULESET:
        raise DerivationVerificationError("derivation ruleset mismatch")

    artifact = parse_canonical_artifact_bytes(artifact_bytes)
    graph = _graph_from_artifact_object(artifact)
    artifact_hash = bytes_sha256(artifact_bytes)
    binding = certificate["artifact_binding"]
    if not isinstance(binding, dict):
        raise DerivationVerificationError("artifact binding must be an object")
    _exact_keys(
        binding,
        {
            "kind",
            "schema_version",
            "artifact_sha256",
            "canonical_byte_count",
        },
        "artifact binding",
    )
    if binding["kind"] != "canonical_digraph_placement_graph":
        raise DerivationVerificationError("artifact kind mismatch")
    if binding["schema_version"] != ARTIFACT_SCHEMA:
        raise DerivationVerificationError("bound artifact schema mismatch")
    if binding["artifact_sha256"] != artifact_hash:
        raise DerivationVerificationError("bound artifact hash mismatch")
    if binding["canonical_byte_count"] != len(artifact_bytes):
        raise DerivationVerificationError("bound artifact byte count mismatch")
    if (
        expected_artifact_sha256 is not None
        and artifact_hash != expected_artifact_sha256
    ):
        raise DerivationVerificationError("expected artifact hash mismatch")

    rows = certificate["states"]
    if not isinstance(rows, list) or not rows:
        raise DerivationVerificationError("state table must be nonempty")
    if rows != sorted(rows, key=lambda row: row.get("active_mask", -1)):
        raise DerivationVerificationError("state table is not in canonical order")

    row_by_mask: dict[int, dict[str, Any]] = {}
    state_fields = {
        "active_mask",
        "left_no_legal_move",
        "right_no_legal_move",
        "terminal",
        "left_moves",
        "right_moves",
        "left_option_game_sha256",
        "right_option_game_sha256",
        "literal_game_sha256",
        "literal_serialization",
    }
    for row in rows:
        if not isinstance(row, dict):
            raise DerivationVerificationError("state row must be an object")
        _exact_keys(row, state_fields, "state row")
        active = _require_plain_int(row["active_mask"], "active mask")
        if active in row_by_mask:
            raise DerivationVerificationError("duplicate active-mask state")
        if active < 0 or active & ~graph.active_mask:
            raise DerivationVerificationError("state mask is outside graph order")
        row_by_mask[active] = row

    reachable = _reachable_masks(graph)
    if set(row_by_mask) != reachable:
        raise DerivationVerificationError(
            "state table is not the exact reachable active-mask closure"
        )

    games: dict[int, Game] = {}
    move_fields = {
        "vertex",
        "deleted_active_mask",
        "destination_active_mask",
        "destination_game_sha256",
    }
    for active in sorted(reachable, key=lambda mask: (mask.bit_count(), mask)):
        row = row_by_mask[active]
        expected_games = _derive_games(graph, reachable)
        # Destination digests below are independently derived, not read from a
        # certificate row.  Recomputing the small bounded closure also keeps
        # the verification logic visibly separate from the builder's rows.
        expected_left = _move_rows(
            _legal_moves(graph, active, blue=True), expected_games
        )
        expected_right = _move_rows(
            _legal_moves(graph, active, blue=False), expected_games
        )
        for side in ("left_moves", "right_moves"):
            moves = row[side]
            if not isinstance(moves, list):
                raise DerivationVerificationError(f"{side} must be a list")
            for move in moves:
                if not isinstance(move, dict):
                    raise DerivationVerificationError("move row must be an object")
                _exact_keys(move, move_fields, "move row")
        if row["left_moves"] != expected_left:
            raise DerivationVerificationError("left legal-move list is not exact")
        if row["right_moves"] != expected_right:
            raise DerivationVerificationError("right legal-move list is not exact")

        left_moves = _legal_moves(graph, active, blue=True)
        right_moves = _legal_moves(graph, active, blue=False)
        if type(row["left_no_legal_move"]) is not bool:
            raise DerivationVerificationError("left terminal flag is not Boolean")
        if type(row["right_no_legal_move"]) is not bool:
            raise DerivationVerificationError("right terminal flag is not Boolean")
        if type(row["terminal"]) is not bool:
            raise DerivationVerificationError("terminal flag is not Boolean")
        if row["left_no_legal_move"] != (not left_moves):
            raise DerivationVerificationError("left terminal flag is false")
        if row["right_no_legal_move"] != (not right_moves):
            raise DerivationVerificationError("right terminal flag is false")
        if row["terminal"] != (not left_moves and not right_moves):
            raise DerivationVerificationError("terminal-state flag is false")

        left_options = sorted(
            {expected_games[destination] for _, _, destination in left_moves},
            key=serialize,
        )
        right_options = sorted(
            {expected_games[destination] for _, _, destination in right_moves},
            key=serialize,
        )
        game = Game.make(left_options, right_options)
        games[active] = game
        expected_left_digests = sorted(game_digest(option) for option in game.left)
        expected_right_digests = sorted(game_digest(option) for option in game.right)
        if row["left_option_game_sha256"] != expected_left_digests:
            raise DerivationVerificationError("left literal-option digest set is false")
        if row["right_option_game_sha256"] != expected_right_digests:
            raise DerivationVerificationError(
                "right literal-option digest set is false"
            )
        if row["literal_serialization"] != serialize(game):
            raise DerivationVerificationError("literal game serialization is false")
        if row["literal_game_sha256"] != game_digest(game):
            raise DerivationVerificationError("literal game digest is false")

    root = certificate["root"]
    if not isinstance(root, dict):
        raise DerivationVerificationError("root binding must be an object")
    _exact_keys(root, {"active_mask", "literal_game_sha256"}, "root binding")
    if root["active_mask"] != graph.active_mask:
        raise DerivationVerificationError("root active mask mismatch")
    root_game = games[graph.active_mask]
    root_digest = game_digest(root_game)
    if root["literal_game_sha256"] != root_digest:
        raise DerivationVerificationError("root literal-game digest mismatch")
    if (
        expected_root_game_sha256 is not None
        and root_digest != expected_root_game_sha256
    ):
        raise DerivationVerificationError("expected root-game hash mismatch")
    return root_game


def verify_derivation_certificate(
    certificate: Mapping[str, Any],
    *,
    artifact_bytes: bytes,
    expected_artifact_sha256: str | None = None,
    expected_root_game_sha256: str | None = None,
) -> tuple[bool, str]:
    """Strictly replay a derivation certificate without trusting its claims."""

    try:
        _replay_derivation(
            certificate,
            artifact_bytes=artifact_bytes,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_root_game_sha256=expected_root_game_sha256,
        )
    except (DerivationVerificationError, KeyError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "valid"


def game_from_verified_derivation(
    certificate: Mapping[str, Any], *, artifact_bytes: bytes
) -> Game:
    """Return the root game only after complete strict derivation replay."""

    return _replay_derivation(
        certificate,
        artifact_bytes=artifact_bytes,
        expected_artifact_sha256=None,
        expected_root_game_sha256=None,
    )


__all__ = [
    "ARTIFACT_SCHEMA",
    "DERIVATION_SCHEMA",
    "MAX_ORDER",
    "RULESET",
    "DerivationVerificationError",
    "build_derivation_certificate",
    "build_graph_artifact",
    "bytes_sha256",
    "canonical_artifact_bytes",
    "canonical_json_bytes",
    "content_addressed_relpath",
    "game_from_verified_derivation",
    "graph_from_artifact",
    "object_sha256",
    "parse_canonical_artifact_bytes",
    "validate_content_addressed_relpath",
    "verify_derivation_certificate",
]
