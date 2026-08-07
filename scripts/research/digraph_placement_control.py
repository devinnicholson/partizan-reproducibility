#!/usr/bin/env python3
"""Replay the published Digraph Placement certificate corpus.

The source artifact for Clow, Davies, and McKay (arXiv:2505.06206) contains
one ``digraph6`` graph and one asserted canonical game form for each of the
1,474 values born by day 3.  This calibration script deliberately does not
call the authors' bundled Rust/gemau implementation.  It decodes each graph,
constructs its complete finite normal-play game tree, parses the asserted
form, and compares the two with the exact short-game relation used by Pilot A.

The script expects paths to the two ancillary files.  Obtain them from the
paper's arXiv source artifact; do not silently substitute a scraped corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Iterable

from short_game_fiber_pilot import Game, birthday, equal, serialize


REPORT_SCHEMA = "partizan.digraph_placement_control.v0"
EXPECTED_CORPUS_SIZE = 1_474
EXPECTED_DAY_TWO_VALUE_COUNT = 22


@dataclass(frozen=True)
class DigraphPlacement:
    """A two-coloured directed graph using the paper's loop convention."""

    blue_mask: int
    edges: tuple[int, ...]

    @property
    def order(self) -> int:
        return len(self.edges)

    @property
    def active_mask(self) -> int:
        return (1 << self.order) - 1

    def is_blue(self, vertex: int) -> bool:
        return bool(self.blue_mask & (1 << vertex))

    def move_mask(self, vertex: int) -> int:
        """Vertices deleted by playing ``vertex``: it and its out-neighbours."""

        return (1 << vertex) | self.edges[vertex]


def _decode_six_bit_bytes(payload: str) -> list[int]:
    values = []
    for character in payload:
        value = ord(character) - 63
        if not 0 <= value <= 63:
            raise ValueError("invalid digraph6 byte")
        values.append(value)
    return values


def parse_digraph6(encoded: str) -> DigraphPlacement:
    """Decode the restricted digraph6 form used by the published corpus.

    A diagonal entry denotes a blue vertex and is not retained as a game arc;
    an absent diagonal denotes red.  Off-diagonal entries are directed arcs.
    """

    encoded = encoded.strip()
    header = ">>digraph6<<"
    if encoded.startswith(header):
        encoded = encoded[len(header) :]
    if not encoded.startswith("&"):
        raise ValueError("digraph6 record must start with '&'")

    values = _decode_six_bit_bytes(encoded[1:])
    if not values:
        return DigraphPlacement(blue_mask=0, edges=())

    first = values[0]
    if first <= 62:
        order = first
        matrix_values = values[1:]
    elif first == 63 and len(values) >= 4 and values[1] != 63:
        order = (values[1] << 12) | (values[2] << 6) | values[3]
        matrix_values = values[4:]
    elif first == 63 and len(values) >= 8 and values[1] == 63:
        order = 0
        for value in values[2:8]:
            order = (order << 6) | value
        matrix_values = values[8:]
    else:
        raise ValueError("invalid digraph6 vertex count")

    matrix_bits: list[bool] = []
    for value in matrix_values:
        matrix_bits.extend(bool(value & (1 << bit)) for bit in range(5, -1, -1))
    required = order * order
    if len(matrix_bits) < required:
        raise ValueError("truncated digraph6 adjacency matrix")
    matrix_bits = matrix_bits[:required]

    blue_mask = 0
    edges = [0] * order
    for source in range(order):
        for target in range(order):
            if not matrix_bits[source * order + target]:
                continue
            if source == target:
                blue_mask |= 1 << source
            else:
                edges[source] |= 1 << target

    return DigraphPlacement(blue_mask=blue_mask, edges=tuple(edges))


def game_from_digraph(graph: DigraphPlacement) -> Game:
    """Construct the complete finite game tree induced by ``graph``."""

    @cache
    def visit(active: int) -> Game:
        left: list[Game] = []
        right: list[Game] = []
        for vertex in range(graph.order):
            if not active & (1 << vertex):
                continue
            destination = visit(active & ~graph.move_mask(vertex))
            (left if graph.is_blue(vertex) else right).append(destination)
        return Game.make(left, right)

    return visit(graph.active_mask)


def integer_game(value: int) -> Game:
    if value == 0:
        return Game()
    if value > 0:
        return Game.make(left=(integer_game(value - 1),))
    return Game.make(right=(integer_game(value + 1),))


def nimber_game(value: int) -> Game:
    options = tuple(nimber_game(option) for option in range(value))
    return Game.make(options, options)


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(text):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def parse_game_form(text: str) -> Game:
    """Parse the integer, nimber, and recursive forms in ``games.txt``."""

    text = "".join(text.split())
    if not text:
        raise ValueError("empty game form")
    if text.lstrip("-").isdigit():
        return integer_game(int(text))
    if text.startswith("*") and text[1:].isdigit():
        return nimber_game(int(text[1:]))
    if text == "*":
        return nimber_game(1)
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError(f"unsupported game form: {text}")

    body = text[1:-1]
    sides = _split_top_level(body, "|")
    if len(sides) != 2:
        raise ValueError(f"expected one top-level bar: {text}")

    def parse_side(side: str) -> Iterable[Game]:
        if not side:
            return ()
        return tuple(parse_game_form(term) for term in _split_top_level(side, ","))

    return Game.make(parse_side(sides[0]), parse_side(sides[1]))


