#!/usr/bin/env python3
"""Read-only v2 replay of the three order-6 order-7 launch parents."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from digraph_ledger_verifier_v2 import (
    canonical_json_bytes,
    object_sha256,
    verify_candidate_evidence,
    verify_target_artifact,
)


EXPECTED_FILES = {
    "manifest.json": "07629279474d48c4222a743947ee69f766d256554c5ab1fe1e3c0e91608c8dcf",
    "events.jsonl": "3943fbd9fa9e8308872d385ef0f74a31edf36414da4d5e6880626eb406e22cd3",
    "summary.json": "c373ee0c67cc1c10d5fabed9faf8911551c08c4ae7e851dd5659d9278a11b369",
    "independent_replay.json": "3cc153d4a8d52d3cda6fcea4e821be6becd9254a5cf62b1fbeabb5ac28561605",
    "negative_tests.json": "5cde10b11132ab87f878e2bad3ce1893a885d89e66bc74551fda67c071b4a351",
    "RUN_COMPLETE.json": "60c4a25f7f2a9c3c443af659c146d30f73a3ca8bdfd673dfcf168bddfb83234c",
}
EXPECTED_MANIFEST_SHA256 = (
    "9e8d78ec958aac4008ded59fb5f65ba3e319570503f298212f3ab7fafc2942bb"
)
EXPECTED_SUMMARY_SHA256 = (
    "67cb2de42fcfb75ba5a78dc0e2b11bc196ba2438b8d1e18344acee803c27bc99"
)
EXPECTED_REPLAY_SHA256 = (
    "0e494771b40b27bb7278e26652cce4cd6f3d266422510f696f6124837f2e897c"
)

CONTROL_BINDINGS: dict[int, dict[str, str]] = {
    338: {
        "target": "0",
        "event_sha256": "139192ec4cf01b2f02610251fe582049a6c07c5fe0780b7d9572e0d45cd85aeb",
        "candidate_sha256": "e03503499a331913704cdaf663c9a184ad3950065b6ab505b406bc2f5abf83da",
        "quotient_sha256": "d57c656db3de1302d098e1d6911aa1a7ff0cbff9716d04d837fad2abb5e3bd9a",
        "literal_game_sha256": "b2f4f1a75c9a372f4e8a255e10795f043beda975d6b55aea71e56803b895eb66",
    },
    41065: {
        "target": "*",
        "event_sha256": "1930813c8b341d6341657076dd95e8ceb5ec123b7fd120cdfe263dd9a8a34a35",
        "candidate_sha256": "88817ee933eb1b5286670e99a77b5547327ae1bbe2260a2ec77bc6ff31ca6056",
        "quotient_sha256": "136941846da7c360629d5ad33cc667ca26db9efffaf8c1c3ecf1e75e58754046",
        "literal_game_sha256": "b1e7d2bc7f66531d2b0523763143faa9c18a385bf22506bc685aad5cdeffd447",
    },
    82835: {
        "target": "{0|1}",
        "event_sha256": "d0ff86e9258cbe3b626b9b759d3460547802ad8195a594da9f57a4f316f5342b",
        "candidate_sha256": "59f0d6de49ca1a34a9e56d6a326778f610abcfd81b82deaad6bef3572480cc81",
        "quotient_sha256": "225f3b8352212fe22cf0f06e6a1f6195eef18281aba22a1a488ef2672560f8de",
        "literal_game_sha256": "f249e4138d4305dbd96f60afd59c193ef96300ffdc01b99f089cd4276876f117",
    },
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def verify(run_dir: Path) -> dict[str, Any]:
    for name, expected in EXPECTED_FILES.items():
        observed = file_sha256(run_dir / name)
        if observed != expected:
            raise ValueError(f"frozen v2 {name} hash mismatch")

    manifest = load_json(run_dir / "manifest.json")
    summary = load_json(run_dir / "summary.json")
    replay = load_json(run_dir / "independent_replay.json")
    completion = load_json(run_dir / "RUN_COMPLETE.json")
    if manifest.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise ValueError("v2 manifest identity mismatch")
    if summary.get("summary_sha256") != EXPECTED_SUMMARY_SHA256:
        raise ValueError("v2 summary identity mismatch")
    if replay.get("report_sha256") != EXPECTED_REPLAY_SHA256:
        raise ValueError("v2 independent replay identity mismatch")
    if not completion.get("complete") or not replay.get("all_assertions_pass"):
        raise ValueError("v2 completion does not pass all checks")
    if (
        completion.get("final_calibration_go_decision", {}).get("decision")
        != "NO_GO"
    ):
        raise ValueError("v2 decision is not the frozen NO_GO")

    target_replays: dict[str, Any] = {}
    for target in ("0", "*", "{0|1}"):
        expected_target = manifest["targets"][target]
        reference = {
            "path": expected_target["sidecar_path"],
            "sha256": expected_target["artifact_sha256"],
        }
        valid, reason, target_replay = verify_target_artifact(
            target_label=target,
            artifact_reference=reference,
            sidecar_loader=lambda relative: (run_dir / relative).read_bytes(),
        )
        if not valid or target_replay is None:
            raise ValueError(f"v2 target {target} replay failed: {reason}")
        target_replays[target] = target_replay

    selected: dict[int, dict[str, Any]] = {}
    previous = "0" * 64
    events_path = run_dir / "events.jsonl"
    with events_path.open("rb") as handle:
        for expected_index, raw in enumerate(handle):
            if not raw.endswith(b"\n"):
                raise ValueError("v2 event ledger has unterminated row")
            event = json.loads(raw)
            if canonical_json_bytes(event) + b"\n" != raw:
                raise ValueError("v2 event row is not canonical")
            supplied = event.pop("event_sha256")
            if event.get("global_event_index") != expected_index:
                raise ValueError("v2 global event index mismatch")
            if event.get("previous_event_sha256") != previous:
                raise ValueError("v2 previous event hash mismatch")
            if object_sha256(event) != supplied:
                raise ValueError("v2 event hash mismatch")
            event["event_sha256"] = supplied
            previous = supplied
            if expected_index in CONTROL_BINDINGS:
                selected[expected_index] = event
            if expected_index >= max(CONTROL_BINDINGS):
                break

    if set(selected) != set(CONTROL_BINDINGS):
        raise ValueError("one or more frozen parent events are missing")

    controls: dict[str, Any] = {}
    for index, expected in CONTROL_BINDINGS.items():
        event = selected[index]
        target = expected["target"]
        if event["event_sha256"] != expected["event_sha256"]:
            raise ValueError(f"v2 {target} parent event hash mismatch")
        if event.get("target") != target:
            raise ValueError(f"v2 {target} parent target mismatch")
        if event.get("policy") != "seeded_unstructured_repertoire":
            raise ValueError(f"v2 {target} parent policy mismatch")
        if event.get("candidate_sha256") != expected["candidate_sha256"]:
            raise ValueError(f"v2 {target} candidate mismatch")
        if event["quotient"]["quotient_sha256"] != expected["quotient_sha256"]:
            raise ValueError(f"v2 {target} quotient mismatch")
        if (
            event["verifier"]["candidate_root_game_sha256"]
            != expected["literal_game_sha256"]
        ):
            raise ValueError(f"v2 {target} literal game mismatch")
        if not event["verifier"]["matched"] or event["accepted_sidecars"] is None:
            raise ValueError(f"v2 {target} parent is not retained exact evidence")
        valid, reason, candidate_replay = verify_candidate_evidence(
            candidate=event["candidate"],
            claimed_candidate_sha256=event["candidate_sha256"],
            claimed_quotient=event["quotient"],
            claimed_descriptors=event["measurements"],
            accepted_sidecars=event["accepted_sidecars"],
            expected_target_binding=target_replays[target].binding,
            sidecar_loader=lambda relative: (run_dir / relative).read_bytes(),
        )
        if not valid or candidate_replay is None:
            raise ValueError(f"v2 {target} parent evidence failed: {reason}")
        controls[target] = {
            "global_event_index": index,
            "event_sha256": event["event_sha256"],
            "candidate": event["candidate"],
            "candidate_sha256": candidate_replay.candidate_sha256,
            "quotient_sha256": candidate_replay.quotient_sha256,
            "literal_game_sha256": candidate_replay.candidate_root_game_sha256,
            "target_root_game_sha256": candidate_replay.target_root_game_sha256,
            "replay_valid": True,
        }

    return {
        "schema_version": "partizan.digraph_order7_parent_control_replay.v1",
        "v2_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "v2_events_file_sha256": EXPECTED_FILES["events.jsonl"],
        "chain_replayed_through_global_event_index": max(CONTROL_BINDINGS),
        "controls": controls,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = verify(args.run_dir.resolve())
    print(canonical_json_bytes(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
