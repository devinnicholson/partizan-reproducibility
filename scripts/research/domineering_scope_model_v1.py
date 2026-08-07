#!/usr/bin/env python3
"""Neural equality model and deterministic features for Domineering scope v1."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Any, Iterable

import numpy as np
import torch
from torch import Tensor, nn

from domineering_exact_v1 import (
    DomineeringPosition,
    horizontal_moves,
    ruleset_quotient,
    vertical_moves,
)


SIGN_ORDER = ("zero", "positive", "negative", "fuzzy")


def connected_component_count(position: DomineeringPosition) -> int:
    remaining = {
        (row, column)
        for row in range(position.height)
        for column in range(position.width)
        if position.occupied(row, column)
    }
    count = 0
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            row, column = stack.pop()
            for neighbour in (
                (row - 1, column),
                (row + 1, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    stack.append(neighbour)
    return count


def boundary_edge_count(position: DomineeringPosition) -> int:
    total = 0
    for row in range(position.height):
        for column in range(position.width):
            if not position.occupied(row, column):
                continue
            total += sum(
                not position.occupied(neighbour_row, neighbour_column)
                for neighbour_row, neighbour_column in (
                    (row - 1, column),
                    (row + 1, column),
                    (row, column - 1),
                    (row, column + 1),
                )
            )
    return total


def descriptor_cell(position: DomineeringPosition) -> tuple[int, int, int, int, int]:
    return (
        position.cell_count,
        len(vertical_moves(position)),
        len(horizontal_moves(position)),
        connected_component_count(position),
        boundary_edge_count(position),
    )


def candidate_arrays(
    positions: Iterable[DomineeringPosition],
) -> tuple[np.ndarray, np.ndarray, list[str], list[tuple[int, int, int, int, int]]]:
    positions = tuple(positions)
    grids = np.zeros((len(positions), 1, 4, 4), dtype=np.float32)
    scalars = np.zeros((len(positions), 5), dtype=np.float32)
    quotients: list[str] = []
    descriptor_cells: list[tuple[int, int, int, int, int]] = []
    for index, position in enumerate(positions):
        if (position.width, position.height) != (4, 4):
            raise ValueError("scope model requires framed 4x4 candidates")
        for row in range(4):
            for column in range(4):
                grids[index, 0, row, column] = float(position.occupied(row, column))
        descriptor = descriptor_cell(position)
        scalars[index] = np.asarray(
            (
                descriptor[0] / 16.0,
                descriptor[1] / 12.0,
                descriptor[2] / 12.0,
                descriptor[3] / 16.0,
                descriptor[4] / 64.0,
            ),
            dtype=np.float32,
        )
        quotients.append(ruleset_quotient(position))
        descriptor_cells.append(descriptor)
    return grids, scalars, quotients, descriptor_cells


def target_descriptor_array(targets: list[dict[str, Any]]) -> np.ndarray:
    result = np.zeros((len(targets), 7), dtype=np.float32)
    for index, target in enumerate(targets):
        result[index, 0] = float(target["birthday"]) / 4.0
        result[index, 1 + SIGN_ORDER.index(target["sign_class"])] = 1.0
        result[index, 5] = np.log1p(target["calibration_literal_count"]) / np.log1p(108)
        result[index, 6] = np.log1p(target["calibration_ruleset_quotient_count"]) / np.log1p(35)
    return result


@dataclass(frozen=True)
class Architecture:
    architecture_id: str
    convolution_channels: int
    hidden_width: int


class DomineeringEqualityCNN(nn.Module):
    def __init__(self, architecture: Architecture, target_count: int = 12) -> None:
        super().__init__()
        channels = architecture.convolution_channels
        hidden = architecture.hidden_width
        self.architecture = architecture
        self.candidate_encoder = nn.Sequential(
            nn.Conv2d(1, channels, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(channels, channels, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Flatten(),
        )
        self.target_embedding = nn.Embedding(target_count, 16)
        self.head = nn.Sequential(
            nn.Linear(channels * 16 + 5 + 16 + 7, hidden),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, 1),
        )

    def forward(
        self,
        grids: Tensor,
        scalars: Tensor,
        target_indices: Tensor,
        target_descriptors: Tensor,
    ) -> Tensor:
        candidate = self.candidate_encoder(grids)
        target = self.target_embedding(target_indices)
        joined = torch.cat((candidate, scalars, target, target_descriptors), dim=1)
        return self.head(joined).squeeze(1)


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def macro_auc(labels: np.ndarray, probabilities: np.ndarray) -> float:
    if labels.shape != probabilities.shape or labels.ndim != 2:
        raise ValueError("macro AUC arrays differ")
    values = []
    for target in range(labels.shape[1]):
        truth = labels[:, target].astype(bool)
        positive = int(truth.sum())
        negative = len(truth) - positive
        if positive == 0 or negative == 0:
            raise ValueError("target lacks both equality classes")
        order = np.argsort(probabilities[:, target], kind="mergesort")
        ranks = np.empty(len(order), dtype=np.float64)
        ranks[order] = np.arange(1, len(order) + 1, dtype=np.float64)
        positive_rank_sum = ranks[truth].sum()
        values.append(
            (positive_rank_sum - positive * (positive + 1) / 2)
            / (positive * negative)
        )
    return float(np.mean(values))


def macro_brier(labels: np.ndarray, probabilities: np.ndarray) -> float:
    return float(np.mean(np.mean((probabilities - labels) ** 2, axis=0)))


def _base_policy_scores(
    probabilities: np.ndarray, temperature: float, seed: int
) -> np.ndarray:
    if probabilities.ndim != 1 or not 0 < temperature:
        raise ValueError("policy probability or temperature differs")
    clipped = np.clip(probabilities.astype(np.float64), 1e-7, 1 - 1e-7)
    logits = np.log(clipped) - np.log1p(-clipped)
    rng = np.random.default_rng(seed)
    gumbel = rng.gumbel(size=len(probabilities))
    return logits / temperature + gumbel


def select_equality_policy(
    probabilities: np.ndarray, *, budget: int, temperature: float, seed: int
) -> np.ndarray:
    if not 0 < budget <= len(probabilities):
        raise ValueError("equality policy budget differs")
    scores = _base_policy_scores(probabilities, temperature, seed)
    indices = np.argpartition(scores, -budget)[-budget:]
    return indices[np.argsort(scores[indices], kind="mergesort")[::-1]]


def select_novelty_policy(
    probabilities: np.ndarray,
    quotients: list[str],
    descriptor_cells: list[tuple[int, int, int, int, int]],
    *,
    budget: int,
    temperature: float,
    alpha: float,
    beta: float,
    seed: int,
) -> np.ndarray:
    if len(probabilities) != len(quotients) or len(probabilities) != len(descriptor_cells):
        raise ValueError("novelty policy arrays differ")
    if not 0 < budget <= len(probabilities) or alpha < 0 or beta < 0:
        raise ValueError("novelty policy configuration differs")
    base = _base_policy_scores(probabilities, temperature, seed)
    quotient_counts: dict[str, int] = {}
    descriptor_counts: dict[tuple[int, int, int, int, int], int] = {}
    selected = np.zeros(len(probabilities), dtype=bool)
    heap: list[tuple[float, int, int, int]] = []
    for index in range(len(probabilities)):
        priority = float(base[index] + alpha + beta)
        heapq.heappush(heap, (-priority, index, 0, 0))

    choices = []
    while len(choices) < budget:
        if not heap:
            raise ValueError("novelty policy exhausted candidates")
        _, index, old_quotient_count, old_descriptor_count = heapq.heappop(heap)
        if selected[index]:
            continue
        quotient_count = quotient_counts.get(quotients[index], 0)
        descriptor_count = descriptor_counts.get(descriptor_cells[index], 0)
        if (
            quotient_count != old_quotient_count
            or descriptor_count != old_descriptor_count
        ):
            priority = float(
                base[index]
                + alpha / np.sqrt(1 + quotient_count)
                + beta / np.sqrt(1 + descriptor_count)
            )
            heapq.heappush(
                heap,
                (-priority, index, quotient_count, descriptor_count),
            )
            continue
        selected[index] = True
        choices.append(index)
        quotient_counts[quotients[index]] = quotient_count + 1
        descriptor_counts[descriptor_cells[index]] = descriptor_count + 1
    return np.asarray(choices, dtype=np.int64)
