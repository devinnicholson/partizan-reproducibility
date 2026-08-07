#!/usr/bin/env python3
"""Reduce the independently replayed Domineering scope evaluation."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from fixed_value_scope_protocol_v1 import artifact_sha256, canonical_json_bytes, load_json
from train_domineering_scope_v1 import file_sha256


POLICIES = (
    "uniform_random_without_replacement",
    "neural_equality_only",
    "neural_equality_plus_ruleset_novelty",
)


def interval(values: np.ndarray) -> list[float]:
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_PROTOCOL.json"))
    parser.add_argument("--analysis", type=Path, default=Path("docs/research/FIXED_VALUE_SCOPE_EXTENSION_V1_4_ANALYSIS.json"))
    parser.add_argument("--evaluation-dir", type=Path, default=Path("output/research/fixed-value-scope-v1/evaluation"))
    args = parser.parse_args()
    protocol = load_json(args.protocol)
    analysis = load_json(args.analysis)
    evaluation = load_json(args.evaluation_dir / "EVALUATION_AUTHORITY_V1.json")
    replay = load_json(args.evaluation_dir / "REPLAY_AUTHORITY_V1.json")
    for value, label in ((analysis, "analysis"), (evaluation, "evaluation"), (replay, "replay")):
        if value.get("artifact_sha256") != artifact_sha256(value):
            raise ValueError(f"{label} authority hash differs")
    if replay.get("status") != "PASS" or replay.get("artifact_sha256") != analysis["replay_authority_artifact_sha256"]:
        raise ValueError("replay did not authorize reduction")
    events_path = args.evaluation_dir / evaluation["events_file"]["path"]
    if file_sha256(events_path) != evaluation["events_file"]["file_sha256"]:
        raise ValueError("event file hash differs before reduction")

    cells: dict[tuple[str, str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "call_count": 0,
            "certified_literal_count": 0,
            "ruleset_quotients": set(),
            "unsigned_shape_quotients": set(),
        }
    )
    with events_path.open("rb") as handle:
        for raw in handle:
            event = json.loads(raw)
            key = (event["policy_id"], event["target_id"], int(event["acquisition_seed"]))
            cell = cells[key]
            cell["call_count"] += 1
            if event["exact_equal_verdict"]:
                cell["certified_literal_count"] += 1
                cell["ruleset_quotients"].add(event["ruleset_quotient"])
                cell["unsigned_shape_quotients"].add(event["unsigned_shape_quotient"])

    targets = protocol["cross_family_experiment"]["targets"]
    seeds = protocol["cross_family_experiment"]["evaluation_seeds"]
    expected_budget = protocol["cross_family_experiment"]["evaluation_budget"]["calls_per_policy_target_seed"]
    cell_rows = []
    for policy in POLICIES:
        for target in targets:
            for seed in seeds:
                cell = cells[(policy, target["target_id"], seed)]
                if cell["call_count"] != expected_budget:
                    raise ValueError("policy-target-seed call count differs")
                cell_rows.append(
                    {
                        "policy_id": policy,
                        "target_id": target["target_id"],
                        "sign_class": target["sign_class"],
                        "acquisition_seed": seed,
                        "call_count": cell["call_count"],
                        "certified_literal_count": cell["certified_literal_count"],
                        "certified_ruleset_quotient_count": len(cell["ruleset_quotients"]),
                        "certified_unsigned_shape_quotient_count": len(cell["unsigned_shape_quotients"]),
                        "exact_equality_rate": cell["certified_literal_count"] / cell["call_count"],
                    }
                )

    arm_metrics = {}
    for policy in POLICIES:
        rows = [row for row in cell_rows if row["policy_id"] == policy]
        arm_metrics[policy] = {
            "policy_target_seed_cell_count": len(rows),
            "mean_certified_literals": float(np.mean([row["certified_literal_count"] for row in rows])),
            "mean_certified_ruleset_quotients": float(np.mean([row["certified_ruleset_quotient_count"] for row in rows])),
            "mean_certified_unsigned_shape_quotients": float(np.mean([row["certified_unsigned_shape_quotient_count"] for row in rows])),
            "exact_equality_rate": float(sum(row["certified_literal_count"] for row in rows) / sum(row["call_count"] for row in rows)),
            "target_seed_coverage": float(np.mean([row["certified_literal_count"] > 0 for row in rows])),
        }

    target_metrics: dict[str, dict[str, dict[str, float]]] = {}
    for target in targets:
        target_metrics[target["target_id"]] = {}
        for policy in POLICIES:
            rows = [
                row
                for row in cell_rows
                if row["target_id"] == target["target_id"] and row["policy_id"] == policy
            ]
            target_metrics[target["target_id"]][policy] = {
                "mean_certified_literals": float(np.mean([row["certified_literal_count"] for row in rows])),
                "mean_certified_ruleset_quotients": float(np.mean([row["certified_ruleset_quotient_count"] for row in rows])),
            }

    q_random = np.asarray([target_metrics[target["target_id"]][POLICIES[0]]["mean_certified_ruleset_quotients"] for target in targets])
    q_equality = np.asarray([target_metrics[target["target_id"]][POLICIES[1]]["mean_certified_ruleset_quotients"] for target in targets])
    q_novelty = np.asarray([target_metrics[target["target_id"]][POLICIES[2]]["mean_certified_ruleset_quotients"] for target in targets])
    l_equality = np.asarray([target_metrics[target["target_id"]][POLICIES[1]]["mean_certified_literals"] for target in targets])
    l_novelty = np.asarray([target_metrics[target["target_id"]][POLICIES[2]]["mean_certified_literals"] for target in targets])
    bootstrap_seed = int.from_bytes(
        hashlib.sha256(
            b"partizan.domineering_scope_bootstrap.v1\n"
            + analysis["execution_artifact_sha256"].encode("ascii")
        ).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(bootstrap_seed)
    repetitions = analysis["bootstrap"]["repetitions"]
    sampled = rng.integers(0, len(targets), size=(repetitions, len(targets)))
    novelty_minus_equality = np.mean((q_novelty - q_equality)[sampled], axis=1)
    novelty_minus_random = np.mean((q_novelty - q_random)[sampled], axis=1)
    literal_ratio = np.mean(l_novelty[sampled], axis=1) / np.mean(l_equality[sampled], axis=1)
    effects = {
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
            "bootstrap_interval": interval(literal_ratio),
        },
    }
    readiness = {
        "all_target_policy_seed_cells_have_a_certificate": all(row["certified_literal_count"] > 0 for row in cell_rows),
        "novelty_minus_equality_ci_lower_greater_than_zero": effects["novelty_minus_equality_ruleset_quotients"]["bootstrap_interval"][0] > 0,
        "novelty_minus_random_ci_lower_greater_than_zero": effects["novelty_minus_random_ruleset_quotients"]["bootstrap_interval"][0] > 0,
        "novelty_to_equality_literal_ratio_ci_lower_at_least_0_9": effects["novelty_to_equality_certified_literal_ratio"]["bootstrap_interval"][0] >= 0.9,
        "zero_resource_failures": evaluation["resource_failure_count"] == 0,
    }
    result = {
        "schema_version": "partizan.fixed_value_scope_result.v1",
        "status": "SCOPE_EXTENSION_READY" if all(readiness.values()) else "SCOPE_EXTENSION_NOT_READY",
        "protocol_artifact_sha256": protocol["artifact_sha256"],
        "analysis_artifact_sha256": analysis["artifact_sha256"],
        "evaluation_authority_artifact_sha256": evaluation["artifact_sha256"],
        "replay_authority_artifact_sha256": replay["artifact_sha256"],
        "exact_verifier_call_count": evaluation["exact_verifier_call_count"],
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_repetitions": repetitions,
        "arm_metrics": arm_metrics,
        "effects": effects,
        "readiness": readiness,
        "target_metrics": target_metrics,
        "cell_rows": cell_rows,
        "paper_state_changed": False,
        "v5_test_material_opened": False,
        "modal_used": False,
    }
    result["artifact_sha256"] = artifact_sha256(result)
    output = args.evaluation_dir / "SCOPE_RESULT_AUTHORITY_V1.json"
    output.write_bytes(canonical_json_bytes(result) + b"\n")
    summary = {key: value for key, value in result.items() if key not in {"target_metrics", "cell_rows"}}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result["status"] == "SCOPE_EXTENSION_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
