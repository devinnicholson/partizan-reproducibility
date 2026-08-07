#!/usr/bin/env python3
"""Historical-only resource preflight for the frozen neural-policy v1 study.

This program deliberately cannot generate validation or test candidates and
does not import any combinatorial-game evaluator.  It authenticates the
registered training ledger, constructs deterministic pools from its historical
toggle-one-arc rows, replays stored exact/quotient bindings, and benchmarks the
pool, rank, selection, canonical-log, and hash-chain paths.

The public ``run_preflight`` function accepts a ranker callback so tests can use
a small deterministic fixture.  The command line has no fixture/stub option:
it requires a self-hashed frozen-model binding and loads the bound adapter
source and ensemble artifact by exact SHA-256.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = "partizan.digraph_order7_neural_policy_resource_preflight.v1"
MODEL_BINDING_SCHEMA = (
    "partizan.digraph_order7_neural_policy_resource_preflight.v1.model_binding"
)
POOL_SCHEMA = f"{SCHEMA_VERSION}.pool"
EVENT_SCHEMA = f"{SCHEMA_VERSION}.event"
EXPECTED_PROTOCOL_SCHEMA = (
    "partizan.digraph_order7_neural_policy_comparison.v1.protocol"
)
EXPECTED_PROTOCOL_STATUS = "DESIGN_FROZEN_AWAITING_MODEL_BINDING"
EXPECTED_TARGETS = ("0", "*", "{0|1}")
COMPARISON_PREFIX = "partizan.digraph_order7_neural_policy_comparison.v1"
PREFLIGHT_RNG_PHASE = "resource_preflight_registered_replay"
EXPECTED_ARMS = (
    "structural_toggle_one_random",
    "neural_toggle_one_ranker",
)
CONTROL_ARM = EXPECTED_ARMS[0]
TREATMENT_ARM = EXPECTED_ARMS[1]
ZERO_SHA256 = "0" * 64
DEFAULT_PROTOCOL = (
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"
)
DEFAULT_REPETITIONS = 3
SAFETY_FACTOR_RUNTIME = 1.25
SAFETY_FACTOR_DISK = 1.50
SAFETY_FACTOR_RSS = 1.50
MINIMUM_PROJECTED_RSS_BYTES = 256 * 1024**2
ARC_POPULATION = tuple(
    (source, target)
    for source in range(7)
    for target in range(7)
    if source != target
)
EXPECTED_COUNTER_RNG = {
    "hash": "sha256",
    "message_encoding": "utf8",
    "message": (
        "{prefix}|{phase}|{target}|{decimal_pair_seed}|"
        "{decimal_unit_index}|{draw_name}|{decimal_rejection_counter}"
    ),
    "integer": "complete_32_byte_digest_unsigned_big_endian",
    "randbelow": "reject_x_ge_2^256_minus_2^256_mod_n_then_x_mod_n",
    "parent_draw_name": "parent",
    "parent_population_order": "lexicographic_quotient_sha256",
    "arc_population_order": "source_major_target_minor_without_loops",
    "arc_permutation": "descending_fisher_yates_indices_41_through_1",
    "arc_draw_name": "arc_shuffle_{descending_index}",
    "pool_arcs": "first_16_in_permutation_order",
    "control_selection_draw_name": "control_selection",
    "control_selection_population_order": "eligible_slots_in_pool_order",
    "validation_phase": "validation",
    "validation_unit_index": "group_index",
    "test_phase": "test",
    "test_unit_index": "verifier_call_index",
}


class PreflightError(ValueError):
    """Raised when a preflight input or integrity condition fails closed."""


RankerCallback = Callable[
    [Sequence[Mapping[str, Any]]],
    Sequence[float],
]


@dataclass(frozen=True)
class HistoricalCandidate:
    """Compact authenticated projection of one registered historical row."""

    target: str
    candidate: Mapping[str, Any]
    candidate_sha256: str
    global_event_index: int
    exact_equal: bool
    quotient_sha256: str | None
    quotient_code: str | None
    weakly_connected: bool


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical ASCII JSON without a trailing newline."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def canonical_json_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def load_json_object(path: Path, *, canonical_line: bool = False) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise PreflightError(f"{path}: expected a JSON object")
    if canonical_line and raw != canonical_json_line(value):
        raise PreflightError(f"{path}: object is not canonical newline JSON")
    return value


def verify_self_hash(
    value: Mapping[str, Any],
    field: str,
    *,
    context: str,
) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if not is_sha256(supplied) or supplied != object_sha256(payload):
        raise PreflightError(f"{context}: embedded {field} does not replay")


def add_self_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    if field in result:
        raise PreflightError(f"cannot overwrite existing {field}")
    result[field] = object_sha256(result)
    return result


def write_report_exclusive(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_line(report))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve_repo_path(repo_root: Path, relative: Any, *, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PreflightError(f"{field}: missing repository-relative path")
    root = repo_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise PreflightError(f"{field}: path escapes repository") from error
    return path


def _require_keys(
    value: Mapping[str, Any],
    required: set[str],
    *,
    context: str,
    exact: bool = False,
) -> None:
    missing = required - set(value)
    if missing:
        raise PreflightError(f"{context}: missing fields {sorted(missing)}")
    if exact and set(value) != required:
        raise PreflightError(
            f"{context}: unexpected fields {sorted(set(value) - required)}"
        )


def validate_preflight_protocol(
    protocol: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Validate the frozen fields consumed by this resource preflight."""

    if protocol.get("schema_version") != EXPECTED_PROTOCOL_SCHEMA:
        raise PreflightError("protocol schema is not frozen neural-policy v1")
    if protocol.get("status") != EXPECTED_PROTOCOL_STATUS:
        raise PreflightError("protocol is not frozen awaiting model binding")
    domain = protocol.get("domain")
    budget = protocol.get("budget")
    resource_gate = protocol.get("resource_gate")
    training = protocol.get("training_source")
    arms = protocol.get("arms")
    model = protocol.get("model")
    splits = protocol.get("splits")
    if not all(
        isinstance(value, Mapping)
        for value in (domain, budget, resource_gate, training, model, splits)
    ) or not isinstance(arms, list):
        raise PreflightError("protocol sections required by preflight are malformed")

    if domain.get("order") != 7:
        raise PreflightError("protocol graph order changed")
    if tuple(domain.get("target_order", ())) != EXPECTED_TARGETS:
        raise PreflightError("protocol target order changed")
    if tuple(arm.get("id") for arm in arms if isinstance(arm, Mapping)) != EXPECTED_ARMS:
        raise PreflightError("protocol primary arms changed")

    expected_budget = {
        "candidate_pool_size": 16,
        "test_pool_kernel": (
            "sixteen_distinct_toggle_one_arcs_without_replacement"
        ),
        "selected_candidates_per_call": 1,
        "exact_verifier_calls_per_arm_target_pair": 2048,
        "arms": 2,
        "targets": 3,
        "pairs_per_target": 12,
        "total_test_exact_verifier_calls": 147456,
        "total_test_raw_pool_candidates": 2359296,
    }
    for field, expected in expected_budget.items():
        if budget.get(field) != expected:
            raise PreflightError(f"protocol budget field {field} changed")
    if (
        budget["candidate_pool_size"]
        * budget["total_test_exact_verifier_calls"]
        != budget["total_test_raw_pool_candidates"]
    ):
        raise PreflightError("protocol raw-pool budget is arithmetically inconsistent")

    seed_derivation = splits.get("seed_derivation")
    counter_rng = splits.get("counter_rng")
    if not isinstance(seed_derivation, Mapping) or not isinstance(
        counter_rng, Mapping
    ):
        raise PreflightError("protocol RNG sections are missing")
    if seed_derivation.get("prefix") != COMPARISON_PREFIX:
        raise PreflightError("protocol RNG prefix changed")
    if dict(counter_rng) != EXPECTED_COUNTER_RNG:
        raise PreflightError("protocol counter RNG or pool ordering changed")

    expected_gate = {
        "preflight_steps_per_arm": 4096,
        "preflight_uses_only_registered_training_candidates": True,
        "preflight_new_semantic_evaluation_allowed": False,
        "maximum_projected_generation_seconds": 3600,
        "generation_wall_seconds": 5400,
        "independent_verification_wall_seconds": 7200,
        "run_directory_bytes": 12884901888,
        "peak_resident_memory_bytes": 4294967296,
    }
    for field, expected in expected_gate.items():
        if resource_gate.get(field) != expected:
            raise PreflightError(f"protocol resource gate field {field} changed")

    if training.get("role") != "training_only":
        raise PreflightError("historical source is not training-only")
    events = training.get("events")
    if not isinstance(events, Mapping):
        raise PreflightError("training event binding is missing")
    event_path = _resolve_repo_path(
        repo_root, events.get("path"), field="training events"
    )
    if not event_path.is_file():
        raise PreflightError(f"training events are missing: {event_path}")
    observed_events_sha = file_sha256(event_path)
    if observed_events_sha != events.get("sha256"):
        raise PreflightError("training event file SHA-256 does not match protocol")
    if events.get("event_count") != 73728:
        raise PreflightError("training event count binding changed")

    required_bindings = model.get("required_binding_fields")
    if (
        not isinstance(required_bindings, list)
        or len(required_bindings) != len(set(required_bindings))
        or not all(isinstance(item, str) and item for item in required_bindings)
    ):
        raise PreflightError("protocol required model bindings are malformed")

    return {
        "event_path": event_path,
        "event_sha256": observed_events_sha,
        "event_count": events["event_count"],
        "pool_size": budget["candidate_pool_size"],
        "total_test_steps": budget["total_test_exact_verifier_calls"],
        "total_test_raw_candidates": budget["total_test_raw_pool_candidates"],
        "steps_per_arm": resource_gate["preflight_steps_per_arm"],
        "resource_gate": dict(resource_gate),
        "training_directory": _resolve_repo_path(
            repo_root, training.get("directory"), field="training directory"
        ),
        "required_model_bindings": tuple(required_bindings),
        "counter_rng": dict(counter_rng),
    }


