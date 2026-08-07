#!/usr/bin/env python3
"""Generate the frozen held-out neural-policy comparison v1 test ledger.

Official mode is intentionally inaccessible without a separately authorized,
self-hashed launch record that binds the verified validation completion,
frozen ensemble and model card, PASS resource preflight, environment, pushed
Partizan source snapshot, and the exact protocol.  Smoke mode uses a separate
seed/phase domain and deterministic mock labels; it can never become evidence.

For every scheduled call the outcome-free pool, structural tier, model scores,
and selected slot are appended before the selected candidate is evaluated.
The scorer receives only the graph, target, and outcome-free pool metadata.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any, Callable, Mapping, Sequence

import digraph_order7_fixed_value_transitions_v1 as fixed_value
import digraph_order7_neural_policy_resource_preflight_v1 as preflight
import digraph_order7_neural_validation_v1 as validation_builder
from digraph_derivation_certificate_v3 import canonical_json_bytes, object_sha256
from digraph_ledger_verifier_v3 import (
    candidate_record,
    candidate_record_sha256,
    descriptor_record,
    graph_from_candidate_record,
    quotient_record,
    weakly_connected,
)
from digraph_placement_control import DigraphPlacement, parse_game_form
from semantic_equality_certificate_v1 import artifact_binding


SCHEMA = "partizan.digraph_order7_neural_policy_test.v1"
LAUNCH_SCHEMA = f"{SCHEMA}.launch"
MANIFEST_SCHEMA = f"{SCHEMA}.manifest"
REGISTRY_SCHEMA = f"{SCHEMA}.prior_split_registry"
POOL_SCHEMA = f"{SCHEMA}.proposal_decision"
EVENT_SCHEMA = f"{SCHEMA}.event"
STREAM_SCHEMA = f"{SCHEMA}.stream_metrics"
INFERENCE_SCHEMA = f"{SCHEMA}.inference"
GENERATION_SCHEMA = f"{SCHEMA}.generation"
PROTOCOL_PATH = Path(
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_COMPARISON_V1_PROTOCOL.json"
)
TRAINING_RUN = Path(
    "output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db"
)
TARGETS = ("0", "*", "{0|1}")
ARMS = (
    "structural_toggle_one_random",
    "neural_toggle_one_ranker",
)
CONTROL_ARM, TREATMENT_ARM = ARMS
CHECKPOINTS = (128, 512, 1024, 2048)
TIERS = (
    (
        "weakly_connected",
        "not_prior_split_candidate",
        "candidate_new_to_arm",
    ),
    ("weakly_connected", "not_prior_split_candidate"),
    ("not_prior_split_candidate",),
    ("all",),
)
ARC_LIST = tuple(
    (source, target)
    for source in range(7)
    for target in range(7)
    if source != target
)
ZERO_SHA256 = "0" * 64
PROTOCOL_PREFIX = "partizan.digraph_order7_neural_policy_comparison.v1"
SMOKE_PREFIX = f"{SCHEMA}.smoke"
OFFICIAL_MODE = "authorized_test"
SMOKE_MODE = "smoke_fixture"
FROZEN_PARTIZAN_COMMIT = "4ae37634d9b2ddd6ee8c0797c391e5cb764a8c6c"
REQUIRED_PARTIZAN_FILES = (
    "python/partizan/digraph_neural_ranker.py",
    "tests/test_digraph_neural_ranker.py",
    "docs/digraph_neural_ranker.md",
    "pyproject.toml",
)
REQUIRED_PARTIZAN_FILE_SHA256 = {
    "python/partizan/digraph_neural_ranker.py": (
        "da4fb00f12f93575a7b91afb47cd8295ef02798c2ed90734a0b25ed1d64f8060"
    ),
    "tests/test_digraph_neural_ranker.py": (
        "4ec13b508202ac09904af2461e9aca1e3b8e06d021a059799d0ab90ca99d27f4"
    ),
    "docs/digraph_neural_ranker.md": (
        "56bda82275d5ceafea07f475b3f69b11e89f94c0f81fa3c600a26e3da294f656"
    ),
    "pyproject.toml": (
        "e317fe6fead9e28a781d86ab50b8885086b3fd9356422f47315232cd2c89ac1e"
    ),
}
FAILED_VALIDATION_INCIDENTS = (
    {
        "directory": (
            "output/research/digraph-order7-neural-validation-v1-b010306e0492"
        ),
        "incident_path": (
            "output/research/"
            "DIGRAPH_ORDER7_NEURAL_VALIDATION_V1_ABORTED_b010306e0492.json"
        ),
        "incident_file_sha256": (
            "a2c3e447b0dd52fef415261af3f3063bd0cfaabd3abb727e0ccf9599b60963ff"
        ),
        "abort_sha256": (
            "ed799fdb7cd583c4e9644d733da7958fcec9047a54bdc2d23ff3223ccd2bd1f1"
        ),
        "authorization_path": (
            "output/research/"
            "DIGRAPH_ORDER7_NEURAL_VALIDATION_V1_AUTHORIZED_ONCE.json"
        ),
        "authorization_sha256": (
            "b010306e0492920408aa5b5df9b4abbc1e30eb3db068f3a953996566a13639a6"
        ),
        "failure_sha256": (
            "961a9ead851a07eabf92ee3123f0eccbc7ca15b2b3e1fe4dca92839d5edbacce"
        ),
        "phase": "labeling.match_sidecar_creation_after_pool_commitment",
    },
    {
        "directory": (
            "output/research/digraph-order7-neural-validation-v1-8219186966a4"
        ),
        "incident_path": (
            "output/research/"
            "DIGRAPH_ORDER7_NEURAL_VALIDATION_V1_ABORTED_8219186966a4.json"
        ),
        "incident_file_sha256": (
            "120ddf8d1949f83688a4a34908432c771a01a7a11f757b4ab02249de75602103"
        ),
        "abort_sha256": (
            "0561e3d427a296e98dd1733599a6dea4f92a3dc9e369997d16efa54150ade34c"
        ),
        "authorization_path": (
            "output/research/"
            "DIGRAPH_ORDER7_NEURAL_VALIDATION_V1_REAUTHORIZED_AFTER_ABORT_b010306e0492.json"
        ),
        "authorization_sha256": (
            "8219186966a44b5e82162975094bd2c4d6a0e8f275b3c116e3facac94b135156"
        ),
        "failure_sha256": (
            "ccc3eefeb1a8852d3c78752c04eb9113e95712e8adb0034e82d91d9778286863"
        ),
        "phase": "labeling.connectivity_censor_before_structural_quotient",
    },
)
REQUIRED_TEST_SOURCES = (
    "scripts/research/digraph_order7_neural_policy_test_v1.py",
    "scripts/research/verify_digraph_order7_neural_policy_test_v1.py",
    "scripts/research/test_digraph_order7_neural_policy_test_v1.py",
    "docs/research/digraph-order7-neural-policy-test-event-v1.schema.json",
    "docs/research/DIGRAPH_ORDER7_NEURAL_POLICY_TEST_V1.md",
)
POOL_FORBIDDEN_OUTCOME_FIELDS = frozenset(
    {
        "exact_decision",
        "quotient",
        "structural_quotient",
        "measurements",
        "descriptor",
        "literal_game_sha256",
        "transition",
        "retention",
        "rejection",
        "sidecars",
        "equality_certificate_sha256",
    }
)
RANKER_ALLOWED_FIELDS = frozenset(
    {
        "candidate",
        "candidate_sha256",
        "target",
        "base_seed",
        "proposal",
        "pool_id",
    }
)

Ranker = Callable[[Sequence[Mapping[str, Any]]], Sequence[float]]


def canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hashed_record(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = object_sha256(payload)
    return result


def verify_embedded(value: Mapping[str, Any], field: str) -> None:
    supplied = value.get(field)
    payload = dict(value)
    payload.pop(field, None)
    if supplied != object_sha256(payload):
        raise ValueError(f"embedded hash {field} does not replay")


def load_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_line(value):
        raise ValueError(f"{path} is not canonical newline JSON")
    return value


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


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


def repo_path(repo_root: Path, relative: Any, *, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{field} path is missing")
    supplied = Path(relative)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError(f"{field} path is not repository-relative")
    path = (repo_root / supplied).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(f"{field} path escapes repository") from error
    return path


def run_directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def peak_rss_bytes() -> int:
    observed = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return observed if sys.platform == "darwin" else observed * 1024


def counter_randbelow(
    size: int,
    *,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    unit_index: int,
    draw_name: str,
) -> int:
    if size <= 0:
        raise ValueError("randbelow size must be positive")
    modulus = 1 << 256
    limit = modulus - (modulus % size)
    rejection_counter = 0
    while True:
        message = (
            f"{prefix}|{phase}|{target}|{pair_seed}|{unit_index}|"
            f"{draw_name}|{rejection_counter}"
        ).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(message).digest(), "big")
        if value < limit:
            return value % size
        rejection_counter += 1


def selected_arcs(
    *,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    call_index: int,
) -> list[tuple[int, int]]:
    arcs = list(ARC_LIST)
    for descending_index in range(41, 0, -1):
        selected_index = counter_randbelow(
            descending_index + 1,
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=call_index,
            draw_name=f"arc_shuffle_{descending_index}",
        )
        arcs[descending_index], arcs[selected_index] = (
            arcs[selected_index],
            arcs[descending_index],
        )
    return arcs[:16]


def smoke_seed(index: int) -> int:
    message = f"{SMOKE_PREFIX}|pair|{index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest()[:8], "big")


def toggle_arc(parent: DigraphPlacement, arc: tuple[int, int]) -> DigraphPlacement:
    source, target = arc
    edges = list(parent.edges)
    edges[source] ^= 1 << target
    return DigraphPlacement(parent.blue_mask, tuple(edges))


def float_hex_scores(values: Sequence[Any]) -> tuple[list[float], list[str]]:
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("ranker returned a nonnumeric score")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("ranker returned a nonfinite score")
        scores.append(score)
    return scores, [score.hex() for score in scores]


def smoke_ranker(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """Outcome-free deterministic fixture scorer in a separate test domain."""

    return [
        int(
            hashlib.sha256(
                (
                    f"{SMOKE_PREFIX}|score|{row['target']}|"
                    f"{row['candidate_sha256']}"
                ).encode("ascii")
            ).hexdigest()[:13],
            16,
        )
        / float(16**13)
        for row in rows
    ]


def ranker_rows(
    *,
    candidates: Sequence[Mapping[str, Any]],
    target: str,
    pair_seed: int,
    pool_id: str,
) -> list[dict[str, Any]]:
    rows = [
        {
            "candidate": row["candidate"],
            "candidate_sha256": row["candidate_sha256"],
            "target": target,
            "base_seed": pair_seed,
            "proposal": {"operator": "toggle_one_arc"},
            "pool_id": pool_id,
        }
        for row in candidates
    ]
    if any(set(row) != RANKER_ALLOWED_FIELDS for row in rows):
        raise AssertionError("ranker row field boundary changed")
    return rows


def first_nonempty_tier(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[int, list[int]]:
    for tier_index in range(len(TIERS)):
        eligible: list[int] = []
        for slot, candidate in enumerate(candidates):
            conditions = (
                candidate["weakly_connected"],
                not candidate["prior_split_candidate_collision"],
                candidate["candidate_new_to_arm"],
            )
            if tier_index == 0 and all(conditions):
                eligible.append(slot)
            elif tier_index == 1 and all(conditions[:2]):
                eligible.append(slot)
            elif tier_index == 2 and conditions[1]:
                eligible.append(slot)
            elif tier_index == 3:
                eligible.append(slot)
        if eligible:
            return tier_index, eligible
    raise AssertionError("the all-candidate tier cannot be empty")


def select_slot(
    *,
    arm: str,
    eligible: Sequence[int],
    candidates: Sequence[Mapping[str, Any]],
    scores: Sequence[float] | None,
    prefix: str,
    phase: str,
    target: str,
    pair_seed: int,
    call_index: int,
) -> tuple[int, dict[str, Any]]:
    if arm == CONTROL_ARM:
        offset = counter_randbelow(
            len(eligible),
            prefix=prefix,
            phase=phase,
            target=target,
            pair_seed=pair_seed,
            unit_index=call_index,
            draw_name="control_selection",
        )
        return eligible[offset], {
            "method": "uniform_first_nonempty_structural_tier",
            "eligible_offset": offset,
            "draw_name": "control_selection",
        }
    if arm != TREATMENT_ARM or scores is None or len(scores) != len(candidates):
        raise ValueError("neural selection lacks one score per candidate")
    selected = min(
        eligible,
        key=lambda slot: (
            -scores[slot],
            candidates[slot]["candidate_sha256"],
        ),
    )
    return selected, {
        "method": "maximum_frozen_model_score_then_candidate_sha256",
        "score_hex": scores[selected].hex(),
        "tie_break": candidates[selected]["candidate_sha256"],
    }


def transition_record(
    *,
    parent: Mapping[str, Any],
    candidate_quotient: str,
    candidate_literal: str,
    inserted: bool,
) -> dict[str, Any]:
    transition_class = fixed_value.classify_transition(
        parent_quotient=parent["quotient_sha256"],
        parent_literal=parent["literal_game_sha256"],
        candidate_quotient=candidate_quotient,
        candidate_literal=candidate_literal,
    )
    return {
        "class": transition_class,
        "parent_quotient_sha256": parent["quotient_sha256"],
        "parent_literal_game_sha256": parent["literal_game_sha256"],
        "candidate_quotient_sha256": candidate_quotient,
        "candidate_literal_game_sha256": candidate_literal,
        "parent_test_discovery": parent["test_discovery"],
        "candidate_test_discovery": inserted,
        "primary": bool(
            parent["test_discovery"]
            and inserted
            and candidate_quotient != parent["quotient_sha256"]
            and transition_class != "quotient_self"
        ),
    }


def mock_exact_decision(
    *,
    graph: DigraphPlacement,
    target: str,
    candidate_sha256: str,
    parent_literal: str,
) -> dict[str, Any] | None:
    if not weakly_connected(graph):
        return None
    equal = int(candidate_sha256[:2], 16) % 3 == 0
    same_literal = int(candidate_sha256[2:4], 16) % 2 == 0
    candidate_literal = (
        parent_literal
        if same_literal
        else hashlib.sha256(
            (
                f"{SMOKE_PREFIX}|literal|{target}|{candidate_sha256}"
            ).encode("ascii")
        ).hexdigest()
    )
    return {
        "relation": "smoke_fixture_mock_equality",
        "candidate_root_game_sha256": candidate_literal,
        "target_root_game_sha256": hashlib.sha256(
            f"{SMOKE_PREFIX}|target|{target}".encode("ascii")
        ).hexdigest(),
        "candidate_leq_target": equal,
        "target_leq_candidate": equal,
        "equal": equal,
        "distinct_game_tree_node_count": 0,
        "distinct_game_tree_edge_count": 0,
        "game_birthday": 0,
    }


def verify_bound_file(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    field: str,
    canonical: bool = False,
) -> tuple[Path, dict[str, Any] | None]:
    path = repo_path(repo_root, binding.get("path"), field=field)
    if not path.is_file() or file_sha256(path) != binding.get("file_sha256"):
        raise ValueError(f"{field} file binding changed")
    return path, load_canonical_json(path) if canonical else None


def verify_environment(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    model_path: Path,
    model_card: Mapping[str, Any],
    model_commitment: Mapping[str, Any],
) -> dict[str, Any]:
    environment_path, environment = verify_bound_file(
        repo_root,
        binding,
        field="frozen model environment",
        canonical=True,
    )
    assert environment is not None
    verify_embedded(environment, "environment_sha256")
    if set(binding) != {"path", "file_sha256", "environment_sha256"}:
        raise ValueError("test environment binding fields changed")
    if binding["environment_sha256"] != environment["environment_sha256"]:
        raise ValueError("test environment self-hash binding changed")
    expected_reference = model_card.get("environment")
    if not isinstance(expected_reference, Mapping):
        raise ValueError("model card has no frozen environment")
    expected_path = (model_path.parent / expected_reference.get("path", "")).resolve()
    if (
        environment_path.resolve() != expected_path
        or binding["file_sha256"] != expected_reference.get("sha256")
    ):
        raise ValueError("test launch does not bind the model-package environment")
    try:
        import numpy as np
    except ImportError as error:
        raise ValueError("official test requires the frozen NumPy runtime") from error
    if (
        environment["schema_version"]
        != "partizan.digraph_order7_neural_model_freeze.v1.environment"
        or environment["status"] != "FROZEN_VALIDATED_MODEL_PACKAGE"
        or environment["python_version"] != platform.python_version()
        or environment["python_implementation"] != platform.python_implementation()
        or environment["numpy_version"] != np.__version__
        or environment["platform"] != platform.platform()
        or environment["machine"] != platform.machine()
        or environment["partizan_commit"] != FROZEN_PARTIZAN_COMMIT
        or environment["ranker_source_sha256"]
        != model_commitment["ranker_source_sha256"]
        or environment["environment_and_timing_are_observational"] is not True
        or environment["test_data_generated"] is not False
        or environment["paper_evidence"] is not False
    ):
        raise ValueError("current runtime differs from the frozen environment")
    return environment


def verify_partizan_snapshot(
    repo_root: Path,
    snapshot: Mapping[str, Any],
) -> None:
    if (
        snapshot.get("repository") != "partizan"
        or not isinstance(snapshot.get("repository_url"), str)
        or not snapshot["repository_url"]
        or snapshot.get("remote_commit_verified") is not True
        or snapshot.get("pushed_commit_sha") != FROZEN_PARTIZAN_COMMIT
    ):
        raise ValueError("Partizan pushed-commit binding is incomplete")
    files = snapshot.get("snapshot_files")
    if not isinstance(files, list) or [
        entry.get("repo_relative_path") for entry in files
    ] != list(REQUIRED_PARTIZAN_FILES):
        raise ValueError("Partizan snapshot file set or order changed")
    canonical_files: list[dict[str, str]] = []
    for entry in files:
        expected_sha = REQUIRED_PARTIZAN_FILE_SHA256[entry["repo_relative_path"]]
        if entry.get("sha256") != expected_sha:
            raise ValueError("Partizan snapshot differs from the frozen file hashes")
        path = repo_path(
            repo_root,
            entry.get("snapshot_path"),
            field="Partizan snapshot",
        )
        if file_sha256(path) != entry.get("sha256"):
            raise ValueError("Partizan snapshot bytes changed")
        canonical_files.append(
            {
                "repo_relative_path": entry["repo_relative_path"],
                "sha256": entry["sha256"],
            }
        )
    payload = {
        "repository": "partizan",
        "repository_url": snapshot["repository_url"],
        "pushed_commit_sha": snapshot["pushed_commit_sha"],
        "files": canonical_files,
    }
    if object_sha256(payload) != snapshot.get("snapshot_sha256"):
        raise ValueError("Partizan snapshot aggregate hash changed")


def verify_validation_incident_exclusions(
    repo_root: Path,
    bindings: Any,
) -> list[dict[str, Any]]:
    if not isinstance(bindings, list) or len(bindings) != len(
        FAILED_VALIDATION_INCIDENTS
    ):
        raise ValueError("complete ordered validation incident chain is required")
    incidents: list[dict[str, Any]] = []
    for index, (binding, expected) in enumerate(
        zip(bindings, FAILED_VALIDATION_INCIDENTS, strict=True)
    ):
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"path", "file_sha256", "abort_sha256"}
        ):
            raise ValueError("validation incident exclusion fields changed")
        incident_path, incident = verify_bound_file(
            repo_root,
            binding,
            field=f"aborted validation incident {index}",
            canonical=True,
        )
        assert incident is not None
        verify_embedded(incident, "abort_sha256")
        expected_run_dir = (repo_root / expected["directory"]).resolve()
        if (
            incident_path != (repo_root / expected["incident_path"]).resolve()
            or binding["file_sha256"] != expected["incident_file_sha256"]
            or binding["abort_sha256"] != expected["abort_sha256"]
            or incident["schema_version"]
            != "partizan.digraph_order7_neural_validation.v1.aborted_incident"
            or incident["status"] != "ABORTED_PERMANENTLY_CLOSED"
            or Path(incident["failed_run_directory"]).resolve()
            != expected_run_dir
            or incident["authorization_sha256"]
            != expected["authorization_sha256"]
            or incident["failure_sha256"] != expected["failure_sha256"]
            or incident["phase"] != expected["phase"]
            or incident["candidate_outcome_and_sidecar_payloads_inspected"]
            is not False
            or incident["inventory_semantic_records_parsed"] is not False
            or incident["preserve_all_failed_run_artifacts"] is not True
            or incident["official_retry_authorized"] is not False
            or incident["resume_authorized"] is not False
            or incident["model_selection"] is not False
            or incident["test_data_generated"] is not False
            or incident["paper_evidence"] is not False
        ):
            raise ValueError("failed validation incident was not excluded")
        authorization_path = (repo_root / expected["authorization_path"]).resolve()
        authorization = load_canonical_json(authorization_path)
        verify_embedded(authorization, "launch_sha256")
        if (
            file_sha256(authorization_path)
            != incident["launch_record_file_sha256"]
            or authorization.get("authorization_sha256")
            != expected["authorization_sha256"]
            or authorization.get("output_directory") != expected["directory"]
            or authorization.get("test_data_generated") is not False
        ):
            raise ValueError("failed validation authorization binding changed")
        if index:
            prior = FAILED_VALIDATION_INCIDENTS[index - 1]
            retry = authorization.get(
                "retry_after_pre_model_execution_failure"
            )
            if (
                not isinstance(retry, Mapping)
                or retry.get("prior_incident_path") != prior["incident_path"]
                or retry.get("prior_incident_file_sha256")
                != prior["incident_file_sha256"]
                or retry.get("prior_abort_sha256") != prior["abort_sha256"]
                or retry.get("prior_authorization_sha256")
                != prior["authorization_sha256"]
                or retry.get("prior_failure_phase") != prior["phase"]
                or retry.get("prior_model_selection") is not False
                or retry.get("resume_prior_run") is not False
                or retry.get("reuse_prior_pool_or_label_artifacts") is not False
            ):
                raise ValueError("failed validation abort chain changed")
        failure_path = expected_run_dir / "FAILURE.json"
        failure = load_canonical_json(failure_path)
        verify_embedded(failure, "failure_sha256")
        if (
            file_sha256(failure_path)
            != incident["failure_record_file_sha256"]
            or failure.get("failure_sha256") != expected["failure_sha256"]
            or failure.get("status") != "FAILED_CLOSED"
            or failure.get("resume_authorized") is not False
            or failure.get("paper_evidence") is not False
        ):
            raise ValueError("failed validation marker binding changed")
        internal = expected_run_dir / "ABORTED_INCIDENT.json"
        if (
            not internal.is_file()
            or file_sha256(internal) != expected["incident_file_sha256"]
            or internal.read_bytes() != incident_path.read_bytes()
        ):
            raise ValueError(
                "internal and external validation incident records differ"
            )
        incidents.append(incident)
    return incidents


def verify_validation_binding(
    repo_root: Path,
    binding: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
    incident_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    run_dir = repo_path(
        repo_root,
        binding.get("directory"),
        field="validation directory",
    )
    failed_directories = {
        (repo_root / incident["directory"]).resolve()
        for incident in FAILED_VALIDATION_INCIDENTS
    }
    if run_dir in failed_directories:
        raise ValueError("failed validation incident cannot supply held-out inputs")
    for marker in ("FAILURE.json", "VERIFICATION_FAILURE.json"):
        if (run_dir / marker).exists():
            raise ValueError("partial or failed validation cannot supply held-out inputs")
    manifest_path, manifest = verify_bound_file(
        repo_root,
        binding.get("manifest", {}),
        field="validation manifest",
        canonical=True,
    )
    assert manifest is not None
    verify_embedded(manifest, "manifest_sha256")
    generation_path, generation = verify_bound_file(
        repo_root,
        binding.get("generation", {}),
        field="validation generation",
        canonical=True,
    )
    assert generation is not None
    verify_embedded(generation, "generation_sha256")
    successful_launch_path, successful_launch = verify_bound_file(
        repo_root,
        binding.get("launch", {}),
        field="successful validation launch",
        canonical=True,
    )
    assert successful_launch is not None
    verify_embedded(successful_launch, "launch_sha256")
    validation_builder.verify_launch_document(
        repo_root, successful_launch, protocol
    )
    if (
        manifest_path.parent != run_dir
        or generation_path.parent != run_dir
        or successful_launch_path.parent != run_dir
        or manifest.get("schema_version")
        != "partizan.digraph_order7_neural_validation.v1.manifest"
        or manifest.get("mode") != "authorized_validation"
        or manifest.get("paper_evidence") is not False
        or generation.get("status")
        != "AWAITING_INDEPENDENT_VALIDATION_REPLAY"
        or generation.get("mode") != "authorized_validation"
        or generation.get("manifest_file_sha256") != file_sha256(manifest_path)
        or successful_launch.get("schema_version")
        != "partizan.digraph_order7_neural_validation.v1.launch"
        or successful_launch.get("status") != "AUTHORIZED_ONCE"
        or successful_launch.get("output_directory")
        != run_dir.relative_to(repo_root).as_posix()
        or successful_launch.get("test_data_generated") is not False
    ):
        raise ValueError("successful validation launch and manifest do not replay")
    manifest_launch = manifest.get("launch")
    if manifest_launch != {
        "file": successful_launch_path.name,
        "file_sha256": file_sha256(successful_launch_path),
        "launch_sha256": successful_launch["launch_sha256"],
        "authorization_sha256": successful_launch["authorization_sha256"],
        "output_directory": successful_launch["output_directory"],
    }:
        raise ValueError("successful validation manifest launch binding changed")
    last_expected = FAILED_VALIDATION_INCIDENTS[-1]
    last_incident = incident_records[-1]
    retry = successful_launch.get("retry_after_pre_model_execution_failure")
    if (
        not isinstance(retry, Mapping)
        or retry.get("prior_incident_path") != last_expected["incident_path"]
        or retry.get("prior_incident_file_sha256")
        != last_expected["incident_file_sha256"]
        or retry.get("prior_abort_sha256") != last_expected["abort_sha256"]
        or retry.get("prior_launch_sha256")
        != last_incident["launch_sha256"]
        or retry.get("prior_authorization_sha256")
        != last_expected["authorization_sha256"]
        or retry.get("prior_failure_phase") != last_expected["phase"]
        or retry.get("prior_model_selection") is not False
        or retry.get("resume_prior_run") is not False
        or retry.get("reuse_prior_pool_or_label_artifacts") is not False
    ):
        raise ValueError("successful validation does not bind the complete abort chain")
    completion_path, completion = verify_bound_file(
        repo_root,
        binding.get("completion", {}),
        field="validation completion",
        canonical=True,
    )
    assert completion is not None
    verify_embedded(completion, "completion_sha256")
    if (
        completion.get("generation_file_sha256")
        != file_sha256(generation_path)
        or
        completion.get("schema_version")
        != "partizan.digraph_order7_neural_validation.v1.completion"
        or completion.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("mode") != "authorized_validation"
        or completion.get("validation_data_authorized_for_model_selection")
        is not True
        or completion.get("test_data_generated") is not False
    ):
        raise ValueError("validation completion is not official and verified")
    if completion_path.parent != run_dir:
        raise ValueError("validation completion is outside its bound directory")
    registry_path, registry = verify_bound_file(
        repo_root,
        binding.get("validation_registry", {}),
        field="validation registry",
        canonical=True,
    )
    assert registry is not None
    verify_embedded(registry, "registry_sha256")
    if (
        completion.get("validation_registry_file_sha256")
        != file_sha256(registry_path)
        or registry.get("schema_version")
        != "partizan.digraph_order7_neural_validation.v1.validation_identity_registry"
        or registry_path.parent != run_dir
    ):
        raise ValueError("validation registry does not bind completion")
    training_path, training = verify_bound_file(
        repo_root,
        binding.get("training_registry", {}),
        field="training registry",
        canonical=True,
    )
    assert training is not None
    verify_embedded(training, "registry_sha256")
    if (
        registry.get("training_registry_sha256") != training["registry_sha256"]
        or training_path.parent != run_dir
    ):
        raise ValueError("training registry does not bind validation registry")
    labels_path, _ = verify_bound_file(
        repo_root,
        binding.get("labels", {}),
        field="validation labels",
    )
    if (
        labels_path.parent != run_dir
        or registry.get("labels_file_sha256") != file_sha256(labels_path)
    ):
        raise ValueError("validation label ledger binding changed")
    verification_path, verification = verify_bound_file(
        repo_root,
        binding.get("independent_verification", {}),
        field="validation independent verification",
        canonical=True,
    )
    assert verification is not None
    verify_embedded(verification, "verification_sha256")
    if (
        verification_path.parent != run_dir
        or verification.get("status") != "PASS_VALIDATION_ONLY"
        or completion.get("verification_file_sha256")
        != file_sha256(verification_path)
    ):
        raise ValueError("validation independent verification changed")
    return {
        "run_dir": run_dir,
        "manifest": manifest,
        "generation": generation,
        "launch": successful_launch,
        "completion": completion,
        "completion_file_sha256": file_sha256(completion_path),
        "training_registry": training,
        "training_registry_file_sha256": file_sha256(training_path),
        "validation_registry": registry,
        "validation_registry_file_sha256": file_sha256(registry_path),
    }


def inspect_ensemble(
    ensemble_path: Path,
    *,
    expected_model_id: str,
) -> dict[str, Any]:
    ensemble = load_json_object(ensemble_path)
    if (
        ensemble.get("schema_version")
        != "partizan.digraph_order7_neural_ensemble.v0.1"
        or ensemble.get("model_id") != expected_model_id
        or ensemble.get("aggregation") != "arithmetic_mean_member_logits"
        or ensemble.get("member_seeds")
        != [10025726846852382910, 7606199125901481151, 1358850120366438448]
    ):
        raise ValueError("frozen ensemble contract changed")
    selection = ensemble.get("selection", {})
    selected = selection.get("selected", {})
    checkpoints = selected.get("member_checkpoint_sha256")
    if (
        not isinstance(checkpoints, list)
        or len(checkpoints) != 3
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in checkpoints
        )
    ):
        raise ValueError("ensemble selected member checkpoints are absent")
    return {
        "model_id": ensemble["model_id"],
        "grid_report_id": selection.get("grid_report_id"),
        "selected": dict(selected),
        "member_checkpoint_sha256": list(checkpoints),
    }


def verify_launch_document(
    repo_root: Path,
    launch: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    verify_embedded(launch, "launch_sha256")
    required = {
        "schema_version",
        "status",
        "protocol",
        "test_design",
        "validation",
        "model",
        "resource_preflight",
        "environment",
        "validation_incident_exclusions",
        "partizan_snapshot",
        "sources",
        "resource_limits",
        "commands",
        "authorization_nonce",
        "output_directory",
        "authorization_sha256",
        "launch_sha256",
    }
    if set(launch) != required:
        raise ValueError("test launch fields differ from the frozen contract")
    if (
        launch["schema_version"] != LAUNCH_SCHEMA
        or launch["status"] != "AUTHORIZED_ONCE"
    ):
        raise ValueError("test launch is not authorized once")
    protocol_binding = {
        "path": PROTOCOL_PATH.as_posix(),
        "sha256": file_sha256(repo_root / PROTOCOL_PATH),
    }
    if launch["protocol"] != protocol_binding:
        raise ValueError("test launch protocol binding changed")
    test = protocol["splits"]["test"]
    expected_design = {
        "targets": list(TARGETS),
        "pair_seeds": test["pair_seeds"],
        "pair_count_per_target": 12,
        "arms": list(ARMS),
        "calls_per_arm_pair": 2048,
        "pool_size": 16,
        "checkpoints": list(CHECKPOINTS),
        "success_stopping_rule": False,
    }
    if launch["test_design"] != expected_design:
        raise ValueError("test launch design changed")
    incidents = verify_validation_incident_exclusions(
        repo_root, launch["validation_incident_exclusions"]
    )
    validation = verify_validation_binding(
        repo_root,
        launch["validation"],
        protocol=protocol,
        incident_records=incidents,
    )
    model_path, model_binding = verify_bound_file(
        repo_root,
        launch["model"].get("binding", {}),
        field="frozen model binding",
        canonical=True,
    )
    assert model_binding is not None
    ranker, model_commitment = preflight.load_official_ranker(
        model_path,
        protocol_sha256=protocol_binding["sha256"],
        required_binding_fields=protocol["model"]["required_binding_fields"],
    )
    model_card_path, model_card = verify_bound_file(
        repo_root,
        launch["model"].get("model_card", {}),
        field="model card",
        canonical=True,
    )
    assert model_card is not None
    model_protocol = model_commitment["protocol_model_bindings"]
    if (
        model_protocol["model_card_sha256"] != file_sha256(model_card_path)
        or model_protocol["training_registry_sha256"]
        != validation["training_registry_file_sha256"]
        or model_protocol["validation_registry_sha256"]
        != validation["validation_registry_file_sha256"]
    ):
        raise ValueError("model card or registry freeze differs from validation")
    ensemble_path = Path(model_commitment["ensemble_path"])
    ensemble_info = inspect_ensemble(
        ensemble_path,
        expected_model_id=model_commitment["ensemble_model_id"],
    )
    expected_ensemble = launch["model"].get("ensemble")
    if expected_ensemble != {
        "path": repo_path(
            repo_root,
            expected_ensemble.get("path"),
            field="ensemble",
        ).relative_to(repo_root).as_posix(),
        "file_sha256": model_commitment["ensemble_file_sha256"],
        "model_id": model_commitment["ensemble_model_id"],
        "member_checkpoint_sha256": ensemble_info[
            "member_checkpoint_sha256"
        ],
    }:
        raise ValueError("test launch ensemble or checkpoint binding changed")
    if repo_path(
        repo_root,
        expected_ensemble["path"],
        field="ensemble",
    ) != ensemble_path:
        raise ValueError("test launch points to a different ensemble path")
    preflight_path, preflight_report = verify_bound_file(
        repo_root,
        launch["resource_preflight"],
        field="resource preflight",
        canonical=True,
    )
    assert preflight_report is not None
    preflight.verify_report(preflight_report)
    if (
        preflight_report.get("status") != "PASS"
        or preflight_report["protocol"]["sha256"] != protocol_binding["sha256"]
        or preflight_report["model"]["binding_file_sha256"]
        != file_sha256(model_path)
        or preflight_report["model"]["binding_sha256"]
        != model_binding["binding_sha256"]
        or preflight_report["model"]["ensemble_file_sha256"]
        != model_commitment["ensemble_file_sha256"]
        or preflight_report["resource_projection"]["status"] != "PASS"
    ):
        raise ValueError("official resource preflight does not bind this model")
    verify_environment(
        repo_root,
        launch["environment"],
        model_path=model_path,
        model_card=model_card,
        model_commitment=model_commitment,
    )
    verify_partizan_snapshot(repo_root, launch["partizan_snapshot"])
    ranker_source_sha = model_commitment["ranker_source_sha256"]
    partizan_ranker_sha = next(
        entry["sha256"]
        for entry in launch["partizan_snapshot"]["snapshot_files"]
        if entry["repo_relative_path"]
        == "python/partizan/digraph_neural_ranker.py"
    )
    if ranker_source_sha != partizan_ranker_sha:
        raise ValueError("bound ranker differs from pushed Partizan snapshot")
    sources = launch["sources"]
    if not isinstance(sources, list):
        raise ValueError("test launch source list is missing")
    observed_source_paths = [entry.get("repo_relative_path") for entry in sources]
    if observed_source_paths != list(REQUIRED_TEST_SOURCES):
        raise ValueError("test launch source set or order changed")
    for entry in sources:
        source_path = repo_path(
            repo_root,
            entry.get("repo_relative_path"),
            field="test source",
        )
        if file_sha256(source_path) != entry.get("sha256"):
            raise ValueError("test source changed after authorization")
    if launch["resource_limits"] != protocol["resource_gate"]:
        raise ValueError("test launch resource limits changed")
    authorization_payload = {
        field: launch[field]
        for field in (
            "protocol",
            "test_design",
            "validation",
            "model",
            "resource_preflight",
            "environment",
            "validation_incident_exclusions",
            "partizan_snapshot",
            "sources",
            "resource_limits",
            "commands",
            "authorization_nonce",
        )
    }
    if object_sha256(authorization_payload) != launch["authorization_sha256"]:
        raise ValueError("test launch authorization hash does not replay")
    expected_output = (
        "output/research/digraph-order7-neural-policy-test-v1-"
        + launch["authorization_sha256"][:12]
    )
    if launch["output_directory"] != expected_output:
        raise ValueError("test output directory is not authorization-derived")
    return {
        "ranker": ranker,
        "model_commitment": model_commitment,
        "model_binding": model_binding,
        "validation": validation,
        "preflight_path": preflight_path,
        "preflight_report": preflight_report,
        "ensemble_info": ensemble_info,
    }


def verify_launch(
    repo_root: Path,
    launch_path: Path,
    protocol: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    launch = load_canonical_json(launch_path)
    return launch, verify_launch_document(repo_root, launch, protocol)


def stage0_controls(
    repo_root: Path,
    training_registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    manifest = load_canonical_json(repo_root / TRAINING_RUN / "manifest.json")
    controls: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        candidates = [
            row
            for row in training_registry["validation_parents"][target]
            if row.get("source") == "stage0_control"
        ]
        if len(candidates) != 1:
            raise ValueError(f"training registry lacks one Stage-0 control for {target}")
        registry_row = candidates[0]
        seed = manifest["seed_controls"][target]
        if (
            seed["candidate"] != registry_row["candidate"]
            or seed["candidate_sha256"] != registry_row["candidate_sha256"]
            or seed["quotient"]["quotient_sha256"]
            != registry_row["quotient_sha256"]
        ):
            raise ValueError("Stage-0 control differs from frozen training manifest")
        controls[target] = {
            "candidate": seed["candidate"],
            "candidate_sha256": seed["candidate_sha256"],
            "quotient_sha256": seed["quotient"]["quotient_sha256"],
            "literal_game_sha256": seed["literal_game_sha256"],
            "test_discovery": False,
        }
    return controls


def prior_split_registry(
    *,
    repo_root: Path,
    mode: str,
    validation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if mode == OFFICIAL_MODE:
        if validation is None:
            raise ValueError("official prior registry requires verified validation")
        training = validation["training_registry"]
        validation_registry = validation["validation_registry"]
        source = {
            "mode": "official_training_plus_validation",
            "training_registry_sha256": training["registry_sha256"],
            "validation_registry_sha256": validation_registry["registry_sha256"],
            "validation_completion_sha256": validation["completion"][
                "completion_sha256"
            ],
        }
        candidate_ids = set(training["candidate_sha256"]) | set(
            validation_registry["candidate_sha256"]
        )
        quotient_ids = set(training["quotient_sha256"]) | set(
            validation_registry["quotient_sha256"]
        )
    else:
        training = validation_builder.training_identity_registry(repo_root)
        source = {
            "mode": "smoke_training_only",
            "training_registry_sha256": training["registry_sha256"],
            "validation_registry_sha256": None,
            "validation_completion_sha256": None,
        }
        candidate_ids = set(training["candidate_sha256"])
        quotient_ids = set(training["quotient_sha256"])
    payload = {
        "schema_version": REGISTRY_SCHEMA,
        "status": (
            "FROZEN_PRIOR_SPLIT_IDENTITIES"
            if mode == OFFICIAL_MODE
            else "SMOKE_ONLY_NOT_EVIDENCE"
        ),
        "mode": mode,
        "source": source,
        "candidate_sha256": sorted(candidate_ids),
        "quotient_sha256": sorted(quotient_ids),
        "stage0_controls": stage0_controls(repo_root, training),
        "counts": {
            "candidate_identities": len(candidate_ids),
            "quotient_identities": len(quotient_ids),
        },
        "literal_game_sha256_is_recorded_not_blocked": True,
        "cross_arm_test_collision_blocks_discovery": False,
        "paper_evidence": False,
    }
    return hashed_record(payload, "registry_sha256")


def copy_official_bundle(
    *,
    repo_root: Path,
    run_dir: Path,
    launch: Mapping[str, Any],
) -> list[dict[str, str]]:
    bindings: list[tuple[str, str, str]] = []
    for entry in launch["sources"]:
        bindings.append(
            ("test_source", entry["repo_relative_path"], entry["sha256"])
        )
    for entry in launch["partizan_snapshot"]["snapshot_files"]:
        bindings.append(
            ("partizan_model", entry["snapshot_path"], entry["sha256"])
        )
    for section, role in (
        ("manifest", "validation_manifest"),
        ("generation", "validation_generation"),
        ("launch", "successful_validation_launch"),
        ("completion", "validation_completion"),
        ("training_registry", "training_registry"),
        ("validation_registry", "validation_registry"),
        ("labels", "validation_labels"),
        ("independent_verification", "validation_verification"),
    ):
        entry = launch["validation"][section]
        bindings.append((role, entry["path"], entry["file_sha256"]))
    bindings.extend(
        (
            role,
            launch["model"][section]["path"],
            launch["model"][section]["file_sha256"],
        )
        for section, role in (
            ("binding", "model_binding"),
            ("model_card", "model_card"),
            ("ensemble", "ensemble"),
        )
    )
    bindings.append(
        (
            "resource_preflight",
            launch["resource_preflight"]["path"],
            launch["resource_preflight"]["file_sha256"],
        )
    )
    bindings.append(
        (
            "model_environment",
            launch["environment"]["path"],
            launch["environment"]["file_sha256"],
        )
    )
    for index, (entry, expected) in enumerate(
        zip(
            launch["validation_incident_exclusions"],
            FAILED_VALIDATION_INCIDENTS,
            strict=True,
        )
    ):
        bindings.extend(
            [
                (
                    f"excluded_validation_incident_{index}",
                    entry["path"],
                    entry["file_sha256"],
                ),
                (
                    f"excluded_validation_authorization_{index}",
                    expected["authorization_path"],
                    file_sha256(
                        repo_root / expected["authorization_path"]
                    ),
                ),
                (
                    f"excluded_validation_failure_{index}",
                    f"{expected['directory']}/FAILURE.json",
                    file_sha256(
                        repo_root / expected["directory"] / "FAILURE.json"
                    ),
                ),
            ]
        )
    copied: list[dict[str, str]] = []
    for role, relative, digest in bindings:
        source = repo_path(repo_root, relative, field=role)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"{role} bytes changed before snapshot copy")
        destination = (
            Path("source")
            / role
            / digest[:2]
            / f"{digest}-{source.name}"
        )
        write_bytes_exclusive(run_dir / destination, data)
        copied.append(
            {
                "role": role,
                "source_path": relative,
                "bundled_path": destination.as_posix(),
                "sha256": digest,
            }
        )
    return copied


class StreamAccumulator:
    def __init__(self, *, target: str, pair_seed: int, arm: str) -> None:
        self.target = target
        self.pair_seed = pair_seed
        self.arm = arm
        self.calls = 0
        self.exact_matches = 0
        self.discoveries: set[str] = set()
        self.literal_digests: set[str] = set()
        self.descriptor_cells: set[tuple[str, ...]] = set()
        self.primary_edges: set[tuple[str, str, str]] = set()
        self.transition_classes: Counter[str] = Counter()
        self.selected_candidates: set[str] = set()
        self.duplicate_count = 0
        self.prior_split_leakage_count = 0
        self.cross_arm_candidate_collisions = 0
        self.cross_arm_quotient_collisions = 0
        self.rejection_stages: Counter[str] = Counter()
        self.tier_counts: Counter[int] = Counter()
        self.checkpoint_discoveries: dict[str, int] = {}
        self.model_inference_seconds = 0.0
        self.cpu_seconds = 0.0

    def update(self, event: Mapping[str, Any]) -> None:
        self.calls += 1
        self.tier_counts[event["structural_filter"]["tier_index"]] += 1
        self.selected_candidates.add(event["candidate_sha256"])
        decision = event["exact_decision"]
        if decision is not None and decision["equal"]:
            self.exact_matches += 1
        if event["prior_split_leakage"]:
            self.prior_split_leakage_count += 1
        if event["cross_arm"]["candidate_seen_by_other_arm"]:
            self.cross_arm_candidate_collisions += 1
        if event["cross_arm"]["quotient_seen_by_other_arm"]:
            self.cross_arm_quotient_collisions += 1
        rejection = event["rejection"]
        if rejection is not None:
            self.rejection_stages[rejection["stage"]] += 1
        if event["retention"]["duplicate_quotient"]:
            self.duplicate_count += 1
        if event["retention"]["inserted"]:
            quotient_sha = event["quotient"]["quotient_sha256"]
            self.discoveries.add(quotient_sha)
            self.literal_digests.add(
                event["exact_decision"]["candidate_root_game_sha256"]
            )
            self.descriptor_cells.add(
                tuple(event["measurements"]["descriptor_cell"])
            )
            transition = event["transition"]
            if transition is not None and transition["primary"]:
                key = (
                    transition["class"],
                    transition["parent_quotient_sha256"],
                    transition["candidate_quotient_sha256"],
                )
                self.primary_edges.add(key)
                self.transition_classes[transition["class"]] += 1
        if self.calls in CHECKPOINTS:
            self.checkpoint_discoveries[str(self.calls)] = len(self.discoveries)

    def record(self, *, deterministic_timings: bool) -> dict[str, Any]:
        payload = {
            "schema_version": STREAM_SCHEMA,
            "target": self.target,
            "pair_seed": self.pair_seed,
            "arm": self.arm,
            "verifier_calls": self.calls,
            "raw_pool_candidates": self.calls * 16,
            "certified_exact_matches": self.exact_matches,
            "quotient_unique_discoveries": len(self.discoveries),
            "quotient_unique_discoveries_by_checkpoint": dict(
                self.checkpoint_discoveries
            ),
            "discovered_quotient_sha256": sorted(self.discoveries),
            "literal_game_digest_count": len(self.literal_digests),
            "literal_game_sha256": sorted(self.literal_digests),
            "occupied_descriptor_cells": len(self.descriptor_cells),
            "descriptor_cells": [
                list(cell) for cell in sorted(self.descriptor_cells)
            ],
            "embodiment_only_edges": sum(
                edge[0] == "embodiment_only" for edge in self.primary_edges
            ),
            "literal_tree_crossing_edges": sum(
                edge[0] == "literal_tree_crossing"
                for edge in self.primary_edges
            ),
            "transition_class_counts": dict(sorted(self.transition_classes.items())),
            "selected_candidate_unique_count": len(self.selected_candidates),
            "duplicate_count": self.duplicate_count,
            "duplicate_rate": (
                self.duplicate_count / self.calls if self.calls else None
            ),
            "prior_split_leakage_count": self.prior_split_leakage_count,
            "prior_split_leakage_rate": (
                self.prior_split_leakage_count / self.calls
                if self.calls
                else None
            ),
            "cross_arm_candidate_collision_count": (
                self.cross_arm_candidate_collisions
            ),
            "cross_arm_quotient_collision_count": (
                self.cross_arm_quotient_collisions
            ),
            "rejection_stage_counts": dict(sorted(self.rejection_stages.items())),
            "structural_tier_counts": {
                str(key): self.tier_counts[key]
                for key in sorted(self.tier_counts)
            },
            "verifier_calls_per_new_quotient": (
                self.calls / len(self.discoveries)
                if self.discoveries
                else None
            ),
            "cpu_seconds": 0.0 if deterministic_timings else self.cpu_seconds,
            "model_inference_seconds": (
                0.0
                if deterministic_timings
                else self.model_inference_seconds
            ),
            "timings_suppressed_for_deterministic_smoke": deterministic_timings,
        }
        return hashed_record(payload, "stream_sha256")


def bootstrap_randbelow(
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
                    f"{PROTOCOL_PREFIX}|inference|bootstrap|{seed}|"
                    f"{resample}|{target}|{draw}|{counter}"
                ).encode("utf-8")
            ).digest(),
            "big",
        )
        if value < limit:
            return value % size
        counter += 1


def nearest_rank(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def compute_inference(
    streams: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    by_key = {
        (row["target"], row["pair_seed"], row["arm"]): row for row in streams
    }
    seeds_by_target = {
        target: sorted(
            {
                row["pair_seed"]
                for row in streams
                if row["target"] == target
            }
        )
        for target in TARGETS
    }
    differences: dict[str, list[int]] = {}
    target_points: dict[str, float] = {}
    for target in TARGETS:
        differences[target] = [
            int(
                by_key[(target, seed, TREATMENT_ARM)][
                    "quotient_unique_discoveries"
                ]
                - by_key[(target, seed, CONTROL_ARM)][
                    "quotient_unique_discoveries"
                ]
            )
            for seed in seeds_by_target[target]
        ]
        if not differences[target]:
            raise ValueError(f"inference has no paired streams for {target}")
        target_points[target] = sum(differences[target]) / len(
            differences[target]
        )
    macro_point = sum(target_points.values()) / len(TARGETS)
    inference_protocol = protocol["primary_analysis"]
    bootstrap = inference_protocol["interval"]
    resamples = int(bootstrap["resamples"])
    bootstrap_macro: list[float] = []
    bootstrap_targets: dict[str, list[float]] = {
        target: [] for target in TARGETS
    }
    for resample in range(resamples):
        target_draws: dict[str, float] = {}
        for target in TARGETS:
            values = differences[target]
            drawn = [
                values[
                    bootstrap_randbelow(
                        len(values),
                        seed=bootstrap["rng_seed"],
                        resample=resample,
                        target=target,
                        draw=draw,
                    )
                ]
                for draw in range(len(values))
            ]
            target_draws[target] = sum(drawn) / len(drawn)
            bootstrap_targets[target].append(target_draws[target])
        bootstrap_macro.append(sum(target_draws.values()) / len(TARGETS))
    target_intervals = {
        target: {
            "lower": nearest_rank(values, 0.025),
            "upper": nearest_rank(values, 0.975),
        }
        for target, values in bootstrap_targets.items()
    }
    macro_interval = {
        "lower": nearest_rank(bootstrap_macro, 0.025),
        "upper": nearest_rank(bootstrap_macro, 0.975),
    }
    ordered_pairs = [
        (target, index, value)
        for target in TARGETS
        for index, value in enumerate(differences[target])
    ]
    sign = inference_protocol["sign_flip"]
    assignment_limit = int(sign["maximum_enumerated_or_sampled_assignments"])
    assignment_count = (
        1 << len(ordered_pairs)
        if (1 << len(ordered_pairs)) <= assignment_limit
        else assignment_limit
    )
    extreme = 0
    sign_chain = ZERO_SHA256
    for assignment in range(assignment_count):
        if (1 << len(ordered_pairs)) <= assignment_limit:
            mask = assignment
        else:
            digest = hashlib.sha256(
                (
                    f"{PROTOCOL_PREFIX}|inference|sign_flip|"
                    f"{sign['rng_seed']}|{assignment}"
                ).encode("utf-8")
            ).digest()
            mask = int.from_bytes(digest, "big")
        signed_target_sums = {target: 0 for target in TARGETS}
        signed_target_counts = {target: 0 for target in TARGETS}
        for bit, (target, _, value) in enumerate(ordered_pairs):
            signed_target_sums[target] += value if (mask >> bit) & 1 else -value
            signed_target_counts[target] += 1
        statistic = sum(
            signed_target_sums[target] / signed_target_counts[target]
            for target in TARGETS
        ) / len(TARGETS)
        if abs(statistic) >= abs(macro_point):
            extreme += 1
        sign_chain = object_sha256(
            {
                "previous": sign_chain,
                "assignment": assignment,
                "mask_low_bits": mask & ((1 << len(ordered_pairs)) - 1),
                "statistic_hex": statistic.hex(),
            }
        )
    sign_p = (
        extreme / assignment_count
        if (1 << len(ordered_pairs)) <= assignment_limit
        else (extreme + 1) / (assignment_count + 1)
    )
    control_total = sum(
        row["quotient_unique_discoveries"]
        for row in streams
        if row["arm"] == CONTROL_ARM
    )
    treatment_total = sum(
        row["quotient_unique_discoveries"]
        for row in streams
        if row["arm"] == TREATMENT_ARM
    )
    relative_lift = (
        (treatment_total - control_total) / control_total
        if control_total
        else None
    )
    payload = {
        "schema_version": INFERENCE_SCHEMA,
        "unit": "paired_target_stream",
        "paired_differences": differences,
        "target_point_estimates": target_points,
        "macro_point_estimate": macro_point,
        "bootstrap": {
            "method": "stratified_paired_percentile_bootstrap",
            "resamples": resamples,
            "rng_seed": bootstrap["rng_seed"],
            "rng_algorithm": "sha256_unbiased_counter_randbelow_v1",
            "percentile_rule": "nearest_rank_ceil_probability_times_n",
            "macro_interval": macro_interval,
            "target_intervals": target_intervals,
            "macro_samples_hex": [value.hex() for value in bootstrap_macro],
            "macro_samples_sha256": object_sha256(
                [value.hex() for value in bootstrap_macro]
            ),
        },
        "sign_flip": {
            "method": "deterministic_two_sided_paired_sign_flip",
            "rng_seed": sign["rng_seed"],
            "assignment_mode": (
                "enumerated"
                if (1 << len(ordered_pairs)) <= assignment_limit
                else "sha256_sampled_with_replacement"
            ),
            "assignment_count": assignment_count,
            "extreme_count": extreme,
            "p_value": sign_p,
            "assignment_statistic_chain_sha256": sign_chain,
        },
        "total_discoveries": {
            CONTROL_ARM: control_total,
            TREATMENT_ARM: treatment_total,
        },
        "relative_lift": relative_lift,
        "proposal_level_inference_performed": False,
        "secondary_metrics_can_rescue_primary": False,
    }
    return hashed_record(payload, "inference_sha256")


def compute_gate(
    *,
    streams: Sequence[Mapping[str, Any]],
    inference: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    literal_by_arm = {
        arm: {
            digest
            for row in streams
            if row["arm"] == arm
            for digest in row["literal_game_sha256"]
        }
        for arm in ARMS
    }
    cells_by_arm = {
        arm: {
            tuple(cell)
            for row in streams
            if row["arm"] == arm
            for cell in row["descriptor_cells"]
        }
        for arm in ARMS
    }
    learned_classes_by_target = {
        target: {
            transition_class
            for row in streams
            if row["arm"] == TREATMENT_ARM and row["target"] == target
            for transition_class, count in row["transition_class_counts"].items()
            if count > 0
        }
        for target in TARGETS
    }
    literal_ratio = (
        len(literal_by_arm[TREATMENT_ARM]) / len(literal_by_arm[CONTROL_ARM])
        if literal_by_arm[CONTROL_ARM]
        else None
    )
    descriptor_ratio = (
        len(cells_by_arm[TREATMENT_ARM]) / len(cells_by_arm[CONTROL_ARM])
        if cells_by_arm[CONTROL_ARM]
        else None
    )
    frozen = protocol["learned_advantage_gate"]
    checks = {
        "primary_point_estimate_positive": (
            inference["macro_point_estimate"]
            > frozen["primary_point_estimate_gt"]
        ),
        "primary_interval_lower_above_zero": (
            inference["bootstrap"]["macro_interval"]["lower"]
            > frozen["primary_interval_lower_gt"]
        ),
        "minimum_total_relative_lift": (
            inference["relative_lift"] is not None
            and inference["relative_lift"]
            >= frozen["minimum_total_relative_lift"]
        ),
        "positive_mean_difference_for_every_target": all(
            value > 0 for value in inference["target_point_estimates"].values()
        ),
        "minimum_literal_digest_ratio_to_control": (
            literal_ratio is not None
            and literal_ratio
            >= frozen["minimum_literal_digest_ratio_to_control"]
        ),
        "minimum_descriptor_cell_ratio_to_control": (
            descriptor_ratio is not None
            and descriptor_ratio
            >= frozen["minimum_descriptor_cell_ratio_to_control"]
        ),
        "both_transition_classes_for_every_target": all(
            {"embodiment_only", "literal_tree_crossing"}
            <= learned_classes_by_target[target]
            for target in TARGETS
        ),
    }
    payload = {
        "checks": checks,
        "all_scientific_checks_pass_before_independent_replay": all(
            checks.values()
        ),
        "literal_digest_counts": {
            arm: len(literal_by_arm[arm]) for arm in ARMS
        },
        "literal_digest_ratio_to_control": literal_ratio,
        "descriptor_cell_counts": {
            arm: len(cells_by_arm[arm]) for arm in ARMS
        },
        "descriptor_cell_ratio_to_control": descriptor_ratio,
        "learned_transition_classes_by_target": {
            target: sorted(learned_classes_by_target[target])
            for target in TARGETS
        },
        "integrity_pending_independent_replay": True,
        "secondary_rescue_allowed": False,
        "diagnostic_arm_substitution_allowed": False,
    }
    return hashed_record(payload, "gate_sha256")


def stream_bundle(
    streams: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    overlap: dict[str, Any] = {}
    for target in TARGETS:
        target_rows = [row for row in streams if row["target"] == target]
        seeds = sorted({row["pair_seed"] for row in target_rows})
        overlap[target] = {}
        for pair_seed in seeds:
            by_arm = {
                row["arm"]: set(row["discovered_quotient_sha256"])
                for row in target_rows
                if row["pair_seed"] == pair_seed
            }
            overlap[target][str(pair_seed)] = sorted(
                by_arm[CONTROL_ARM] & by_arm[TREATMENT_ARM]
            )
    payload = {
        "schema_version": f"{STREAM_SCHEMA}.bundle",
        "streams": list(streams),
        "stream_count": len(streams),
        "cross_arm_quotient_overlap": overlap,
    }
    return hashed_record(payload, "bundle_sha256")


def evaluate_selected(
    *,
    graph: DigraphPlacement,
    candidate: Mapping[str, Any],
    candidate_sha: str,
    target: str,
    parent: Mapping[str, Any],
    mode: str,
    target_games: Mapping[str, Any],
    target_bindings: Mapping[str, Mapping[str, str]],
    prior_candidates: set[str],
    prior_quotients: set[str],
    repertoire: dict[str, dict[str, Any]],
    other_candidates: set[str],
    other_quotients: set[str],
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    connected = weakly_connected(graph)
    candidate_collision = candidate_sha in prior_candidates
    if not connected:
        semantic = {
            "weakly_connected": False,
            "exact_decision": None,
            "structural_quotient": None,
            "quotient": None,
            "measurements": None,
            "prior_split_candidate_collision": candidate_collision,
            "prior_split_quotient_collision": False,
            "prior_split_leakage": candidate_collision,
            "cross_arm": {
                "candidate_seen_by_other_arm": candidate_sha in other_candidates,
                "quotient_seen_by_other_arm": False,
            },
            "transition": None,
            "retention": {
                "new_quotient": False,
                "duplicate_quotient": False,
                "inserted": False,
                "sidecars": None,
                "equality_certificate_sha256": None,
            },
            "rejection": {
                "stage": "representation_grammar",
                "reason": "weakly_disconnected",
            },
        }
        return semantic, None

    structural_quotient = quotient_record(graph)
    quotient_collision = (
        structural_quotient["quotient_sha256"] in prior_quotients
    )
    if mode == SMOKE_MODE:
        decision = mock_exact_decision(
            graph=graph,
            target=target,
            candidate_sha256=candidate_sha,
            parent_literal=parent["literal_game_sha256"],
        )
    else:
        decision, _ = fixed_value.exact_decision(graph, target_games[target])
    measurements = descriptor_record(graph) if decision is not None else None
    equal = decision is not None and decision["equal"]
    quotient = structural_quotient if equal else None
    candidate_q = structural_quotient["quotient_sha256"]
    new_quotient = equal and candidate_q not in repertoire
    duplicate = equal and candidate_q in repertoire
    leakage = candidate_collision or quotient_collision
    inserted = bool(equal and new_quotient and not leakage)
    sidecars = None
    equality_sha = None
    if inserted and mode == OFFICIAL_MODE:
        sidecars, equality_sha = fixed_value.build_match_sidecars(
            graph=graph,
            target=target_games[target],
            target_binding=target_bindings[target],
            run_dir=run_dir,
        )
    transition = None
    if equal:
        transition = transition_record(
            parent=parent,
            candidate_quotient=candidate_q,
            candidate_literal=decision["candidate_root_game_sha256"],
            inserted=inserted,
        )
    rejection = None
    if leakage:
        rejection = {
            "stage": "prior_split_registry",
            "reason": (
                "prior_split_candidate_and_quotient_collision"
                if candidate_collision and quotient_collision
                else (
                    "prior_split_candidate_collision"
                    if candidate_collision
                    else "prior_split_quotient_collision"
                )
            ),
        }
    elif not equal:
        rejection = {
            "stage": "exact_equality",
            "reason": "exact_value_mismatch",
        }
    elif duplicate:
        rejection = {
            "stage": "discovery_accounting",
            "reason": "duplicate_quotient",
        }
    if inserted:
        repertoire[candidate_q] = {
            "candidate": dict(candidate),
            "candidate_sha256": candidate_sha,
            "quotient_sha256": candidate_q,
            "literal_game_sha256": decision["candidate_root_game_sha256"],
            "test_discovery": True,
        }
    semantic = {
        "weakly_connected": connected,
        "exact_decision": decision,
        "structural_quotient": structural_quotient,
        "quotient": quotient,
        "measurements": measurements,
        "prior_split_candidate_collision": candidate_collision,
        "prior_split_quotient_collision": quotient_collision,
        "prior_split_leakage": leakage,
        "cross_arm": {
            "candidate_seen_by_other_arm": candidate_sha in other_candidates,
            "quotient_seen_by_other_arm": candidate_q in other_quotients,
        },
        "transition": transition,
        "retention": {
            "new_quotient": bool(new_quotient),
            "duplicate_quotient": bool(duplicate),
            "inserted": inserted,
            "sidecars": sidecars,
            "equality_certificate_sha256": equality_sha,
        },
        "rejection": rejection,
    }
    return semantic, repertoire.get(candidate_q) if inserted else None


def generate_test_ledgers(
    *,
    run_dir: Path,
    mode: str,
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    ranker: Ranker,
    registry: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    prefix = PROTOCOL_PREFIX if mode == OFFICIAL_MODE else SMOKE_PREFIX
    phase = "test" if mode == OFFICIAL_MODE else "smoke_test"
    prior_candidates = set(registry["candidate_sha256"])
    prior_quotients = set(registry["quotient_sha256"])
    target_games = {target: parse_game_form(target) for target in TARGETS}
    target_bindings: dict[str, dict[str, str]] = {}
    if mode == OFFICIAL_MODE:
        for target in TARGETS:
            artifact = fixed_value.target_artifact(target, target_games[target])
            reference = fixed_value.write_content_addressed(
                run_dir, "targets", artifact
            )
            target_bindings[target] = artifact_binding(
                kind="abstract_short_game_target",
                schema_version="partizan.abstract_short_game_target.v1",
                artifact_sha256=reference["sha256"],
                root=target_games[target],
            )

    proposals_path = run_dir / "proposal_decisions.jsonl"
    events_path = run_dir / "events.jsonl"
    proposal_fd = os.open(
        proposals_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    event_fd = os.open(
        events_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    previous_proposal = ZERO_SHA256
    previous_global_event = ZERO_SHA256
    previous_arm_event = {arm: ZERO_SHA256 for arm in ARMS}
    global_index = 0
    streams: list[dict[str, Any]] = []
    try:
        with os.fdopen(proposal_fd, "wb") as proposal_handle, os.fdopen(
            event_fd, "wb"
        ) as event_handle:
            for target in TARGETS:
                for pair_seed in pair_seeds:
                    control = registry["stage0_controls"][target]
                    repertoires = {
                        arm: {
                            control["quotient_sha256"]: dict(control)
                        }
                        for arm in ARMS
                    }
                    live_candidate_ids = {
                        arm: {control["candidate_sha256"]} for arm in ARMS
                    }
                    selected_candidates = {arm: set() for arm in ARMS}
                    selected_quotients = {arm: set() for arm in ARMS}
                    accumulators = {
                        arm: StreamAccumulator(
                            target=target,
                            pair_seed=pair_seed,
                            arm=arm,
                        )
                        for arm in ARMS
                    }
                    for call_index in range(calls_per_arm_pair):
                        arcs = selected_arcs(
                            prefix=prefix,
                            phase=phase,
                            target=target,
                            pair_seed=pair_seed,
                            call_index=call_index,
                        )
                        for arm in ARMS:
                            arm_cpu_started = time.process_time()
                            repertoire = repertoires[arm]
                            ordered_parent_ids = sorted(repertoire)
                            parent_index = counter_randbelow(
                                len(ordered_parent_ids),
                                prefix=prefix,
                                phase=phase,
                                target=target,
                                pair_seed=pair_seed,
                                unit_index=call_index,
                                draw_name="parent",
                            )
                            parent_q = ordered_parent_ids[parent_index]
                            parent = repertoire[parent_q]
                            parent_graph = graph_from_candidate_record(
                                parent["candidate"]
                            )
                            candidates: list[dict[str, Any]] = []
                            for slot, arc in enumerate(arcs):
                                graph = toggle_arc(parent_graph, arc)
                                candidate = candidate_record(graph)
                                candidate_sha = candidate_record_sha256(candidate)
                                candidates.append(
                                    {
                                        "slot_index": slot,
                                        "arc": [arc[0], arc[1]],
                                        "candidate": candidate,
                                        "candidate_sha256": candidate_sha,
                                        "weakly_connected": weakly_connected(graph),
                                        "prior_split_candidate_collision": (
                                            candidate_sha in prior_candidates
                                        ),
                                        "candidate_new_to_arm": (
                                            candidate_sha
                                            not in live_candidate_ids[arm]
                                        ),
                                    }
                                )
                            if len({row["candidate_sha256"] for row in candidates}) != 16:
                                raise AssertionError("test pool contains duplicate candidates")
                            tier_index, eligible = first_nonempty_tier(candidates)
                            pool_id = object_sha256(
                                {
                                    "schema_version": f"{SCHEMA}.pool_id",
                                    "mode": mode,
                                    "target": target,
                                    "pair_seed": pair_seed,
                                    "call_index": call_index,
                                    "arm": arm,
                                    "parent_quotient_sha256": parent_q,
                                }
                            )
                            score_values: list[float] | None = None
                            score_hex: list[str] | None = None
                            inference_seconds = 0.0
                            if arm == TREATMENT_ARM:
                                rows = ranker_rows(
                                    candidates=candidates,
                                    target=target,
                                    pair_seed=pair_seed,
                                    pool_id=pool_id,
                                )
                                before = time.perf_counter()
                                supplied_scores = ranker(rows)
                                inference_seconds = time.perf_counter() - before
                                if len(supplied_scores) != 16:
                                    raise ValueError(
                                        "ranker did not return sixteen scores"
                                    )
                                score_values, score_hex = float_hex_scores(
                                    supplied_scores
                                )
                            selected_slot, selection_method = select_slot(
                                arm=arm,
                                eligible=eligible,
                                candidates=candidates,
                                scores=score_values,
                                prefix=prefix,
                                phase=phase,
                                target=target,
                                pair_seed=pair_seed,
                                call_index=call_index,
                            )
                            proposal_payload = {
                                "schema_version": POOL_SCHEMA,
                                "mode": mode,
                                "global_proposal_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "rng": {
                                    "prefix": prefix,
                                    "phase": phase,
                                    "unit_index": call_index,
                                    "parent_draw_name": "parent",
                                    "parent_population_size": len(
                                        ordered_parent_ids
                                    ),
                                    "parent_population_order_sha256": object_sha256(
                                        ordered_parent_ids
                                    ),
                                    "parent_selected_index": parent_index,
                                    "arc_draw_names": [
                                        f"arc_shuffle_{index}"
                                        for index in range(41, 0, -1)
                                    ],
                                    "arcs": [
                                        [source, destination]
                                        for source, destination in arcs
                                    ],
                                },
                                "pool_id": pool_id,
                                "parent": {
                                    "candidate_sha256": parent[
                                        "candidate_sha256"
                                    ],
                                    "quotient_sha256": parent_q,
                                    "literal_game_sha256": parent[
                                        "literal_game_sha256"
                                    ],
                                    "test_discovery": parent[
                                        "test_discovery"
                                    ],
                                },
                                "proposal_operator": "toggle_one_arc",
                                "candidates": candidates,
                                "structural_filter": {
                                    "tier_index": tier_index,
                                    "tier": list(TIERS[tier_index]),
                                    "eligible_slots": list(eligible),
                                    "has_exact_value_access": False,
                                    "has_graph_quotient_access": False,
                                },
                                "model": {
                                    "used": arm == TREATMENT_ARM,
                                    "score_hex_by_slot": score_hex,
                                    "outcome_fields_received": [],
                                },
                                "selection": {
                                    "selected_slot": selected_slot,
                                    "selected_candidate_sha256": candidates[
                                        selected_slot
                                    ]["candidate_sha256"],
                                    **selection_method,
                                },
                                "outcome_fields_absent_at_selection": True,
                                "previous_proposal_sha256": previous_proposal,
                            }
                            if POOL_FORBIDDEN_OUTCOME_FIELDS & set(
                                proposal_payload
                            ):
                                raise AssertionError(
                                    "proposal commitment contains an outcome"
                                )
                            proposal_record = hashed_record(
                                proposal_payload, "proposal_sha256"
                            )
                            proposal_handle.write(canonical_line(proposal_record))
                            proposal_handle.flush()
                            previous_proposal = proposal_record["proposal_sha256"]

                            selected = candidates[selected_slot]
                            graph = graph_from_candidate_record(
                                selected["candidate"]
                            )
                            other_arm = (
                                TREATMENT_ARM
                                if arm == CONTROL_ARM
                                else CONTROL_ARM
                            )
                            semantic, inserted_row = evaluate_selected(
                                graph=graph,
                                candidate=selected["candidate"],
                                candidate_sha=selected["candidate_sha256"],
                                target=target,
                                parent=parent,
                                mode=mode,
                                target_games=target_games,
                                target_bindings=target_bindings,
                                prior_candidates=prior_candidates,
                                prior_quotients=prior_quotients,
                                repertoire=repertoire,
                                other_candidates=selected_candidates[other_arm],
                                other_quotients=selected_quotients[other_arm],
                                run_dir=run_dir,
                            )
                            selected_candidates[arm].add(
                                selected["candidate_sha256"]
                            )
                            if semantic["structural_quotient"] is not None:
                                selected_quotients[arm].add(
                                    semantic["structural_quotient"][
                                        "quotient_sha256"
                                    ]
                                )
                            if inserted_row is not None:
                                live_candidate_ids[arm].add(
                                    inserted_row["candidate_sha256"]
                                )
                            event_payload = {
                                "schema_version": EVENT_SCHEMA,
                                "mode": mode,
                                "global_event_index": global_index,
                                "target": target,
                                "pair_seed": pair_seed,
                                "call_index": call_index,
                                "arm": arm,
                                "proposal_sha256": proposal_record[
                                    "proposal_sha256"
                                ],
                                "pool_id": pool_id,
                                "parent": proposal_record["parent"],
                                "proposal": {
                                    "operator": "toggle_one_arc",
                                    "arc": selected["arc"],
                                    "selected_slot": selected_slot,
                                },
                                "candidate": selected["candidate"],
                                "candidate_sha256": selected[
                                    "candidate_sha256"
                                ],
                                "structural_filter": proposal_record[
                                    "structural_filter"
                                ],
                                "model_selected_score_hex": (
                                    score_hex[selected_slot]
                                    if score_hex is not None
                                    else None
                                ),
                                "exact_verifier_call_consumed": True,
                                **semantic,
                                "previous_arm_event_sha256": (
                                    previous_arm_event[arm]
                                ),
                                "previous_global_event_sha256": (
                                    previous_global_event
                                ),
                            }
                            event_record = hashed_record(
                                event_payload, "event_sha256"
                            )
                            event_handle.write(canonical_line(event_record))
                            event_handle.flush()
                            previous_arm_event[arm] = event_record["event_sha256"]
                            previous_global_event = event_record["event_sha256"]
                            accumulators[arm].model_inference_seconds += (
                                inference_seconds
                            )
                            accumulators[arm].update(event_record)
                            accumulators[arm].cpu_seconds += (
                                time.process_time() - arm_cpu_started
                            )
                            global_index += 1
                            fixed_value.clear_caches()
                        if call_index + 1 in CHECKPOINTS:
                            os.fsync(proposal_handle.fileno())
                            os.fsync(event_handle.fileno())
                    for arm in ARMS:
                        streams.append(
                            accumulators[arm].record(
                                deterministic_timings=mode == SMOKE_MODE
                            )
                        )
            proposal_handle.flush()
            event_handle.flush()
            os.fsync(proposal_handle.fileno())
            os.fsync(event_handle.fileno())
    except BaseException:
        raise
    stream_result = stream_bundle(streams)
    inference = compute_inference(streams, protocol)
    gate = compute_gate(
        streams=streams,
        inference=inference,
        protocol=protocol,
    )
    return (
        stream_result,
        inference,
        gate,
        previous_proposal,
        previous_global_event,
    )


def build_run(
    *,
    repo_root: Path,
    run_dir: Path,
    mode: str,
    protocol: Mapping[str, Any],
    pair_seeds: Sequence[int],
    calls_per_arm_pair: int,
    ranker: Ranker,
    launch: Mapping[str, Any] | None,
    launch_info: Mapping[str, Any] | None,
) -> dict[str, Any]:
    test = protocol["splits"]["test"]
    if mode == OFFICIAL_MODE:
        if launch is None or launch_info is None:
            raise ValueError(
                "official test cannot run without a verified one-time launch"
            )
        replay_info = verify_launch_document(repo_root, launch, protocol)
        if (
            list(pair_seeds) != list(test["pair_seeds"])
            or calls_per_arm_pair != test["verifier_calls_per_arm_pair"]
            or run_dir.resolve()
            != (repo_root / launch["output_directory"]).resolve()
        ):
            raise ValueError("official test design or output directory changed")
        if (
            replay_info["model_commitment"]
            != launch_info["model_commitment"]
            or replay_info["validation"]["completion"]
            != launch_info["validation"]["completion"]
        ):
            raise ValueError("official launch replay differs before creation")
    elif mode == SMOKE_MODE:
        expected_smoke = [smoke_seed(0)]
        official_seed_sets = set(protocol["splits"]["validation"]["pair_seeds"]) | set(
            protocol["splits"]["test"]["pair_seeds"]
        )
        if (
            launch is not None
            or launch_info is not None
            or list(pair_seeds) != expected_smoke
            or calls_per_arm_pair < 1
            or calls_per_arm_pair > 8
            or expected_smoke[0] in official_seed_sets
        ):
            raise ValueError("smoke design differs from its isolated seed domain")
    else:
        raise ValueError("unknown test mode")

    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        launch_binding = None
        source_bundle: list[dict[str, str]] = []
        if launch is not None:
            write_json_exclusive(run_dir / "launch_record.json", launch)
            launch_binding = {
                "file": "launch_record.json",
                "file_sha256": file_sha256(run_dir / "launch_record.json"),
                "launch_sha256": launch["launch_sha256"],
                "authorization_sha256": launch["authorization_sha256"],
            }
            source_bundle = copy_official_bundle(
                repo_root=repo_root,
                run_dir=run_dir,
                launch=launch,
            )
        registry = prior_split_registry(
            repo_root=repo_root,
            mode=mode,
            validation=(
                launch_info["validation"] if launch_info is not None else None
            ),
        )
        write_json_exclusive(run_dir / "prior_split_registry.json", registry)
        manifest_payload = {
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
            "launch": launch_binding,
            "source_bundle": source_bundle,
            "prior_split_registry_sha256": registry["registry_sha256"],
            "test_design": {
                "targets": list(TARGETS),
                "pair_seeds": list(pair_seeds),
                "arms": list(ARMS),
                "calls_per_arm_pair": calls_per_arm_pair,
                "candidate_pool_size": 16,
                "checkpoints": [
                    checkpoint
                    for checkpoint in CHECKPOINTS
                    if checkpoint <= calls_per_arm_pair
                ],
                "success_stopping_rule": False,
                "counter_rng_phase": (
                    "test" if mode == OFFICIAL_MODE else "smoke_test"
                ),
            },
            "model": (
                {
                    "binding_sha256": launch_info["model_binding"][
                        "binding_sha256"
                    ],
                    "ensemble_model_id": launch_info["model_commitment"][
                        "ensemble_model_id"
                    ],
                    "ensemble_file_sha256": launch_info["model_commitment"][
                        "ensemble_file_sha256"
                    ],
                    "member_checkpoint_sha256": launch_info["ensemble_info"][
                        "member_checkpoint_sha256"
                    ],
                    "ranker_source_sha256": launch_info["model_commitment"][
                        "ranker_source_sha256"
                    ],
                    "cpu_only_deterministic": True,
                }
                if launch_info is not None
                else {
                    "fixture": "sha256_outcome_free_score_v1",
                    "required_partizan_pushed_commit_sha": (
                        FROZEN_PARTIZAN_COMMIT
                    ),
                    "cpu_only_deterministic": True,
                }
            ),
            "resource_limits": (
                launch["resource_limits"] if launch is not None else None
            ),
            "paper_evidence": False,
        }
        manifest = hashed_record(manifest_payload, "manifest_sha256")
        write_json_exclusive(run_dir / "manifest.json", manifest)
        (
            streams,
            inference,
            gate,
            final_proposal_sha,
            final_event_sha,
        ) = generate_test_ledgers(
            run_dir=run_dir,
            mode=mode,
            pair_seeds=pair_seeds,
            calls_per_arm_pair=calls_per_arm_pair,
            ranker=ranker,
            registry=registry,
            protocol=protocol,
        )
        write_json_exclusive(run_dir / "stream_metrics.json", streams)
        write_json_exclusive(run_dir / "inference.json", inference)
        write_json_exclusive(run_dir / "learned_advantage_gate.json", gate)
        elapsed = time.monotonic() - started
        directory_bytes = run_directory_size(run_dir)
        rss = 0 if mode == SMOKE_MODE else peak_rss_bytes()
        if mode == OFFICIAL_MODE:
            limits = protocol["resource_gate"]
            if (
                elapsed > limits["generation_wall_seconds"]
                or directory_bytes > limits["run_directory_bytes"]
                or rss > limits["peak_resident_memory_bytes"]
            ):
                raise OSError("official test exceeded a frozen resource limit")
        expected_events = len(TARGETS) * len(pair_seeds) * len(ARMS) * (
            calls_per_arm_pair
        )
        generation_payload = {
            "schema_version": GENERATION_SCHEMA,
            "status": (
                "AWAITING_INDEPENDENT_TEST_REPLAY"
                if mode == OFFICIAL_MODE
                else "SMOKE_ONLY_NOT_EVIDENCE"
            ),
            "mode": mode,
            "manifest_file_sha256": file_sha256(run_dir / "manifest.json"),
            "prior_split_registry_file_sha256": file_sha256(
                run_dir / "prior_split_registry.json"
            ),
            "proposal_file_sha256": file_sha256(
                run_dir / "proposal_decisions.jsonl"
            ),
            "event_file_sha256": file_sha256(run_dir / "events.jsonl"),
            "stream_metrics_file_sha256": file_sha256(
                run_dir / "stream_metrics.json"
            ),
            "inference_file_sha256": file_sha256(run_dir / "inference.json"),
            "gate_file_sha256": file_sha256(
                run_dir / "learned_advantage_gate.json"
            ),
            "proposal_count": expected_events,
            "event_count": expected_events,
            "exact_verifier_calls_consumed": expected_events,
            "raw_pool_candidate_count": expected_events * 16,
            "final_proposal_sha256": final_proposal_sha,
            "final_event_sha256": final_event_sha,
            "generation_wall_seconds": (
                0.0 if mode == SMOKE_MODE else elapsed
            ),
            "run_directory_bytes_before_marker": directory_bytes,
            "peak_resident_memory_bytes": rss,
            "timing_suppressed_for_deterministic_smoke": mode == SMOKE_MODE,
            "test_outcomes_sealed_from_proposal_and_ranking": True,
            "scientific_gate_pending_independent_replay": True,
            "paper_evidence": False,
        }
        generation = hashed_record(generation_payload, "generation_sha256")
        write_json_exclusive(run_dir / "GENERATION_COMPLETE.json", generation)
        return generation
    except BaseException as error:
        failure_payload = {
            "schema_version": f"{SCHEMA}.generation_failure",
            "status": "INCOMPLETE_FAIL",
            "mode": mode,
            "error_type": type(error).__name__,
            "error": str(error),
            "resume_authorized": False,
            "paper_evidence": False,
        }
        try:
            write_json_exclusive(
                run_dir / "FAILURE.json",
                hashed_record(failure_payload, "failure_sha256"),
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
        if args.launch_record is not None:
            raise SystemExit("smoke mode cannot consume an official launch")
        if args.output is None:
            raise SystemExit("smoke mode requires --output")
        run_dir = (
            args.output
            if args.output.is_absolute()
            else repo_root / args.output
        ).resolve()
        if not run_dir.name.startswith("smoke-"):
            raise SystemExit("smoke output basename must start with 'smoke-'")
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=SMOKE_MODE,
            protocol=protocol,
            pair_seeds=[smoke_seed(0)],
            calls_per_arm_pair=args.smoke_calls,
            ranker=smoke_ranker,
            launch=None,
            launch_info=None,
        )
    else:
        if args.launch_record is None:
            raise SystemExit(
                "official test requires a separate authorized one-time launch"
            )
        if args.output is not None:
            raise SystemExit("official test output is fixed by the launch")
        launch_path = (
            args.launch_record
            if args.launch_record.is_absolute()
            else repo_root / args.launch_record
        ).resolve()
        launch, launch_info = verify_launch(repo_root, launch_path, protocol)
        run_dir = (repo_root / launch["output_directory"]).resolve()
        test = protocol["splits"]["test"]
        generation = build_run(
            repo_root=repo_root,
            run_dir=run_dir,
            mode=OFFICIAL_MODE,
            protocol=protocol,
            pair_seeds=test["pair_seeds"],
            calls_per_arm_pair=test["verifier_calls_per_arm_pair"],
            ranker=launch_info["ranker"],
            launch=launch,
            launch_info=launch_info,
        )
    print(json.dumps(generation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