def canonical_coloured_digraph(graph: DigraphPlacement) -> str:
    """Return a brute-force canonical code for small coloured digraphs.

    Pilot G applies this only to the published day-two slice (order at most
    four), so exhaustive colour-preserving relabelling is both exact and cheap.
    """

    blue = [vertex for vertex in range(graph.order) if graph.is_blue(vertex)]
    red = [vertex for vertex in range(graph.order) if not graph.is_blue(vertex)]
    candidates: list[str] = []
    for blue_order in itertools.permutations(blue):
        for red_order in itertools.permutations(red):
            order = blue_order + red_order
            colours = "B" * len(blue) + "R" * len(red)
            adjacency = "".join(
                "1" if graph.edges[source] & (1 << target) else "0"
                for source in order
                for target in order
            )
            candidates.append(f"{colours}:{adjacency}")
    return min(candidates)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replay(graphs_path: Path, games_path: Path, limit: int | None) -> dict[str, object]:
    graph_lines = graphs_path.read_text(encoding="utf-8").splitlines()
    game_lines = games_path.read_text(encoding="utf-8").splitlines()
    if len(graph_lines) != len(game_lines):
        raise ValueError("graph and game corpus lengths differ")
    if len(graph_lines) != EXPECTED_CORPUS_SIZE:
        raise ValueError(f"expected {EXPECTED_CORPUS_SIZE} records")

    records = list(zip(graph_lines, game_lines, strict=True))
    if limit is not None:
        records = records[:limit]

    mismatches: list[dict[str, object]] = []
    day_two_codes: list[str] = []
    order_histogram: dict[int, int] = {}
    selected_controls: dict[str, dict[str, object]] = {}
    control_forms = {"-2", "-1", "0", "*", "1", "2", "{0|1}"}

    for index, (graph_text, game_text) in enumerate(records):
        graph = parse_digraph6(graph_text)
        observed = game_from_digraph(graph)
        asserted = parse_game_form(game_text)
        matches = equal(observed, asserted)
        order_histogram[graph.order] = order_histogram.get(graph.order, 0) + 1

        if not matches:
            mismatches.append(
                {
                    "index": index,
                    "asserted_form": game_text,
                    "observed_literal_form": serialize(observed),
                }
            )

        if birthday(asserted) <= 2:
            day_two_codes.append(canonical_coloured_digraph(graph))

        if game_text in control_forms:
            selected_controls[game_text] = {
                "index": index,
                "order": graph.order,
                "matches": matches,
                "graph_sha256": hashlib.sha256(graph_text.encode("ascii")).hexdigest(),
            }

    full_run = limit is None
    assertions = {
        "rust_decoder_fixture_matches": parse_digraph6("&DI?AO?").order == 5
        and sum(mask.bit_count() for mask in parse_digraph6("&DI?AO?").edges) == 4,
        "all_replayed_values_match": not mismatches,
        "published_corpus_has_1474_pairs": len(graph_lines) == EXPECTED_CORPUS_SIZE,
    }
    if full_run:
        assertions.update(
            {
                "day_two_slice_has_22_values": len(day_two_codes)
                == EXPECTED_DAY_TWO_VALUE_COUNT,
                "day_two_graphs_are_quotient_unique": len(set(day_two_codes))
                == EXPECTED_DAY_TWO_VALUE_COUNT,
                "selected_controls_present": set(selected_controls) == control_forms,
            }
        )

    return {
        "schema_version": REPORT_SCHEMA,
        "status": "calibration_only",
        "source": {
            "paper": "Clow, Davies, and McKay, Constructing All Birthday 3 Games as Digraphs",
            "arxiv": "https://arxiv.org/abs/2505.06206",
            "graphs_sha256": file_sha256(graphs_path),
            "games_sha256": file_sha256(games_path),
            "authors_rust_checker_used": False,
        },
        "records_replayed": len(records),
        "full_corpus_run": full_run,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "order_histogram": {
            str(key): value for key, value in sorted(order_histogram.items())
        },
        "day_two": {
            "value_count": len(day_two_codes) if full_run else None,
            "coloured_isomorphism_class_count": (
                len(set(day_two_codes)) if full_run else None
            ),
        },
        "selected_controls": selected_controls,
        "assertions": assertions,
        "all_assertions_pass": all(assertions.values()),
        "independent_cgsuite_status": "pending",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphs", type=Path, required=True)
    parser.add_argument("--games", type=Path, required=True)
    parser.add_argument(
        "--limit",
        type=int,
        help="replay a prefix for debugging; full-corpus invariants are then omitted",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = replay(args.graphs, args.games, args.limit)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not report["all_assertions_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
