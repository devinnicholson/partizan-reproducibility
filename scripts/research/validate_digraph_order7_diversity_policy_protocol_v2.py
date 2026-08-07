#!/usr/bin/env python3
"""Validate the frozen diversity-aware proposal-policy design.

The checks cover semantic invariants that JSON Schema cannot express:
source hashes, historical label counts, fresh seed derivation, V1 quarantine,
equal arm budgets, feature access, rank fusion, model selection, co-primary
estimands, fail-closed gates, and immutable execution rules.

The validator uses only the Python standard library and performs no new
combinatorial-game evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "partizan.digraph_order7_diversity_policy_comparison.v2.protocol"
DEFAULT_PROTOCOL = "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json"
DEFAULT_SCHEMA = (
    "docs/research/digraph-order7-diversity-policy-v2.protocol.schema.json"
)
EXPECTED_TARGETS = ["0", "*", "{0|1}"]
EXPECTED_CHECKPOINTS = [128, 512, 1024, 2048]
EXPECTED_PREFIX = "partizan.digraph_order7_diversity_policy_comparison.v2"
V1_PAIR_SEEDS = {
    11448075053716368180,
    9759795490829068362,
    13501455009403444918,
    10579151060415195887,
    6098339239841364612,
    14904992585275127460,
    13043129261239847808,
    60697066254384076,
    17779090450779344136,
    6489503931449319523,
    3590080119804342207,
    1642929648877530156,
    9209559138057076377,
    9482378533701589007,
    10549691255450657187,
    13393417613690885423,
}
EXPECTED_TOP_LEVEL = {
    "schema_version",
    "status",
    "freeze_date",
    "preregistration_path",
    "domain",
    "source_evidence",
    "splits",
    "leakage",
    "budget",
    "structural_filter",
    "arms",
    "equality_model",
    "novelty_model",
    "acquisition",
    "validation_selection",
    "primary_analysis",
    "secondary_metrics",
    "pareto_restoration_gate",
    "integrity",
    "resource_gate",
    "failure_policy",
    "claim_boundary",
}
EXPECTED_TIERS = [
    ["weakly_connected", "not_prior_split_candidate", "candidate_new_to_arm"],
    ["weakly_connected", "not_prior_split_candidate"],
    ["not_prior_split_candidate"],
    ["all"],
]
EXPECTED_ARMS = {
    "structural_toggle_one_random": {
        "role": "structural_control",
        "kernel": "toggle_one_arc_only",
        "selection": "uniform_first_nonempty_structural_tier",
        "uses_structural_filter": True,
        "uses_equality_model": False,
        "uses_novelty_model": False,
    },
    "neural_toggle_one_equality": {
        "role": "frozen_v1_equality_baseline",
        "kernel": "toggle_one_arc_only",
        "selection": (
            "maximum_frozen_v1_equality_logit_then_candidate_sha256"
        ),
        "uses_structural_filter": True,
        "uses_equality_model": True,
        "uses_novelty_model": False,
    },
    "neural_toggle_one_equality_novelty": {
        "role": "primary_treatment",
        "kernel": "toggle_one_arc_only",
        "selection": (
            "maximum_frozen_rank_fusion_score_then_candidate_sha256"
        ),
        "uses_structural_filter": True,
        "uses_equality_model": True,
        "uses_novelty_model": True,
    },
}
REQUIRED_FORBIDDEN_NOVELTY_INPUTS = {
    "candidate_sha256",
    "target_token",
    "quotient_code",
    "quotient_sha256",
    "literal_game_sha256",
    "proposal_operator",
    "event_index",
    "exact_decision",
    "retention",
    "descriptors",
    "future_repertoire",
}
REQUIRED_BINDING_FIELDS = {
    "model_card_sha256",
    "checkpoint_sha256",
    "feature_source_sha256",
    "training_registry_sha256",
    "validation_registry_sha256",
    "package_lock_sha256",
    "training_seeds",
    "checkpoint_selection_rule",
}


def append(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_pair_seed(prefix: str, split: str, index: int) -> int:
    message = f"{prefix}|{split}|pair|{index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest()[:8], "big")


def derive_named_seed(prefix: str, name: str, index: int) -> int:
    message = f"{prefix}|{name}|seed|{index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest()[:8], "big")


def repo_path(repo_root: Path, relative: str, errors: list[str]) -> Path:
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        errors.append(f"path escapes repository: {relative}")
    return candidate


def verify_bound_file(
    repo_root: Path,
    binding: dict[str, Any],
    label: str,
    errors: list[str],
) -> Path:
    path = repo_path(repo_root, str(binding.get("path", "")), errors)
    if not path.is_file():
        errors.append(f"{label} is missing: {path}")
        return path
    expected = binding.get("sha256")
    observed = sha256_file(path)
    append(
        errors,
        observed == expected,
        f"{label} SHA-256 mismatch: expected {expected}, observed {observed}",
    )
    return path


def verify_training_ledger(
    path: Path,
    expected: dict[str, Any],
    errors: list[str],
) -> None:
    all_rows = 0
    nonnull_rows = 0
    digest_counts: Counter[str] = Counter()
    base_seeds: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"training event {line_number} is invalid JSON: {exc}")
                return
            all_rows += 1
            base_seed = event.get("base_seed")
            if isinstance(base_seed, int):
                base_seeds.add(base_seed)
            decision = event.get("exact_decision")
            if decision is None:
                continue
            nonnull_rows += 1
            if not isinstance(decision, dict):
                errors.append(
                    f"training event {line_number} has a nonobject exact decision"
                )
                continue
            digest = decision.get("candidate_root_game_sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                errors.append(
                    f"training event {line_number} lacks its literal-game digest"
                )
                continue
            digest_counts[digest] += 1
    repeated = {digest: count for digest, count in digest_counts.items() if count >= 2}
    append(
        errors,
        all_rows == expected.get("all_rows"),
        "historical training all-row count changed",
    )
    append(
        errors,
        nonnull_rows == expected.get("nonnull_exact_decision_rows"),
        "historical nonnull exact-decision count changed",
    )
    append(
        errors,
        len(digest_counts) == expected.get("literal_digest_groups"),
        "historical literal-digest group count changed",
    )
    append(
        errors,
        len(repeated) == expected.get("contrastive_eligible_groups"),
        "contrastive eligible-group count changed",
    )
    append(
        errors,
        sum(repeated.values()) == expected.get("contrastive_eligible_rows"),
        "contrastive eligible-row count changed",
    )
    v2_pair_seeds = {
        derive_pair_seed(EXPECTED_PREFIX, "validation", index) for index in range(4)
    } | {
        derive_pair_seed(EXPECTED_PREFIX, "test", index) for index in range(12)
    }
    append(
        errors,
        base_seeds.isdisjoint(v2_pair_seeds),
        "V2 pair seeds overlap historical training base seeds",
    )


def validate(
    protocol: dict[str, Any],
    repo_root: Path,
    *,
    check_bound_files: bool = True,
) -> list[str]:
    errors: list[str] = []

    append(
        errors,
        set(protocol) == EXPECTED_TOP_LEVEL,
        "top-level protocol fields differ from the frozen contract",
    )
    append(
        errors,
        protocol.get("schema_version") == SCHEMA_VERSION,
        "schema_version is not the frozen v2 value",
    )
    append(
        errors,
        protocol.get("status")
        == "DESIGN_FROZEN_AWAITING_V2_IMPLEMENTATION_BINDING",
        "design status changed",
    )
    append(errors, protocol.get("freeze_date") == "2026-07-27", "freeze date changed")

    preregistration = repo_path(
        repo_root, str(protocol.get("preregistration_path", "")), errors
    )
    schema_path = repo_path(repo_root, DEFAULT_SCHEMA, errors)
    if check_bound_files:
        append(errors, preregistration.is_file(), "preregistration file is missing")
        append(errors, schema_path.is_file(), "protocol schema file is missing")
        if schema_path.is_file():
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"protocol schema is invalid JSON: {exc}")
            else:
                append(
                    errors,
                    schema.get("properties", {})
                    .get("schema_version", {})
                    .get("const")
                    == SCHEMA_VERSION,
                    "protocol schema version binding changed",
                )

    domain = protocol.get("domain", {})
    append(
        errors,
        domain
        == {
            "ruleset": "finite_normal_play_digraph_placement",
            "order": 7,
            "targets": EXPECTED_TARGETS,
            "target_order": EXPECTED_TARGETS,
            "representation_grammar": (
                "weakly_connected_two_colour_loopless_directed_graphs"
            ),
            "claim_population": (
                "fresh_seed_bounded_search_trajectories_under_this_frozen_grammar"
            ),
        },
        "domain or claim population changed",
    )

    sources = protocol.get("source_evidence", {})
    append(
        errors,
        set(sources)
        == {"historical_training", "frozen_equality_model", "v1_diagnostic"},
        "source-evidence families changed",
    )
    training = sources.get("historical_training", {})
    append(
        errors,
        training.get("role") == "novelty_model_training_only",
        "historical source must remain novelty-model training-only",
    )
    append(
        errors,
        training.get("allowed_labels")
        == ["exact_decision.candidate_root_game_sha256"],
        "novelty training label source changed",
    )
    append(
        errors,
        training.get("forbidden_roles")
        == ["v2_validation_evidence", "v2_test_evidence"],
        "historical-source evidence exclusions changed",
    )
    expected_training_counts = {
        "all_rows": 73728,
        "nonnull_exact_decision_rows": 73664,
        "literal_digest_groups": 60744,
        "contrastive_eligible_groups": 6868,
        "contrastive_eligible_rows": 19788,
    }
    observed_training_counts = {
        key: training.get("events", {}).get(key) for key in expected_training_counts
    }
    append(
        errors,
        observed_training_counts == expected_training_counts,
        "historical training count contract changed",
    )
    equality_source = sources.get("frozen_equality_model", {})
    append(
        errors,
        equality_source.get("role")
        == "unchanged_v1_equality_baseline_and_v2_equality_component",
        "V1 equality-model role changed",
    )
    append(
        errors,
        equality_source.get("model_id")
        == (
            "ensemble-sha256:"
            "13f5348609b73fa6f7ac9a5d846940aeea204e4ea6f142a50d420c7e4ea51c8f"
        ),
        "frozen V1 equality model ID changed",
    )
    append(
        errors,
        equality_source.get("checkpoint_sha256")
        == "36e558638cf1b209d0c81a2d4944ad09747f85fa0456d1bba6000d7ca3fbc827",
        "frozen V1 equality checkpoint changed",
    )
    append(
        errors,
        equality_source.get("post_freeze_parameter_change_allowed") is False,
        "V1 equality-model parameters must remain frozen",
    )
    diagnostic = sources.get("v1_diagnostic", {})
    append(
        errors,
        diagnostic.get("status") == "NO_GO"
        and diagnostic.get("quotient_relative_lift") == 0.5757603750490751
        and diagnostic.get("literal_digest_ratio_to_random")
        == 0.3959628438728117,
        "V1 diagnostic result or disclosure changed",
    )
    append(
        errors,
        diagnostic.get("may_count_as_v2_evidence") is False
        and diagnostic.get("may_train_v2_novelty_model") is False,
        "V1 validation/test cannot become V2 evidence or model training",
    )
    quarantine = diagnostic.get("quarantine_bindings", {})
    expected_validation_attempts = [
        {
            "path": (
                "output/research/digraph-order7-neural-validation-v1-"
                "b010306e0492/pools.committed.jsonl"
            ),
            "sha256": (
                "b0cd2481c81ed8f38ff75164346b79b3042b3aadb583842431f8d44ca1e494bb"
            ),
            "row_count": 12288,
            "status": "aborted_after_pool_commitment",
        },
        {
            "path": (
                "output/research/digraph-order7-neural-validation-v1-"
                "8219186966a4/pools.committed.jsonl"
            ),
            "sha256": (
                "b0cd2481c81ed8f38ff75164346b79b3042b3aadb583842431f8d44ca1e494bb"
            ),
            "row_count": 12288,
            "status": "aborted_after_pool_commitment",
        },
        {
            "path": (
                "output/research/digraph-order7-neural-validation-v1-"
                "e1f70eb74da1/pools.committed.jsonl"
            ),
            "sha256": (
                "b0cd2481c81ed8f38ff75164346b79b3042b3aadb583842431f8d44ca1e494bb"
            ),
            "row_count": 12288,
            "status": "verified_validation",
        },
    ]
    expected_quarantine = {
        "v1_validation_pool_attempts": expected_validation_attempts,
        "v1_validation_registry": {
            "path": (
                "output/research/digraph-order7-neural-validation-v1-"
                "e1f70eb74da1/validation_identity_registry.json"
            ),
            "sha256": (
                "8e6977e129dfa551e8b29b0ec7f416427a1f06c0bf44111e5f82701be140f28a"
            ),
        },
        "v1_test_prior_split_registry": {
            "path": (
                "output/research/digraph-order7-neural-policy-test-v1-"
                "4de8aba36c32/prior_split_registry.json"
            ),
            "sha256": (
                "944840af478dea9d0558813f211bd1c5f2822aa056d0e211d4ca6a4a469d2566"
            ),
        },
        "v1_test_events": {
            "path": (
                "output/research/digraph-order7-neural-policy-test-v1-"
                "4de8aba36c32/events.jsonl"
            ),
            "sha256": (
                "d88df5048f680906833177d7635323820bfbb19dbb16d7af0e10c97f10bcc843"
            ),
            "row_count": 147456,
        },
        "v1_test_completion": {
            "path": (
                "output/research/digraph-order7-neural-policy-test-v1-"
                "4de8aba36c32/RUN_COMPLETE.json"
            ),
            "sha256": (
                "7931c90f3de44bcdc2cdea69abfcdca2ceb3b9c99effde2bdc5a61ba9d90f6f1"
            ),
            "status": "NO_GO",
        },
    }
    append(
        errors,
        quarantine == expected_quarantine,
        "V1 prior-split quarantine bindings changed",
    )
    if check_bound_files:
        events_path = verify_bound_file(
            repo_root, training.get("events", {}), "historical training events", errors
        )
        verify_bound_file(
            repo_root,
            equality_source.get("package", {}),
            "frozen equality package",
            errors,
        )
        verify_bound_file(
            repo_root,
            equality_source.get("binding", {}),
            "frozen equality binding",
            errors,
        )
        verify_bound_file(
            repo_root,
            diagnostic.get("promotion_record", {}),
            "V1 promotion record",
            errors,
        )
        for index, binding in enumerate(
            quarantine.get("v1_validation_pool_attempts", [])
        ):
            path = verify_bound_file(
                repo_root,
                binding,
                f"V1 validation pool attempt {index}",
                errors,
            )
            if path.is_file():
                with path.open("rb") as handle:
                    observed_rows = sum(1 for _line in handle)
                append(
                    errors,
                    observed_rows == binding.get("row_count"),
                    f"V1 validation pool attempt {index} row count changed",
                )
        for key in (
            "v1_validation_registry",
            "v1_test_prior_split_registry",
            "v1_test_events",
            "v1_test_completion",
        ):
            path = verify_bound_file(
                repo_root,
                quarantine.get(key, {}),
                key.replace("_", " "),
                errors,
            )
            if key == "v1_test_events" and path.is_file():
                with path.open("rb") as handle:
                    observed_rows = sum(1 for _line in handle)
                append(
                    errors,
                    observed_rows
                    == quarantine.get(key, {}).get("row_count"),
                    "V1 test event row count changed",
                )
        if events_path.is_file():
            verify_training_ledger(events_path, training.get("events", {}), errors)

    splits = protocol.get("splits", {})
    derivation = splits.get("seed_derivation", {})
    prefix = derivation.get("prefix")
    append(errors, prefix == EXPECTED_PREFIX, "V2 seed prefix changed")
    append(
        errors,
        derivation.get("algorithm")
        == "first_8_bytes_sha256_unsigned_big_endian"
        and derivation.get("message") == "{prefix}|{split}|pair|{decimal_index}",
        "seed derivation changed",
    )
    expected_counter_rng = {
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
        "random_selection_draw_name": "random_selection",
        "random_selection_population_order": "eligible_slots_in_pool_order",
        "validation_phase": "validation",
        "validation_unit_index": "group_index",
        "test_phase": "test",
        "test_unit_index": "verifier_call_index",
    }
    append(
        errors,
        splits.get("counter_rng") == expected_counter_rng,
        "counter RNG mapping changed",
    )
    validation = splits.get("validation", {})
    test = splits.get("test", {})
    validation_seeds = validation.get("pair_seeds", [])
    test_seeds = test.get("pair_seeds", [])
    append(
        errors,
        validation_seeds
        == [derive_pair_seed(EXPECTED_PREFIX, "validation", index) for index in range(4)],
        "validation seeds do not replay from the frozen domain",
    )
    append(
        errors,
        test_seeds
        == [derive_pair_seed(EXPECTED_PREFIX, "test", index) for index in range(12)],
        "test seeds do not replay from the frozen domain",
    )
    append(
        errors,
        len(set(validation_seeds)) == len(validation_seeds) == 4,
        "validation seeds must contain four unique values",
    )
    append(
        errors,
        len(set(test_seeds)) == len(test_seeds) == 12,
        "test seeds must contain twelve unique values",
    )
    append(
        errors,
        set(validation_seeds).isdisjoint(test_seeds),
        "V2 validation and test seeds overlap",
    )
    append(
        errors,
        set(validation_seeds + test_seeds).isdisjoint(V1_PAIR_SEEDS),
        "V2 seed families overlap V1 validation or test",
    )
    append(
        errors,
        validation.get("pair_count_per_target") == 4
        and validation.get("proposals_per_pair") == 1024
        and validation.get("groups_per_pair") == 64
        and validation.get("group_size") == 16
        and validation.get("groups_per_pair") * validation.get("group_size")
        == validation.get("proposals_per_pair"),
        "validation grouping or budget changed",
    )
    append(
        errors,
        validation.get("parent_source")
        == (
            "uniform_lexicographically_sorted_historical_training_"
            "retained_repertoire"
        )
        and validation.get("pool_kernel")
        == "sixteen_distinct_toggle_one_arcs_without_replacement",
        "validation parent source or pool kernel changed",
    )
    append(
        errors,
        validation.get("adaptive_parent_repertoire") is False
        and validation.get("adaptive_policy_memory") is True
        and validation.get("all_candidates_labeled_once") is True
        and validation.get("same_committed_pools_for_all_configurations") is True,
        "validation static-pool or adaptive-memory contract changed",
    )
    append(
        errors,
        validation.get("all_committed_rows_retained") is True
        and validation.get("metric_row_filter")
        == "eligible_for_validation_metric_true"
        and validation.get("zero_eligible_pool_policy") == "exclude_pool_and_report",
        "validation row eligibility policy changed",
    )
    append(
        errors,
        test.get("pair_count_per_target") == 12
        and test.get("verifier_calls_per_arm_pair") == 2048
        and test.get("checkpoints") == EXPECTED_CHECKPOINTS
        and test.get("success_stopping_rule") is False,
        "test split budget, checkpoints, or stopping rule changed",
    )

    leakage = protocol.get("leakage", {})
    append(
        errors,
        leakage.get("prior_split_sources")
        == [
            "historical_training_v1",
            "all_generated_v1_validation_attempts",
            "official_v1_test",
            "v2_validation_before_test",
        ],
        "prior-split quarantine source list changed",
    )
    append(
        errors,
        leakage.get("blocked_prior_split_identities")
        == ["candidate_sha256", "quotient_sha256"],
        "candidate and quotient identities must define prior-split leakage",
    )
    append(
        errors,
        leakage.get("recorded_not_blocked") == ["literal_game_sha256"],
        "literal-game overlap must remain audit-only",
    )
    append(
        errors,
        leakage.get("v1_validation_and_test_use")
        == "registry_and_design_only_never_training_or_v2_evidence",
        "V1 validation/test quarantine changed",
    )
    for key, expected_value in {
        "prior_split_collision_consumes_selected_verifier_call": True,
        "prior_split_collision_counts_as_discovery": False,
        "cross_arm_test_collision_blocks_discovery": False,
        "shared_stage0_controls_are_discoveries": False,
        "selected_v2_validation_rows_may_train_model": False,
        "all_v2_validation_rows_may_train_model": False,
    }.items():
        append(
            errors,
            leakage.get(key) is expected_value,
            f"leakage policy {key} changed",
        )

    budget = protocol.get("budget", {})
    expected_budget = {
        "candidate_pool_size": 16,
        "test_pool_kernel": (
            "sixteen_distinct_toggle_one_arcs_without_replacement"
        ),
        "selected_candidates_per_call": 1,
        "exact_verifier_calls_per_arm_target_pair": 2048,
        "arms": 3,
        "targets": 3,
        "pairs_per_target": 12,
        "total_test_exact_verifier_calls": 221184,
        "total_test_raw_pool_candidates": 3538944,
        "validation_exact_candidate_labels": 12288,
    }
    append(errors, budget == expected_budget, "three-arm budget contract changed")
    append(
        errors,
        budget.get("total_test_exact_verifier_calls")
        == (
            budget.get("exact_verifier_calls_per_arm_target_pair", 0)
            * budget.get("arms", 0)
            * budget.get("targets", 0)
            * budget.get("pairs_per_target", 0)
        ),
        "total exact-verifier budget arithmetic is inconsistent",
    )
    append(
        errors,
        budget.get("total_test_raw_pool_candidates")
        == (
            budget.get("total_test_exact_verifier_calls", 0)
            * budget.get("candidate_pool_size", 0)
        ),
        "total raw-candidate budget arithmetic is inconsistent",
    )
    append(
        errors,
        budget.get("validation_exact_candidate_labels")
        == 4 * 3 * 64 * 16,
        "validation exact-label budget arithmetic is inconsistent",
    )

    structural = protocol.get("structural_filter", {})
    append(
        errors,
        structural.get("has_exact_value_access") is False
        and structural.get("has_graph_quotient_access") is False
        and structural.get("has_literal_game_access") is False,
        "structural filter gained semantic oracle access",
    )
    append(
        errors,
        structural.get("first_nonempty_tier") is True
        and structural.get("tiers") == EXPECTED_TIERS,
        "structural eligibility tiers changed",
    )

    arms = protocol.get("arms", [])
    arm_map = {arm.get("id"): arm for arm in arms if isinstance(arm, dict)}
    append(
        errors,
        len(arms) == len(arm_map) == 3,
        "arms must contain three unique identifiers",
    )
    append(errors, set(arm_map) == set(EXPECTED_ARMS), "arm identifiers changed")
    for arm_id, expected in EXPECTED_ARMS.items():
        observed = arm_map.get(arm_id, {})
        for key, value in expected.items():
            append(
                errors,
                observed.get(key) == value,
                f"{arm_id}.{key} changed from the frozen design",
            )
    append(
        errors,
        {arm.get("kernel") for arm in arms if isinstance(arm, dict)}
        == {"toggle_one_arc_only"},
        "arms no longer share one proposal kernel",
    )

    equality = protocol.get("equality_model", {})
    append(
        errors,
        equality
        == {
            "binding": "source_evidence.frozen_equality_model",
            "input_fields": [
                "candidate_directed_graph",
                "candidate_vertex_colours",
                "target_token",
            ],
            "output": "equality_logit",
            "test_inference": "deterministic_cpu_only",
            "online_updates": False,
        },
        "frozen equality-model inference contract changed",
    )

    novelty = protocol.get("novelty_model", {})
    novelty_inputs = set(novelty.get("input_fields", []))
    forbidden_inputs = set(novelty.get("forbidden_input_fields", []))
    append(
        errors,
        novelty.get("binding_status")
        == "AWAITING_FROZEN_MODEL_CARD_AND_CHECKPOINT",
        "novelty-model binding status changed",
    )
    append(
        errors,
        novelty_inputs
        == {"candidate_directed_graph", "candidate_vertex_colours"},
        "novelty-model input contract changed",
    )
    append(
        errors,
        novelty_inputs.isdisjoint(forbidden_inputs)
        and REQUIRED_FORBIDDEN_NOVELTY_INPUTS <= forbidden_inputs,
        "novelty-model leakage-prone input prohibition changed",
    )
    append(
        errors,
        novelty.get("training_label")
        == "training_only_complete_literal_game_digest_equivalence",
        "novelty training label changed",
    )
    append(
        errors,
        novelty.get("training_rows")
        == {
            "source_rows": 73664,
            "eligible_groups_with_at_least_two_rows": 6868,
            "eligible_rows": 19788,
            "singleton_groups_contribute_to_loss": False,
        },
        "novelty contrastive-row contract changed",
    )
    expected_architecture = {
        "family": "directed_message_passing_graph_embedding_v2",
        "initial_node_features": ["is_blue", "is_red"],
        "input_projection": "linear_then_relu",
        "message_aggregation": [
            "unnormalized_incoming_sum",
            "unnormalized_outgoing_sum",
        ],
        "message_update": (
            "linear_self_plus_linear_incoming_plus_linear_outgoing_then_"
            "relu_then_dropout"
        ),
        "graph_pooling": ["mean", "maximum"],
        "projection_head": (
            "linear_2h_to_h_then_relu_then_linear_h_to_embedding_width_then_"
            "l2_normalize"
        ),
        "hidden_width": 64,
        "message_passing_layers": 3,
        "dropout": 0.1,
    }
    append(
        errors,
        novelty.get("architecture") == expected_architecture,
        "novelty-model architecture changed",
    )
    expected_grid = {
        "embedding_width": [16, 32],
        "contrastive_temperature": [0.1, 0.2],
        "learning_rate": [0.001],
        "weight_decay": [0.0001],
        "digest_groups_per_batch": 64,
        "rows_per_digest_group_per_epoch": 2,
        "maximum_epochs": 60,
        "checkpoint_epochs": "1_through_60_inclusive",
        "training_seed_derivation": (
            "first_8_bytes_sha256_of_prefix_novelty_training_seed_index"
        ),
        "training_seeds": [
            11554741894640848524,
            5751780749325247006,
            15000233837857862382,
        ],
        "optimizer": "AdamW",
        "loss": "supervised_nt_xent_one_same_digest_positive_per_anchor",
        "batch_order": (
            "training_seed_group_shuffle_each_epoch_with_deterministic_"
            "within_group_rotation"
        ),
        "member_aggregation": (
            "arithmetic_mean_of_member_minimum_cosine_distances"
        ),
    }
    append(
        errors,
        novelty.get("finite_grid") == expected_grid,
        "novelty-model finite grid changed",
    )
    append(
        errors,
        novelty.get("finite_grid", {}).get("training_seeds")
        == [
            derive_named_seed(EXPECTED_PREFIX, "novelty_training", index)
            for index in range(3)
        ],
        "novelty training seeds do not replay",
    )
    expected_freeze = {
        "repository": "partizan",
        "pushed_main_commit_sha_required": True,
        "remote_commit_verification_required": True,
        "snapshot_hash_required": True,
        "required_files": [
            "python/partizan/digraph_diversity_ranker.py",
            "python/partizan/digraph_neural_ranker.py",
            "tests/test_digraph_diversity_ranker.py",
            "tests/test_digraph_neural_ranker.py",
            "docs/digraph_diversity_ranker.md",
            "docs/digraph_neural_ranker.md",
            "pyproject.toml",
        ],
        "copy_snapshot_before_validation_pool_commitment": True,
        "post_validation_source_change_allowed": False,
    }
    append(
        errors,
        novelty.get("pre_validation_implementation_freeze") == expected_freeze,
        "pre-validation Partizan implementation freeze changed",
    )
    append(
        errors,
        novelty.get("test_inference") == "deterministic_cpu_only"
        and novelty.get("online_parameter_updates") is False,
        "novelty-model inference or parameter-freeze policy changed",
    )
    append(
        errors,
        set(novelty.get("required_binding_fields", []))
        == REQUIRED_BINDING_FIELDS,
        "novelty-model launch bindings changed",
    )

    acquisition = protocol.get("acquisition", {})
    expected_acquisition = {
        "novelty_memory_initialization": "shared_stage0_control_graph_only",
        "novelty_memory_update": (
            "append_selected_prior_split_nonleaking_exact_match_graph_after_"
            "verification"
        ),
        "novelty_memory_is_arm_local": True,
        "literal_digest_or_quotient_in_memory": False,
        "candidate_novelty": (
            "arithmetic_mean_across_members_of_minimum_cosine_distance_to_"
            "member_embeddings_in_arm_local_memory"
        ),
        "within_pool_transform": (
            "ascending_midrank_fraction_in_zero_one_with_higher_better"
        ),
        "combined_score": (
            "equality_midrank_fraction_plus_lambda_times_novelty_midrank_fraction"
        ),
        "lambda_grid": [0.25, 0.5, 1.0, 2.0],
        "final_tie_break": "lexicographically_smallest_candidate_sha256",
        "memory_updates_change_parameters": False,
    }
    append(
        errors,
        acquisition == expected_acquisition,
        "rank-fusion acquisition contract changed",
    )

    selection = protocol.get("validation_selection", {})
    expected_selection = {
        "unit": "ordered_static_validation_pool_sequence",
        "configuration_count_before_epochs_and_lambda": 4,
        "feasibility_constraints": [
            "total_quotient_discovery_ratio_to_frozen_equality_at_least_0.95",
            "total_literal_digest_ratio_to_random_at_least_0.95",
        ],
        "selection_rule": (
            "feasible_then_maximum_target_macro_literal_digest_difference_vs_"
            "equality_then_maximum_target_macro_quotient_difference_vs_equality_"
            "then_smaller_embedding_width_then_lower_temperature_then_earlier_"
            "epoch_then_smaller_lambda"
        ),
        "no_feasible_configuration_policy": "NO_LAUNCH",
        "validation_rows_become_prior_split_before_test": True,
        "validation_metrics_may_change_test_thresholds": False,
    }
    append(
        errors,
        selection == expected_selection,
        "validation configuration-selection rule changed",
    )

    analysis = protocol.get("primary_analysis", {})
    append(
        errors,
        analysis.get("unit") == "paired_target_stream",
        "paired target stream must remain the analysis unit",
    )
    expected_co_primary = [
        {
            "id": "literal_superiority_to_equality",
            "treatment": "neural_toggle_one_equality_novelty",
            "control": "neural_toggle_one_equality",
            "outcome": (
                "literal_game_unique_prior_split_nonleaking_independently_"
                "certified_exact_target_discoveries_at_2048_calls"
            ),
            "estimator": "target_macro_average_of_paired_stream_differences",
            "success": "point_estimate_gt_0_and_interval_lower_gt_0",
        },
        {
            "id": "quotient_noninferiority_to_equality",
            "treatment": "neural_toggle_one_equality_novelty",
            "control": "neural_toggle_one_equality",
            "outcome": (
                "quotient_unique_prior_split_nonleaking_independently_certified_"
                "exact_target_discoveries_at_2048_calls"
            ),
            "estimator": "ratio_of_target_macro_mean_stream_counts",
            "noninferiority_margin_ratio": 0.95,
            "success": "point_estimate_ge_0.95_and_interval_lower_ge_0.95",
        },
    ]
    append(
        errors,
        analysis.get("co_primary") == expected_co_primary,
        "co-primary estimands or thresholds changed",
    )
    append(
        errors,
        analysis.get("random_reference")
        == {
            "treatment": "neural_toggle_one_equality_novelty",
            "control": "structural_toggle_one_random",
            "quotient_outcome_success": (
                "paired_difference_point_gt_0_and_interval_lower_gt_0_and_total_"
                "relative_lift_at_least_0.05"
            ),
            "literal_outcome_success": "total_digest_ratio_at_least_0.95",
        },
        "random-reference requirements changed",
    )
    append(
        errors,
        analysis.get("interval")
        == {
            "method": "stratified_paired_percentile_bootstrap",
            "confidence": 0.95,
            "resamples": 20000,
            "rng_seed": 12792362788753498044,
        },
        "bootstrap design changed",
    )
    append(
        errors,
        analysis.get("sign_flip")
        == {
            "method": "deterministic_two_sided_paired_sign_flip",
            "maximum_enumerated_or_sampled_assignments": 1000000,
            "rng_seed": 10520555185417374640,
        },
        "sign-flip diagnostic changed",
    )
    append(
        errors,
        analysis.get("interval", {}).get("rng_seed")
        == derive_named_seed(EXPECTED_PREFIX, "bootstrap", 0)
        and analysis.get("sign_flip", {}).get("rng_seed")
        == derive_named_seed(EXPECTED_PREFIX, "sign_flip", 0),
        "analysis seeds do not replay",
    )

    secondary = protocol.get("secondary_metrics", {})
    append(
        errors,
        secondary.get("checkpoints") == EXPECTED_CHECKPOINTS,
        "secondary checkpoints changed",
    )
    append(
        errors,
        secondary.get("human_preference_measured") is False
        and secondary.get("aesthetic_quality_measured") is False,
        "unmeasured aesthetic or preference outcome was promoted",
    )

    expected_gate = {
        "all_integrity_checks_pass": True,
        "literal_superiority_to_equality_point_gt_0": True,
        "literal_superiority_to_equality_interval_lower_gt_0": True,
        "quotient_ratio_to_equality_point_ge": 0.95,
        "quotient_ratio_to_equality_interval_lower_ge": 0.95,
        "quotient_superiority_to_random_point_gt_0": True,
        "quotient_superiority_to_random_interval_lower_gt_0": True,
        "minimum_quotient_relative_lift_to_random": 0.05,
        "minimum_literal_digest_ratio_to_random": 0.95,
        "positive_literal_mean_difference_vs_equality_for_every_target": True,
        "minimum_descriptor_cell_ratio_to_random": 0.9,
        "both_transition_classes_for_every_target": True,
        "secondary_metrics_may_substitute": False,
    }
    append(
        errors,
        protocol.get("pareto_restoration_gate") == expected_gate,
        "Pareto-restoration gate changed",
    )

    integrity = protocol.get("integrity", {})
    required_true = {
        "protocol_schema_validation",
        "protocol_semantic_validation",
        "selected_proposal_always_consumes_one_verifier_call",
        "all_pool_candidates_logged",
        "all_selected_candidates_independently_replayed",
        "all_retained_artifacts_independently_replayed",
        "model_scores_and_embeddings_independently_replayed",
        "novelty_memory_and_rank_fusion_independently_replayed",
        "global_hash_chain",
        "immutable_exclusive_run_directories",
        "test_generated_only_after_model_freeze",
        "test_generated_only_after_v2_validation_registry_freeze",
        "resource_preflight_required",
    }
    for key in required_true:
        append(
            errors,
            integrity.get(key) is True,
            f"integrity requirement {key} is not true",
        )
    append(
        errors,
        integrity.get("corruption_family_count") == 26,
        "all twenty-six corruption families are required",
    )
    append(
        errors,
        set(integrity) == required_true | {"corruption_family_count"},
        "integrity fields changed",
    )

    expected_resource = {
        "preflight_steps_per_arm": 4096,
        "preflight_uses_only_registered_historical_candidates": True,
        "preflight_new_semantic_evaluation_allowed": False,
        "maximum_projected_generation_seconds": 3600,
        "generation_wall_seconds": 5400,
        "independent_verification_wall_seconds": 7200,
        "run_directory_bytes": 12884901888,
        "peak_resident_memory_bytes": 4294967296,
    }
    append(
        errors,
        protocol.get("resource_gate") == expected_resource,
        "resource preflight gate changed",
    )

    expected_failure = {
        "validation_launches_authorized": 1,
        "test_launches_authorized": 1,
        "resume_allowed": False,
        "overwrite_allowed": False,
        "post_validation_model_change_allowed": False,
        "post_test_model_change_allowed": False,
        "post_test_threshold_change_allowed": False,
        "secondary_rescue_allowed": False,
        "failed_primary_claim_status": "NO_GO",
        "new_model_requires": (
            "new_protocol_version_new_validation_and_test_seeds_and_v1_v2_"
            "disclosure"
        ),
    }
    append(
        errors,
        protocol.get("failure_policy") == expected_failure,
        "failure policy changed",
    )

    claim = protocol.get("claim_boundary", {})
    append(
        errors,
        claim.get("v1_no_go_must_be_disclosed") is True,
        "V1 NO_GO disclosure is no longer mandatory",
    )
    append(
        errors,
        claim.get("kqqkqq_role")
        == "historical_motivation_only_no_policy_observations",
        "KQQKQQ claim role changed",
    )
    forbidden = set(claim.get("forbidden", []))
    append(
        errors,
        {
            "complete_fiber_size",
            "prevalence",
            "unrestricted_chess_generalization",
            "human_aesthetic_preference",
            "autonomous_taste",
            "best_representation",
            "universal_creativity",
            "neural_model_certifies_correctness",
            "kqqkqq_validates_the_policy",
        }
        <= forbidden,
        "claim boundary lost a required prohibition",
    )

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "protocol",
        nargs="?",
        default=DEFAULT_PROTOCOL,
        help="protocol JSON path, relative to --repo-root by default",
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--skip-bound-files",
        action="store_true",
        help="check protocol semantics without hashing bound artifacts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_absolute():
        protocol_path = repo_root / protocol_path
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    errors = validate(
        protocol,
        repo_root,
        check_bound_files=not args.skip_bound_files,
    )
    if errors:
        raise SystemExit(
            "diversity-policy protocol validation failed:\n"
            + "\n".join(f"- {error}" for error in errors)
        )
    print("diversity-policy protocol validation passed")
    print(
        "source bindings, fresh splits, three-arm budgets, rank fusion, "
        "co-primary analyses, and fail-closed gates replay"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
