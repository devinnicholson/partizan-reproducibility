#!/usr/bin/env python3
"""Recreate the frozen V3 authorized layout and invoke its frozen verifier.

The V3 verifier intentionally requires the run directory to appear at the
authorization-derived repository path.  This wrapper preserves that check. It
materializes a disposable repository layout from the frozen source snapshot,
the compact dependency package, and (for a full replay) the extracted evidence
tree.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "partizan.v3_portable_replay_staging.v1"
DEFAULT_RUN = Path(
    "output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4"
)
VERIFIER_RELATIVE = Path(
    "scripts/research/verify_digraph_order7_diversity_policy_test_v3.py"
)
VALIDATOR_DEPENDENCIES = {
    Path("docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"):
        "20f4c36b97661c2523e0750a207457e55e1d7cd95679a8bfead91492cbd8c868",
    Path("docs/research/DIGRAPH_ORDER7_DIVERSITY_POLICY_V2_PROTOCOL.json"):
        "a792a397bc2acdaf98bfe1cb5ef1e363d39635df0bc41f69ae535d28d227b0cc",
}
VERIFIER_OUTPUTS = frozenset(
    {
        "RUN_COMPLETE.json",
        "corruption_tests.json",
        "independent_gate.json",
        "independent_inference.json",
        "independent_stream_metrics.json",
        "independent_verification.json",
        "report.json",
    }
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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


def safe_relative(value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    return relative


def iter_bindings(value: Any) -> Iterable[tuple[Path, str]]:
    """Yield path/SHA-256 bindings recursively, without assuming field names."""

    if isinstance(value, Mapping):
        path = value.get("path")
        sha256 = value.get("sha256")
        if isinstance(path, str) and isinstance(sha256, str) and len(sha256) == 64:
            yield safe_relative(path), sha256
        for nested in value.values():
            yield from iter_bindings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_bindings(nested)


def materialize_file(source: Path, destination: Path, mode: str) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists() or destination.is_symlink():
        if destination.is_file() and file_sha256(destination) == file_sha256(source):
            return
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        destination.symlink_to(source.resolve())
    elif mode == "hardlink":
        os.link(source, destination)
    elif mode == "copy":
        shutil.copy2(source, destination)
    elif mode == "auto":
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    else:
        raise ValueError(f"unsupported materialization mode: {mode}")


def materialize_tree(
    source_root: Path,
    destination_root: Path,
    mode: str,
    *,
    skip_top_level_names: frozenset[str] = frozenset(),
) -> int:
    count = 0
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        if len(relative.parts) == 1 and relative.name in skip_top_level_names:
            continue
        materialize_file(source, destination_root / relative, mode)
        count += 1
    return count


def find_bound_source(
    repo_root: Path,
    source_run: Path,
    relative: Path,
    expected_sha256: str,
) -> Path:
    candidates = (
        source_run / "source_bundle" / relative,
        repo_root / relative,
    )
    for candidate in candidates:
        if candidate.is_file() and file_sha256(candidate) == expected_sha256:
            return candidate
    raise FileNotFoundError(
        f"no byte-matching source for {relative} ({expected_sha256})"
    )


def prepare_layout(
    *,
    repo_root: Path,
    source_run: Path,
    staging_root: Path,
    materialization: str,
    full_replay: bool,
) -> dict[str, Any]:
    launch = load_json_object(source_run / "launch_record.json")
    manifest = load_json_object(source_run / "manifest.json")
    expected_output = safe_relative(str(launch.get("output_directory", "")))
    expected_name = (
        "digraph-order7-diversity-policy-test-v3-"
        + str(launch.get("authorization_sha256", ""))[:12]
    )
    if expected_output.name != expected_name:
        raise ValueError("authorization-derived output directory does not replay")
    if source_run.name != expected_output.name:
        raise ValueError("source run does not match its authorization-derived name")
    if staging_root.exists() and any(staging_root.iterdir()):
        raise FileExistsError(f"staging root is not empty: {staging_root}")
    staging_root.mkdir(parents=True, exist_ok=True)
    staged_run = staging_root / expected_output

    run_file_count = 0
    if full_replay:
        run_file_count = materialize_tree(
            source_run,
            staged_run,
            materialization,
            skip_top_level_names=VERIFIER_OUTPUTS,
        )
    else:
        for name in ("launch_record.json", "manifest.json"):
            materialize_file(source_run / name, staged_run / name, materialization)
            run_file_count += 1
        run_file_count += materialize_tree(
            source_run / "source_bundle",
            staged_run / "source_bundle",
            materialization,
        )

    protocol_binding = launch.get("protocol")
    if not isinstance(protocol_binding, Mapping):
        raise ValueError("launch protocol binding is absent")
    protocol_path = safe_relative(str(protocol_binding.get("path", "")))
    protocol_source = find_bound_source(
        repo_root,
        source_run,
        protocol_path,
        str(protocol_binding.get("sha256", "")),
    )
    protocol = load_json_object(protocol_source)

    unique_bindings: dict[Path, str] = {}
    for relative, sha256 in (*iter_bindings(launch), *iter_bindings(protocol)):
        previous = unique_bindings.setdefault(relative, sha256)
        if previous != sha256:
            raise ValueError(f"conflicting frozen bindings for {relative}")
    for relative, sha256 in sorted(unique_bindings.items(), key=lambda item: str(item[0])):
        source = find_bound_source(repo_root, source_run, relative, sha256)
        materialize_file(source, staging_root / relative, materialization)
    for relative, sha256 in VALIDATOR_DEPENDENCIES.items():
        source = repo_root / relative
        if not source.is_file() or file_sha256(source) != sha256:
            raise ValueError(f"frozen validator dependency changed: {relative}")
        materialize_file(source, staging_root / relative, materialization)

    if full_replay:
        model_binding = launch.get("model_package")
        if not isinstance(model_binding, Mapping):
            raise ValueError("model package binding is absent")
        model_directory = (repo_root / safe_relative(str(model_binding["path"]))).parent
        materialize_tree(
            model_directory,
            staging_root / model_directory.relative_to(repo_root),
            materialization,
        )

    return {
        "authorization_sha256": launch["authorization_sha256"],
        "binding_count": len(unique_bindings),
        "validator_dependency_count": len(VALIDATOR_DEPENDENCIES),
        "expected_output_directory": expected_output.as_posix(),
        "launch_file_sha256": file_sha256(source_run / "launch_record.json"),
        "manifest_file_sha256": file_sha256(source_run / "manifest.json"),
        "run_file_count": run_file_count,
        "source_snapshot_count": len(manifest.get("source_bundle", [])),
        "staged_run": staged_run,
    }


def check_authorized_layout(staging_root: Path, staged_run: Path) -> None:
    module_root = staging_root / "scripts/research"
    sys.path.insert(0, str(module_root))
    try:
        verifier = importlib.import_module(
            "verify_digraph_order7_diversity_policy_test_v3"
        )
        protocol = verifier.load_json_object(staging_root / verifier.PROTOCOL_PATH)
        errors = verifier.protocol_validator.validate(
            protocol,
            staging_root,
            check_bound_files=True,
        )
        if errors:
            raise ValueError("frozen protocol validation failed: " + "; ".join(errors))
        manifest = verifier.load_canonical_json(staged_run / "manifest.json")
        verifier.verify_self_hash(manifest, "manifest_sha256", label="V3 manifest")
        verifier.verify_launch_and_dependencies(
            repo_root=staging_root,
            run_dir=staged_run,
            manifest=manifest,
            protocol=protocol,
        )
    finally:
        sys.path.pop(0)
        for name in tuple(sys.modules):
            module = sys.modules.get(name)
            module_file = getattr(module, "__file__", None)
            if module_file and str(module_file).startswith(str(module_root)):
                sys.modules.pop(name, None)


def write_authority(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    authority = dict(payload)
    authority["artifact_sha256"] = object_sha256(authority)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(authority) + b"\n")
    return authority


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--source-run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--staging-root", type=Path)
    parser.add_argument(
        "--materialization",
        choices=("auto", "hardlink", "symlink", "copy"),
        default="auto",
    )
    parser.add_argument(
        "--mode",
        choices=("layout-check", "full-replay"),
        default="layout-check",
    )
    parser.add_argument("--authority-output", type=Path, required=True)
    return parser.parse_args()


def execute(args: argparse.Namespace, staging_root: Path) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    source_run = args.source_run_dir
    if not source_run.is_absolute():
        source_run = repo_root / source_run
    source_run = source_run.resolve()
    full_replay = args.mode == "full-replay"
    prepared = prepare_layout(
        repo_root=repo_root,
        source_run=source_run,
        staging_root=staging_root,
        materialization=args.materialization,
        full_replay=full_replay,
    )
    staged_run = prepared.pop("staged_run")
    check_authorized_layout(staging_root, staged_run)

    completion: dict[str, Any] | None = None
    if full_replay:
        verifier = staging_root / VERIFIER_RELATIVE
        completed = subprocess.run(
            [
                sys.executable,
                str(verifier),
                str(staged_run),
                "--repo-root",
                str(staging_root),
            ],
            check=True,
            env={
                **os.environ,
                "PYTHONPATH": str(staging_root / "scripts/research"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
        )
        completion = json.loads(completed.stdout)
        if completion.get("status") != "GO":
            raise ValueError("full frozen replay did not reach GO")

    verifier_source = source_run / "source_bundle" / VERIFIER_RELATIVE
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FULL_REPLAY" if full_replay else "PASS_AUTHORIZED_LAYOUT",
        "mode": args.mode,
        "materialization": args.materialization,
        "source_run_directory": source_run.name,
        "frozen_verifier_sha256": file_sha256(verifier_source),
        "wrapper_sha256": file_sha256(Path(__file__).resolve()),
        "authorization_path_check_preserved": True,
        "frozen_verifier_modified": False,
        "full_scientific_replay_performed": full_replay,
        **prepared,
    }
    if completion is not None:
        payload["completion_status"] = completion["status"]
        payload["completion_sha256"] = completion["completion_sha256"]
    authority_output = args.authority_output
    if not authority_output.is_absolute():
        authority_output = repo_root / authority_output
    return write_authority(authority_output, payload)


def main() -> int:
    args = parse_args()
    if args.staging_root is not None:
        authority = execute(args, args.staging_root.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="partizan-v3-replay-") as temporary:
            authority = execute(args, Path(temporary).resolve())
    print(json.dumps(authority, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
