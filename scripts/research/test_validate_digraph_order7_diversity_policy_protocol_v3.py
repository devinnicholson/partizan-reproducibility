#!/usr/bin/env python3
"""Mutation tests for the frozen diversity-policy V3 protocol."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import validate_digraph_order7_diversity_policy_protocol_v3 as validator


REPO_ROOT = Path(__file__).resolve().parents[2]


def changed(protocol: dict) -> dict:
    return copy.deepcopy(protocol)


def main() -> int:
    protocol = json.loads((REPO_ROOT / validator.PROTOCOL_PATH).read_bytes())
    positive = validator.validate(
        protocol,
        REPO_ROOT,
        check_bound_files=True,
    )
    if positive:
        raise AssertionError(f"positive V3 protocol failed: {positive}")
    mutations: list[tuple[str, dict]] = []

    value = changed(protocol)
    value["schema_version"] = "partizan.invalid"
    mutations.append(("schema_version", value))

    value = changed(protocol)
    value["status"] = "TEST_GENERATED"
    mutations.append(("pre_outcome_status", value))

    value = changed(protocol)
    value["repair_scope"]["changed"].append("model")
    mutations.append(("repair_scope", value))

    value = changed(protocol)
    value["repair_scope"]["v2_outcome_used_for_model_training"] = True
    mutations.append(("v2_training_reuse", value))

    value = changed(protocol)
    value["repair_scope"]["unchanged"].remove("scientific_thresholds")
    mutations.append(("threshold_thaw", value))

    value = changed(protocol)
    value["domain"]["proposal_operator"] = "toggle_two_arcs"
    mutations.append(("operator_confound", value))

    value = changed(protocol)
    value["initialization"][
        "minimum_weakly_connected_nonprior_candidate_neighbors"
    ] = 31
    mutations.append(("support_threshold", value))

    value = changed(protocol)
    value["initialization"]["shared_across_arms"] = False
    mutations.append(("unpaired_initialization", value))

    value = changed(protocol)
    value["initialization"]["neighbor_exact_value_used_for_selection"] = True
    mutations.append(("initialization_oracle", value))

    value = changed(protocol)
    value["arms"].pop()
    mutations.append(("arm_omission", value))

    value = changed(protocol)
    value["arms"][0]["uses_equality_model"] = True
    mutations.append(("control_model_access", value))

    value = changed(protocol)
    value["models"]["novelty"] = "different-model"
    mutations.append(("model_thaw", value))

    value = changed(protocol)
    value["models"]["lambda"] = 1.0
    mutations.append(("lambda_thaw", value))

    value = changed(protocol)
    value["models"]["online_parameter_updates"] = True
    mutations.append(("online_update", value))

    value = changed(protocol)
    value["structural_filter"]["has_graph_quotient_access"] = True
    mutations.append(("quotient_oracle", value))

    value = changed(protocol)
    value["structural_filter"]["tiers"][0].remove("candidate_new_to_arm")
    mutations.append(("tier_drift", value))

    value = changed(protocol)
    value["acquisition"]["literal_digest_or_quotient_in_memory"] = True
    mutations.append(("memory_oracle", value))

    value = changed(protocol)
    value["splits"]["validation"]["pair_seeds"][0] += 1
    mutations.append(("validation_seed", value))

    value = changed(protocol)
    value["splits"]["test"]["pair_seeds"][0] += 1
    mutations.append(("test_seed", value))

    value = changed(protocol)
    value["splits"]["test"]["pair_seeds"][0] = value["splits"]["validation"][
        "pair_seeds"
    ][0]
    mutations.append(("split_overlap", value))

    value = changed(protocol)
    value["budget"]["validation_exact_verifier_calls"] -= 1
    mutations.append(("validation_budget", value))

    value = changed(protocol)
    value["budget"]["test_exact_verifier_calls"] -= 1
    mutations.append(("test_budget", value))

    value = changed(protocol)
    value["validation_gate"]["first_pool_tier_zero_for_every_stream"] = False
    mutations.append(("validation_gate", value))

    value = changed(protocol)
    value["primary_analysis"]["quotient_noninferiority"][
        "zero_denominator_rule"
    ] = "pass"
    mutations.append(("zero_denominator", value))

    value = changed(protocol)
    value["primary_analysis"]["interval"]["resamples"] = 1000
    mutations.append(("bootstrap_lowering", value))

    value = changed(protocol)
    value["pareto_restoration_gate"][
        "minimum_quotient_relative_lift_to_random"
    ] = 0.0
    mutations.append(("gate_lowering", value))

    value = changed(protocol)
    value["pareto_restoration_gate"][
        "nonzero_quotient_and_literal_support_every_arm_and_target"
    ] = False
    mutations.append(("support_gate_omission", value))

    value = changed(protocol)
    value["integrity"]["corruption_family_count"] = 29
    mutations.append(("corruption_omission", value))

    value = changed(protocol)
    value["resource_gate"]["run_directory_bytes"] *= 2
    mutations.append(("resource_drift", value))

    value = changed(protocol)
    value["claim_boundary"]["v2_deadlock_no_go_must_be_disclosed"] = False
    mutations.append(("v2_disclosure_removed", value))

    if len(mutations) != 30:
        raise AssertionError(f"expected 30 mutations, got {len(mutations)}")
    for name, mutation in mutations:
        errors = validator.validate(
            mutation,
            REPO_ROOT,
            check_bound_files=True,
        )
        if not errors:
            raise AssertionError(f"mutation escaped: {name}")
        print(f"rejected {name}")
    print("positive V3 protocol passed; 30 negative controls rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