def _validate_candidate_record(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict) or set(candidate) != {
        "order",
        "blue_vertices",
        "arcs",
    }:
        raise PreflightError("historical candidate has malformed fields")
    if candidate.get("order") != 7:
        raise PreflightError("historical candidate order is not seven")
    blue = candidate.get("blue_vertices")
    arcs = candidate.get("arcs")
    if (
        not isinstance(blue, list)
        or blue != sorted(blue)
        or len(blue) != len(set(blue))
        or any(
            isinstance(vertex, bool)
            or not isinstance(vertex, int)
            or not 0 <= vertex < 7
            for vertex in blue
        )
    ):
        raise PreflightError("historical blue-vertex list is not canonical")
    if not isinstance(arcs, list):
        raise PreflightError("historical arc list is malformed")
    normalized: list[list[int]] = []
    for arc in arcs:
        if (
            not isinstance(arc, list)
            or len(arc) != 2
            or any(
                isinstance(vertex, bool)
                or not isinstance(vertex, int)
                or not 0 <= vertex < 7
                for vertex in arc
            )
            or arc[0] == arc[1]
        ):
            raise PreflightError("historical arc is invalid")
        normalized.append([arc[0], arc[1]])
    if normalized != sorted(normalized) or len(normalized) != len(
        {tuple(arc) for arc in normalized}
    ):
        raise PreflightError("historical arc list is not canonical")
    return candidate


def _weakly_connected(candidate: Mapping[str, Any]) -> bool:
    adjacency = [set() for _ in range(7)]
    for source, target in candidate["arcs"]:
        adjacency[source].add(target)
        adjacency[target].add(source)
    seen = {0}
    pending = [0]
    while pending:
        source = pending.pop()
        for target in sorted(adjacency[source]):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return len(seen) == 7


def _parse_historical_event(
    event: Mapping[str, Any],
    *,
    expected_index: int,
    expected_previous: str,
) -> HistoricalCandidate | None:
    supplied_index = event.get("global_event_index")
    supplied_previous = event.get("previous_event_sha256")
    supplied_hash = event.get("event_sha256")
    if supplied_index != expected_index:
        raise PreflightError("historical event index is not contiguous")
    if supplied_previous != expected_previous:
        raise PreflightError("historical event predecessor chain is broken")
    payload = dict(event)
    payload.pop("event_sha256", None)
    if not is_sha256(supplied_hash) or supplied_hash != object_sha256(payload):
        raise PreflightError("historical event hash does not replay")

    proposal = event.get("proposal")
    decision = event.get("exact_decision")
    if (
        not isinstance(proposal, Mapping)
        or proposal.get("operator") != "toggle_one_arc"
        or decision is None
    ):
        return None
    if not isinstance(decision, Mapping) or not isinstance(
        decision.get("equal"), bool
    ):
        raise PreflightError("historical exact decision is malformed")
    target = event.get("target")
    if target not in EXPECTED_TARGETS:
        raise PreflightError("historical event target changed")

    candidate = _validate_candidate_record(event.get("candidate"))
    candidate_sha = event.get("candidate_sha256")
    if (
        not is_sha256(candidate_sha)
        or object_sha256(candidate) != candidate_sha
    ):
        raise PreflightError("historical candidate digest does not replay")

    connected = event.get("weakly_connected")
    if not isinstance(connected, bool) or _weakly_connected(candidate) != connected:
        raise PreflightError("historical connectivity result does not replay")

    exact_equal = decision["equal"]
    quotient = event.get("quotient")
    quotient_sha: str | None = None
    quotient_code: str | None = None
    if exact_equal:
        if not isinstance(quotient, Mapping):
            raise PreflightError("historical exact match lacks known quotient")
        quotient_sha = quotient.get("quotient_sha256")
        quotient_code = quotient.get("canonical_code")
        if (
            not is_sha256(quotient_sha)
            or not isinstance(quotient_code, str)
            or hashlib.sha256(quotient_code.encode("ascii")).hexdigest()
            != quotient_sha
        ):
            raise PreflightError("historical quotient digest does not replay")
    elif quotient is not None:
        raise PreflightError("historical exact mismatch unexpectedly has quotient")

    return HistoricalCandidate(
        target=target,
        candidate=candidate,
        candidate_sha256=candidate_sha,
        global_event_index=expected_index,
        exact_equal=exact_equal,
        quotient_sha256=quotient_sha,
        quotient_code=quotient_code,
        weakly_connected=connected,
    )


