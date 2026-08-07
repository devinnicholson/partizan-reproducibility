#!/usr/bin/env python3
"""Generate the one-time V3 three-arm held-out policy test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping, Sequence

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import digraph_order7_diversity_policy_test_v2 as v2
import digraph_order7_diversity_policy_validation_v3 as v3_validation
import validate_digraph_order7_diversity_policy_protocol_v3 as protocol_validator


SCHEMA = "partizan.digraph_order7_diversity_policy_test.v3"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
PROTOCOL_PATH = protocol_validator.PROTOCOL_PATH
INITIALIZATION_MANIFEST = v3_validation.INITIALIZATION_MANIFEST
VALIDATION_RUN = Path(
    "output/research/digraph-order7-diversity-policy-validation-v3-e5a2280aac6b"
)
VALIDATION_COMPLETION = VALIDATION_RUN / "VALIDATION_COMPLETE.json"
PRIOR_REGISTRY = VALIDATION_RUN / "test_prior_split_registry.json"
RESOURCE_PREFLIGHT = Path(
    "output/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_RESOURCE_PREFLIGHT_V3.json"
)
MODEL_DIR = v2.MODEL_DIR
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
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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
        label="initialization manifest",
    )
    completion = load_canonical_json(repo_root / VALIDATION_COMPLETION)
    verify_self_hash(
        completion,
        "completion_sha256",
        label="V3 validation completion",
    )
    registry = load_canonical_json(repo_root / PRIOR_REGISTRY)
    verify_self_hash(registry, "registry_sha256", label="test prior registry")
    if (
        completion.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("test_authorization_allowed") is not True
        or completion.get("model_or_threshold_selection_performed") is not False
        or completion.get("test_data_generated") is not False
        or registry.get("status") != "FROZEN_ALL_PRE_TEST_IDENTITIES"
        or registry.get("model_training_use") is not False
        or registry.get("model_selection_use") is not False
    ):
        raise ValueError("V3 validation-to-test boundary changed")
    return protocol, initialization, completion, registry


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


def verify_launch(
    *,
    repo_root: Path,
    launch: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    verify_self_hash(launch, "launch_sha256", label="V3 test launch")
    if (
        launch.get("schema_version") != LAUNCH_SCHEMA
        or launch.get("status") != "AUTHORIZED_ONCE"
        or launch.get("test_data_generated") is not False
        or launch.get("paper_evidence") is not False
    ):
        raise ValueError("V3 test launch boundary changed")
    expected_design = {
        "targets": list(TARGETS),
        "pair_seeds": protocol["splits"]["test"]["pair_seeds"],
        "initialization_indices": list(range(12)),
        "arms": list(ARMS),
        "calls_per_arm_pair": 2048,
        "candidate_pool_size": 16,
        "checkpoints": [128, 512, 1024, 2048],
        "success_stopping_rule": False,
    }
    if launch.get("test_design") != expected_design:
        raise ValueError("V3 test launch design changed")
    if launch.get("protocol") != {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }:
        raise ValueError("V3 test protocol binding changed")
    for field in (
        "initialization_manifest",
        "validation_completion",
        "prior_registry",
        "model_package",
        "model_verification",
        "resource_preflight",
    ):
        safe_binding(repo_root, launch[field], label=field)
    sources = launch.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("V3 test source inventory is empty")
    for index, binding in enumerate(sources):
        safe_binding(repo_root, binding, label=f"V3 test source {index}")
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
        raise ValueError("V3 test authorization does not replay")
    expected_output = (
        "output/research/digraph-order7-diversity-policy-test-v3-"
        + launch["authorization_sha256"][:12]
    )
    if launch.get("output_directory") != expected_output:
        raise ValueError("V3 test output is not authorization-derived")


def build_run(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    launch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    protocol, initialization, validation_completion, registry = frozen_sources(
        repo_root
    )
    test = protocol["splits"]["test"]
    if mode == OFFICIAL_MODE:
        if launch is None:
            raise ValueError("official V3 test requires a one-time launch")
        verify_launch(repo_root=repo_root, launch=launch, protocol=protocol)
        if (
            list(pair_seeds) != test["pair_seeds"]
            or calls_per_arm_pair != 2048
            or run_dir.resolve()
            != (repo_root / launch["output_directory"]).resolve()
        ):
            raise ValueError("official V3 test design changed")
    elif mode == SMOKE_MODE:
        if launch is not None or len(pair_seeds) != 1:
            raise ValueError("V3 test smoke boundary changed")
        if not 1 <= calls_per_arm_pair <= 4:
            raise ValueError("V3 test smoke calls must be 1..4")
    else:
        raise ValueError("unknown V3 test mode")
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        source_bundle = []
        if launch is not None:
            write_json_exclusive(run_dir / "launch_record.json", launch)
            source_bundle = v2.snapshot_bound_sources(
                repo_root=repo_root,
                run_dir=run_dir,
                sources=launch["sources"],
            )
        write_json_exclusive(run_dir / "prior_split_registry.json", registry)
        write_json_exclusive(
            run_dir / "initialization_manifest.json",
            initialization,
        )
        manifest = hashed_record(
            {
                "schema_version": MANIFEST_SCHEMA,
                "status": (
                    "AWAITING_INDEPENDENT_TEST_REPLAY"
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
                "source_bundle": source_bundle,
                "validation_completion_sha256": validation_completion[
                    "completion_sha256"
                ],
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
                    "checkpoints": [
                        value
                        for value in (128, 512, 1024, 2048)
                        if value <= calls_per_arm_pair
                    ],
                    "pair_local_hash_chains": True,
                    "success_stopping_rule": False,
                },
                "kernel": {
                    "implementation": "frozen_v2_three_arm_kernel",
                    "fresh_pair_seeds": mode == OFFICIAL_MODE,
                    "pair_specific_initialization": True,
                    "model_or_threshold_change": False,
                },
                "test_data_generated": mode == OFFICIAL_MODE,
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
            registry_for_pair = v3_validation.pair_registry(
                registry,
                initialization,
                split="test",
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
        write_json_exclusive(run_dir / "stream_metrics.json", aggregate)
        report = pending_report(streams, protocol)
        write_json_exclusive(run_dir / "preliminary_report.json", report)
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
            elapsed > protocol["resource_gate"]["test_generation_wall_seconds"]
            or size > protocol["resource_gate"]["run_directory_bytes"]
            or rss > protocol["resource_gate"]["peak_resident_memory_bytes"]
        ):
            raise OSError("V3 test exceeded a resource limit")
        generation = hashed_record(
            {
                "schema_version": GENERATION_SCHEMA,
                "status": (
                    "AWAITING_INDEPENDENT_TEST_REPLAY"
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
                "stream_metrics_file_sha256": file_sha256(
                    run_dir / "stream_metrics.json"
                ),
                "preliminary_report_file_sha256": file_sha256(
                    run_dir / "preliminary_report.json"
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
                "scientific_gate_pending_independent_replay": True,
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
            raise SystemExit("official test requires only --launch-record")
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
            pair_seeds=protocol["splits"]["test"]["pair_seeds"],
            calls_per_arm_pair=2048,
            launch=launch,
        )
    print(json.dumps(generation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
