#!/usr/bin/env python3
"""Generate the V3 acquisition-support validation rehearsal."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping, Sequence

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import digraph_order7_diversity_policy_test_v2 as v2
import validate_digraph_order7_diversity_policy_protocol_v3 as protocol_validator


SCHEMA = "partizan.digraph_order7_diversity_policy_validation.v3"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
PROTOCOL_PATH = protocol_validator.PROTOCOL_PATH
INITIALIZATION_MANIFEST = Path(
    "output/research/digraph-order7-policy-v3-initializations-v1/"
    "INITIALIZATION_MANIFEST.json"
)
PRIOR_REGISTRY = Path(
    "output/research/digraph-order7-v2-reachability-diagnostic-v1/"
    "V3_PRIOR_SPLIT_IDENTITY_REGISTRY.json"
)
TARGETS = v2.TARGETS
ARMS = v2.ARMS
OFFICIAL_MODE = v2.OFFICIAL_MODE
SMOKE_MODE = v2.SMOKE_MODE
SMOKE_PREFIX = f"{SCHEMA}.smoke"


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


def peak_rss_bytes() -> int:
    observed = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return observed if sys.platform == "darwin" else observed * 1024


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


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


def frozen_sources(
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    errors = protocol_validator.validate(
        protocol,
        repo_root,
        check_bound_files=True,
    )
    if errors:
        raise ValueError("V3 protocol validation failed: " + "; ".join(errors))
    initialization = load_canonical_json(repo_root / INITIALIZATION_MANIFEST)
    verify_self_hash(
        initialization,
        "manifest_sha256",
        label="V3 initialization manifest",
    )
    registry = load_canonical_json(repo_root / PRIOR_REGISTRY)
    verify_self_hash(registry, "registry_sha256", label="V3 prior registry")
    if (
        initialization.get("status") != "FROZEN_BEFORE_V3_VALIDATION_AND_TEST"
        or initialization.get("test_data_generated") is not False
        or initialization.get("model_training_use", False) is not False
        or registry.get("status") != "FROZEN_ALL_PRE_V3_IDENTITIES"
        or registry.get("model_training_use") is not False
    ):
        raise ValueError("V3 frozen source boundary changed")
    return protocol, initialization, registry


def pair_registry(
    registry: Mapping[str, Any],
    initialization: Mapping[str, Any],
    *,
    split: str,
    index: int,
) -> dict[str, Any]:
    controls = {}
    prior_candidates = set(registry["candidate_sha256"])
    prior_quotients = set(registry["quotient_sha256"])
    for target in TARGETS:
        row = initialization["initializations"][split][target][index]
        if (
            row["candidate_sha256"] not in prior_candidates
            or row["quotient_sha256"] not in prior_quotients
            or row[
                "weakly_connected_nonprior_candidate_neighbor_count"
            ]
            < 32
            or row["counts_as_discovery"] is not False
            or row["shared_across_arms"] is not True
        ):
            raise ValueError("V3 initialization control boundary changed")
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


def validation_projection(
    *,
    run_dir: Path,
    streams: Sequence[Mapping[str, Any]],
    pair_count: int,
    calls: int,
) -> dict[str, Any]:
    clean_exact: Counter[tuple[str, str]] = Counter()
    first_tiers: dict[str, int] = {}
    for pair_index in range(pair_count):
        path = run_dir / "pairs" / f"{pair_index:02d}" / "events.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                if event["call_index"] == 0:
                    key = (
                        f"{event['target']}|{event['pair_seed']}|"
                        f"{event['arm']}"
                    )
                    first_tiers[key] = event["structural_filter"][
                        "tier_index"
                    ]
                decision = event["exact_decision"]
                if (
                    isinstance(decision, Mapping)
                    and decision.get("equal") is True
                    and not event["prior_split_leakage"]
                ):
                    clean_exact[(event["target"], event["arm"])] += 1
    by_target_arm = {
        f"{target}|{arm}": {
            "clean_exact_matches": clean_exact[(target, arm)],
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
            and all(tier == 0 for tier in first_tiers.values())
        ),
        "at_least_one_nonprior_selection_every_stream": all(
            row["prior_split_collision_count"] < calls for row in streams
        ),
        "at_least_one_clean_exact_match_every_arm_and_target": all(
            row["clean_exact_matches"] > 0 for row in by_target_arm.values()
        ),
        "at_least_one_quotient_discovery_every_arm_and_target": all(
            row["quotient_discoveries"] > 0 for row in by_target_arm.values()
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


def verify_launch(
    *,
    repo_root: Path,
    launch: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    verify_self_hash(launch, "launch_sha256", label="V3 validation launch")
    if (
        launch.get("schema_version") != LAUNCH_SCHEMA
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("V3 validation launch boundary changed")
    expected_design = {
        "targets": list(TARGETS),
        "pair_seeds": protocol["splits"]["validation"]["pair_seeds"],
        "initialization_indices": [0, 1, 2, 3],
        "arms": list(ARMS),
        "calls_per_arm_pair": 128,
        "candidate_pool_size": 16,
        "model_or_threshold_selection_allowed": False,
    }
    if launch.get("validation_design") != expected_design:
        raise ValueError("V3 validation launch design changed")
    if launch.get("protocol") != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("V3 validation protocol binding changed")
    for field in (
        "initialization_manifest",
        "prior_registry",
        "model_package",
        "model_verification",
    ):
        safe_binding(repo_root, launch[field], label=field)
    for index, binding in enumerate(launch.get("sources", [])):
        safe_binding(repo_root, binding, label=f"V3 validation source {index}")
    authorization_payload = {
        field: launch[field]
        for field in (
            "protocol",
            "validation_design",
            "sources",
            "initialization_manifest",
            "prior_registry",
            "model_package",
            "model_verification",
            "commands",
            "resource_limits",
            "authorization_nonce",
        )
    }
    if object_sha256(authorization_payload) != launch.get(
        "authorization_sha256"
    ):
        raise ValueError("V3 validation authorization does not replay")
    expected_output = (
        "output/research/digraph-order7-diversity-policy-validation-v3-"
        + launch["authorization_sha256"][:12]
    )
    if launch.get("output_directory") != expected_output:
        raise ValueError("V3 validation output is not authorization-derived")


def build_run(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    launch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    protocol, initialization, registry = frozen_sources(repo_root)
    validation = protocol["splits"]["validation"]
    if mode == OFFICIAL_MODE:
        if launch is None:
            raise ValueError("official V3 validation requires a launch")
        verify_launch(repo_root=repo_root, launch=launch, protocol=protocol)
        if (
            list(pair_seeds) != validation["pair_seeds"]
            or calls_per_arm_pair != 128
            or run_dir.resolve()
            != (repo_root / launch["output_directory"]).resolve()
        ):
            raise ValueError("official V3 validation design changed")
        split = "validation"
    elif mode == SMOKE_MODE:
        if launch is not None or len(pair_seeds) != 1:
            raise ValueError("V3 validation smoke boundary changed")
        if not 1 <= calls_per_arm_pair <= 4:
            raise ValueError("V3 validation smoke calls must be 1..4")
        split = "validation"
    else:
        raise ValueError("unknown V3 validation mode")
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        if launch is not None:
            write_json_exclusive(run_dir / "launch_record.json", launch)
        write_json_exclusive(run_dir / "prior_split_registry.json", registry)
        write_json_exclusive(
            run_dir / "initialization_manifest.json",
            initialization,
        )
        manifest = hashed_record(
            {
                "schema_version": MANIFEST_SCHEMA,
                "status": (
                    "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
                    if mode == OFFICIAL_MODE
                    else "SMOKE_ONLY_NOT_EVIDENCE"
                ),
                "mode": mode,
                "protocol": {
                    "path": PROTOCOL_PATH.as_posix(),
                    "sha256": file_sha256(repo_root / PROTOCOL_PATH),
                },
                "launch_file_sha256": (
                    file_sha256(run_dir / "launch_record.json")
                    if launch is not None
                    else None
                ),
                "prior_registry_sha256": registry["registry_sha256"],
                "initialization_manifest_sha256": initialization[
                    "manifest_sha256"
                ],
                "design": {
                    "targets": list(TARGETS),
                    "pair_seeds": list(pair_seeds),
                    "initialization_indices": list(range(len(pair_seeds))),
                    "arms": list(ARMS),
                    "calls_per_arm_pair": calls_per_arm_pair,
                    "candidate_pool_size": 16,
                    "pair_local_hash_chains": True,
                    "model_or_threshold_selection_allowed": False,
                },
                "kernel": {
                    "implementation": "frozen_v2_three_arm_kernel",
                    "fresh_pair_seeds": mode == OFFICIAL_MODE,
                    "pair_specific_initialization": True,
                },
                "test_data_generated": False,
                "paper_evidence": False,
            },
            "manifest_sha256",
        )
        write_json_exclusive(run_dir / "manifest.json", manifest)
        rankers = v2.FrozenRankers(repo_root) if mode == OFFICIAL_MODE else None
        streams = []
        endpoints = []
        for pair_index, pair_seed in enumerate(pair_seeds):
            pair_dir = run_dir / "pairs" / f"{pair_index:02d}"
            pair_dir.mkdir(parents=True, exist_ok=False)
            registry_for_pair = pair_registry(
                registry,
                initialization,
                split=split,
                index=(pair_index if mode == OFFICIAL_MODE else 0),
            )
            bundle, final_proposal, final_event = v2.generate_ledgers(
                run_dir=pair_dir,
                mode=mode,
                pair_seeds=[pair_seed],
                calls_per_arm_pair=calls_per_arm_pair,
                registry=registry_for_pair,
                rankers=rankers,
            )
            write_json_exclusive(pair_dir / "stream_metrics.json", bundle)
            streams.extend(bundle["streams"])
            endpoints.append(
                {
                    "pair_index": pair_index,
                    "pair_seed": pair_seed,
                    "proposal_count": len(TARGETS)
                    * len(ARMS)
                    * calls_per_arm_pair,
                    "event_count": len(TARGETS)
                    * len(ARMS)
                    * calls_per_arm_pair,
                    "proposal_file_sha256": file_sha256(
                        pair_dir / "proposal_decisions.jsonl"
                    ),
                    "event_file_sha256": file_sha256(
                        pair_dir / "events.jsonl"
                    ),
                    "stream_file_sha256": file_sha256(
                        pair_dir / "stream_metrics.json"
                    ),
                    "final_proposal_sha256": final_proposal,
                    "final_event_sha256": final_event,
                }
            )
        aggregate = v2.stream_bundle(streams)
        write_json_exclusive(run_dir / "validation_stream_metrics.json", aggregate)
        projection = validation_projection(
            run_dir=run_dir,
            streams=streams,
            pair_count=len(pair_seeds),
            calls=calls_per_arm_pair,
        )
        write_json_exclusive(run_dir / "validation_projection.json", projection)
        expected_events = (
            len(TARGETS)
            * len(pair_seeds)
            * len(ARMS)
            * calls_per_arm_pair
        )
        elapsed = time.monotonic() - started
        size = directory_size(run_dir)
        rss = 0 if mode == SMOKE_MODE else peak_rss_bytes()
        if mode == OFFICIAL_MODE and (
            elapsed > protocol["resource_gate"]["validation_wall_seconds"]
            or size > protocol["resource_gate"]["run_directory_bytes"]
            or rss > protocol["resource_gate"]["peak_resident_memory_bytes"]
        ):
            raise OSError("V3 validation exceeded a resource limit")
        generation = hashed_record(
            {
                "schema_version": GENERATION_SCHEMA,
                "status": (
                    "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
                    if mode == OFFICIAL_MODE
                    else "SMOKE_ONLY_NOT_EVIDENCE"
                ),
                "mode": mode,
                "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
                "prior_registry_file_sha256": file_sha256(
                    run_dir / "prior_split_registry.json"
                ),
                "initialization_manifest_file_sha256": file_sha256(
                    run_dir / "initialization_manifest.json"
                ),
                "aggregate_stream_file_sha256": file_sha256(
                    run_dir / "validation_stream_metrics.json"
                ),
                "projection_file_sha256": file_sha256(
                    run_dir / "validation_projection.json"
                ),
                "pair_endpoints": endpoints,
                "proposal_count": expected_events,
                "event_count": expected_events,
                "exact_verifier_calls_consumed": expected_events,
                "raw_pool_candidate_count": expected_events * 16,
                "generation_wall_seconds": (
                    0.0 if mode == SMOKE_MODE else elapsed
                ),
                "run_directory_bytes_before_marker": size,
                "peak_resident_memory_bytes": rss,
                "test_data_generated": False,
                "paper_evidence": False,
            },
            "generation_sha256",
        )
        write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
        return generation
    except BaseException as error:
        try:
            write_json_exclusive(
                run_dir / "FAILURE.json",
                hashed_record(
                    {
                        "schema_version": f"{SCHEMA}.failure",
                        "status": "INCOMPLETE_FAIL",
                        "mode": mode,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "resume_authorized": False,
                        "paper_evidence": False,
                    },
                    "failure_sha256",
                ),
            )
        except BaseException:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=(SMOKE_MODE, OFFICIAL_MODE), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-record", type=Path)
    parser.add_argument("--smoke-calls", type=int, default=2)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    protocol = load_json_object(repo_root / PROTOCOL_PATH)
    if args.mode == SMOKE_MODE:
        if args.output is None or args.launch_record is not None:
            raise SystemExit("smoke requires only --output")
        run_dir = (
            args.output
            if args.output.is_absolute()
            else repo_root / args.output
        ).resolve()
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=SMOKE_MODE,
            pair_seeds=[smoke_seed()],
            calls_per_arm_pair=args.smoke_calls,
            launch=None,
        )
    else:
        if args.launch_record is None or args.output is not None:
            raise SystemExit("official validation requires only --launch-record")
        launch_path = (
            args.launch_record
            if args.launch_record.is_absolute()
            else repo_root / args.launch_record
        )
        launch = load_canonical_json(launch_path)
        verify_launch(repo_root=repo_root, launch=launch, protocol=protocol)
        generation = build_run(
            repo_root=repo_root,
            run_dir=(repo_root / launch["output_directory"]).resolve(),
            mode=OFFICIAL_MODE,
            pair_seeds=protocol["splits"]["validation"]["pair_seeds"],
            calls_per_arm_pair=128,
            launch=launch,
        )
    print(json.dumps(generation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
