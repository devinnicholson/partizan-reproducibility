#!/usr/bin/env python3
"""Exact bounded Domineering semantics for the fixed-value scope study.

Left places vertical dominoes and Right places horizontal dominoes.  A
position is a finite set of available cells inside a rectangular frame.  The
module constructs the complete finite normal-play game and delegates Conway
comparison to the repository's independent short-game oracle.

The frame is part of the literal representation.  ``geometric_quotient``
removes empty margins and quotients translations, rotations, and reflections;
mathematical equality remains the exact normal-play relation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from typing import Iterable

from short_game_fiber_pilot import Game, equal, game_digest, serialize


MAX_CELLS = 20


@dataclass(frozen=True, slots=True)
class DomineeringPosition:
    width: int
    height: int
    mask: int

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("Domineering dimensions must be positive")
        cell_count = self.width * self.height
        if cell_count > MAX_CELLS:
            raise ValueError(f"Domineering position exceeds {MAX_CELLS} cells")
        if self.mask < 0 or self.mask >= 1 << cell_count:
            raise ValueError("Domineering mask falls outside its frame")

    @property
    def cell_count(self) -> int:
        return self.mask.bit_count()

    def occupied(self, row: int, column: int) -> bool:
        if not (0 <= row < self.height and 0 <= column < self.width):
            return False
        return bool(self.mask & (1 << (row * self.width + column)))

    def remove(self, cells: Iterable[tuple[int, int]]) -> "DomineeringPosition":
        removed = 0
        for row, column in cells:
            if not self.occupied(row, column):
                raise ValueError("cannot remove an unavailable Domineering cell")
            removed |= 1 << (row * self.width + column)
        return DomineeringPosition(self.width, self.height, self.mask & ~removed)


def position_from_cells(
    width: int, height: int, cells: Iterable[tuple[int, int]]
) -> DomineeringPosition:
    mask = 0
    for row, column in cells:
        if not (0 <= row < height and 0 <= column < width):
            raise ValueError("Domineering cell falls outside its frame")
        mask |= 1 << (row * width + column)
    return DomineeringPosition(width, height, mask)


def vertical_moves(position: DomineeringPosition) -> tuple[DomineeringPosition, ...]:
    moves = []
    for row in range(position.height - 1):
        for column in range(position.width):
            if position.occupied(row, column) and position.occupied(row + 1, column):
                moves.append(position.remove(((row, column), (row + 1, column))))
    return tuple(moves)


def horizontal_moves(position: DomineeringPosition) -> tuple[DomineeringPosition, ...]:
    moves = []
    for row in range(position.height):
        for column in range(position.width - 1):
            if position.occupied(row, column) and position.occupied(row, column + 1):
                moves.append(position.remove(((row, column), (row, column + 1))))
    return tuple(moves)


@cache
def game_from_position(position: DomineeringPosition) -> Game:
    left = tuple(game_from_position(child) for child in vertical_moves(position))
    right = tuple(game_from_position(child) for child in horizontal_moves(position))
    return Game.make(left, right)


def literal_code(position: DomineeringPosition) -> str:
    rows = []
    for row in range(position.height):
        rows.append(
            "".join(
                "1" if position.occupied(row, column) else "0"
                for column in range(position.width)
            )
        )
    return f"{position.width}x{position.height}:" + "/".join(rows)


def literal_digest(position: DomineeringPosition) -> str:
    payload = "partizan.domineering_literal.v1\n" + literal_code(position)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _trimmed_cells(position: DomineeringPosition) -> tuple[tuple[int, int], ...]:
    cells = [
        (row, column)
        for row in range(position.height)
        for column in range(position.width)
        if position.occupied(row, column)
    ]
    if not cells:
        return ()
    minimum_row = min(row for row, _ in cells)
    minimum_column = min(column for _, column in cells)
    return tuple(sorted((row - minimum_row, column - minimum_column) for row, column in cells))


def _normalise_cells(cells: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    cells = tuple(cells)
    if not cells:
        return ()
    minimum_row = min(row for row, _ in cells)
    minimum_column = min(column for _, column in cells)
    return tuple(sorted((row - minimum_row, column - minimum_column) for row, column in cells))


def _dihedral_images(
    cells: tuple[tuple[int, int], ...]
) -> tuple[tuple[tuple[int, int], ...], ...]:
    if not cells:
        return ((),)

    def transform(row: int, column: int, index: int) -> tuple[int, int]:
        if index == 0:
            return row, column
        if index == 1:
            return row, -column
        if index == 2:
            return -row, column
        if index == 3:
            return -row, -column
        if index == 4:
            return column, row
        if index == 5:
            return column, -row
        if index == 6:
            return -column, row
        return -column, -row

    return tuple(
        _normalise_cells(transform(row, column, index) for row, column in cells)
        for index in range(8)
    )


def _quotient_code(images: Iterable[tuple[tuple[int, int], ...]]) -> str:
    canonical = min(images)
    if not canonical:
        return "empty"
    height = 1 + max(row for row, _ in canonical)
    width = 1 + max(column for _, column in canonical)
    occupied = set(canonical)
    body = "/".join(
        "".join("1" if (row, column) in occupied else "0" for column in range(width))
        for row in range(height)
    )
    return f"{width}x{height}:{body}"


def ruleset_quotient(position: DomineeringPosition) -> str:
    """Canonical code under translations and player-preserving reflections.

    Quarter-turn rotations and diagonal reflections exchange vertical and
    horizontal moves, and therefore exchange Left and Right.  They are not
    symmetries of a fixed labelled Domineering value and are excluded here.
    """

    cells = _trimmed_cells(position)
    images = tuple(
        _normalise_cells(transform)
        for transform in (
            cells,
            ((row, -column) for row, column in cells),
            ((-row, column) for row, column in cells),
            ((-row, -column) for row, column in cells),
        )
    )
    return _quotient_code(images)


def unsigned_shape_quotient(position: DomineeringPosition) -> str:
    """Canonical unlabelled shape code under the full dihedral group."""

    return _quotient_code(_dihedral_images(_trimmed_cells(position)))


# Backward-compatible descriptive alias.  Scientific quotient counts use the
# player-preserving ``ruleset_quotient`` above.
geometric_quotient = unsigned_shape_quotient


def exact_value_record(position: DomineeringPosition) -> dict[str, object]:
    game = game_from_position(position)
    return {
        "literal_code": literal_code(position),
        "literal_sha256": literal_digest(position),
        "ruleset_quotient": ruleset_quotient(position),
        "unsigned_shape_quotient": unsigned_shape_quotient(position),
        "available_cell_count": position.cell_count,
        "left_move_count": len(vertical_moves(position)),
        "right_move_count": len(horizontal_moves(position)),
        "game_serialization": serialize(game),
        "game_sha256": game_digest(game),
    }


def exact_equal(
    left: DomineeringPosition, right: DomineeringPosition
) -> bool:
    return equal(game_from_position(left), game_from_position(right))
