#!/usr/bin/env python3
"""Independent replay and finalizer for V3 acquisition-support validation."""

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
import verify_digraph_order7_diversity_policy_test_v2 as v2_verifier


SCHEMA = "partizan.digraph_order7_diversity_policy_validation.v3"
PROTOCOL_PATH = protocol_validator.PROTOCOL_PATH
INITIALIZATION_MANIFEST = Path(
    "output/research/digraph-order7-policy-v3-initializations-v1/"
    "INITIALIZATION_MANIFEST.json"
)
PRIOR_REGISTRY = Path(
    "output/research/digraph-order7-v2-reachability-diagnostic-v1/"
    "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
)
TARGETS = v2_verifier.TARGETS
ARMS = v2_verifier.ARMS
OFFICIAL_MODE = v2_verifier.OFFICIAL_MODE
SMOKE_MODE = v2_verifier.SMOKE_MODE
CORRUPTION_FAMILIES = (
    "protocol",
    "launch",
    "source",
    "v2_completion",
    "v2_verification",
    "diagnostic",
    "prior_registry",
    "initialization_manifest",
    "initialization_assignment",
    "initialization_support",
    "validation_seed",
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
    "stream_projection",
    "validation_registry_completion",
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


def expected_pair_registry(
    registry: Mapping[str, Any],
    initialization: Mapping[str, Any],
    *,
    split: str,
    index: int,
) -> dict[str, Any]:
    controls = {}
    candidates = set(registry["candidate_sha256"])
    quotients = set(registry["quotient_sha256"])
    for target in TARGETS:
        row = initialization["initializations"][split][target][index]
        if (
            row["candidate_sha256"] not in candidates
            or row["quotient_sha256"] not in quotients
            or row[
                "weakly_connected_nonprior_candidate_neighbor_count"
            ]
            < 32
            or row["counts_as_discovery"] is not False
            or row["shared_across_arms"] is not True
            or row["selected_using_semantic_outcome"] is not False
        ):
            raise ValueError("initialization assignment changed")
        controls[target] = {
            "candidate": row["candidate"],
            "candidate_sha256": row["candidate_sha256"],
            "quotient_sha256": row["quotient_sha256"],
            "literal_game_sha256": row["literal_game_sha256"],
            "test_discovery": False,
            "initialization_id": row["initialization_id"],
        }
    return {
        "candidate_sha256": registry["candidate_sha256"],
        "quotient_sha256": registry["quotient_sha256"],
        "literal_game_sha256_audit_only": registry[
            "literal_game_sha256_audit_only"
        ],
        "stage0_controls": controls,
    }


def independent_projection(
    *,
    run_dir: Path,
    streams: Sequence[Mapping[str, Any]],
    pair_count: int,
    calls: int,
) -> dict[str, Any]:
    clean: Counter[tuple[str, str]] = Counter()
    first_tiers = {}
    for pair_index in range(pair_count):
        with (
            run_dir / "pairs" / f"{pair_index:02d}" / "events.jsonl"
        ).open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                if event["call_index"] == 0:
                    key = (
                        f"{event['target']}|{event['pair_seed']}|"
                        f"{event['arm']}"
                    )
                    first_tiers[key] = event["structural_filter"]["tier_index"]
                decision = event["exact_decision"]
                if (
                    isinstance(decision, Mapping)
                    and decision.get("equal") is True
                    and not event["prior_split_leakage"]
                ):
                    clean[(event["target"], event["arm"])] += 1
    by_target_arm = {
        f"{target}|{arm}": {
            "clean_exact_matches": clean[(target, arm)],
            "quotient_discoveries": sum(
                row["quotient_unique_discoveries"]
                for row in streams
                if row["target"] == target and row["arm"] == arm
            ),
            "literal_discoveries": sum(
                row["literal_game_unique_discoveries"]
                for row in streams
                if row["target"] == target and row["arm"] == arm
            ),
        }
        for target in TARGETS
        for arm in ARMS
    }
    checks = {
        "first_pool_tier_zero_for_every_stream": (
            len(first_tiers) == len(TARGETS) * pair_count * len(ARMS)
            and all(value == 0 for value in first_tiers.values())
        ),
        "at_least_one_nonprior_selection_every_stream": all(
            row["prior_split_collision_count"] < calls for row in streams
        ),
        "at_least_one_clean_exact_match_every_arm_and_target": all(
            value["clean_exact_matches"] > 0
            for value in by_target_arm.values()
        ),
        "at_least_one_quotient_discovery_every_arm_and_target": all(
            value["quotient_discoveries"] > 0
            for value in by_target_arm.values()
        ),
    }
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.projection",
            "status": (
                "PASS_SUPPORT_VALIDATION_ONLY"
                if all(checks.values())
                else "FAIL_SUPPORT_VALIDATION"
            ),
            "checks": checks,
            "first_tier_by_stream": dict(sorted(first_tiers.items())),
            "by_target_arm": by_target_arm,
            "model_or_threshold_selection_performed": False,
            "test_initializations_or_seeds_used": False,
            "test_data_generated": False,
            "paper_evidence": False,
        },
        "projection_sha256",
    )


