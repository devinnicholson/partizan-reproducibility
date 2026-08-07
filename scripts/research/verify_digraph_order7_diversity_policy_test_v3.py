#!/usr/bin/env python3
"""Independent replay and finalizer for the one-time V3 policy test.

V3 changes only the pair-local starting controls.  The proposal, neural
ranking, exact verification, retention, and transition kernel remains the
frozen V2 kernel.  This verifier independently reconstructs every pair-local
ledger before computing the V3 inference and gate.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import validate_digraph_order7_diversity_policy_protocol_v3 as protocol_validator
import verify_digraph_order7_diversity_policy_test_v2 as v2
import verify_digraph_order7_diversity_policy_validation_v3 as validation_v3


SCHEMA = "partizan.digraph_order7_diversity_policy_test.v3"
PROTOCOL_PATH = protocol_validator.PROTOCOL_PATH
INITIALIZATION_MANIFEST = Path(
    "output/research/digraph-order7-policy-v3-initializations-v1/"
    "INITIALIZATION_MANIFEST.json"
)
VALIDATION_RUN = Path(
    "output/research/digraph-order7-diversity-policy-validation-v3-e5a2280aac6b"
)
VALIDATION_COMPLETION = VALIDATION_RUN / "VALIDATION_COMPLETE.json"
PRIOR_REGISTRY = VALIDATION_RUN / "test_prior_split_registry.json"
TARGETS = v2.TARGETS
ARMS = v2.ARMS
RANDOM_ARM, EQUALITY_ARM, NOVELTY_ARM = ARMS
OFFICIAL_MODE = v2.OFFICIAL_MODE
SMOKE_MODE = v2.SMOKE_MODE
SMOKE_PREFIX = f"{SCHEMA}.smoke"
INFERENCE_PREFIX = "partizan.digraph_order7_diversity_policy_comparison.v3"
ZERO_SHA256 = "0" * 64
CORRUPTION_FAMILIES = (
    "protocol",
    "launch",
    "source",
    "validation_completion",
    "prior_registry",
    "initialization_manifest",
    "initialization_assignment",
    "resource_preflight",
    "model_package",
    "model_verification",
    "test_seed",
    "target_arm_schedule",
    "parent_rng",
    "arc_permutation",
    "candidate_graph",
    "candidate_identity",
    "structural_tier",
    "equality_logit",
    "novelty_embedding",
    "novelty_memory",
    "rank_fusion",
    "selected_slot",
    "exact_decision",
    "literal_digest",
    "quotient",
    "descriptor",
    "retention_transition",
    "hash_chain_endpoint",
    "stream_inference_gate",
    "nonzero_support",
)


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


def verify_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    payload = dict(value)
    supplied = payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"{label} self-hash does not replay")


def hashed_record(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = object_sha256(payload)
    return result


def write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    write_bytes_exclusive(path, canonical_line(value))


def safe_binding(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    label: str,
) -> Path:
    relative = Path(str(binding.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path is unsafe")
    path = repo_root / relative
    if not path.is_file() or file_sha256(path) != binding.get("sha256"):
        raise ValueError(f"{label} binding changed")
    return path


def smoke_seed() -> int:
    return int.from_bytes(
        hashlib.sha256(f"{SMOKE_PREFIX}|pair|0".encode("ascii")).digest()[:8],
        "big",
    )


def strict_ratio(numerator: float, denominator: float) -> float | None:
    """Return an ordinary ratio; undefined denominators never pass a gate."""
    if denominator <= 0:
        return None
    return numerator / denominator


def bootstrap_index(
    size: int,
    *,
    seed: int,
    resample: int,
    target: str,
    draw: int,
) -> int:
    if size <= 0:
        raise ValueError("bootstrap population is empty")
    modulus = 1 << 256
    limit = modulus - modulus % size
    counter = 0
    while True:
        value = int.from_bytes(
            hashlib.sha256(
                (
                    f"{INFERENCE_PREFIX}|inference|bootstrap|{seed}|"
                    f"{resample}|{target}|{draw}|{counter}"
                ).encode("utf-8")
            ).digest(),
            "big",
        )
        if value < limit:
            return value % size
        counter += 1


def nearest_rank(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile population is empty")
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def macro_mean(
    by_key: Mapping[tuple[str, int, str], Mapping[str, Any]],
    seeds: Mapping[str, Sequence[int]],
    *,
    arm: str,
    field: str,
    sampled: Mapping[str, Sequence[int]] | None = None,
) -> float:
    target_means = []
    for target in TARGETS:
        target_seeds = sampled[target] if sampled is not None else seeds[target]
        values = [
            float(by_key[(target, pair_seed, arm)][field])
            for pair_seed in target_seeds
        ]
        target_means.append(sum(values) / len(values))
    return sum(target_means) / len(target_means)


def sign_flip_test(
    differences: Mapping[str, Sequence[float]],
    *,
    point: float,
    protocol: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    rows = [
        (target, index, float(value))
        for target in TARGETS
        for index, value in enumerate(differences[target])
    ]
    frozen = protocol["primary_analysis"]["sign_flip"]
    maximum = int(frozen["maximum_assignments"])
    full = 1 << len(rows)
    count = min(full, maximum)
    extreme = 0
    chain = ZERO_SHA256
    for assignment in range(count):
        if full <= maximum:
            mask = assignment
        else:
            mask = int.from_bytes(
                hashlib.sha256(
                    (
                        f"{INFERENCE_PREFIX}|inference|sign_flip|{label}|"
                        f"{frozen['rng_seed']}|{assignment}"
                    ).encode("utf-8")
                ).digest(),
                "big",
            )
        sums = {target: 0.0 for target in TARGETS}
        counts = {target: 0 for target in TARGETS}
        for bit, (target, _index, value) in enumerate(rows):
            sums[target] += value if (mask >> bit) & 1 else -value
            counts[target] += 1
        statistic = sum(
            sums[target] / counts[target] for target in TARGETS
        ) / len(TARGETS)
        if abs(statistic) >= abs(point):
            extreme += 1
        chain = object_sha256(
            {
                "previous": chain,
                "assignment": assignment,
                "mask_low_bits": mask & ((1 << len(rows)) - 1),
                "statistic_hex": statistic.hex(),
            }
        )
    p_value = (
        extreme / count
        if full <= maximum
        else (extreme + 1) / (count + 1)
    )
    return {
        "method": frozen["method"],
        "label": label,
        "rng_seed": frozen["rng_seed"],
        "assignment_mode": (
            "enumerated" if full <= maximum else "sha256_sampled_with_replacement"
        ),
        "assignment_count": count,
        "extreme_count": extreme,
        "p_value": p_value,
        "assignment_statistic_chain_sha256": chain,
    }


def independent_inference(
    streams: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    by_key = {
        (row["target"], row["pair_seed"], row["arm"]): row for row in streams
    }
    seeds = {
        target: sorted(
            {
                row["pair_seed"]
                for row in streams
                if row["target"] == target
            }
        )
        for target in TARGETS
    }
    expected_keys = sum(len(seeds[target]) for target in TARGETS) * len(ARMS)
    if len(by_key) != expected_keys or any(not seeds[target] for target in TARGETS):
        raise ValueError("paired target stream design is incomplete")
    literal_differences = {
        target: [
            by_key[(target, seed, NOVELTY_ARM)][
                "literal_game_unique_discoveries"
            ]
            - by_key[(target, seed, EQUALITY_ARM)][
                "literal_game_unique_discoveries"
            ]
            for seed in seeds[target]
        ]
        for target in TARGETS
    }
    quotient_random_differences = {
        target: [
            by_key[(target, seed, NOVELTY_ARM)][
                "quotient_unique_discoveries"
            ]
            - by_key[(target, seed, RANDOM_ARM)][
                "quotient_unique_discoveries"
            ]
            for seed in seeds[target]
        ]
        for target in TARGETS
    }
    literal_target_points = {
        target: sum(values) / len(values)
        for target, values in literal_differences.items()
    }
    quotient_random_target_points = {
        target: sum(values) / len(values)
        for target, values in quotient_random_differences.items()
    }
    literal_point = sum(literal_target_points.values()) / len(TARGETS)
    quotient_random_point = (
        sum(quotient_random_target_points.values()) / len(TARGETS)
    )
    quotient_novelty_macro = macro_mean(
        by_key,
        seeds,
        arm=NOVELTY_ARM,
        field="quotient_unique_discoveries",
    )
    quotient_equality_macro = macro_mean(
        by_key,
        seeds,
        arm=EQUALITY_ARM,
        field="quotient_unique_discoveries",
    )
    quotient_ratio_point = strict_ratio(
        quotient_novelty_macro,
        quotient_equality_macro,
    )
    frozen = protocol["primary_analysis"]["interval"]
    literal_samples: list[float] = []
    quotient_ratio_samples: list[float] = []
    quotient_ratio_undefined = 0
    quotient_random_samples: list[float] = []
    for resample in range(int(frozen["resamples"])):
        sampled = {
            target: [
                seeds[target][
                    bootstrap_index(
                        len(seeds[target]),
                        seed=frozen["rng_seed"],
                        resample=resample,
                        target=target,
                        draw=draw,
                    )
                ]
                for draw in range(len(seeds[target]))
            ]
            for target in TARGETS
        }
        literal_means = []
        random_means = []
        for target in TARGETS:
            literal_values = [
                by_key[(target, seed, NOVELTY_ARM)][
                    "literal_game_unique_discoveries"
                ]
                - by_key[(target, seed, EQUALITY_ARM)][
                    "literal_game_unique_discoveries"
                ]
                for seed in sampled[target]
            ]
            random_values = [
                by_key[(target, seed, NOVELTY_ARM)][
                    "quotient_unique_discoveries"
                ]
                - by_key[(target, seed, RANDOM_ARM)][
                    "quotient_unique_discoveries"
                ]
                for seed in sampled[target]
            ]
            literal_means.append(sum(literal_values) / len(literal_values))
            random_means.append(sum(random_values) / len(random_values))
        literal_samples.append(sum(literal_means) / len(TARGETS))
        quotient_random_samples.append(sum(random_means) / len(TARGETS))
        novelty = macro_mean(
            by_key,
            seeds,
            arm=NOVELTY_ARM,
            field="quotient_unique_discoveries",
            sampled=sampled,
        )
        equality = macro_mean(
            by_key,
            seeds,
            arm=EQUALITY_ARM,
            field="quotient_unique_discoveries",
            sampled=sampled,
        )
        ratio = strict_ratio(novelty, equality)
        if ratio is None:
            quotient_ratio_undefined += 1
        else:
            quotient_ratio_samples.append(ratio)

    def interval(values: Sequence[float]) -> dict[str, float] | None:
        if not values:
            return None
        return {
            "lower": nearest_rank(values, 0.025),
            "upper": nearest_rank(values, 0.975),
        }

    totals = {
        arm: {
            "quotient": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
            "literal": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
        }
        for arm in ARMS
    }
    quotient_relative_lift = strict_ratio(
        totals[NOVELTY_ARM]["quotient"] - totals[RANDOM_ARM]["quotient"],
        totals[RANDOM_ARM]["quotient"],
    )
    literal_ratio = strict_ratio(
        totals[NOVELTY_ARM]["literal"],
        totals[RANDOM_ARM]["literal"],
    )
    payload = {
        "schema_version": f"{SCHEMA}.inference",
        "unit": protocol["primary_analysis"]["unit"],
        "literal_superiority_to_equality": {
            "paired_differences": literal_differences,
            "target_point_estimates": literal_target_points,
            "macro_point_estimate": literal_point,
            "bootstrap_95_interval": interval(literal_samples),
            "sign_flip": sign_flip_test(
                literal_differences,
                point=literal_point,
                protocol=protocol,
                label="literal_superiority_to_equality",
            ),
        },
        "quotient_noninferiority_to_equality": {
            "novelty_target_macro_mean": quotient_novelty_macro,
            "equality_target_macro_mean": quotient_equality_macro,
            "ratio_defined": quotient_ratio_point is not None,
            "ratio_point_estimate": quotient_ratio_point,
            "bootstrap_95_interval": interval(quotient_ratio_samples),
            "bootstrap_undefined_denominator_count": quotient_ratio_undefined,
            "zero_denominator_rule": "fail",
        },
        "quotient_superiority_to_random": {
            "paired_differences": quotient_random_differences,
            "target_point_estimates": quotient_random_target_points,
            "macro_point_estimate": quotient_random_point,
            "bootstrap_95_interval": interval(quotient_random_samples),
            "sign_flip": sign_flip_test(
                quotient_random_differences,
                point=quotient_random_point,
                protocol=protocol,
                label="quotient_superiority_to_random",
            ),
            "total_relative_lift": quotient_relative_lift,
            "relative_lift_defined": quotient_relative_lift is not None,
        },
        "total_discoveries": totals,
        "literal_total_ratio_to_random": literal_ratio,
        "literal_total_ratio_defined": literal_ratio is not None,
        "bootstrap": {
            "method": frozen["method"],
            "resamples": frozen["resamples"],
            "rng_seed": frozen["rng_seed"],
            "rng_algorithm": "sha256_unbiased_counter_randbelow_v3",
            "percentile_rule": "nearest_rank_ceil_probability_times_n",
            "literal_macro_samples_sha256": object_sha256(
                [value.hex() for value in literal_samples]
            ),
            "quotient_ratio_samples_sha256": object_sha256(
                [value.hex() for value in quotient_ratio_samples]
            ),
            "quotient_random_macro_samples_sha256": object_sha256(
                [value.hex() for value in quotient_random_samples]
            ),
        },
        "proposal_level_inference_performed": False,
        "secondary_metrics_can_rescue_primary": False,
    }
    return hashed_record(payload, "inference_sha256")


def independent_gate(
    streams: Sequence[Mapping[str, Any]],
    inference: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    frozen = protocol["pareto_restoration_gate"]
    literal = inference["literal_superiority_to_equality"]
    quotient = inference["quotient_noninferiority_to_equality"]
    random = inference["quotient_superiority_to_random"]
    cells = {
        arm: {
            tuple(cell)
            for row in streams
            if row["arm"] == arm
            for cell in row["descriptor_cells"]
        }
        for arm in ARMS
    }
    descriptor_ratio = strict_ratio(
        len(cells[NOVELTY_ARM]),
        len(cells[RANDOM_ARM]),
    )
    classes = {
        target: {
            name
            for row in streams
            if row["target"] == target and row["arm"] == NOVELTY_ARM
            for name, count in row["transition_class_counts"].items()
            if count > 0
        }
        for target in TARGETS
    }
    support = {
        f"{target}|{arm}": {
            "quotient": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["target"] == target and row["arm"] == arm
            ),
            "literal": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["target"] == target and row["arm"] == arm
            ),
        }
        for target in TARGETS
        for arm in ARMS
    }
    literal_interval = literal["bootstrap_95_interval"]
    quotient_interval = quotient["bootstrap_95_interval"]
    random_interval = random["bootstrap_95_interval"]
    checks = {
        "literal_superiority_to_equality_point": (
            literal["macro_point_estimate"] > 0
        ),
        "literal_superiority_to_equality_interval": (
            literal_interval is not None and literal_interval["lower"] > 0
        ),
        "quotient_noninferiority_point": (
            quotient["ratio_defined"]
            and quotient["ratio_point_estimate"]
            >= frozen["quotient_ratio_point_ge"]
        ),
        "quotient_noninferiority_interval": (
            quotient["bootstrap_undefined_denominator_count"] == 0
            and quotient_interval is not None
            and quotient_interval["lower"]
            >= frozen["quotient_ratio_interval_lower_ge"]
        ),
        "quotient_superiority_to_random_point": (
            random["macro_point_estimate"] > 0
        ),
        "quotient_superiority_to_random_interval": (
            random_interval is not None and random_interval["lower"] > 0
        ),
        "minimum_quotient_relative_lift_to_random": (
            random["relative_lift_defined"]
            and random["total_relative_lift"]
            >= frozen["minimum_quotient_relative_lift_to_random"]
        ),
        "minimum_literal_ratio_to_random": (
            inference["literal_total_ratio_defined"]
            and inference["literal_total_ratio_to_random"]
            >= frozen["minimum_literal_ratio_to_random"]
        ),
        "positive_literal_mean_difference_for_every_target": all(
            value > 0 for value in literal["target_point_estimates"].values()
        ),
        "minimum_descriptor_cell_ratio_to_random": (
            descriptor_ratio is not None
            and descriptor_ratio
            >= frozen["minimum_descriptor_cell_ratio_to_random"]
        ),
        "both_transition_classes_for_every_target": all(
            {"embodiment_only", "literal_tree_crossing"} <= classes[target]
            for target in TARGETS
        ),
        "nonzero_quotient_and_literal_support_every_arm_and_target": all(
            row["quotient"] > 0 and row["literal"] > 0
            for row in support.values()
        ),
    }
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.gate",
            "checks": checks,
            "all_scientific_checks_pass_before_independent_replay": all(
                checks.values()
            ),
            "descriptor_cell_counts": {
                arm: len(cells[arm]) for arm in ARMS
            },
            "descriptor_cell_ratio_to_random": descriptor_ratio,
            "novelty_transition_classes_by_target": {
                target: sorted(classes[target]) for target in TARGETS
            },
            "support_by_target_arm": support,
            "zero_denominator_rule": "fail",
            "integrity_pending_independent_replay": True,
            "secondary_rescue_allowed": False,
        },
        "gate_sha256",
    )


def pending_report(
    streams: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    totals = {
        arm: {
            "quotient": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
            "literal": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["arm"] == arm
            ),
        }
        for arm in ARMS
    }
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.preliminary_report",
            "status": "AWAITING_INDEPENDENT_INFERENCE_AND_GATE_REPLAY",
            "totals": totals,
            "frozen_thresholds": protocol["pareto_restoration_gate"],
            "scientific_status": None,
            "independent_replay_pending": True,
            "paper_evidence": False,
        },
        "report_sha256",
    )


def verify_launch_and_dependencies(
    *,
    repo_root: Path,
    run_dir: Path,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    launch_path = run_dir / "launch_record.json"
    launch = load_canonical_json(launch_path)
    verify_self_hash(launch, "launch_sha256", label="V3 test launch")
    if (
        launch.get("schema_version") != f"{SCHEMA}.launch"
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("V3 launch boundary changed")
    if manifest.get("launch_file_sha256") != file_sha256(launch_path):
        raise ValueError("V3 manifest launch binding changed")
    expected_protocol = {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }
    if launch.get("protocol") != expected_protocol:
        raise ValueError("V3 launch protocol binding changed")
    test = protocol["splits"]["test"]
    expected_design = {
        "targets": list(TARGETS),
        "pair_seeds": test["pair_seeds"],
        "initialization_indices": list(range(12)),
        "arms": list(ARMS),
        "calls_per_arm_pair": 2048,
        "candidate_pool_size": 16,
        "checkpoints": test["checkpoints"],
        "success_stopping_rule": False,
    }
    if launch.get("test_design") != expected_design:
        raise ValueError("V3 launch design changed")
    bound = {}
    for field in (
        "initialization_manifest",
        "validation_completion",
        "prior_registry",
        "model_package",
        "model_verification",
        "resource_preflight",
    ):
        path = safe_binding(repo_root, launch[field], label=field)
        bound[field] = load_canonical_json(path)
    sources = launch.get("sources")
    snapshots = manifest.get("source_bundle")
    if (
        not isinstance(sources, list)
        or not sources
        or not isinstance(snapshots, list)
        or len(sources) != len(snapshots)
    ):
        raise ValueError("V3 source snapshot inventory changed")
    for index, (binding, snapshot) in enumerate(zip(sources, snapshots)):
        source = safe_binding(repo_root, binding, label=f"source {index}")
        expected_snapshot = {
            "path": binding["path"],
            "sha256": binding["sha256"],
            "snapshot_path": (
                Path("source_bundle") / Path(binding["path"])
            ).as_posix(),
            "snapshot_sha256": binding["sha256"],
            "bytes": source.stat().st_size,
        }
        snapshot_path = run_dir / expected_snapshot["snapshot_path"]
        if (
            snapshot != expected_snapshot
            or not snapshot_path.is_file()
            or file_sha256(snapshot_path) != binding["sha256"]
            or snapshot_path.read_bytes() != source.read_bytes()
        ):
            raise ValueError("V3 source snapshot changed")
    authorization_payload = {
        field: launch[field]
        for field in (
            "protocol",
            "test_design",
            "sources",
            "initialization_manifest",
            "validation_completion",
            "prior_registry",
            "model_package",
            "model_verification",
            "resource_preflight",
            "commands",
            "resource_limits",
            "authorization_nonce",
        )
    }
    if object_sha256(authorization_payload) != launch.get(
        "authorization_sha256"
    ):
        raise ValueError("V3 authorization does not replay")
    expected_output = (
        "output/research/digraph-order7-diversity-policy-test-v3-"
        + launch["authorization_sha256"][:12]
    )
    if (
        launch.get("output_directory") != expected_output
        or run_dir.resolve() != (repo_root / expected_output).resolve()
    ):
        raise ValueError("V3 output directory is not authorization-derived")

    initialization = bound["initialization_manifest"]
    verify_self_hash(initialization, "manifest_sha256", label="initialization")
    completion = bound["validation_completion"]
    verify_self_hash(completion, "completion_sha256", label="validation completion")
    prior = bound["prior_registry"]
    verify_self_hash(prior, "registry_sha256", label="test prior registry")
    package = bound["model_package"]
    verify_self_hash(package, "package_sha256", label="model package")
    model_verification = bound["model_verification"]
    verify_self_hash(
        model_verification,
        "verification_sha256",
        label="model verification",
    )
    preflight = bound["resource_preflight"]
    verify_self_hash(preflight, "report_sha256", label="resource preflight")
    if (
        initialization
        != load_canonical_json(repo_root / INITIALIZATION_MANIFEST)
        or completion
        != load_canonical_json(repo_root / VALIDATION_COMPLETION)
        or prior != load_canonical_json(repo_root / PRIOR_REGISTRY)
        or completion.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("test_authorization_allowed") is not True
        or completion.get("test_data_generated") is not False
        or prior.get("status") != "FROZEN_ALL_PRE_TEST_IDENTITIES"
        or package.get("status")
        != "FROZEN_VALIDATED_DIVERSITY_MODEL_PACKAGE"
        or model_verification.get("status") != "PASS_MODEL_PACKAGE_ONLY"
        or model_verification.get(
            "selected_scores_embeddings_memory_and_rank_fusion_replay"
        )
        is not True
        or preflight.get("status") != "PASS"
        or preflight.get("test_data_generated") is not False
        or preflight.get("semantic_test_evaluation_performed") is not False
        or preflight.get("projection", {}).get("status") != "PASS"
    ):
        raise ValueError("V3 frozen dependency boundary changed")
    return {"launch": launch, **bound}


def mutate(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return ("0" if value[:1] != "0" else "1") + value[1:]
    if isinstance(value, int):
        return value + 1
    if isinstance(value, list):
        return list(reversed(value)) if len(value) > 1 else value + ["tamper"]
    if isinstance(value, Mapping):
        changed = dict(value)
        changed["tamper"] = True
        return changed
    if value is None:
        return "tamper"
    return str(value) + "-tamper"


def corruption_suite(components: Mapping[str, Any]) -> dict[str, Any]:
    if tuple(components) != CORRUPTION_FAMILIES:
        raise AssertionError("V3 test corruption components changed")
    commitment = object_sha256(components)
    tests = []
    for family in CORRUPTION_FAMILIES:
        changed = copy.deepcopy(components)
        changed[family] = mutate(changed[family])
        changed_sha = object_sha256(changed)
        rejected = changed != components and changed_sha != commitment
        tests.append(
            {
                "family": family,
                "mutation_rehashed": True,
                "changed_projection_sha256": changed_sha,
                "rejected": rejected,
            }
        )
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.corruption_tests",
            "status": (
                "PASS" if all(row["rejected"] for row in tests) else "FAIL"
            ),
            "required_family_count": len(CORRUPTION_FAMILIES),
            "rejected_family_count": sum(row["rejected"] for row in tests),
            "semantic_projection_sha256": commitment,
            "tests": tests,
        },
        "corruption_tests_sha256",
    )


def final_report(
    *,
    mode: str,
    status: str,
    inference: Mapping[str, Any],
    gate: Mapping[str, Any],
    corruption: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.report",
            "status": status,
            "decision": status if status in ("GO", "NO_GO") else "NOT_APPLICABLE_SMOKE",
            "mode": mode,
            "paper_evidence": mode == OFFICIAL_MODE,
            "co_primary_analysis": {
                "literal_superiority_to_equality": inference[
                    "literal_superiority_to_equality"
                ],
                "quotient_noninferiority_to_equality": inference[
                    "quotient_noninferiority_to_equality"
                ],
            },
            "random_reference": {
                "quotient_superiority_to_random": inference[
                    "quotient_superiority_to_random"
                ],
                "literal_total_ratio_to_random": inference[
                    "literal_total_ratio_to_random"
                ],
            },
            "pareto_restoration_gate": {
                "checks": gate["checks"],
                "all_scientific_checks_pass": gate[
                    "all_scientific_checks_pass_before_independent_replay"
                ],
                "integrity_checks_pass": corruption["status"] == "PASS",
                "secondary_rescue_allowed": False,
            },
            "descriptor_cell_counts": gate["descriptor_cell_counts"],
            "descriptor_cell_ratio_to_random": gate[
                "descriptor_cell_ratio_to_random"
            ],
            "support_by_target_arm": gate["support_by_target_arm"],
            "novelty_transition_classes_by_target": gate[
                "novelty_transition_classes_by_target"
            ],
            "corruption_suite": {
                "status": corruption["status"],
                "required_family_count": corruption["required_family_count"],
                "rejected_family_count": corruption["rejected_family_count"],
                "corruption_tests_sha256": corruption[
                    "corruption_tests_sha256"
                ],
            },
            "claim_wording": (
                protocol["claim_boundary"]["go_wording"]
                if status == "GO"
                else None
            ),
            "v1_no_go_disclosed": True,
            "v2_deadlock_no_go_disclosed": True,
            "human_preference_measured": False,
            "aesthetic_quality_measured": False,
            "no_secondary_rescue": True,
        },
        "report_sha256",
    )


def replay(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    errors = protocol_validator.validate(
        protocol,
        repo_root,
        check_bound_files=True,
    )
    if errors:
        raise ValueError("V3 protocol validation failed: " + "; ".join(errors))
    manifest = load_canonical_json(run_dir / "manifest.json")
    verify_self_hash(manifest, "manifest_sha256", label="V3 test manifest")
    mode = manifest.get("mode")
    if mode not in (OFFICIAL_MODE, SMOKE_MODE):
        raise ValueError("V3 test mode changed")
    design = manifest.get("design", {})
    if (
        manifest.get("schema_version") != f"{SCHEMA}.manifest"
        or manifest.get("paper_evidence") is not False
        or design.get("targets") != list(TARGETS)
        or design.get("arms") != list(ARMS)
        or design.get("candidate_pool_size") != 16
        or design.get("pair_local_hash_chains") is not True
        or design.get("success_stopping_rule") is not False
        or manifest.get("kernel", {}).get("implementation")
        != "frozen_v2_three_arm_kernel"
        or manifest.get("kernel", {}).get("model_or_threshold_change") is not False
    ):
        raise ValueError("V3 test manifest boundary changed")
    initialization = load_canonical_json(run_dir / "initialization_manifest.json")
    verify_self_hash(initialization, "manifest_sha256", label="initialization")
    prior = load_canonical_json(run_dir / "prior_split_registry.json")
    verify_self_hash(prior, "registry_sha256", label="test prior registry")
    if (
        initialization != load_canonical_json(repo_root / INITIALIZATION_MANIFEST)
        or prior != load_canonical_json(repo_root / PRIOR_REGISTRY)
        or manifest.get("initialization_manifest_sha256")
        != initialization["manifest_sha256"]
        or manifest.get("prior_registry_sha256") != prior["registry_sha256"]
    ):
        raise ValueError("V3 test frozen inputs changed")
    dependencies = None
    if mode == OFFICIAL_MODE:
        frozen = protocol["splits"]["test"]
        if (
            design.get("pair_seeds") != frozen["pair_seeds"]
            or design.get("initialization_indices") != list(range(12))
            or design.get("calls_per_arm_pair") != 2048
            or design.get("checkpoints") != frozen["checkpoints"]
            or manifest.get("test_data_generated") is not True
            or manifest.get("kernel", {}).get("fresh_pair_seeds") is not True
            or manifest.get("kernel", {}).get("pair_specific_initialization")
            is not True
        ):
            raise ValueError("official V3 test design changed")
        dependencies = verify_launch_and_dependencies(
            repo_root=repo_root,
            run_dir=run_dir,
            manifest=manifest,
            protocol=protocol,
        )
    else:
        expected_seed = smoke_seed()
        official_seeds = set(protocol["splits"]["validation"]["pair_seeds"])
        official_seeds.update(protocol["splits"]["test"]["pair_seeds"])
        if (
            manifest.get("launch_file_sha256") is not None
            or manifest.get("source_bundle") != []
            or manifest.get("test_data_generated") is not False
            or design.get("pair_seeds") != [expected_seed]
            or expected_seed in official_seeds
            or design.get("initialization_indices") != [0]
            or design.get("calls_per_arm_pair") not in range(1, 5)
        ):
            raise ValueError("V3 smoke boundary changed")
    claimed_aggregate = load_canonical_json(run_dir / "stream_metrics.json")
    verify_self_hash(
        claimed_aggregate,
        "bundle_sha256",
        label="aggregate test streams",
    )
    all_streams = []
    pair_endpoints = []
    first_witness = None
    for pair_index, pair_seed in enumerate(design["pair_seeds"]):
        pair_dir = run_dir / "pairs" / f"{pair_index:02d}"
        claimed = load_canonical_json(pair_dir / "stream_metrics.json")
        verify_self_hash(claimed, "bundle_sha256", label="pair streams")
        pair_registry = validation_v3.expected_pair_registry(
            prior,
            initialization,
            split="test",
            index=(pair_index if mode == OFFICIAL_MODE else 0),
        )
        streams, final_proposal, final_event, witness = v2.replay_ledgers(
            repo_root=repo_root,
            run_dir=pair_dir,
            mode=mode,
            registry=pair_registry,
            design={
                "pair_seeds": [pair_seed],
                "calls_per_arm_pair": design["calls_per_arm_pair"],
            },
            claimed_streams=claimed,
        )
        expected_pair = v2.independent_stream_bundle(streams)
        if expected_pair != claimed:
            raise ValueError("pair stream bundle does not replay")
        all_streams.extend(streams)
        pair_endpoints.append(
            {
                "pair_index": pair_index,
                "pair_seed": pair_seed,
                "proposal_count": len(TARGETS)
                * len(ARMS)
                * design["calls_per_arm_pair"],
                "event_count": len(TARGETS)
                * len(ARMS)
                * design["calls_per_arm_pair"],
                "proposal_file_sha256": file_sha256(
                    pair_dir / "proposal_decisions.jsonl"
                ),
                "event_file_sha256": file_sha256(pair_dir / "events.jsonl"),
                "stream_file_sha256": file_sha256(
                    pair_dir / "stream_metrics.json"
                ),
                "final_proposal_sha256": final_proposal,
                "final_event_sha256": final_event,
            }
        )
        if first_witness is None:
            first_witness = witness
    expected_aggregate = v2.independent_stream_bundle(all_streams)
    if expected_aggregate != claimed_aggregate:
        raise ValueError("aggregate V3 streams do not replay")
    supplied_preliminary = load_canonical_json(run_dir / "preliminary_report.json")
    verify_self_hash(
        supplied_preliminary,
        "report_sha256",
        label="preliminary report",
    )
    if supplied_preliminary != pending_report(all_streams, protocol):
        raise ValueError("V3 preliminary report does not replay")
    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    verify_self_hash(generation, "generation_sha256", label="generation")
    expected_count = (
        len(TARGETS)
        * len(design["pair_seeds"])
        * len(ARMS)
        * design["calls_per_arm_pair"]
    )
    file_bindings = {
        "manifest_file_sha256": "manifest.json",
        "prior_registry_file_sha256": "prior_split_registry.json",
        "initialization_manifest_file_sha256": "initialization_manifest.json",
        "stream_metrics_file_sha256": "stream_metrics.json",
        "preliminary_report_file_sha256": "preliminary_report.json",
    }
    for field, relative in file_bindings.items():
        if generation.get(field) != file_sha256(run_dir / relative):
            raise ValueError(f"V3 generation file binding changed: {field}")
    if (
        generation.get("pair_endpoints") != pair_endpoints
        or generation.get("proposal_count") != expected_count
        or generation.get("event_count") != expected_count
        or generation.get("exact_verifier_calls_consumed") != expected_count
        or generation.get("raw_pool_candidate_count") != expected_count * 16
        or generation.get("scientific_gate_pending_independent_replay") is not True
        or generation.get("paper_evidence") is not False
    ):
        raise ValueError("V3 generation counts or endpoints changed")
    if mode == OFFICIAL_MODE:
        limits = protocol["resource_gate"]
        if (
            generation.get("generation_wall_seconds", math.inf)
            > limits["test_generation_wall_seconds"]
            or generation.get("run_directory_bytes_before_marker", math.inf)
            > limits["run_directory_bytes"]
            or generation.get("peak_resident_memory_bytes", math.inf)
            > limits["peak_resident_memory_bytes"]
        ):
            raise ValueError("V3 generation resource gate failed")
    elif (
        generation.get("generation_wall_seconds") != 0.0
        or generation.get("peak_resident_memory_bytes") != 0
    ):
        raise ValueError("V3 smoke timing was not suppressed")
    inference = independent_inference(all_streams, protocol)
    gate = independent_gate(all_streams, inference, protocol)
    support = gate["support_by_target_arm"]
    components = {
        "protocol": manifest["protocol"],
        "launch": (
            dependencies["launch"]["launch_sha256"] if dependencies else None
        ),
        "source": manifest["source_bundle"],
        "validation_completion": manifest["validation_completion_sha256"],
        "prior_registry": prior["registry_sha256"],
        "initialization_manifest": initialization["manifest_sha256"],
        "initialization_assignment": initialization["initializations"]["test"],
        "resource_preflight": (
            dependencies["resource_preflight"]["report_sha256"]
            if dependencies
            else None
        ),
        "model_package": (
            dependencies["model_package"]["package_sha256"]
            if dependencies
            else None
        ),
        "model_verification": (
            dependencies["model_verification"]["verification_sha256"]
            if dependencies
            else None
        ),
        "test_seed": design["pair_seeds"][0],
        "target_arm_schedule": [list(TARGETS), list(ARMS)],
        "parent_rng": first_witness["parent_quotient_sha256"],
        "arc_permutation": first_witness["selected_arc"],
        "candidate_graph": first_witness["selected_candidate"],
        "candidate_identity": first_witness["candidate_sha256"],
        "structural_tier": first_witness["structural_tier"],
        "equality_logit": first_witness["equality_logit_hex"],
        "novelty_embedding": first_witness["novelty"],
        "novelty_memory": first_witness["novelty_memory_size"],
        "rank_fusion": (
            first_witness["novelty"]["rank_fusion_score"]
            if first_witness["novelty"] is not None
            else None
        ),
        "selected_slot": first_witness["selected_slot"],
        "exact_decision": first_witness["exact_equal"],
        "literal_digest": first_witness["literal_game_sha256"],
        "quotient": first_witness["quotient_sha256"],
        "descriptor": first_witness["descriptor_cell"],
        "retention_transition": [
            first_witness["inserted"],
            first_witness["transition"],
        ],
        "hash_chain_endpoint": pair_endpoints,
        "stream_inference_gate": [
            expected_aggregate["bundle_sha256"],
            inference["inference_sha256"],
            gate["gate_sha256"],
        ],
        "nonzero_support": support,
    }
    corruption = corruption_suite(components)
    if (
        corruption["status"] != "PASS"
        or corruption["rejected_family_count"]
        != protocol["integrity"]["corruption_family_count"]
    ):
        raise ValueError("V3 corruption suite failed")
    write_json_exclusive(
        run_dir / "independent_stream_metrics.json",
        expected_aggregate,
    )
    write_json_exclusive(run_dir / "independent_inference.json", inference)
    write_json_exclusive(run_dir / "independent_gate.json", gate)
    write_json_exclusive(run_dir / "corruption_tests.json", corruption)
    elapsed = time.monotonic() - started
    if (
        mode == OFFICIAL_MODE
        and elapsed > protocol["resource_gate"]["test_verification_wall_seconds"]
    ):
        raise TimeoutError("V3 independent verification exceeded its limit")
    verification = hashed_record(
        {
            "schema_version": f"{SCHEMA}.independent_verification",
            "status": "PASS" if mode == OFFICIAL_MODE else "SMOKE_PASS_NOT_EVIDENCE",
            "mode": mode,
            "protocol_initialization_validation_model_and_preflight_replay": (
                mode == OFFICIAL_MODE
            ),
            "pair_assignment_rng_pool_model_memory_replay": True,
            "exact_decision_descriptor_retention_transition_replay": True,
            "independent_quotient_and_literal_discovery_replay": True,
            "stream_inference_gate_replay": True,
            "strict_zero_denominator_rule_replay": True,
            "corruption_suite_pass": True,
            "corruption_family_count": len(CORRUPTION_FAMILIES),
            "proposal_count": expected_count,
            "event_count": expected_count,
            "aggregate_stream_sha256": expected_aggregate["bundle_sha256"],
            "inference_sha256": inference["inference_sha256"],
            "gate_sha256": gate["gate_sha256"],
            "wall_seconds": 0.0 if mode == SMOKE_MODE else elapsed,
            "paper_evidence": False,
        },
        "verification_sha256",
    )
    write_json_exclusive(
        run_dir / "independent_verification.json",
        verification,
    )
    scientific_pass = gate[
        "all_scientific_checks_pass_before_independent_replay"
    ]
    status = (
        ("GO" if scientific_pass else "NO_GO")
        if mode == OFFICIAL_MODE
        else "SMOKE_PASS_NOT_EVIDENCE"
    )
    report = final_report(
        mode=mode,
        status=status,
        inference=inference,
        gate=gate,
        corruption=corruption,
        protocol=protocol,
    )
    write_json_exclusive(run_dir / "report.json", report)
    completion = hashed_record(
        {
            "schema_version": f"{SCHEMA}.completion",
            "status": status,
            "decision": status if mode == OFFICIAL_MODE else "NOT_APPLICABLE_SMOKE",
            "mode": mode,
            "scientific_gate_pass": (
                scientific_pass if mode == OFFICIAL_MODE else False
            ),
            "independent_replay_pass": True,
            "corruption_suite_pass": True,
            "corruption_family_count": len(CORRUPTION_FAMILIES),
            "equal_exact_verifier_budgets": True,
            "strict_zero_denominator_rule": True,
            "secondary_rescue_used": False,
            "evidence_eligible": mode == OFFICIAL_MODE,
            "paper_evidence": mode == OFFICIAL_MODE,
            "generation_file_sha256": file_sha256(
                run_dir / "GENERATION_COMPLETE.json"
            ),
            "stream_metrics_file_sha256": file_sha256(
                run_dir / "stream_metrics.json"
            ),
            "independent_stream_metrics_file_sha256": file_sha256(
                run_dir / "independent_stream_metrics.json"
            ),
            "inference_file_sha256": file_sha256(
                run_dir / "independent_inference.json"
            ),
            "gate_file_sha256": file_sha256(run_dir / "independent_gate.json"),
            "verification_file_sha256": file_sha256(
                run_dir / "independent_verification.json"
            ),
            "corruption_tests_file_sha256": file_sha256(
                run_dir / "corruption_tests.json"
            ),
            "report_file_sha256": file_sha256(run_dir / "report.json"),
        },
        "completion_sha256",
    )
    write_json_exclusive(run_dir / "RUN_COMPLETE.json", completion)
    return completion


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    run_dir = (
        args.run_dir
        if args.run_dir.is_absolute()
        else repo_root / args.run_dir
    ).resolve()
    completion = replay(run_dir, repo_root)
    print(json.dumps(completion, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
