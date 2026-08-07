#!/usr/bin/env python3
"""Validation helpers for the prospective fixed-value scope protocol v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from domineering_exact_v1 import (
    DomineeringPosition,
    game_from_position,
    literal_code,
    ruleset_quotient,
)
from short_game_fiber_pilot import Game, birthday, equal, game_digest, leq


SCHEMA = "partizan.fixed_value_scope_extension_protocol.v1"
CANDIDATE_DOMAIN = b"partizan.domineering_scope_candidate.v1\n"


class ProtocolError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise ProtocolError("protocol root must be an object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def artifact_sha256(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("artifact_sha256", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def candidate_bucket(position: DomineeringPosition) -> int:
    digest = hashlib.sha256(CANDIDATE_DOMAIN + literal_code(position).encode("ascii"))
    return int.from_bytes(digest.digest(), "big") % 100


def _sign_class(game: Game) -> str:
    zero = Game.make()
    if equal(game, zero):
        return "zero"
    zero_leq_game = leq(zero, game)
    game_leq_zero = leq(game, zero)
    if zero_leq_game and not game_leq_zero:
        return "positive"
    if game_leq_zero and not zero_leq_game:
        return "negative"
    return "fuzzy"


def calibration_classes() -> list[list[tuple[Game, DomineeringPosition]]]:
    classes: list[list[tuple[Game, DomineeringPosition]]] = []
    for mask in range(1 << 9):
        position = DomineeringPosition(3, 3, mask)
        game = game_from_position(position)
        for members in classes:
            if equal(game, members[0][0]):
                members.append((game, position))
                break
        else:
            classes.append([(game, position)])
    return classes


def derive_target_roster() -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for members in calibration_classes():
        game = members[0][0]
        quotient_count = len(
            {ruleset_quotient(position) for _, position in members}
        )
        if quotient_count < 3:
            continue
        eligible.append(
            {
                "birthday": birthday(game),
                "calibration_literal_count": len(members),
                "calibration_representative_mask": min(
                    position.mask for _, position in members
                ),
                "calibration_ruleset_quotient_count": quotient_count,
                "game_sha256": game_digest(game),
                "sign_class": _sign_class(game),
            }
        )

    selected: list[dict[str, Any]] = []
    for sign_class, count in (
        ("zero", 1),
        ("positive", 3),
        ("negative", 3),
        ("fuzzy", 5),
    ):
        candidates = sorted(
            (row for row in eligible if row["sign_class"] == sign_class),
            key=lambda row: (
                -row["calibration_ruleset_quotient_count"],
                row["game_sha256"],
            ),
        )
        if len(candidates) < count:
            raise ProtocolError(f"insufficient {sign_class} calibration targets")
        selected.extend(candidates[:count])

    for index, row in enumerate(selected):
        row["target_id"] = f"dom-v1-{index:02d}"
    return selected


def validate_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if protocol.get("schema_version") != SCHEMA:
        failures.append("schema version differs")
    calculated = artifact_sha256(protocol)
    if protocol.get("artifact_sha256") != calculated:
        failures.append("artifact SHA-256 differs")

    experiment = protocol.get("cross_family_experiment", {})
    if experiment.get("targets") != derive_target_roster():
        failures.append("target roster does not replay from the 3x3 calibration universe")

    budget = experiment.get("evaluation_budget", {})
    calculated_calls = (
        int(budget.get("calls_per_policy_target_seed", -1))
        * int(budget.get("policy_count", -1))
        * int(budget.get("seed_count", -1))
        * int(budget.get("target_count", -1))
    )
    if calculated_calls != 221_184 or budget.get("total_exact_verifier_calls") != calculated_calls:
        failures.append("evaluation call contract differs")

    bucket_counts = [0] * 100
    for mask in range(1 << 16):
        bucket_counts[candidate_bucket(DomineeringPosition(4, 4, mask))] += 1
    benchmark = protocol.get("resource_benchmark", {})
    if bucket_counts[0] != benchmark.get("candidate_count"):
        failures.append("benchmark candidate count differs")
    if bucket_counts[0] * len(experiment.get("targets", [])) != benchmark.get("call_count"):
        failures.append("benchmark call count differs")

    boundary = protocol.get("information_boundary", {})
    if boundary.get("v5_test_material_opened") is not False:
        failures.append("V5 test boundary differs")
    if boundary.get("partial_evaluation_metrics_opened") is not False:
        failures.append("partial evaluation boundary differs")

    return {
        "schema_version": "partizan.fixed_value_scope_protocol_validation.v1",
        "status": "PASS" if not failures else "FAIL",
        "protocol_artifact_sha256": calculated,
        "calibration_position_count": 512,
        "calibration_value_count": len(calibration_classes()),
        "selected_target_count": len(experiment.get("targets", [])),
        "candidate_partition_counts": {
            "benchmark": bucket_counts[0],
            "training": sum(bucket_counts[1:26]),
            "tuning": sum(bucket_counts[26:41]),
            "evaluation": sum(bucket_counts[41:]),
        },
        "failures": failures,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json"),
    )
    args = parser.parse_args()
    result = validate_protocol(load_json(args.protocol))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