def load_historical_registry(
    events_path: Path,
    *,
    expected_event_count: int,
    expected_final_event_sha256: str | None = None,
) -> tuple[dict[str, tuple[HistoricalCandidate, ...]], dict[str, Any]]:
    """Authenticate and compact the registered toggle-one training rows."""

    previous = ZERO_SHA256
    event_count = 0
    by_target: dict[str, dict[str, HistoricalCandidate]] = {
        target: {} for target in EXPECTED_TARGETS
    }
    labeled_toggle_rows = 0
    known_exact_decision_rows = 0
    with events_path.open(encoding="ascii") as handle:
        for event_count, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise PreflightError(
                    f"historical event line {event_count} is invalid JSON"
                ) from error
            if not isinstance(event, dict):
                raise PreflightError("historical event is not an object")
            known_exact_decision_rows += int(event.get("exact_decision") is not None)
            parsed = _parse_historical_event(
                event,
                expected_index=event_count - 1,
                expected_previous=previous,
            )
            previous_value = event.get("event_sha256")
            if not isinstance(previous_value, str):
                raise PreflightError("historical event hash is missing")
            previous = previous_value
            if parsed is None:
                continue
            labeled_toggle_rows += 1
            prior = by_target[parsed.target].get(parsed.candidate_sha256)
            if prior is not None and (
                prior.candidate != parsed.candidate
                or prior.exact_equal != parsed.exact_equal
                or prior.quotient_sha256 != parsed.quotient_sha256
                or prior.quotient_code != parsed.quotient_code
                or prior.weakly_connected != parsed.weakly_connected
            ):
                raise PreflightError(
                    "duplicate historical candidate has inconsistent known result"
                )
            if prior is None:
                by_target[parsed.target][parsed.candidate_sha256] = parsed

    if event_count != expected_event_count:
        raise PreflightError(
            "historical ledger count does not match frozen protocol"
        )
    if (
        expected_final_event_sha256 is not None
        and previous != expected_final_event_sha256
    ):
        raise PreflightError("historical final event hash does not match marker")

    registry: dict[str, tuple[HistoricalCandidate, ...]] = {}
    for target in EXPECTED_TARGETS:
        rows = tuple(
            by_target[target][digest] for digest in sorted(by_target[target])
        )
        if len(rows) < 16:
            raise PreflightError(
                f"historical target {target} has fewer than sixteen candidates"
            )
        registry[target] = rows

    commitment = object_sha256(
        {
            target: [
                {
                    "candidate_sha256": row.candidate_sha256,
                    "event_index": row.global_event_index,
                    "exact_equal": row.exact_equal,
                    "quotient_sha256": row.quotient_sha256,
                }
                for row in registry[target]
            ]
            for target in EXPECTED_TARGETS
        }
    )
    summary = {
        "all_event_rows_authenticated": event_count,
        "known_exact_decision_rows": known_exact_decision_rows,
        "labeled_toggle_one_rows": labeled_toggle_rows,
        "unique_registered_candidates_by_target": {
            target: len(registry[target]) for target in EXPECTED_TARGETS
        },
        "final_historical_event_sha256": previous,
        "registry_sha256": commitment,
    }
    return registry, summary


def _counter_randbelow(
    n: int,
    *,
    phase: str,
    target: str,
    pair_seed: int,
    unit_index: int,
    draw_name: str,
) -> int:
    """Frozen SHA-256 rejection-sampling draw from the comparison protocol."""

    if n <= 0:
        raise PreflightError("randbelow population must be positive")
    limit = (1 << 256) - ((1 << 256) % n)
    rejection = 0
    while True:
        message = (
            f"{COMPARISON_PREFIX}|{phase}|{target}|{pair_seed}|"
            f"{unit_index}|{draw_name}|{rejection}"
        ).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(message).digest(), "big")
        if value < limit:
            return value % n
        rejection += 1


def _preflight_pair_seed(pair_index: int) -> int:
    message = (
        f"{COMPARISON_PREFIX}|resource_preflight|pair|{pair_index}"
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest()[:8], "big")


def _preflight_rng_context(step_index: int, target: str) -> dict[str, Any]:
    pair_index = step_index // 2048
    return {
        "phase": PREFLIGHT_RNG_PHASE,
        "target": target,
        "pair_index": pair_index,
        "pair_seed": _preflight_pair_seed(pair_index),
        "unit_index": step_index % 2048,
    }


