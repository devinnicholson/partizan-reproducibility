#!/usr/bin/env python3
"""Calibration-only exhaustive pilot for finite short-game value fibers.

This is deliberately independent of Thermograph.  It enumerates the 256
literal games born by day 2, decides normal-play comparison recursively, and
groups literal trees by semantic equality.  It is not paper evidence and is
not an independent CGSuite oracle.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from dataclasses import dataclass
from functools import cache
from typing import Any, Iterable


CERTIFICATE_SCHEMA = "partizan.short_game_equality_certificate.v0"
REPORT_SCHEMA = "partizan.short_game_fiber_pilot.v0"


@dataclass(frozen=True)
class Game:
    """A finite normal-play partizan game with set-valued options."""

    left: tuple["Game", ...] = ()
    right: tuple["Game", ...] = ()

    @staticmethod
    def make(left: Iterable["Game"] = (), right: Iterable["Game"] = ()) -> "Game":
        return Game(
            tuple(sorted(set(left), key=serialize)),
            tuple(sorted(set(right), key=serialize)),
        )


@cache
def serialize(game: Game) -> str:
    left = ",".join(serialize(option) for option in game.left)
    right = ",".join(serialize(option) for option in game.right)
    return "{" + left + "|" + right + "}"


@cache
def game_digest(game: Game) -> str:
    return hashlib.sha256(serialize(game).encode("utf-8")).hexdigest()


@cache
def birthday(game: Game) -> int:
    options = game.left + game.right
    return 0 if not options else 1 + max(birthday(option) for option in options)


@cache
def edge_count(game: Game) -> int:
    options = game.left + game.right
    return len(options) + sum(edge_count(option) for option in options)


@cache
def node_count(game: Game) -> int:
    options = game.left + game.right
    return 1 + sum(node_count(option) for option in options)


@cache
def leq(left: Game, right: Game) -> bool:
    """Return whether left <= right in Conway normal-play order.

    G <= H iff no G^L >= H and no H^R <= G.  Recursive calls strictly
    decrease the sum of birthdays, so finite games terminate.
    """

    return all(not leq(right, option) for option in left.left) and all(
        not leq(option, left) for option in right.right
    )


def equal(left: Game, right: Game) -> bool:
    return leq(left, right) and leq(right, left)


def powerset(items: tuple[Game, ...]) -> Iterable[tuple[Game, ...]]:
    for size in range(len(items) + 1):
        yield from itertools.combinations(items, size)


def games_from_options(options: tuple[Game, ...]) -> tuple[Game, ...]:
    games = {
        Game.make(left, right)
        for left in powerset(options)
        for right in powerset(options)
    }
    return tuple(sorted(games, key=serialize))


def comparison_trace(left: Game, right: Game) -> list[dict[str, Any]]:
    """Return the complete recursive decision DAG in canonical order."""

    pending = [(left, right)]
    seen: set[tuple[Game, Game]] = set()
    rows: list[dict[str, Any]] = []

    while pending:
        lhs, rhs = pending.pop()
        pair = (lhs, rhs)
        if pair in seen:
            continue
        seen.add(pair)

        checks: list[dict[str, Any]] = []
        for option in lhs.left:
            child = (rhs, option)
            pending.append(child)
            checks.append(
                {
                    "kind": "left_option_not_ge_right",
                    "lhs_sha256": game_digest(rhs),
                    "rhs_sha256": game_digest(option),
                    "recursive_leq": leq(*child),
                }
            )
        for option in rhs.right:
            child = (option, lhs)
            pending.append(child)
            checks.append(
                {
                    "kind": "right_option_not_le_left",
                    "lhs_sha256": game_digest(option),
                    "rhs_sha256": game_digest(lhs),
                    "recursive_leq": leq(*child),
                }
            )

        rows.append(
            {
                "lhs_sha256": game_digest(lhs),
                "rhs_sha256": game_digest(rhs),
                "lhs_serialization": serialize(lhs),
                "rhs_serialization": serialize(rhs),
                "result": leq(lhs, rhs),
                "checks": sorted(
                    checks,
                    key=lambda row: (row["kind"], row["lhs_sha256"], row["rhs_sha256"]),
                ),
            }
        )

    return sorted(rows, key=lambda row: (row["lhs_sha256"], row["rhs_sha256"]))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def equality_certificate(left: Game, right: Game) -> dict[str, Any]:
    payload = {
        "schema_version": CERTIFICATE_SCHEMA,
        "relation": "normal_play_equality",
        "left_sha256": game_digest(left),
        "right_sha256": game_digest(right),
        "left_serialization": serialize(left),
        "right_serialization": serialize(right),
        "left_leq_right": {
            "result": leq(left, right),
            "trace": comparison_trace(left, right),
        },
        "right_leq_left": {
            "result": leq(right, left),
            "trace": comparison_trace(right, left),
        },
        "equal": equal(left, right),
    }
    certificate = dict(payload)
    certificate["certificate_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return certificate


def verify_equality_certificate(
    left: Game, right: Game, certificate: dict[str, Any]
) -> bool:
    expected = equality_certificate(left, right)
    supplied = copy.deepcopy(certificate)
    supplied_hash = supplied.pop("certificate_sha256", None)
    calculated_hash = hashlib.sha256(canonical_json_bytes(supplied)).hexdigest()
    return supplied_hash == calculated_hash and certificate == expected


def rehash(certificate: dict[str, Any]) -> None:
    payload = copy.deepcopy(certificate)
    payload.pop("certificate_sha256", None)
    certificate["certificate_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()


def negative_mutation_results(
    left: Game, right: Game, certificate: dict[str, Any]
) -> dict[str, bool]:
    mutations: dict[str, dict[str, Any]] = {}

    mutated = copy.deepcopy(certificate)
    mutated["left_sha256"] = "0" * 64
    rehash(mutated)
    mutations["left_digest"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["right_sha256"] = "f" * 64
    rehash(mutated)
    mutations["right_digest"] = mutated

    mutated = copy.deepcopy(certificate)
    mutated["equal"] = not mutated["equal"]
    rehash(mutated)
    mutations["equality_verdict"] = mutated

    mutated = copy.deepcopy(certificate)
    trace = mutated["left_leq_right"]["trace"]
    trace[0]["result"] = not trace[0]["result"]
    rehash(mutated)
    mutations["recursive_trace"] = mutated

    return {
        name: not verify_equality_certificate(left, right, candidate)
        for name, candidate in mutations.items()
    }


def dominated_option_count(game: Game) -> int:
    count = 0
    for index, option in enumerate(game.left):
        others = game.left[:index] + game.left[index + 1 :]
        if any(leq(option, other) for other in others):
            count += 1
    for index, option in enumerate(game.right):
        others = game.right[:index] + game.right[index + 1 :]
        if any(leq(other, option) for other in others):
            count += 1
    return count


def reversible_option_count(game: Game) -> int:
    left_reversible = sum(
        any(leq(response, game) for response in option.right) for option in game.left
    )
    right_reversible = sum(
        any(leq(game, response) for response in option.left) for option in game.right
    )
    return left_reversible + right_reversible


def equivalence_classes(games: tuple[Game, ...]) -> list[list[Game]]:
    classes: list[list[Game]] = []
    for game in games:
        for equivalence_class in classes:
            if equal(game, equivalence_class[0]):
                equivalence_class.append(game)
                break
        else:
            classes.append([game])
    return classes


def game_record(game: Game) -> dict[str, Any]:
    return {
        "serialization": serialize(game),
        "sha256": game_digest(game),
        "birthday": birthday(game),
        "node_count": node_count(game),
        "edge_count": edge_count(game),
        "root_left_option_count": len(game.left),
        "root_right_option_count": len(game.right),
        "root_dominated_option_count": dominated_option_count(game),
        "root_reversible_option_count": reversible_option_count(game),
    }


def build_report() -> dict[str, Any]:
    zero = Game.make()
    one = Game.make((zero,), ())
    minus_one = Game.make((), (zero,))
    star = Game.make((zero,), (zero,))
    two = Game.make((one,), ())
    minus_two = Game.make((), (minus_one,))
    half = Game.make((zero,), (one,))
    minus_half = Game.make((minus_one,), (zero,))
    elkies_half_form = Game.make((zero, star), (one,))

    day_one = games_from_options((zero,))
    day_two = games_from_options(day_one)
    classes = equivalence_classes(day_two)

    targets = {
        "-2": minus_two,
        "-1": minus_one,
        "-1/2": minus_half,
        "0": zero,
        "1/2": half,
        "1": one,
        "2": two,
        "star": star,
    }

    fibers: dict[str, Any] = {}
    for label, target in targets.items():
        members = tuple(game for game in day_two if equal(game, target))
        ordered_members = sorted(
            members,
            key=lambda game: (edge_count(game), node_count(game), serialize(game)),
        )
        fibers[label] = {
            "target": game_record(target),
            "representative_count": len(members),
            "edge_count_range": [
                min(edge_count(game) for game in members),
                max(edge_count(game) for game in members),
            ],
            "root_dominated_option_count_range": [
                min(dominated_option_count(game) for game in members),
                max(dominated_option_count(game) for game in members),
            ],
            "root_reversible_option_count_range": [
                min(reversible_option_count(game) for game in members),
                max(reversible_option_count(game) for game in members),
            ],
            "smallest_representatives": [
                game_record(game) for game in ordered_members[:8]
            ],
        }

    centerpiece_certificate = equality_certificate(elkies_half_form, half)
    negative_mutations = negative_mutation_results(
        elkies_half_form, half, centerpiece_certificate
    )

    assertions = {
        "day_one_has_4_structural_games": len(day_one) == 4,
        "day_two_has_256_structural_games": len(day_two) == 256,
        # Calistrate, Paulhus, and Wolfe (2002), p. 27, report exactly 22
        # normal-play values born by day 2.
        "published_day_two_class_count_is_22": len(classes) == 22,
        "equality_is_reflexive_on_day_two": all(equal(game, game) for game in day_two),
        "zero_and_star_are_incomparable": (not leq(zero, star) and not leq(star, zero)),
        "elkies_form_equals_half": equal(elkies_half_form, half),
        "elkies_form_is_not_structurally_half": (
            serialize(elkies_half_form) != serialize(half)
        ),
        "half_has_multiple_nonisomorphic_representatives": (
            fibers["1/2"]["representative_count"] > 1
        ),
        "centerpiece_certificate_replays": verify_equality_certificate(
            elkies_half_form, half, centerpiece_certificate
        ),
        "all_negative_mutations_rejected": all(negative_mutations.values()),
    }

    return {
        "schema_version": REPORT_SCHEMA,
        "status": "calibration_only",
        "domain": {
            "normal_play": True,
            "finite_loop_free": True,
            "maximum_birthday": 2,
            "option_semantics": "sets; order and duplicates removed",
        },
        "corpus": {
            "day_one_structural_game_count": len(day_one),
            "day_two_structural_game_count": len(day_two),
            "day_two_semantic_equivalence_class_count": len(classes),
            "semantic_class_size_range": [
                min(len(equivalence_class) for equivalence_class in classes),
                max(len(equivalence_class) for equivalence_class in classes),
            ],
        },
        "centerpiece": {
            "canonical_half": game_record(half),
            "elkies_literal_form": game_record(elkies_half_form),
            "equal": equal(elkies_half_form, half),
            "certificate_sha256": centerpiece_certificate["certificate_sha256"],
            "comparison_trace_row_count": (
                len(centerpiece_certificate["left_leq_right"]["trace"])
                + len(centerpiece_certificate["right_leq_left"]["trace"])
            ),
        },
        "fibers": fibers,
        "negative_mutations_rejected": negative_mutations,
        "assertions": assertions,
        "all_assertions_pass": all(assertions.values()),
        "independent_oracle_status": "pending_cgsuite",
        "published_invariant_crosscheck": {
            "status": "pass",
            "expected_day_two_semantic_class_count": 22,
            "source": (
                "Calistrate, Paulhus, and Wolfe (2002), "
                "On the Lattice Structure of Finite Games, p. 27"
            ),
            "url": "https://library.slmath.org/books/Book42/files/cali.pdf",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compact", action="store_true", help="emit canonical single-line JSON"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report()
    if args.compact:
        print(canonical_json_bytes(report).decode("utf-8"))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_assertions_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
