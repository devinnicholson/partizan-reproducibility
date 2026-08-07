#!/usr/bin/env python3
"""Semantic validator for the frozen diversity-policy V3 protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256


PROTOCOL_PATH = Path(
    "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PROTOCOL.json"
)
SCHEMA_PATH = Path(
    "docs/research/digraph-order7-diversity-policy-v3.protocol.schema.json"
)
V1_PROTOCOL = Path(
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"
)
V2_PROTOCOL = Path(
    "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json"
)
TARGETS = ("0", "*", "{0|1}")
ARMS = (
    "structural_toggle_one_random",
    "neural_toggle_one_equality",
    "neural_toggle_one_equality_novelty",
)
SEED_PREFIX = "partizan.digraph_order7_policy_v3.split.v1"
EXPECTED_TOP_LEVEL = {
    "schema_version",
    "status",
    "freeze_date",
    "preregistration_path",
    "repair_scope",
    "source_evidence",
    "domain",
    "initialization",
    "arms",
    "models",
    "structural_filter",
    "acquisition",
    "splits",
    "budget",
    "validation_gate",
    "primary_analysis",
    "pareto_restoration_gate",
    "integrity",
    "resource_gate",
    "failure_policy",
    "claim_boundary",
}


def canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_line(value):
        raise ValueError(f"{path}: expected canonical newline JSON")
    return value


def embedded_hash_valid(value: Mapping[str, Any], field: str) -> bool:
    payload = dict(value)
    supplied = payload.pop(field, None)
    return supplied == object_sha256(payload)


def split_seed(split: str, index: int) -> int:
    return int.from_bytes(
        hashlib.sha256(
            f"{SEED_PREFIX}|{split}|pair|{index}".encode("ascii")
        ).digest()[:8],
        "big",
    )


def validate(
    protocol: Mapping[str, Any],
    repo_root: Path,
    *,
    check_bound_files: bool,
) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(
        set(protocol) == EXPECTED_TOP_LEVEL,
        "top-level schema keys changed",
    )
    require(
        protocol.get("schema_version")
        == "partizan.digraph_order7_diversity_policy_protocol.v3",
        "schema version changed",
    )
    require(
        protocol.get("status")
        == "DESIGN_FROZEN_VALIDATION_AND_TEST_DATA_NOT_GENERATED",
        "pre-outcome status changed",
    )
    require(protocol.get("freeze_date") == "2026-07-27", "freeze date changed")
    prereg_path = Path(str(protocol.get("preregistration_path", "")))
    require(
        prereg_path
        == Path(
            "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PREREGISTRATION.md"
        ),
        "preregistration path changed",
    )
    repair = protocol.get("repair_scope", {})
    require(
        repair.get("changed") == ["pair_specific_historical_exact_initialization"],
        "repair scope expanded",
    )
    require(
        all(
            repair.get(field) is False
            for field in (
                "v2_outcome_used_for_model_training",
                "v2_outcome_used_for_model_selection",
                "v2_outcome_used_for_threshold_selection",
            )
        ),
        "V2 outcome reuse boundary changed",
    )
    unchanged = set(repair.get("unchanged", []))
    require(
        {
            "equality_model",
            "novelty_model",
            "lambda",
            "test_budget",
            "outcomes",
            "inference",
            "scientific_thresholds",
        }
        <= unchanged,
        "frozen V2 components changed",
    )
    domain = protocol.get("domain", {})
    require(
        domain
        == {
            "ruleset": "digraph_placement",
            "order": 7,
            "targets": list(TARGETS),
            "proposal_operator": "toggle_one_arc_only",
            "candidate_pool_size": 16,
        },
        "domain or proposal kernel changed",
    )
    initialization = protocol.get("initialization", {})
    require(
        initialization.get("minimum_weakly_connected_nonprior_candidate_neighbors")
        == 32,
        "initialization support threshold changed",
    )
    require(
        initialization.get("pair_specific") is True
        and initialization.get("shared_across_arms") is True
        and initialization.get("counts_as_discovery") is False,
        "paired initialization boundary changed",
    )
    require(
        all(
            initialization.get(field) is False
            for field in (
                "neighbor_exact_value_used_for_selection",
                "neighbor_quotient_used_for_selection",
                "neighbor_literal_digest_used_for_selection",
            )
        ),
        "initialization oracle access changed",
    )
    arms = protocol.get("arms", [])
    require(
        [row.get("id") for row in arms] == list(ARMS),
        "three-arm order changed",
    )
    if len(arms) == 3:
        require(
            arms[0].get("uses_equality_model") is False
            and arms[0].get("uses_novelty_model") is False
            and arms[1].get("uses_equality_model") is True
            and arms[1].get("uses_novelty_model") is False
            and arms[2].get("uses_equality_model") is True
            and arms[2].get("uses_novelty_model") is True,
            "arm model access changed",
        )
    models = protocol.get("models", {})
    require(
        models.get("novelty")
        == "ensemble-sha256:313da31b97d65fe2ee12be075c1c21ac866a061db00ef5e8bb15ed55b65142f9"
        and models.get("lambda") == 0.5
        and models.get("online_parameter_updates") is False
        and models.get("v3_training_rows") == 0
        and models.get("v3_model_selection") is False,
        "frozen model contract changed",
    )
    structural = protocol.get("structural_filter", {})
    require(
        structural.get("has_exact_value_access") is False
        and structural.get("has_graph_quotient_access") is False
        and structural.get("has_literal_game_access") is False,
        "structural filter gained outcome access",
    )
    require(
        structural.get("tiers")
        == [
            ["weakly_connected", "not_prior_split_candidate", "candidate_new_to_arm"],
            ["weakly_connected", "not_prior_split_candidate"],
            ["not_prior_split_candidate"],
            ["all"],
        ],
        "structural tiers changed",
    )
    acquisition = protocol.get("acquisition", {})
    require(
        acquisition.get("novelty_memory_is_arm_local") is True
        and acquisition.get("literal_digest_or_quotient_in_memory") is False
        and acquisition.get("final_tie_break")
        == "lexicographically_smallest_candidate_sha256",
        "novelty memory or tie-break changed",
    )
    splits = protocol.get("splits", {})
    validation = splits.get("validation", {})
    test = splits.get("test", {})
    expected_validation = [split_seed("validation", index) for index in range(4)]
    expected_test = [split_seed("test", index) for index in range(12)]
    require(
        validation.get("pair_count_per_target") == 4
        and validation.get("verifier_calls_per_arm_pair") == 128
        and validation.get("pair_seeds") == expected_validation
        and validation.get("initialization_indices") == list(range(4))
        and validation.get("model_or_threshold_selection_allowed") is False,
        "validation split or budget changed",
    )
    require(
        test.get("pair_count_per_target") == 12
        and test.get("verifier_calls_per_arm_pair") == 2048
        and test.get("checkpoints") == [128, 512, 1024, 2048]
        and test.get("pair_seeds") == expected_test
        and test.get("initialization_indices") == list(range(12))
        and test.get("success_stopping_rule") is False,
        "test split, budget, or stopping rule changed",
    )
    new_seeds = set(expected_validation + expected_test)
    require(
        len(new_seeds) == 16
        and not (set(expected_validation) & set(expected_test)),
        "V3 split overlap detected",
    )
    if check_bound_files:
        previous = set()
        for path in (V1_PROTOCOL, V2_PROTOCOL):
            old = load_json_object(repo_root / path)
            for split in ("validation", "test"):
                previous.update(old["splits"][split]["pair_seeds"])
        require(not (new_seeds & previous), "V3 seed reuses V1 or V2")
    budget = protocol.get("budget", {})
    require(
        budget.get("validation_exact_verifier_calls")
        == 3 * 4 * 3 * 128
        and budget.get("validation_raw_pool_candidates")
        == 3 * 4 * 3 * 128 * 16
        and budget.get("test_exact_verifier_calls")
        == 3 * 12 * 3 * 2048
        and budget.get("test_raw_pool_candidates")
        == 3 * 12 * 3 * 2048 * 16
        and budget.get("equal_test_budget_per_arm_target_pair") is True,
        "frozen budget arithmetic changed",
    )
    validation_gate = protocol.get("validation_gate", {})
    require(
        all(
            validation_gate.get(field) is True
            for field in (
                "all_integrity_checks_pass",
                "first_pool_tier_zero_for_every_stream",
                "at_least_one_nonprior_selection_every_stream",
                "at_least_one_clean_exact_match_every_arm_and_target",
                "at_least_one_quotient_discovery_every_arm_and_target",
            )
        )
        and validation_gate.get("test_initializations_or_seeds_used") is False
        and validation_gate.get("parameter_or_threshold_change_allowed") is False,
        "validation gate changed",
    )
    primary = protocol.get("primary_analysis", {})
    require(
        primary.get("unit") == "paired_target_stream"
        and primary.get("quotient_noninferiority", {}).get("margin") == 0.95
        and primary.get("quotient_noninferiority", {}).get(
            "zero_denominator_rule"
        )
        == "fail"
        and primary.get("interval", {}).get("resamples") == 20000
        and primary.get("interval", {}).get("rng_seed")
        == 12792362788753498044,
        "primary analysis changed",
    )
    gate = protocol.get("pareto_restoration_gate", {})
    require(
        gate.get("zero_denominator_rule") == "fail"
        and gate.get("nonzero_quotient_and_literal_support_every_arm_and_target")
        is True
        and gate.get("minimum_quotient_relative_lift_to_random") == 0.05
        and gate.get("minimum_literal_ratio_to_random") == 0.95
        and gate.get("minimum_descriptor_cell_ratio_to_random") == 0.9
        and gate.get("secondary_metrics_may_substitute") is False,
        "Pareto gate changed",
    )
    integrity = protocol.get("integrity", {})
    require(
        integrity.get("corruption_family_count") == 30
        and all(
            integrity.get(field) is True
            for field in (
                "protocol_schema_validation",
                "protocol_semantic_validation",
                "all_pool_candidates_logged",
                "all_selected_candidates_independently_replayed",
                "model_scores_embeddings_memory_and_fusion_replayed",
                "initialization_assignment_independently_replayed",
                "global_hash_chain",
                "immutable_exclusive_directories",
            )
        ),
        "integrity contract changed",
    )
    resource = protocol.get("resource_gate", {})
    require(
        resource.get("validation_wall_seconds") == 900
        and resource.get("test_generation_wall_seconds") == 5400
        and resource.get("test_verification_wall_seconds") == 7200
        and resource.get("run_directory_bytes") == 12_884_901_888
        and resource.get("peak_resident_memory_bytes") == 4_294_967_296,
        "resource gate changed",
    )
    failure = protocol.get("failure_policy", {})
    require(
        failure.get("validation_launches_authorized") == 1
        and failure.get("test_launches_authorized") == 1
        and failure.get("resume_allowed") is False
        and failure.get("overwrite_allowed") is False
        and failure.get("post_validation_change_allowed") is False
        and failure.get("post_test_change_allowed") is False
        and failure.get("secondary_rescue_allowed") is False
        and failure.get("failed_primary_claim_status") == "NO_GO"
        and failure.get("all_v1_v2_v3_outcomes_disclosed") is True,
        "failure policy changed",
    )
    claim = protocol.get("claim_boundary", {})
    require(
        claim.get("v1_no_go_must_be_disclosed") is True
        and claim.get("v2_deadlock_no_go_must_be_disclosed") is True
        and claim.get("human_preference_measured") is False
        and claim.get("aesthetic_quality_measured") is False
        and claim.get("neural_model_certifies_correctness") is False,
        "claim boundary changed",
    )

    if check_bound_files:
        source = protocol.get("source_evidence", {})
        expected_status = {
            "v2_completion": ("status", "NO_GO"),
            "v2_verification": ("status", "PASS"),
            "model_verification": ("status", "PASS_MODEL_PACKAGE_ONLY"),
        }
        for name, binding in source.items():
            path = Path(str(binding.get("path", "")))
            if path.is_absolute() or ".." in path.parts:
                require(False, f"{name} source path is unsafe")
                continue
            full = repo_root / path
            require(full.is_file(), f"{name} source is missing")
            if full.is_file():
                require(
                    file_sha256(full) == binding.get("sha256"),
                    f"{name} source hash changed",
                )
                value = load_canonical_json(full)
                if name in expected_status:
                    field, expected = expected_status[name]
                    require(
                        value.get(field) == expected,
                        f"{name} source status changed",
                    )
        manifest_path = repo_root / initialization.get("manifest_path", "")
        if manifest_path.is_file():
            manifest = load_canonical_json(manifest_path)
            require(
                embedded_hash_valid(manifest, "manifest_sha256"),
                "initialization manifest self-hash changed",
            )
            require(
                manifest.get("manifest_sha256")
                == source.get("initialization_manifest", {}).get(
                    "manifest_sha256"
                ),
                "initialization manifest identity changed",
            )
            require(
                manifest.get("split_seed_derivation", {}).get(
                    "validation_pair_seeds"
                )
                == expected_validation
                and manifest.get("split_seed_derivation", {}).get(
                    "test_pair_seeds"
                )
                == expected_test,
                "manifest and protocol split seeds differ",
            )
            for split, expected_count in (("validation", 4), ("test", 12)):
                for target in TARGETS:
                    rows = manifest["initializations"][split][target]
                    require(
                        len(rows) == expected_count,
                        f"{split} initialization count changed for {target}",
                    )
                    require(
                        all(
                            row[
                                "weakly_connected_nonprior_candidate_neighbor_count"
                            ]
                            >= 32
                            and row["shared_across_arms"] is True
                            and row["counts_as_discovery"] is False
                            and row["selected_using_semantic_outcome"] is False
                            for row in rows
                        ),
                        f"{split} initialization support changed for {target}",
                    )
        else:
            require(False, "initialization manifest is missing")
        prereg = repo_root / prereg_path
        require(prereg.is_file(), "preregistration is missing")
        schema = repo_root / SCHEMA_PATH
        require(schema.is_file(), "protocol schema is missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    protocol_path = (
        args.protocol
        if args.protocol.is_absolute()
        else repo_root / args.protocol
    )
    errors = validate(
        load_json_object(protocol_path),
        repo_root,
        check_bound_files=True,
    )
    if errors:
        for error in errors:
            print(error)
        return 1
    print("diversity-policy V3 protocol validation passed")
    print(
        "V2 disclosure, warm starts, fresh splits, fixed models, budgets, "
        "zero-denominator failure, and fail-closed gates replay"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
