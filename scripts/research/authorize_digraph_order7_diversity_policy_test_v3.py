#!/usr/bin/env python3
"""Authorize exactly one V3 held-out policy test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
import digraph_order7_diversity_policy_test_v3 as test_builder
import validate_digraph_order7_diversity_policy_protocol_v3 as protocol_validator


HEX_64 = re.compile(r"[0-9a-f]{64}")
DEFAULT_LAUNCH = Path(
    "output/research/"
    "DIGRAPH_ORDER7_DIVERSITY_POLICY_TEST_V3_AUTHORIZED_ONCE.json"
)
MODEL_PACKAGE = test_builder.MODEL_DIR / "MODEL_PACKAGE.json"
MODEL_VERIFICATION = (
    test_builder.MODEL_DIR / "MODEL_PACKAGE_VERIFICATION.json"
)
SOURCES = (
    test_builder.PROTOCOL_PATH.as_posix(),
    "docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V3_PREREGISTRATION.md",
    "docs/research/digraph-order7-diversity-policy-v3.protocol.schema.json",
    "docs/research/digraph-order7-diversity-policy-test-event-v2.schema.json",
    "scripts/research/validate_digraph_order7_diversity_policy_protocol_v3.py",
    "scripts/research/test_validate_digraph_order7_diversity_policy_protocol_v3.py",
    "scripts/research/diagnose_digraph_order7_v2_reachability.py",
    "scripts/research/freeze_digraph_order7_policy_v3_initializations.py",
    "scripts/research/digraph_order7_diversity_policy_validation_v3.py",
    "scripts/research/verify_digraph_order7_diversity_policy_validation_v3.py",
    "scripts/research/test_digraph_order7_diversity_policy_validation_v3.py",
    "scripts/research/digraph_order7_diversity_policy_test_v3.py",
    "scripts/research/verify_digraph_order7_diversity_policy_test_v3.py",
    "scripts/research/test_digraph_order7_diversity_policy_test_v3.py",
    "scripts/research/digraph_order7_diversity_policy_resource_preflight_v3.py",
    "scripts/research/test_digraph_order7_diversity_policy_resource_preflight_v3.py",
    "scripts/research/authorize_digraph_order7_diversity_policy_test_v3.py",
    "scripts/research/test_authorize_digraph_order7_diversity_policy_test_v3.py",
    "scripts/research/digraph_order7_diversity_policy_test_v2.py",
    "scripts/research/verify_digraph_order7_diversity_policy_test_v2.py",
    "scripts/research/freeze_digraph_order7_diversity_model_v2.py",
    "scripts/research/verify_digraph_order7_diversity_model_package_v2.py",
    "scripts/research/verify_digraph_order7_fixed_value_transitions_v1.py",
    "scripts/research/verify_digraph_order7_neural_validation_v1.py",
    "scripts/research/digraph_order7_neural_policy_test_v1.py",
    "scripts/research/digraph_derivation_certificate_v3.py",
    "scripts/research/digraph_ledger_verifier_v3.py",
    "scripts/research/digraph_placement_control.py",
    "scripts/research/semantic_equality_certificate_v1.py",
    "scripts/research/short_game_fiber_pilot.py",
)


class AuthorizationError(ValueError):
    """Raised when V3 test authorization must fail closed."""


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
        raise AuthorizationError(f"{path}: expected a JSON object")
    return value


def load_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_line(value):
        raise AuthorizationError(f"{path}: expected canonical newline JSON")
    return value


def verify_self_hash(
    value: Mapping[str, Any],
    field: str,
    *,
    label: str,
) -> None:
    payload = dict(value)
    supplied = payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise AuthorizationError(f"{label} self-hash does not replay")


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


def binding(repo_root: Path, relative: Path) -> dict[str, str]:
    path = repo_root / relative
    if not path.is_file():
        raise AuthorizationError(f"bound artifact is missing: {relative}")
    return {"path": relative.as_posix(), "sha256": file_sha256(path)}


def repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise AuthorizationError("launch path must be inside repository") from error


def validate_dependencies(repo_root: Path) -> None:
    initialization = load_canonical_json(
        repo_root / test_builder.INITIALIZATION_MANIFEST
    )
    completion = load_canonical_json(
        repo_root / test_builder.VALIDATION_COMPLETION
    )
    registry = load_canonical_json(repo_root / test_builder.PRIOR_REGISTRY)
    package = load_canonical_json(repo_root / MODEL_PACKAGE)
    model_verification = load_canonical_json(repo_root / MODEL_VERIFICATION)
    preflight = load_canonical_json(repo_root / test_builder.RESOURCE_PREFLIGHT)
    verify_self_hash(
        initialization,
        "manifest_sha256",
        label="initialization manifest",
    )
    verify_self_hash(
        completion,
        "completion_sha256",
        label="validation completion",
    )
    verify_self_hash(registry, "registry_sha256", label="test prior registry")
    verify_self_hash(package, "package_sha256", label="model package")
    verify_self_hash(
        model_verification,
        "verification_sha256",
        label="model verification",
    )
    verify_self_hash(preflight, "report_sha256", label="resource preflight")
    if (
        completion.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("test_authorization_allowed") is not True
        or completion.get("model_or_threshold_selection_performed") is not False
        or completion.get("test_data_generated") is not False
        or registry.get("status") != "FROZEN_ALL_PRE_TEST_IDENTITIES"
        or registry.get("model_training_use") is not False
        or registry.get("model_selection_use") is not False
        or package.get("status")
        != "FROZEN_VALIDATED_DIVERSITY_MODEL_PACKAGE"
        or package.get("test_data_generated") is not False
        or model_verification.get("status") != "PASS_MODEL_PACKAGE_ONLY"
        or model_verification.get(
            "selected_scores_embeddings_memory_and_rank_fusion_replay"
        )
        is not True
        or preflight.get("status") != "PASS"
        or preflight.get("projection", {}).get("status") != "PASS"
        or preflight.get("semantic_test_evaluation_performed") is not False
        or preflight.get("test_data_generated") is not False
    ):
        raise AuthorizationError("V3 test dependency boundary changed")


def build_launch(
    *,
    repo_root: Path,
    launch_path: Path,
    authorization_nonce: str,
) -> dict[str, Any]:
    if not HEX_64.fullmatch(authorization_nonce):
        raise AuthorizationError(
            "authorization nonce must be 64 lowercase hexadecimal characters"
        )
    if launch_path.exists():
        raise FileExistsError(launch_path)
    protocol = load_json_object(repo_root / test_builder.PROTOCOL_PATH)
    errors = protocol_validator.validate(
        protocol,
        repo_root,
        check_bound_files=True,
    )
    if errors:
        raise AuthorizationError(
            "V3 protocol validation failed: " + "; ".join(errors)
        )
    validate_dependencies(repo_root)
    sources = [binding(repo_root, Path(relative)) for relative in SOURCES]
    test = protocol["splits"]["test"]
    design = {
        "targets": list(test_builder.TARGETS),
        "pair_seeds": test["pair_seeds"],
        "initialization_indices": list(range(12)),
        "arms": list(test_builder.ARMS),
        "calls_per_arm_pair": 2048,
        "candidate_pool_size": 16,
        "checkpoints": test["checkpoints"],
        "success_stopping_rule": False,
    }
    relative_launch = repo_relative(repo_root, launch_path)
    commands = {
        "generate": (
            "PYTHONPATH=scripts/research python3 "
            "scripts/research/digraph_order7_diversity_policy_test_v3.py "
            "--repo-root . --mode authorized_test --launch-record "
            + relative_launch
        ),
        "verify": (
            "PYTHONPATH=scripts/research python3 "
            "scripts/research/verify_digraph_order7_diversity_policy_test_v3.py "
            "<authorization-derived-output-directory> --repo-root ."
        ),
    }
    authorization_payload = {
        "protocol": binding(repo_root, test_builder.PROTOCOL_PATH),
        "test_design": design,
        "sources": sources,
        "initialization_manifest": binding(
            repo_root,
            test_builder.INITIALIZATION_MANIFEST,
        ),
        "validation_completion": binding(
            repo_root,
            test_builder.VALIDATION_COMPLETION,
        ),
        "prior_registry": binding(repo_root, test_builder.PRIOR_REGISTRY),
        "model_package": binding(repo_root, MODEL_PACKAGE),
        "model_verification": binding(repo_root, MODEL_VERIFICATION),
        "resource_preflight": binding(
            repo_root,
            test_builder.RESOURCE_PREFLIGHT,
        ),
        "commands": commands,
        "resource_limits": protocol["resource_gate"],
        "authorization_nonce": authorization_nonce,
    }
    authorization_sha = object_sha256(authorization_payload)
    output_directory = (
        "output/research/digraph-order7-diversity-policy-test-v3-"
        + authorization_sha[:12]
    )
    if (repo_root / output_directory).exists():
        raise AuthorizationError("authorization-derived output already exists")
    payload = {
        "schema_version": test_builder.LAUNCH_SCHEMA,
        "status": "AUTHORIZED_ONCE",
        **authorization_payload,
        "authorization_sha256": authorization_sha,
        "output_directory": output_directory,
        "test_data_generated": False,
        "paper_evidence": False,
    }
    launch = dict(payload)
    launch["launch_sha256"] = object_sha256(payload)
    test_builder.verify_launch(
        repo_root=repo_root,
        launch=launch,
        protocol=protocol,
    )
    return launch


def authorize(
    *,
    repo_root: Path,
    launch_path: Path,
    authorization_nonce: str,
) -> dict[str, Any]:
    launch = build_launch(
        repo_root=repo_root,
        launch_path=launch_path,
        authorization_nonce=authorization_nonce,
    )
    write_bytes_exclusive(launch_path, canonical_line(launch))
    return launch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--launch-record", type=Path, default=DEFAULT_LAUNCH)
    parser.add_argument("--authorization-nonce", required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    launch_path = (
        args.launch_record
        if args.launch_record.is_absolute()
        else repo_root / args.launch_record
    ).resolve()
    launch = authorize(
        repo_root=repo_root,
        launch_path=launch_path,
        authorization_nonce=args.authorization_nonce,
    )
    print(json.dumps(launch, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