def _arc_permutation(rng_context: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    arcs = list(ARC_POPULATION)
    for descending_index in range(len(arcs) - 1, 0, -1):
        other = _counter_randbelow(
            descending_index + 1,
            phase=str(rng_context["phase"]),
            target=str(rng_context["target"]),
            pair_seed=int(rng_context["pair_seed"]),
            unit_index=int(rng_context["unit_index"]),
            draw_name=f"arc_shuffle_{descending_index}",
        )
        arcs[descending_index], arcs[other] = arcs[other], arcs[descending_index]
    return tuple(arcs)


def _parent_population(
    population: Sequence[HistoricalCandidate],
) -> tuple[HistoricalCandidate, ...]:
    representatives: dict[str, HistoricalCandidate] = {}
    for row in population:
        if row.quotient_sha256 is None:
            continue
        prior = representatives.get(row.quotient_sha256)
        if prior is None or row.candidate_sha256 < prior.candidate_sha256:
            representatives[row.quotient_sha256] = row
    return tuple(representatives[digest] for digest in sorted(representatives))


def construct_registered_pool(
    registry: Mapping[str, Sequence[HistoricalCandidate]],
    *,
    target: str,
    step_index: int,
    pool_size: int,
    parent_population: Sequence[HistoricalCandidate] | None = None,
) -> tuple[
    str,
    tuple[HistoricalCandidate, ...],
    dict[str, Any],
]:
    population = registry[target]
    if len(population) < pool_size:
        raise PreflightError("registered population is smaller than pool")
    rng_context = _preflight_rng_context(step_index, target)
    parents = (
        tuple(parent_population)
        if parent_population is not None
        else _parent_population(population)
    )
    if not parents:
        raise PreflightError("registered target lacks an exact-match parent control")
    parent_index = _counter_randbelow(
        len(parents),
        phase=str(rng_context["phase"]),
        target=target,
        pair_seed=int(rng_context["pair_seed"]),
        unit_index=int(rng_context["unit_index"]),
        draw_name="parent",
    )
    parent = parents[parent_index]
    permutation = _arc_permutation(rng_context)
    pool_arcs = permutation[:pool_size]

    # Historical rows stand in for the sixteen ordered arc slots.  The mapping
    # is injective because the population exceeds 42 and arc indices are
    # distinct.  This keeps every scored row registered while exercising the
    # frozen Fisher--Yates ordering and all pool/selection/logging paths.
    parent_offset = int(parent.candidate_sha256[:16], 16) % len(population)
    arc_index = {arc: index for index, arc in enumerate(ARC_POPULATION)}
    chosen = [
        population[(parent_offset + arc_index[arc] + 1) % len(population)]
        for arc in pool_arcs
    ]
    if len({row.candidate_sha256 for row in chosen}) != pool_size:
        raise PreflightError("historical arc-slot proxy mapping is not injective")
    pool_payload = {
        "schema_version": POOL_SCHEMA,
        "target": target,
        "step_index": step_index,
        "rng_context": rng_context,
        "parent_population_order": "lexicographic_quotient_sha256",
        "parent_quotient_sha256": parent.quotient_sha256,
        "parent_candidate_sha256": parent.candidate_sha256,
        "arc_population_order": "source_major_target_minor_without_loops",
        "arc_permutation": "descending_fisher_yates_indices_41_through_1",
        "pool_arcs": [list(arc) for arc in pool_arcs],
        "candidate_sha256_order": [row.candidate_sha256 for row in chosen],
    }
    context = {
        **rng_context,
        "parent_candidate_sha256": parent.candidate_sha256,
        "parent_quotient_sha256": parent.quotient_sha256,
        "pool_arcs": tuple(pool_arcs),
    }
    return object_sha256(pool_payload), tuple(chosen), context


def _ranker_rows(
    pool: Sequence[HistoricalCandidate],
    *,
    pool_id: str,
    target: str,
    step_index: int,
) -> list[dict[str, Any]]:
    return [
        {
            "candidate": row.candidate,
            "candidate_sha256": row.candidate_sha256,
            "target": target,
            "base_seed": step_index,
            "proposal": {"operator": "toggle_one_arc"},
            "ranker_pool": {"pool_id": pool_id},
        }
        for row in pool
    ]


def _validated_scores(
    ranker: RankerCallback,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[float, ...]:
    try:
        supplied = ranker(rows)
    except Exception as error:
        raise PreflightError(f"ranker callback failed: {error}") from error
    if isinstance(supplied, (str, bytes)) or not isinstance(supplied, Sequence):
        raise PreflightError("ranker callback must return a score sequence")
    if len(supplied) != len(rows):
        raise PreflightError("ranker callback returned wrong score count")
    scores: list[float] = []
    for value in supplied:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PreflightError("ranker score is not numeric")
        score = float(value)
        if not math.isfinite(score):
            raise PreflightError("ranker score is not finite")
        scores.append(score)
    return tuple(scores)


def assert_ranker_deterministic(
    ranker: RankerCallback,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    first = _validated_scores(ranker, rows)
    second = _validated_scores(ranker, rows)
    if tuple(value.hex() for value in first) != tuple(
        value.hex() for value in second
    ):
        raise PreflightError("ranker callback is nondeterministic")
    return object_sha256([value.hex() for value in first])


def _eligible_indices(
    pool: Sequence[HistoricalCandidate],
    seen_by_arm: set[str],
) -> tuple[int, tuple[int, ...]]:
    """Replay all structural tiers; registered rows necessarily reach tier 4."""

    tiers: tuple[tuple[int, ...], ...] = (
        tuple(
            index
            for index, row in enumerate(pool)
            if row.weakly_connected
            and False  # all preflight rows are registered prior-split candidates
            and row.candidate_sha256 not in seen_by_arm
        ),
        tuple(
            index
            for index, row in enumerate(pool)
            if row.weakly_connected
            and False  # all preflight rows are registered prior-split candidates
        ),
        tuple(),  # every preflight candidate is prior-split by construction
        tuple(range(len(pool))),
    )
    for tier_index, indices in enumerate(tiers):
        if indices:
            return tier_index, indices
    raise PreflightError("no structural tier contains a candidate")


def _select_candidate(
    *,
    arm: str,
    pool: Sequence[HistoricalCandidate],
    pool_id: str,
    eligible: Sequence[int],
    scores: Sequence[float] | None,
    rng_context: Mapping[str, Any],
) -> int:
    if arm == CONTROL_ARM:
        offset = _counter_randbelow(
            len(eligible),
            phase=str(rng_context["phase"]),
            target=str(rng_context["target"]),
            pair_seed=int(rng_context["pair_seed"]),
            unit_index=int(rng_context["unit_index"]),
            draw_name="control_selection",
        )
        return eligible[offset]
    if arm != TREATMENT_ARM or scores is None:
        raise PreflightError("unknown arm or missing treatment scores")
    return min(
        eligible,
        key=lambda index: (-scores[index], pool[index].candidate_sha256),
    )


def _known_result_record(row: HistoricalCandidate) -> dict[str, Any]:
    """Replay stored exact/quotient bindings without semantic evaluation."""

    if object_sha256(row.candidate) != row.candidate_sha256:
        raise PreflightError("selected candidate digest changed after registry load")
    if row.exact_equal:
        if (
            row.quotient_sha256 is None
            or row.quotient_code is None
            or hashlib.sha256(row.quotient_code.encode("ascii")).hexdigest()
            != row.quotient_sha256
        ):
            raise PreflightError("selected stored quotient no longer replays")
    elif row.quotient_sha256 is not None or row.quotient_code is not None:
        raise PreflightError("selected mismatch has forbidden quotient data")
    return {
        "historical_event_index": row.global_event_index,
        "known_exact_equal": row.exact_equal,
        "known_quotient_sha256": row.quotient_sha256,
    }


def benchmark_arm(
    *,
    arm: str,
    registry: Mapping[str, Sequence[HistoricalCandidate]],
    ranker: RankerCallback,
    pool_size: int,
    steps: int,
) -> dict[str, Any]:
    """Run one deterministic pool/selection/log/hash pass for one arm."""

    seen_by_arm: set[str] = set()
    previous = ZERO_SHA256
    log_bytes = 0
    pool_bytes = 0
    ranker_seconds = 0.0
    construction_seconds = 0.0
    selection_log_hash_seconds = 0.0
    exact_equal_count = 0
    tier_counts = [0, 0, 0, 0]
    selected_order: list[str] = []
    pool_id_chain = ZERO_SHA256
    pool_candidate_order_chain = ZERO_SHA256
    parent_populations = {
        target: _parent_population(registry[target])
        for target in EXPECTED_TARGETS
    }

    started = time.perf_counter()
    for step_index in range(steps):
        target = EXPECTED_TARGETS[step_index % len(EXPECTED_TARGETS)]
        before = time.perf_counter()
        pool_id, pool, rng_context = construct_registered_pool(
            registry,
            target=target,
            step_index=step_index,
            pool_size=pool_size,
            parent_population=parent_populations[target],
        )
        rank_rows = _ranker_rows(
            pool,
            pool_id=pool_id,
            target=target,
            step_index=step_index,
        )
        pool_record = {
            "pool_id": pool_id,
            "target": target,
            "step_index": step_index,
            "rng_context": rng_context,
            "parent": {
                "candidate_sha256": rng_context["parent_candidate_sha256"],
                "quotient_sha256": rng_context["parent_quotient_sha256"],
            },
            "ordered_toggle_one_arcs": [
                list(arc) for arc in rng_context["pool_arcs"]
            ],
            "historical_rows_are_arc_slot_proxies": True,
            "candidates": [
                {
                    "candidate": row.candidate,
                    "candidate_sha256": row.candidate_sha256,
                    "ordered_toggle_one_arc": list(
                        rng_context["pool_arcs"][index]
                    ),
                    "weakly_connected": row.weakly_connected,
                    "registered_training_candidate": True,
                }
                for index, row in enumerate(pool)
            ],
        }
        pool_canonical_bytes = canonical_json_bytes(pool_record)
        pool_bytes += len(pool_canonical_bytes)
        pool_id_chain = object_sha256(
            {
                "previous_sha256": pool_id_chain,
                "step_index": step_index,
                "pool_id": pool_id,
            }
        )
        pool_candidate_order_chain = object_sha256(
            {
                "previous_sha256": pool_candidate_order_chain,
                "step_index": step_index,
                "candidate_sha256_order": [
                    row.candidate_sha256 for row in pool
                ],
            }
        )
        construction_seconds += time.perf_counter() - before

        scores: tuple[float, ...] | None = None
        if arm == TREATMENT_ARM:
            before = time.perf_counter()
            scores = _validated_scores(ranker, rank_rows)
            ranker_seconds += time.perf_counter() - before

        before = time.perf_counter()
        tier_index, eligible = _eligible_indices(pool, seen_by_arm)
        tier_counts[tier_index] += 1
        selected_index = _select_candidate(
            arm=arm,
            pool=pool,
            pool_id=pool_id,
            eligible=eligible,
            scores=scores,
            rng_context=rng_context,
        )
        selected = pool[selected_index]
        known_result = _known_result_record(selected)
        exact_equal_count += int(selected.exact_equal)
        seen_by_arm.add(selected.candidate_sha256)
        selected_order.append(selected.candidate_sha256)

        event_payload = {
            "schema_version": EVENT_SCHEMA,
            "arm": arm,
            "step_index": step_index,
            "target": target,
            "pool": pool_record,
            "structural_filter": {
                "first_nonempty_tier_zero_based": tier_index,
                "eligible_slots": list(eligible),
                "preflight_candidates_are_prior_split": True,
            },
            "selection": {
                "selected_slot": selected_index,
                "selected_candidate_sha256": selected.candidate_sha256,
                "score_hex_by_slot": (
                    [score.hex() for score in scores]
                    if scores is not None
                    else None
                ),
            },
            "registered_result_replay": known_result,
            "previous_event_sha256": previous,
        }
        event = dict(event_payload)
        event["event_sha256"] = object_sha256(event_payload)
        line = canonical_json_line(event)
        log_bytes += len(line)
        previous = event["event_sha256"]
        selection_log_hash_seconds += time.perf_counter() - before

    wall_seconds = time.perf_counter() - started
    deterministic = {
        "arm": arm,
        "steps": steps,
        "pool_candidates_exercised": steps * pool_size,
        "selected_registered_results_replayed": steps,
        "selected_exact_equal_count": exact_equal_count,
        "structural_tier_counts": tier_counts,
        "pool_canonical_bytes": pool_bytes,
        "canonical_log_bytes": log_bytes,
        "pool_id_order_sha256": pool_id_chain,
        "pool_candidate_order_sha256": pool_candidate_order_chain,
        "selected_candidate_order_sha256": object_sha256(selected_order),
        "final_event_sha256": previous,
    }
    deterministic["pass_sha256"] = object_sha256(deterministic)
    observational = {
        "wall_seconds": wall_seconds,
        "candidate_pool_construction_seconds": construction_seconds,
        "ranker_inference_seconds": ranker_seconds,
        "selection_log_hash_seconds": selection_log_hash_seconds,
        "timing_is_observational_and_nondeterministic": True,
    }
    return {"deterministic": deterministic, "observational": observational}


def _rss_bytes() -> int:
    observed = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux and the BSDs used in CI generally report KiB.
    if sys.platform == "darwin":
        return observed
    return observed * 1024


def _load_prior_timing_sources(
    *,
    training_directory: Path,
    expected_events_sha256: str,
    expected_event_count: int,
) -> dict[str, Any]:
    generation_path = training_directory / "GENERATION_COMPLETE.json"
    verification_path = training_directory / "independent_verification.json"
    if not generation_path.is_file() or not verification_path.is_file():
        raise PreflightError("historical timing marker is missing")
    generation = load_json_object(generation_path, canonical_line=True)
    verification = load_json_object(verification_path, canonical_line=True)
    verify_self_hash(
        generation,
        "generation_sha256",
        context="historical generation marker",
    )
    verify_self_hash(
        verification,
        "verification_sha256",
        context="historical verification marker",
    )
    if (
        generation.get("events_file_sha256") != expected_events_sha256
        or generation.get("event_count") != expected_event_count
        or verification.get("event_count") != expected_event_count
        or verification.get("final_event_sha256")
        != generation.get("final_event_sha256")
    ):
        raise PreflightError("historical timing markers do not bind the ledger")
    generation_seconds = generation.get("generation_wall_seconds")
    verification_seconds = verification.get("wall_seconds")
    run_bytes = generation.get("run_directory_bytes_before_marker")
    if (
        isinstance(generation_seconds, bool)
        or not isinstance(generation_seconds, (int, float))
        or generation_seconds <= 0
        or isinstance(verification_seconds, bool)
        or not isinstance(verification_seconds, (int, float))
        or verification_seconds <= 0
        or isinstance(run_bytes, bool)
        or not isinstance(run_bytes, int)
        or run_bytes <= 0
    ):
        raise PreflightError("historical resource measurements are malformed")
    return {
        "generation": {
            "path": str(generation_path),
            "file_sha256": file_sha256(generation_path),
            "internal_sha256": generation["generation_sha256"],
            "wall_seconds": float(generation_seconds),
            "event_count": expected_event_count,
            "run_directory_bytes_before_marker": run_bytes,
        },
        "independent_verification": {
            "path": str(verification_path),
            "file_sha256": file_sha256(verification_path),
            "internal_sha256": verification["verification_sha256"],
            "wall_seconds": float(verification_seconds),
            "event_count": expected_event_count,
        },
        "final_event_sha256": generation["final_event_sha256"],
    }


def project_resources(
    *,
    repeated_passes: Mapping[str, Sequence[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    historical_exact_calls: int,
    historical_event_file_bytes: int,
    total_test_steps: int,
    total_test_raw_candidates: int,
    pool_size: int,
    observed_peak_rss_bytes: int,
    caps: Mapping[str, Any],
) -> dict[str, Any]:
    if historical_exact_calls <= 0:
        raise PreflightError("historical exact-call count must be positive")
    if total_test_steps * pool_size != total_test_raw_candidates:
        raise PreflightError("test step and raw-candidate budgets disagree")

    all_passes = [
        run
        for arm in EXPECTED_ARMS
        for run in repeated_passes[arm]
    ]
    max_pass_seconds_per_step = max(
        run["observational"]["wall_seconds"]
        / run["deterministic"]["steps"]
        for run in all_passes
    )
    preflight_upper_seconds = (
        max_pass_seconds_per_step
        * total_test_steps
        * SAFETY_FACTOR_RUNTIME
    )
    prior_generation = prior["generation"]
    prior_verification = prior["independent_verification"]
    historical_generation_scaled = (
        prior_generation["wall_seconds"]
        / historical_exact_calls
        * total_test_steps
    )
    # Pool/rank/log work and semantic verification are serial in generation.
    # Taking their sum is more conservative than the preregistered slower-of
    # lower bound; the outer max also protects against the prior end-to-end rate.
    projected_generation_seconds = SAFETY_FACTOR_RUNTIME * max(
        preflight_upper_seconds + historical_generation_scaled,
        prior_generation["wall_seconds"]
        / prior_generation["event_count"]
        * total_test_steps,
    )
    projected_independent_verification_seconds = (
        prior_verification["wall_seconds"]
        / prior_verification["event_count"]
        * total_test_steps
        * SAFETY_FACTOR_RUNTIME
    )

    max_log_bytes_per_step = max(
        run["deterministic"]["canonical_log_bytes"]
        / run["deterministic"]["steps"]
        for run in all_passes
    )
    prior_nonledger_bytes = max(
        0,
        prior_generation["run_directory_bytes_before_marker"]
        - historical_event_file_bytes,
    )
    projected_sidecar_bytes = (
        prior_nonledger_bytes
        / prior_generation["event_count"]
        * total_test_steps
    )
    projected_log_bytes = max_log_bytes_per_step * total_test_steps
    projected_run_directory_bytes = math.ceil(
        SAFETY_FACTOR_DISK * (projected_sidecar_bytes + projected_log_bytes)
    )
    projected_peak_rss_bytes = math.ceil(
        max(
            MINIMUM_PROJECTED_RSS_BYTES,
            observed_peak_rss_bytes * SAFETY_FACTOR_RSS,
        )
    )

    gate_checks = {
        "projected_generation_within_preflight_cap": (
            projected_generation_seconds
            <= caps["maximum_projected_generation_seconds"]
        ),
        "projected_generation_within_wall_limit": (
            projected_generation_seconds <= caps["generation_wall_seconds"]
        ),
        "projected_independent_verification_within_wall_limit": (
            projected_independent_verification_seconds
            <= caps["independent_verification_wall_seconds"]
        ),
        "projected_run_directory_within_limit": (
            projected_run_directory_bytes <= caps["run_directory_bytes"]
        ),
        "projected_peak_rss_within_limit": (
            projected_peak_rss_bytes <= caps["peak_resident_memory_bytes"]
        ),
    }
    return {
        "formula": {
            "runtime_safety_factor": SAFETY_FACTOR_RUNTIME,
            "disk_safety_factor": SAFETY_FACTOR_DISK,
            "rss_safety_factor": SAFETY_FACTOR_RSS,
            "generation": (
                "runtime_safety_factor * max("
                "preflight_upper_scaled + prior_generation_exact_scaled,"
                "prior_end_to_end_generation_scaled)"
            ),
            "independent_verification": (
                "runtime_safety_factor * prior_verification_seconds_per_event "
                "* total_test_steps"
            ),
            "disk": (
                "disk_safety_factor * (prior_nonledger_bytes_per_event * "
                "total_test_steps + max_preflight_log_bytes_per_step * "
                "total_test_steps)"
            ),
            "rss": (
                "max(256_MiB, observed_peak_rss_bytes * rss_safety_factor)"
            ),
        },
        "inputs": {
            "historical_exact_calls": historical_exact_calls,
            "historical_event_file_bytes": historical_event_file_bytes,
            "total_test_steps": total_test_steps,
            "total_test_raw_candidates": total_test_raw_candidates,
            "pool_size": pool_size,
            "maximum_observed_pass_seconds_per_step": max_pass_seconds_per_step,
            "maximum_observed_log_bytes_per_step": max_log_bytes_per_step,
            "observed_peak_rss_bytes": observed_peak_rss_bytes,
            "prior_generation_wall_seconds": prior_generation["wall_seconds"],
            "prior_generation_event_count": prior_generation["event_count"],
            "prior_run_directory_bytes_before_marker": prior_generation[
                "run_directory_bytes_before_marker"
            ],
            "prior_independent_verification_wall_seconds": prior_verification[
                "wall_seconds"
            ],
            "prior_independent_verification_event_count": prior_verification[
                "event_count"
            ],
            "inputs_are_observational_and_machine_dependent": True,
        },
        "intermediate": {
            "preflight_repeated_run_upper_seconds": preflight_upper_seconds,
            "historical_generation_exact_scaled_seconds": (
                historical_generation_scaled
            ),
            "projected_sidecar_bytes_before_safety_factor": (
                projected_sidecar_bytes
            ),
            "projected_log_bytes_before_safety_factor": projected_log_bytes,
        },
        "projected": {
            "generation_seconds": projected_generation_seconds,
            "independent_verification_seconds": (
                projected_independent_verification_seconds
            ),
            "run_directory_bytes": projected_run_directory_bytes,
            "peak_resident_memory_bytes": projected_peak_rss_bytes,
        },
        "caps": dict(caps),
        "checks": gate_checks,
        "status": "PASS" if all(gate_checks.values()) else "FAIL_CLOSED",
    }


def _numpy_version() -> str | None:
    try:
        return importlib.metadata.version("numpy")
    except importlib.metadata.PackageNotFoundError:
        return None


def run_preflight(
    *,
    repo_root: Path,
    protocol_path: Path,
    ranker: RankerCallback,
    model_commitment: Mapping[str, Any],
    repetitions: int = DEFAULT_REPETITIONS,
    steps_override_for_tests: int | None = None,
) -> dict[str, Any]:
    """Run the preflight and return a canonical self-hashed report object.

    ``steps_override_for_tests`` exists solely to keep corruption fixtures
    small.  Official CLI execution never exposes it and always requires 4,096.
    """

    if repetitions < 2:
        raise PreflightError("preflight requires at least two repeated passes")
    protocol = load_json_object(protocol_path)
    protocol_info = validate_preflight_protocol(protocol, repo_root)
    steps = (
        protocol_info["steps_per_arm"]
        if steps_override_for_tests is None
        else steps_override_for_tests
    )
    if steps <= 0:
        raise PreflightError("preflight step count must be positive")

    prior = _load_prior_timing_sources(
        training_directory=protocol_info["training_directory"],
        expected_events_sha256=protocol_info["event_sha256"],
        expected_event_count=protocol_info["event_count"],
    )
    registry, registry_summary = load_historical_registry(
        protocol_info["event_path"],
        expected_event_count=protocol_info["event_count"],
        expected_final_event_sha256=prior["final_event_sha256"],
    )

    probe_pool_id, probe_pool, _ = construct_registered_pool(
        registry,
        target=EXPECTED_TARGETS[0],
        step_index=0,
        pool_size=protocol_info["pool_size"],
    )
    ranker_probe_sha = assert_ranker_deterministic(
        ranker,
        _ranker_rows(
            probe_pool,
            pool_id=probe_pool_id,
            target=EXPECTED_TARGETS[0],
            step_index=0,
        ),
    )

    repeated: dict[str, list[dict[str, Any]]] = {
        arm: [] for arm in EXPECTED_ARMS
    }
    for arm in EXPECTED_ARMS:
        for _ in range(repetitions):
            repeated[arm].append(
                benchmark_arm(
                    arm=arm,
                    registry=registry,
                    ranker=ranker,
                    pool_size=protocol_info["pool_size"],
                    steps=steps,
                )
            )
        pass_hashes = {
            run["deterministic"]["pass_sha256"] for run in repeated[arm]
        }
        if len(pass_hashes) != 1:
            raise PreflightError(f"{arm} deterministic pass hash changed")

    observed_rss = _rss_bytes()
    projection = project_resources(
        repeated_passes=repeated,
        prior=prior,
        historical_exact_calls=registry_summary["known_exact_decision_rows"],
        historical_event_file_bytes=protocol_info["event_path"].stat().st_size,
        total_test_steps=protocol_info["total_test_steps"],
        total_test_raw_candidates=protocol_info["total_test_raw_candidates"],
        pool_size=protocol_info["pool_size"],
        observed_peak_rss_bytes=observed_rss,
        caps=protocol_info["resource_gate"],
    )
    official_budget_exercised = steps == protocol_info["steps_per_arm"]
    official_model_bound = (
        model_commitment.get("official_frozen_model_binding") is True
    )
    if projection["status"] == "FAIL_CLOSED":
        report_status = "FAIL_CLOSED"
    elif official_budget_exercised and official_model_bound:
        report_status = "PASS"
    else:
        report_status = "TEST_FIXTURE_ONLY"

    deterministic_replay = {
        "pool_contract": (
            "frozen SHA-256 rejection sampling, lexicographic quotient parent "
            "order, descending Fisher-Yates over 42 source-major arcs, first "
            "16 arcs in permutation order, and registered historical rows as "
            "non-semantic arc-slot proxies"
        ),
        "counter_rng": protocol_info["counter_rng"],
        "preflight_rng_phase": PREFLIGHT_RNG_PHASE,
        "preflight_pair_seed_derivation": (
            "first_8_bytes_sha256(prefix|resource_preflight|pair|pair_index)"
        ),
        "target_schedule": "step_index_modulo_frozen_target_order",
        "ranker_probe_score_hex_sha256": ranker_probe_sha,
        "registry": registry_summary,
        "arms": {
            arm: repeated[arm][0]["deterministic"] for arm in EXPECTED_ARMS
        },
        "repetition_pass_sha256": {
            arm: [
                run["deterministic"]["pass_sha256"] for run in repeated[arm]
            ]
            for arm in EXPECTED_ARMS
        },
    }
    deterministic_replay["deterministic_replay_sha256"] = object_sha256(
        deterministic_replay
    )

    report_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": report_status,
        "paper_evidence": False,
        "semantic_evaluations_performed": 0,
        "validation_or_test_candidates_generated": 0,
        "protocol": {
            "path": str(protocol_path),
            "sha256": file_sha256(protocol_path),
            "schema_version": protocol["schema_version"],
            "status": protocol["status"],
        },
        "historical_source": {
            "events_path": str(protocol_info["event_path"]),
            "events_sha256": protocol_info["event_sha256"],
            "events_file_bytes": protocol_info["event_path"].stat().st_size,
            "prior_timing_sources": prior,
            "known_results_only": True,
        },
        "model": dict(model_commitment),
        "preflight": {
            "steps_per_arm": steps,
            "protocol_steps_per_arm": protocol_info["steps_per_arm"],
            "repetitions": repetitions,
            "pool_size": protocol_info["pool_size"],
            "official_budget_exercised": official_budget_exercised,
            "deterministic_replay": deterministic_replay,
            "observational_timings": {
                arm: [run["observational"] for run in repeated[arm]]
                for arm in EXPECTED_ARMS
            },
        },
        "resource_projection": projection,
        "environment": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "numpy_version": _numpy_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "observed_peak_rss_bytes": observed_rss,
            "environment_fields_are_observational_and_nondeterministic": True,
        },
        "integrity": {
            "registered_training_candidates_only": True,
            "stored_exact_and_quotient_bindings_replayed": True,
            "new_semantic_evaluation_allowed": False,
            "ranker_callback_deterministic_on_probe": True,
            "all_pool_candidates_canonically_logged": True,
            "global_hash_chain_exercised": True,
            "resource_caps_fail_closed": True,
        },
    }
    return add_self_hash(report_payload, "report_sha256")


def verify_report(report: Mapping[str, Any]) -> None:
    verify_self_hash(report, "report_sha256", context="preflight report")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise PreflightError("preflight report schema changed")
    if report.get("semantic_evaluations_performed") != 0:
        raise PreflightError("preflight report claims a semantic evaluation")
    if report.get("validation_or_test_candidates_generated") != 0:
        raise PreflightError("preflight report claims fresh candidates")
    projection = report.get("resource_projection")
    if not isinstance(projection, Mapping):
        raise PreflightError("preflight report lacks resource projection")
    checks = projection.get("checks")
    projection_status = (
        "PASS"
        if isinstance(checks, Mapping) and checks and all(checks.values())
        else "FAIL_CLOSED"
    )
    if projection.get("status") != projection_status:
        raise PreflightError("preflight gate status does not match checks")
    preflight = report.get("preflight")
    model = report.get("model")
    official = (
        isinstance(preflight, Mapping)
        and preflight.get("official_budget_exercised") is True
        and isinstance(model, Mapping)
        and model.get("official_frozen_model_binding") is True
    )
    expected_report_status = (
        "FAIL_CLOSED"
        if projection_status == "FAIL_CLOSED"
        else ("PASS" if official else "TEST_FIXTURE_ONLY")
    )
    if report.get("status") != expected_report_status:
        raise PreflightError("preflight report status does not match official gates")


def _resolve_binding_path(binding_path: Path, supplied: Any, *, field: str) -> Path:
    if not isinstance(supplied, str) or not supplied:
        raise PreflightError(f"model binding {field} path is missing")
    path = Path(supplied)
    if not path.is_absolute():
        path = binding_path.parent / path
    return path.resolve()


def load_official_ranker(
    binding_path: Path,
    *,
    protocol_sha256: str,
    required_binding_fields: Iterable[str],
) -> tuple[RankerCallback, dict[str, Any]]:
    """Load the bound official adapter; fixture stubs are structurally barred."""

    binding = load_json_object(binding_path, canonical_line=True)
    verify_self_hash(
        binding, "binding_sha256", context="official model binding"
    )
    required_top = {
        "schema_version",
        "status",
        "protocol_sha256",
        "ensemble",
        "ranker",
        "protocol_model_bindings",
        "binding_sha256",
    }
    _require_keys(binding, required_top, context="model binding", exact=True)
    if binding["schema_version"] != MODEL_BINDING_SCHEMA:
        raise PreflightError("unsupported model-binding schema")
    if binding["status"] != "FROZEN":
        raise PreflightError("official model binding is not frozen")
    if binding["protocol_sha256"] != protocol_sha256:
        raise PreflightError("official model binding targets another protocol")

    ensemble = binding["ensemble"]
    ranker_binding = binding["ranker"]
    protocol_bindings = binding["protocol_model_bindings"]
    if not all(
        isinstance(value, Mapping)
        for value in (ensemble, ranker_binding, protocol_bindings)
    ):
        raise PreflightError("official model-binding sections are malformed")
    _require_keys(
        ensemble,
        {"path", "file_sha256", "model_id"},
        context="ensemble binding",
        exact=True,
    )
    _require_keys(
        ranker_binding,
        {
            "kind",
            "source_path",
            "source_sha256",
            "factory_callable",
        },
        context="ranker binding",
        exact=True,
    )
    if ranker_binding["kind"] != "frozen_model_adapter":
        raise PreflightError("test fixture rankers cannot satisfy official binding")
    if set(protocol_bindings) != set(required_binding_fields):
        raise PreflightError("protocol model-binding fields are incomplete")
    for field in required_binding_fields:
        value = protocol_bindings[field]
        if field == "training_seeds":
            if not isinstance(value, list) or not value:
                raise PreflightError("bound training seeds are malformed")
        elif not isinstance(value, str) or not value:
            raise PreflightError(f"bound protocol model field {field} is malformed")
        elif field.endswith("_sha256") and not is_sha256(value):
            raise PreflightError(f"bound protocol model field {field} is not SHA-256")

    ensemble_path = _resolve_binding_path(
        binding_path, ensemble["path"], field="ensemble"
    )
    source_path = _resolve_binding_path(
        binding_path, ranker_binding["source_path"], field="ranker source"
    )
    if not ensemble_path.is_file() or not source_path.is_file():
        raise PreflightError("bound ensemble or ranker source is missing")
    observed_ensemble_sha = file_sha256(ensemble_path)
    observed_source_sha = file_sha256(source_path)
    if observed_ensemble_sha != ensemble["file_sha256"]:
        raise PreflightError("bound ensemble file SHA-256 changed")
    if observed_source_sha != ranker_binding["source_sha256"]:
        raise PreflightError("bound ranker source SHA-256 changed")
    ensemble_value = load_json_object(ensemble_path)
    if ensemble_value.get("model_id") != ensemble["model_id"]:
        raise PreflightError("bound ensemble model ID changed")
    if protocol_bindings.get("checkpoint_sha256") != observed_ensemble_sha:
        raise PreflightError("checkpoint SHA-256 does not bind ensemble file")

    module_name = (
        "_partizan_resource_preflight_adapter_"
        + observed_source_sha[:16]
    )
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise PreflightError("could not load bound ranker adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    factory_name = ranker_binding["factory_callable"]
    factory = getattr(module, factory_name, None)
    if not callable(factory):
        raise PreflightError("bound ranker factory is not callable")
    callback = factory(
        model_artifact_path=ensemble_path,
        model_id=ensemble["model_id"],
    )
    if not callable(callback):
        raise PreflightError("bound ranker factory did not return a callback")

    commitment = {
        "binding_path": str(binding_path),
        "binding_file_sha256": file_sha256(binding_path),
        "binding_sha256": binding["binding_sha256"],
        "ensemble_path": str(ensemble_path),
        "ensemble_file_sha256": observed_ensemble_sha,
        "ensemble_model_id": ensemble["model_id"],
        "ranker_source_path": str(source_path),
        "ranker_source_sha256": observed_source_sha,
        "ranker_factory_callable": factory_name,
        "protocol_model_bindings": dict(protocol_bindings),
        "official_frozen_model_binding": True,
    }
    return callback, commitment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--protocol", type=Path, default=Path(DEFAULT_PROTOCOL))
    parser.add_argument("--model-binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    protocol_path = (
        args.protocol
        if args.protocol.is_absolute()
        else repo_root / args.protocol
    ).resolve()
    protocol = load_json_object(protocol_path)
    protocol_info = validate_preflight_protocol(protocol, repo_root)
    ranker, commitment = load_official_ranker(
        args.model_binding.resolve(),
        protocol_sha256=file_sha256(protocol_path),
        required_binding_fields=protocol_info["required_model_bindings"],
    )
    report = run_preflight(
        repo_root=repo_root,
        protocol_path=protocol_path,
        ranker=ranker,
        model_commitment=commitment,
        repetitions=args.repetitions,
    )
    verify_report(report)
    output = (
        args.output if args.output.is_absolute() else repo_root / args.output
    ).resolve()
    write_report_exclusive(output, report)
    print(f"{report['status']}: wrote {output}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PreflightError) as error:
        print(f"INCOMPLETE_FAIL: {error}", file=sys.stderr)
        raise SystemExit(2)