def validation_identity_registry(
    *,
    run_dir: Path,
    prior: Mapping[str, Any],
    pair_count: int,
) -> dict[str, Any]:
    candidates = set(prior["candidate_sha256"])
    quotients = set(prior["quotient_sha256"])
    literals = set(prior["literal_game_sha256_audit_only"])
    event_count = 0
    event_files = []
    for pair_index in range(pair_count):
        relative = Path("pairs") / f"{pair_index:02d}" / "events.jsonl"
        path = run_dir / relative
        rows = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                rows += 1
                event_count += 1
                candidates.add(event["candidate_sha256"])
                structural = event.get("structural_quotient")
                if isinstance(structural, Mapping):
                    quotients.add(structural["quotient_sha256"])
                decision = event.get("exact_decision")
                if isinstance(decision, Mapping):
                    literals.add(decision["candidate_root_game_sha256"])
        event_files.append(
            {
                "path": relative.as_posix(),
                "sha256": file_sha256(path),
                "row_count": rows,
            }
        )
    return hashed_record(
        {
            "schema_version": f"{SCHEMA}.test_prior_registry",
            "status": "FROZEN_ALL_PRE_TEST_IDENTITIES",
            "source_prior_registry_sha256": prior["registry_sha256"],
            "validation_event_files": event_files,
            "candidate_sha256": sorted(candidates),
            "quotient_sha256": sorted(quotients),
            "literal_game_sha256_audit_only": sorted(literals),
            "counts": {
                "candidate_identities": len(candidates),
                "quotient_identities": len(quotients),
                "literal_game_identities_audit_only": len(literals),
                "validation_event_rows": event_count,
            },
            "blocking_rule": ["candidate_sha256", "quotient_sha256"],
            "recorded_not_blocked": ["literal_game_sha256"],
            "model_training_use": False,
            "model_selection_use": False,
            "test_data_generated": False,
            "paper_evidence": False,
        },
        "registry_sha256",
    )


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
        raise AssertionError("V3 validation corruption components changed")
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
    verify_self_hash(manifest, "manifest_sha256", label="validation manifest")
    mode = manifest.get("mode")
    if mode not in (OFFICIAL_MODE, SMOKE_MODE):
        raise ValueError("V3 validation mode changed")
    design = manifest.get("design", {})
    if (
        manifest.get("schema_version") != f"{SCHEMA}.manifest"
        or manifest.get("paper_evidence") is not False
        or manifest.get("test_data_generated") is not False
        or design.get("targets") != list(TARGETS)
        or design.get("arms") != list(ARMS)
        or design.get("candidate_pool_size") != 16
        or design.get("model_or_threshold_selection_allowed") is not False
    ):
        raise ValueError("V3 validation manifest boundary changed")
    initialization = load_canonical_json(run_dir / "initialization_manifest.json")
    verify_self_hash(
        initialization,
        "manifest_sha256",
        label="initialization manifest",
    )
    prior = load_canonical_json(run_dir / "prior_split_registry.json")
    verify_self_hash(prior, "registry_sha256", label="V3 prior registry")
    if (
        initialization
        != load_canonical_json(repo_root / INITIALIZATION_MANIFEST)
        or prior != load_canonical_json(repo_root / PRIOR_REGISTRY)
        or manifest.get("initialization_manifest_sha256")
        != initialization["manifest_sha256"]
        or manifest.get("prior_registry_sha256") != prior["registry_sha256"]
    ):
        raise ValueError("V3 validation frozen inputs changed")
    if mode == OFFICIAL_MODE:
        frozen = protocol["splits"]["validation"]
        if (
            design.get("pair_seeds") != frozen["pair_seeds"]
            or design.get("initialization_indices") != [0, 1, 2, 3]
            or design.get("calls_per_arm_pair") != 128
        ):
            raise ValueError("official V3 validation design changed")
        launch = load_canonical_json(run_dir / "launch_record.json")
        verify_self_hash(launch, "launch_sha256", label="validation launch")
        if manifest.get("launch_file_sha256") != file_sha256(
            run_dir / "launch_record.json"
        ):
            raise ValueError("validation launch binding changed")
        split = "validation"
    else:
        if (
            manifest.get("launch_file_sha256") is not None
            or len(design.get("pair_seeds", [])) != 1
            or design.get("calls_per_arm_pair") not in range(1, 5)
        ):
            raise ValueError("V3 validation smoke boundary changed")
        launch = {}
        split = "validation"
    claimed_aggregate = load_canonical_json(
        run_dir / "validation_stream_metrics.json"
    )
    verify_self_hash(
        claimed_aggregate,
        "bundle_sha256",
        label="aggregate streams",
    )
    all_streams = []
    pair_endpoints = []
    first_witness = None
    for pair_index, pair_seed in enumerate(design["pair_seeds"]):
        pair_dir = run_dir / "pairs" / f"{pair_index:02d}"
        claimed = load_canonical_json(pair_dir / "stream_metrics.json")
        verify_self_hash(claimed, "bundle_sha256", label="pair streams")
        pair_registry = expected_pair_registry(
            prior,
            initialization,
            split=split,
            index=(pair_index if mode == OFFICIAL_MODE else 0),
        )
        streams, final_proposal, final_event, witness = (
            v2_verifier.replay_ledgers(
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
        )
        expected_pair = v2_verifier.independent_stream_bundle(streams)
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
    expected_aggregate = v2_verifier.independent_stream_bundle(all_streams)
    if expected_aggregate != claimed_aggregate:
        raise ValueError("aggregate validation streams do not replay")
    projection = independent_projection(
        run_dir=run_dir,
        streams=all_streams,
        pair_count=len(design["pair_seeds"]),
        calls=design["calls_per_arm_pair"],
    )
    supplied_projection = load_canonical_json(
        run_dir / "validation_projection.json"
    )
    verify_self_hash(
        supplied_projection,
        "projection_sha256",
        label="validation projection",
    )
    if projection != supplied_projection:
        raise ValueError("V3 validation projection does not replay")
    registry = validation_identity_registry(
        run_dir=run_dir,
        prior=prior,
        pair_count=len(design["pair_seeds"]),
    )
    generation = load_canonical_json(run_dir / "GENERATION_COMPLETE.json")
    verify_self_hash(
        generation,
        "generation_sha256",
        label="validation generation",
    )
    expected_count = (
        len(TARGETS)
        * len(design["pair_seeds"])
        * len(ARMS)
        * design["calls_per_arm_pair"]
    )
    if (
        generation.get("pair_endpoints") != pair_endpoints
        or generation.get("proposal_count") != expected_count
        or generation.get("event_count") != expected_count
        or generation.get("exact_verifier_calls_consumed") != expected_count
        or generation.get("raw_pool_candidate_count") != expected_count * 16
        or generation.get("paper_evidence") is not False
        or generation.get("test_data_generated") is not False
    ):
        raise ValueError("validation generation boundary changed")
    if mode == OFFICIAL_MODE and (
        generation.get("generation_wall_seconds", math.inf)
        > protocol["resource_gate"]["validation_wall_seconds"]
        or generation.get("run_directory_bytes_before_marker", math.inf)
        > protocol["resource_gate"]["run_directory_bytes"]
        or generation.get("peak_resident_memory_bytes", math.inf)
        > protocol["resource_gate"]["peak_resident_memory_bytes"]
    ):
        raise ValueError("V3 validation resource gate failed")
    components = {
        "protocol": manifest["protocol"],
        "launch": launch.get("launch_sha256"),
        "source": manifest["kernel"],
        "v2_completion": protocol["source_evidence"]["v2_completion"],
        "v2_verification": protocol["source_evidence"]["v2_verification"],
        "diagnostic": protocol["source_evidence"]["reachability_diagnostic"],
        "prior_registry": prior["registry_sha256"],
        "initialization_manifest": initialization["manifest_sha256"],
        "initialization_assignment": initialization["initializations"][
            "validation"
        ],
        "initialization_support": 32,
        "validation_seed": design["pair_seeds"][0],
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
        "stream_projection": [
            expected_aggregate["bundle_sha256"],
            projection["projection_sha256"],
        ],
        "validation_registry_completion": registry["registry_sha256"],
    }
    corruption = corruption_suite(components)
    if (
        corruption["status"] != "PASS"
        or corruption["rejected_family_count"] != 30
    ):
        raise ValueError("V3 validation corruption suite failed")
    write_json_exclusive(
        run_dir / "test_prior_split_registry.json",
        registry,
    )
    write_json_exclusive(run_dir / "corruption_tests.json", corruption)
    elapsed = time.monotonic() - started
    validation_pass = (
        projection["status"] == "PASS_SUPPORT_VALIDATION_ONLY"
    )
    verification = hashed_record(
        {
            "schema_version": f"{SCHEMA}.independent_verification",
            "status": (
                "PASS_VALIDATION_ONLY"
                if mode == OFFICIAL_MODE and validation_pass
                else (
                    "NO_GO_VALIDATION"
                    if mode == OFFICIAL_MODE
                    else "SMOKE_PASS_NOT_EVIDENCE"
                )
            ),
            "mode": mode,
            "protocol_and_initialization_replay": True,
            "pair_assignment_rng_pool_model_memory_replay": True,
            "exact_decision_descriptor_retention_transition_replay": True,
            "stream_projection_and_registry_replay": True,
            "corruption_suite_pass": True,
            "corruption_family_count": 30,
            "proposal_count": expected_count,
            "event_count": expected_count,
            "aggregate_stream_sha256": expected_aggregate["bundle_sha256"],
            "projection_sha256": projection["projection_sha256"],
            "test_prior_registry_sha256": registry["registry_sha256"],
            "wall_seconds": 0.0 if mode == SMOKE_MODE else elapsed,
            "test_data_generated": False,
            "paper_evidence": False,
        },
        "verification_sha256",
    )
    write_json_exclusive(
        run_dir / "independent_verification.json",
        verification,
    )
    completion = hashed_record(
        {
            "schema_version": f"{SCHEMA}.completion",
            "status": verification["status"],
            "mode": mode,
            "validation_support_gate_pass": (
                validation_pass if mode == OFFICIAL_MODE else False
            ),
            "test_authorization_allowed": (
                validation_pass if mode == OFFICIAL_MODE else False
            ),
            "model_or_threshold_selection_performed": False,
            "independent_replay_pass": True,
            "corruption_suite_pass": True,
            "corruption_family_count": 30,
            "generation_file_sha256": file_sha256(
                run_dir / "GENERATION_COMPLETE.json"
            ),
            "projection_file_sha256": file_sha256(
                run_dir / "validation_projection.json"
            ),
            "test_prior_registry_file_sha256": file_sha256(
                run_dir / "test_prior_split_registry.json"
            ),
            "verification_file_sha256": file_sha256(
                run_dir / "independent_verification.json"
            ),
            "corruption_tests_file_sha256": file_sha256(
                run_dir / "corruption_tests.json"
            ),
            "test_data_generated": False,
            "paper_evidence": False,
        },
        "completion_sha256",
    )
    write_json_exclusive(run_dir / "VALIDATION_COMPLETE.json", completion)
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
