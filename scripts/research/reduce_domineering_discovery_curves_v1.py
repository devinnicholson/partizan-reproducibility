#!/usr/bin/env python3
"""Compute frozen prefix-budget discovery curves from terminal events."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from fixed_value_scope_protocol_v1 import artifact_sha256, canonical_json_bytes, load_json


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def interval(values: np.ndarray) -> list[float]:
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def cell_prefix_metrics(events: list[dict[str, Any]], budget: int) -> dict[str, float | int]:
    prefix = [row for row in events if int(row["proposal_rank"]) < budget]
    if len(prefix) != budget or {int(row["proposal_rank"]) for row in prefix} != set(range(budget)):
        raise ValueError("cell prefix is incomplete or has duplicate ranks")
    exact = [row for row in prefix if row["exact_equal_verdict"]]
    return {
        "call_count": budget,
        "certified_literal_count": len(exact),
        "certified_ruleset_quotient_count": len({row["ruleset_quotient"] for row in exact}),
        "certified_unsigned_shape_quotient_count": len({row["unsigned_shape_quotient"] for row in exact}),
        "exact_equality_rate": len(exact) / budget,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_SCOPE_DISCOVERY_CURVES_V1_PROTOCOL.json"),
    )
    parser.add_argument(
        "--scope-protocol",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json"),
    )
    parser.add_argument(
        "--evaluation-authority",
        type=Path,
        default=Path("output/research/fixed-value-scope-v1/evaluation/EVALUATION_AUTHORITY_V1.json"),
    )
    parser.add_argument(
        "--scope-result",
        type=Path,
        default=Path("output/research/fixed-value-scope-v1/evaluation/SCOPE_RESULT_AUTHORITY_V1.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/research/fixed-value-scope-v1/validation-v1"),
    )
    args = parser.parse_args()
    analysis = load_json(args.protocol)
    scope_protocol = load_json(args.scope_protocol)
    evaluation = load_json(args.evaluation_authority)
    scope_result = load_json(args.scope_result)
    for value, label in ((analysis, "analysis protocol"), (scope_protocol, "scope protocol"), (evaluation, "evaluation"), (scope_result, "scope result")):
        if value.get("artifact_sha256") != artifact_sha256(value):
            raise ValueError(f"{label} hash differs")
    events_path = args.evaluation_authority.parent / evaluation["events_file"]["path"]
    if file_sha256(events_path) != analysis["event_file_sha256"]:
        raise ValueError("event stream hash differs")

    cells: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    with events_path.open("rb") as handle:
        for raw in handle:
            event = json.loads(raw)
            key = (event["policy_id"], event["target_id"], int(event["acquisition_seed"]))
            cells[key].append(event)

    targets = scope_protocol["cross_family_experiment"]["targets"]
    policies = tuple(analysis["policies"])
    seeds = tuple(analysis["acquisition_seeds"])
    budgets = tuple(analysis["prefix_budgets"])
    expected_cells = {
        (policy, target["target_id"], seed)
        for policy in policies
        for target in targets
        for seed in seeds
    }
    if set(cells) != expected_cells:
        raise ValueError("event stream cell coverage differs")
    rows: list[dict[str, Any]] = []
    for budget in budgets:
        for policy in policies:
            for target in targets:
                for seed in seeds:
                    metrics = cell_prefix_metrics(cells[(policy, target["target_id"], seed)], budget)
                    rows.append(
                        {
                            "budget": budget,
                            "policy_id": policy,
                            "target_id": target["target_id"],
                            "sign_class": target["sign_class"],
                            "acquisition_seed": seed,
                            **metrics,
                        }
                    )

    rng = np.random.default_rng(int(analysis["uncertainty"]["bootstrap_seed"]))
    repetitions = int(analysis["uncertainty"]["bootstrap_repetitions"])
    random_policy, equality_policy, novelty_policy = policies
    curve_rows: list[dict[str, Any]] = []
    effects: dict[str, Any] = {}
    for budget in budgets:
        budget_rows = [row for row in rows if row["budget"] == budget]
        for policy in policies:
            arm = [row for row in budget_rows if row["policy_id"] == policy]
            curve_rows.append(
                {
                    "budget": budget,
                    "policy_id": policy,
                    "mean_certified_literals": float(np.mean([row["certified_literal_count"] for row in arm])),
                    "mean_certified_ruleset_quotients": float(np.mean([row["certified_ruleset_quotient_count"] for row in arm])),
                    "mean_certified_unsigned_shape_quotients": float(np.mean([row["certified_unsigned_shape_quotient_count"] for row in arm])),
                    "exact_equality_rate": float(sum(row["certified_literal_count"] for row in arm) / sum(row["call_count"] for row in arm)),
                }
            )

        target_values: dict[str, dict[str, tuple[float, float]]] = {}
        for target in targets:
            target_values[target["target_id"]] = {}
            for policy in policies:
                arm = [
                    row for row in budget_rows
                    if row["policy_id"] == policy and row["target_id"] == target["target_id"]
                ]
                target_values[target["target_id"]][policy] = (
                    float(np.mean([row["certified_ruleset_quotient_count"] for row in arm])),
                    float(np.mean([row["certified_literal_count"] for row in arm])),
                )
        q_random = np.asarray([target_values[target["target_id"]][random_policy][0] for target in targets])
        q_equality = np.asarray([target_values[target["target_id"]][equality_policy][0] for target in targets])
        q_novelty = np.asarray([target_values[target["target_id"]][novelty_policy][0] for target in targets])
        l_equality = np.asarray([target_values[target["target_id"]][equality_policy][1] for target in targets])
        l_novelty = np.asarray([target_values[target["target_id"]][novelty_policy][1] for target in targets])
        sampled = rng.integers(0, len(targets), size=(repetitions, len(targets)))
        novelty_minus_equality = np.mean((q_novelty - q_equality)[sampled], axis=1)
        novelty_minus_random = np.mean((q_novelty - q_random)[sampled], axis=1)
        novelty_literals = np.mean(l_novelty[sampled], axis=1)
        equality_literals = np.mean(l_equality[sampled], axis=1)
        ratio = np.divide(
            novelty_literals,
            equality_literals,
            out=np.full_like(novelty_literals, np.nan),
            where=equality_literals != 0,
        )
        effects[str(budget)] = {
            "novelty_minus_equality_ruleset_quotients": {
                "estimate": float(np.mean(q_novelty - q_equality)),
                "bootstrap_interval": interval(novelty_minus_equality),
            },
            "novelty_minus_random_ruleset_quotients": {
                "estimate": float(np.mean(q_novelty - q_random)),
                "bootstrap_interval": interval(novelty_minus_random),
            },
            "novelty_to_equality_certified_literal_ratio": {
                "estimate": float(np.mean(l_novelty) / np.mean(l_equality)),
                "bootstrap_interval": interval(ratio[np.isfinite(ratio)]),
            },
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "DISCOVERY_CURVES_V1.csv"
    with csv_path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(curve_rows[0]))
        writer.writeheader()
        writer.writerows(curve_rows)
    terminal_rows = {
        row["policy_id"]: row for row in curve_rows if row["budget"] == budgets[-1]
    }
    terminal_matches = True
    for policy in policies:
        expected = scope_result["arm_metrics"][policy]
        observed = terminal_rows[policy]
        for observed_key, expected_key in (
            ("mean_certified_literals", "mean_certified_literals"),
            ("mean_certified_ruleset_quotients", "mean_certified_ruleset_quotients"),
            ("mean_certified_unsigned_shape_quotients", "mean_certified_unsigned_shape_quotients"),
            ("exact_equality_rate", "exact_equality_rate"),
        ):
            terminal_matches &= bool(np.isclose(observed[observed_key], expected[expected_key]))
    checks = {
        "all_prefixes_complete": len(rows) == len(budgets) * len(policies) * len(targets) * len(seeds),
        "terminal_budget_matches_primary_result": budgets[-1] == 2048,
        "terminal_arm_metrics_match_primary_result": terminal_matches,
        "event_cell_coverage_matches_contract": set(cells) == expected_cells,
        "event_count_matches_primary_contract": sum(len(value) for value in cells.values()) == 221_184,
        "zero_new_verifier_calls": True,
        "v5_test_material_remained_sealed": True,
    }
    result = {
        "schema_version": "partizan.domineering_discovery_curves_authority.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "protocol_artifact_sha256": analysis["artifact_sha256"],
        "scope_result_artifact_sha256": analysis["scope_result_artifact_sha256"],
        "evaluation_authority_artifact_sha256": evaluation["artifact_sha256"],
        "event_file_sha256": analysis["event_file_sha256"],
        "prefix_budgets": list(budgets),
        "bootstrap_repetitions": repetitions,
        "bootstrap_seed": int(analysis["uncertainty"]["bootstrap_seed"]),
        "curve_file_sha256": file_sha256(csv_path),
        "curve_rows": curve_rows,
        "effects": effects,
        "checks": checks,
        "scientific_role": "post-hoc secondary analysis of frozen event prefixes",
        "new_exact_verifier_calls": 0,
        "paper_state_changed": False,
        "v5_test_material_opened": False,
        "modal_used": False,
    }
    result["artifact_sha256"] = artifact_sha256(result)
    output = args.output_dir / "DISCOVERY_CURVES_AUTHORITY_V1.json"
    output.write_bytes(canonical_json_bytes(result) + b"\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
