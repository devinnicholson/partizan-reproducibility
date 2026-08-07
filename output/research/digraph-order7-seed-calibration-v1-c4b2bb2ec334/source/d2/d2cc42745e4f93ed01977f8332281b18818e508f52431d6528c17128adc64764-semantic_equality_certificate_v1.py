#!/usr/bin/env python3
"""Build and replay the frozen finite short-game equality certificate v1.

The builder uses the Pilot A comparator to populate a proof DAG.  The verifier
does *not* call that comparator: it validates every Conway-order recurrence
locally from a closed game table and a closed comparison DAG.  The included
self-test is calibration only and is not paper evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from short_game_fiber_pilot import Game, game_digest, leq, serialize


CERTIFICATE_SCHEMA = "partizan.short_game_equality_certificate.v1"
SELF_TEST_SCHEMA = "partizan.short_game_equality_certificate_self_test.v1"
SEMANTICS = {
    "play_convention": "normal_play",
    "domain": "finite_loop_free_partizan_games",
    "option_semantics": "sets; order and duplicates removed",
}
HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rehash(certificate: dict[str, Any]) -> None:
    payload = copy.deepcopy(certificate)
    payload.pop("certificate_sha256", None)
    certificate["certificate_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()


def game_closure(roots: Iterable[Game]) -> set[Game]:
    pending = list(roots)
    seen: set[Game] = set()
    while pending:
        game = pending.pop()
        if game in seen:
            continue
        seen.add(game)
        pending.extend(game.left)
        pending.extend(game.right)
    return seen


def game_table(roots: Iterable[Game]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "sha256": game_digest(game),
                "serialization": serialize(game),
                "left_options": [game_digest(option) for option in game.left],
                "right_options": [game_digest(option) for option in game.right],
            }
            for game in game_closure(roots)
        ),
        key=lambda row: row["sha256"],
    )


def comparison_dependencies(left: Game, right: Game) -> list[dict[str, str]]:
    dependencies = [
        {
            "kind": "left_option_not_ge_right",
            "lhs_sha256": game_digest(right),
            "rhs_sha256": game_digest(option),
        }
        for option in left.left
    ]
    dependencies.extend(
        {
            "kind": "right_option_not_le_left",
            "lhs_sha256": game_digest(option),
            "rhs_sha256": game_digest(left),
        }
        for option in right.right
    )
    return sorted(
        dependencies,
        key=lambda row: (row["kind"], row["lhs_sha256"], row["rhs_sha256"]),
    )


def comparison_dag(roots: Iterable[tuple[Game, Game]]) -> list[dict[str, Any]]:
    pending = list(roots)
    seen: set[tuple[Game, Game]] = set()
    rows: list[dict[str, Any]] = []
    while pending:
        left, right = pending.pop()
        if (left, right) in seen:
            continue
        seen.add((left, right))
        dependencies = comparison_dependencies(left, right)
        pending.extend((right, option) for option in left.left)
        pending.extend((option, left) for option in right.right)
        rows.append(
            {
                "lhs_sha256": game_digest(left),
                "rhs_sha256": game_digest(right),
                "result": leq(left, right),
                "dependencies": dependencies,
            }
        )
    return sorted(rows, key=lambda row: (row["lhs_sha256"], row["rhs_sha256"]))


def artifact_binding(
    *, kind: str, schema_version: str, artifact_sha256: str, root: Game
) -> dict[str, str]:
    if not HEX_256.fullmatch(artifact_sha256):
        raise ValueError("artifact_sha256 must be lowercase SHA-256")
    return {
        "kind": kind,
        "schema_version": schema_version,
        "artifact_sha256": artifact_sha256,
        "root_game_sha256": game_digest(root),
    }


def build_certificate(
    candidate: Game,
    target: Game,
    *,
    candidate_binding: dict[str, str],
    target_binding: dict[str, str],
) -> dict[str, Any]:
    if candidate_binding["root_game_sha256"] != game_digest(candidate):
        raise ValueError("candidate binding has the wrong root game")
    if target_binding["root_game_sha256"] != game_digest(target):
        raise ValueError("target binding has the wrong root game")

    left_leq_right = leq(candidate, target)
    right_leq_left = leq(target, candidate)
    payload = {
        "schema_version": CERTIFICATE_SCHEMA,
        "relation": "normal_play_equality",
        "semantics": SEMANTICS,
        "bindings": {
            "candidate": candidate_binding,
            "target": target_binding,
        },
        "game_table": game_table((candidate, target)),
        "comparison_dag": comparison_dag(((candidate, target), (target, candidate))),
        "verdict": {
            "candidate_leq_target": left_leq_right,
            "target_leq_candidate": right_leq_left,
            "equal": left_leq_right and right_leq_left,
        },
    }
    certificate = copy.deepcopy(payload)
    certificate["certificate_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return certificate


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{context} has unexpected or missing fields")


def verify_certificate(
    certificate: dict[str, Any],
    *,
    expected_candidate_artifact_sha256: str | None = None,
    expected_target_artifact_sha256: str | None = None,
    expected_candidate_root_game_sha256: str | None = None,
    expected_target_root_game_sha256: str | None = None,
) -> tuple[bool, str]:
    """Replay a certificate without invoking ``leq`` or any canonicalizer."""

    try:
        _exact_keys(
            certificate,
            {
                "schema_version",
                "relation",
                "semantics",
                "bindings",
                "game_table",
                "comparison_dag",
                "verdict",
                "certificate_sha256",
            },
            "certificate",
        )
        supplied_hash = certificate["certificate_sha256"]
        if not isinstance(supplied_hash, str) or not HEX_256.fullmatch(supplied_hash):
            raise ValueError("certificate hash is malformed")
        payload = copy.deepcopy(certificate)
        payload.pop("certificate_sha256")
        calculated_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if supplied_hash != calculated_hash:
            raise ValueError("certificate hash mismatch")
        if certificate["schema_version"] != CERTIFICATE_SCHEMA:
            raise ValueError("unsupported schema")
        if certificate["relation"] != "normal_play_equality":
            raise ValueError("unsupported relation")
        if certificate["semantics"] != SEMANTICS:
            raise ValueError("semantics mismatch")

        bindings = certificate["bindings"]
        _exact_keys(bindings, {"candidate", "target"}, "bindings")
        for name in ("candidate", "target"):
            binding = bindings[name]
            _exact_keys(
                binding,
                {"kind", "schema_version", "artifact_sha256", "root_game_sha256"},
                f"{name} binding",
            )
            if not all(isinstance(value, str) for value in binding.values()):
                raise ValueError(f"{name} binding contains a non-string")
            if not HEX_256.fullmatch(binding["artifact_sha256"]):
                raise ValueError(f"{name} artifact hash is malformed")
            if not HEX_256.fullmatch(binding["root_game_sha256"]):
                raise ValueError(f"{name} root hash is malformed")
        if (
            expected_candidate_artifact_sha256 is not None
            and bindings["candidate"]["artifact_sha256"]
            != expected_candidate_artifact_sha256
        ):
            raise ValueError("candidate artifact binding mismatch")
        if (
            expected_target_artifact_sha256 is not None
            and bindings["target"]["artifact_sha256"] != expected_target_artifact_sha256
        ):
            raise ValueError("target artifact binding mismatch")
        if (
            expected_candidate_root_game_sha256 is not None
            and bindings["candidate"]["root_game_sha256"]
            != expected_candidate_root_game_sha256
        ):
            raise ValueError("candidate root-game binding mismatch")
        if (
            expected_target_root_game_sha256 is not None
            and bindings["target"]["root_game_sha256"]
            != expected_target_root_game_sha256
        ):
            raise ValueError("target root-game binding mismatch")

        rows = certificate["game_table"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("game table must be a nonempty list")
        if rows != sorted(rows, key=lambda row: row.get("sha256", "")):
            raise ValueError("game table is not in canonical order")
        games: dict[str, dict[str, Any]] = {}
        for row in rows:
            _exact_keys(
                row,
                {"sha256", "serialization", "left_options", "right_options"},
                "game row",
            )
            digest = row["sha256"]
            if not isinstance(digest, str) or not HEX_256.fullmatch(digest):
                raise ValueError("game digest is malformed")
            if digest in games:
                raise ValueError("duplicate game row")
            if sha256_text(row["serialization"]) != digest:
                raise ValueError("game digest does not bind its serialization")
            for side in ("left_options", "right_options"):
                options = row[side]
                if not isinstance(options, list) or len(options) != len(set(options)):
                    raise ValueError("options must be a duplicate-free list")
                if any(not isinstance(option, str) for option in options):
                    raise ValueError("option digest is not a string")
            games[digest] = row

        birthdays: dict[str, int] = {}
        active: set[str] = set()

        def validate_game(digest: str) -> int:
            if digest in birthdays:
                return birthdays[digest]
            if digest in active:
                raise ValueError("game table contains a cycle")
            if digest not in games:
                raise ValueError("game table references a missing option")
            active.add(digest)
            row = games[digest]
            options = row["left_options"] + row["right_options"]
            option_birthdays = [validate_game(option) for option in options]
            left_serializations = [
                games[option]["serialization"] for option in row["left_options"]
            ]
            right_serializations = [
                games[option]["serialization"] for option in row["right_options"]
            ]
            if left_serializations != sorted(left_serializations):
                raise ValueError("left options are not in canonical order")
            if right_serializations != sorted(right_serializations):
                raise ValueError("right options are not in canonical order")
            reconstructed = (
                "{"
                + ",".join(left_serializations)
                + "|"
                + ",".join(right_serializations)
                + "}"
            )
            if reconstructed != row["serialization"]:
                raise ValueError("game serialization does not match its options")
            active.remove(digest)
            birthdays[digest] = 0 if not options else 1 + max(option_birthdays)
            return birthdays[digest]

        for digest in games:
            validate_game(digest)

        candidate_root = bindings["candidate"]["root_game_sha256"]
        target_root = bindings["target"]["root_game_sha256"]
        if candidate_root not in games or target_root not in games:
            raise ValueError("a bound root is absent from the game table")

        dag_rows = certificate["comparison_dag"]
        if not isinstance(dag_rows, list) or not dag_rows:
            raise ValueError("comparison DAG must be a nonempty list")
        if dag_rows != sorted(
            dag_rows,
            key=lambda row: (row.get("lhs_sha256", ""), row.get("rhs_sha256", "")),
        ):
            raise ValueError("comparison DAG is not in canonical order")
        comparisons: dict[tuple[str, str], dict[str, Any]] = {}
        for row in dag_rows:
            _exact_keys(
                row,
                {"lhs_sha256", "rhs_sha256", "result", "dependencies"},
                "comparison row",
            )
            pair = (row["lhs_sha256"], row["rhs_sha256"])
            if pair in comparisons:
                raise ValueError("duplicate comparison row")
            if pair[0] not in games or pair[1] not in games:
                raise ValueError("comparison references a missing game")
            if type(row["result"]) is not bool:
                raise ValueError("comparison result is not Boolean")
            comparisons[pair] = row

        reachable: set[tuple[str, str]] = set()
        pending = [(candidate_root, target_root), (target_root, candidate_root)]
        while pending:
            pair = pending.pop()
            if pair in reachable:
                continue
            if pair not in comparisons:
                raise ValueError("comparison DAG is not closed")
            reachable.add(pair)
            lhs, rhs = pair
            expected_dependencies = [
                {
                    "kind": "left_option_not_ge_right",
                    "lhs_sha256": rhs,
                    "rhs_sha256": option,
                }
                for option in games[lhs]["left_options"]
            ]
            expected_dependencies.extend(
                {
                    "kind": "right_option_not_le_left",
                    "lhs_sha256": option,
                    "rhs_sha256": lhs,
                }
                for option in games[rhs]["right_options"]
            )
            expected_dependencies.sort(
                key=lambda row: (row["kind"], row["lhs_sha256"], row["rhs_sha256"])
            )
            if comparisons[pair]["dependencies"] != expected_dependencies:
                raise ValueError("comparison dependency list is not exact")
            child_pairs = [
                (dependency["lhs_sha256"], dependency["rhs_sha256"])
                for dependency in expected_dependencies
            ]
            for child in child_pairs:
                if child not in comparisons:
                    raise ValueError("comparison dependency row is missing")
                if (
                    birthdays[child[0]] + birthdays[child[1]]
                    >= birthdays[lhs] + birthdays[rhs]
                ):
                    raise ValueError("comparison dependency is not well-founded")
            expected_result = not any(
                comparisons[child]["result"] for child in child_pairs
            )
            if comparisons[pair]["result"] != expected_result:
                raise ValueError("comparison recurrence is false")
            pending.extend(child_pairs)
        if reachable != set(comparisons):
            raise ValueError("comparison DAG contains unreachable rows")

        verdict = certificate["verdict"]
        _exact_keys(
            verdict,
            {"candidate_leq_target", "target_leq_candidate", "equal"},
            "verdict",
        )
        if any(type(value) is not bool for value in verdict.values()):
            raise ValueError("verdict contains a non-Boolean")
        candidate_leq_target = comparisons[(candidate_root, target_root)]["result"]
        target_leq_candidate = comparisons[(target_root, candidate_root)]["result"]
        if verdict["candidate_leq_target"] != candidate_leq_target:
            raise ValueError("candidate <= target verdict mismatch")
        if verdict["target_leq_candidate"] != target_leq_candidate:
            raise ValueError("target <= candidate verdict mismatch")
        if verdict["equal"] != (candidate_leq_target and target_leq_candidate):
            raise ValueError("equality verdict mismatch")
        if not verdict["equal"]:
            raise ValueError("certificate does not prove equality")
    except (KeyError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "valid"


def mutation_results(
    certificate: dict[str, Any], candidate_hash: str, target_hash: str
) -> dict[str, dict[str, Any]]:
    mutations: dict[str, dict[str, Any]] = {}

    mutated = copy.deepcopy(certificate)
    mutated["certificate_sha256"] = "0" * 64
    mutations["certificate_hash"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["bindings"]["candidate"]["artifact_sha256"] = "1" * 64
    rehash(mutated)
    mutations["candidate_artifact_binding"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["bindings"]["target"]["root_game_sha256"] = "2" * 64
    rehash(mutated)
    mutations["target_root_game_binding"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["comparison_dag"][0]["result"] = not mutated["comparison_dag"][0]["result"]
    rehash(mutated)
    mutations["comparison_result"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["comparison_dag"].pop()
    rehash(mutated)
    mutations["missing_comparison_row"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["game_table"][0]["left_options"].append(
        mutated["game_table"][0]["left_options"][0]
        if mutated["game_table"][0]["left_options"]
        else mutated["game_table"][0]["sha256"]
    )
    rehash(mutated)
    mutations["game_option_table"] = mutated

    return {
        name: {
            "rejected": not verify_certificate(
                candidate,
                expected_candidate_artifact_sha256=candidate_hash,
                expected_target_artifact_sha256=target_hash,
                expected_candidate_root_game_sha256=certificate["bindings"][
                    "candidate"
                ]["root_game_sha256"],
                expected_target_root_game_sha256=certificate["bindings"]["target"][
                    "root_game_sha256"
                ],
            )[0],
            "reason": verify_certificate(
                candidate,
                expected_candidate_artifact_sha256=candidate_hash,
                expected_target_artifact_sha256=target_hash,
                expected_candidate_root_game_sha256=certificate["bindings"][
                    "candidate"
                ]["root_game_sha256"],
                expected_target_root_game_sha256=certificate["bindings"]["target"][
                    "root_game_sha256"
                ],
            )[1],
        }
        for name, candidate in mutations.items()
    }


def self_test() -> tuple[dict[str, Any], dict[str, Any]]:
    zero = Game.make()
    one = Game.make((zero,), ())
    star = Game.make((zero,), (zero,))
    half = Game.make((zero,), (one,))
    elkies_half = Game.make((zero, star), (one,))
    candidate_hash = sha256_text("abstract-game:" + serialize(elkies_half))
    target_hash = sha256_text("abstract-game:" + serialize(half))
    certificate = build_certificate(
        elkies_half,
        half,
        candidate_binding=artifact_binding(
            kind="abstract_short_game",
            schema_version="partizan.abstract_short_game.v1",
            artifact_sha256=candidate_hash,
            root=elkies_half,
        ),
        target_binding=artifact_binding(
            kind="abstract_short_game",
            schema_version="partizan.abstract_short_game.v1",
            artifact_sha256=target_hash,
            root=half,
        ),
    )
    valid, reason = verify_certificate(
        certificate,
        expected_candidate_artifact_sha256=candidate_hash,
        expected_target_artifact_sha256=target_hash,
        expected_candidate_root_game_sha256=game_digest(elkies_half),
        expected_target_root_game_sha256=game_digest(half),
    )
    unequal_target_hash = sha256_text("abstract-game:" + serialize(zero))
    unequal_certificate = build_certificate(
        elkies_half,
        zero,
        candidate_binding=artifact_binding(
            kind="abstract_short_game",
            schema_version="partizan.abstract_short_game.v1",
            artifact_sha256=candidate_hash,
            root=elkies_half,
        ),
        target_binding=artifact_binding(
            kind="abstract_short_game",
            schema_version="partizan.abstract_short_game.v1",
            artifact_sha256=unequal_target_hash,
            root=zero,
        ),
    )
    unequal_valid, unequal_reason = verify_certificate(
        unequal_certificate,
        expected_candidate_artifact_sha256=candidate_hash,
        expected_target_artifact_sha256=unequal_target_hash,
        expected_candidate_root_game_sha256=game_digest(elkies_half),
        expected_target_root_game_sha256=game_digest(zero),
    )
    mutations = mutation_results(certificate, candidate_hash, target_hash)
    assertions = {
        "centerpiece_verdict_is_equal": certificate["verdict"]["equal"] is True,
        "certificate_replays_without_comparator": valid,
        "unequal_pair_is_not_accepted_as_equality_certificate": (
            not unequal_valid
            and unequal_reason == "certificate does not prove equality"
        ),
        "all_negative_mutations_rejected": all(
            result["rejected"] for result in mutations.values()
        ),
    }
    report = {
        "schema_version": SELF_TEST_SCHEMA,
        "status": "calibration_only",
        "certificate_schema": CERTIFICATE_SCHEMA,
        "certificate_sha256": certificate["certificate_sha256"],
        "game_table_row_count": len(certificate["game_table"]),
        "comparison_dag_row_count": len(certificate["comparison_dag"]),
        "replay": {"valid": valid, "reason": reason},
        "unequal_control": {"valid": unequal_valid, "reason": unequal_reason},
        "negative_mutations": mutations,
        "assertions": assertions,
        "all_assertions_pass": all(assertions.values()),
        "scope_warning": (
            "This certificate proves equality of two supplied finite game trees. "
            "A separate ruleset-specific derivation certificate is required to "
            "prove that a board or graph exports the claimed candidate tree."
        ),
    }
    return certificate, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the self-test report")
    parser.add_argument("--certificate-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    certificate, report = self_test()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    if args.certificate_output:
        args.certificate_output.write_text(
            json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(rendered, end="")
    return 0 if report["all_assertions_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
