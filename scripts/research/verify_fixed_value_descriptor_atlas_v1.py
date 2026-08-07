#!/usr/bin/env python3
"""Independently reconstruct and verify the fixed-value descriptor atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


TARGETS = ("0", "*", "{0|1}")
FIELDS = (
    "graph_arc_count",
    "blue_vertex_count",
    "red_vertex_count",
    "distinct_game_tree_node_count",
    "distinct_game_tree_edge_count",
    "game_birthday",
    "root_dominated_option_count",
    "root_reversible_option_count",
    "root_simplification_count",
)


def compact(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def percentile(ordered: list[int], p: float) -> int | float:
    offset = (len(ordered) - 1) * p
    lo = int(offset)
    hi = min(lo + 1, len(ordered) - 1)
    result = ordered[lo] * (hi - offset) + ordered[hi] * (offset - lo)
    result = round(result, 6)
    return int(result) if result.is_integer() else result


def stats(values: list[int]) -> dict[str, int | float]:
    ordered = sorted(values)
    return {
        "minimum": ordered[0],
        "q1": percentile(ordered, 0.25),
        "median": percentile(ordered, 0.5),
        "q3": percentile(ordered, 0.75),
        "maximum": ordered[-1],
        "distinct_values": len(frozenset(ordered)),
    }


def reconstruct(events_path: Path) -> tuple[dict[str, Any], int, str]:
    first_by_quotient: dict[str, dict[str, dict[str, Any]]] = {
        target: {} for target in TARGETS
    }
    ledger_hash = hashlib.sha256()
    count = 0
    with events_path.open("rb") as source:
        for line_number, raw in enumerate(source):
            ledger_hash.update(raw)
            record = json.loads(raw)
            count += 1
            if record["global_event_index"] != line_number:
                raise AssertionError(
                    f"event index mismatch at ledger line {line_number + 1}"
                )
            exact = record.get("exact_decision") or {}
            kept = record.get("retention") or {}
            if not (
                record.get("target") in TARGETS
                and record.get("weakly_connected") is True
                and record.get("leakage_collision") is False
                and exact.get("equal") is True
                and kept.get("inserted") is True
                and record.get("quotient")
                and record.get("measurements")
            ):
                continue
            target = record["target"]
            quotient = record["quotient"]["quotient_sha256"]
            measures = record["measurements"]
            first_by_quotient[target].setdefault(
                quotient,
                {
                    "candidate_sha256": record["candidate_sha256"],
                    "descriptor_cell": measures["descriptor_cell"],
                    "descriptors": {field: measures[field] for field in FIELDS},
                    "first_global_event_index": line_number,
                    "literal_game_sha256": exact["candidate_root_game_sha256"],
                    "quotient_sha256": quotient,
                },
            )
    return first_by_quotient, count, ledger_hash.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--atlas", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    atlas = json.loads(args.atlas.read_text(encoding="utf-8"))
    atlas_without_digest = dict(atlas)
    declared_atlas_digest = atlas_without_digest.pop("atlas_sha256")
    computed_atlas_digest = hashlib.sha256(compact(atlas_without_digest)).hexdigest()

    summary_path = args.run_dir / "summary.json"
    events_path = args.run_dir / "events.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    representatives, event_count, ledger_digest = reconstruct(events_path)

    checks: dict[str, bool] = {
        "atlas_self_hash": computed_atlas_digest == declared_atlas_digest,
        "event_count": event_count
        == summary["event_count"]
        == atlas["source"]["event_count"],
        "events_sha256": ledger_digest == atlas["source"]["events_sha256"],
        "summary_sha256": file_digest(summary_path)
        == atlas["source"]["summary_sha256"],
    }

    ordered_manifest = []
    for target in TARGETS:
        records = representatives[target]
        expected = summary["target_unions"][target]["counts"][
            "heldout_quotient_unique_representatives"
        ]
        checks[f"{target}:population"] = (
            len(records)
            == expected
            == atlas["targets"][target]["quotient_unique_representatives"]
        )
        cell_count = len(
            {tuple(record["descriptor_cell"]) for record in records.values()}
        )
        checks[f"{target}:descriptor_cells"] = (
            cell_count == atlas["targets"][target]["occupied_descriptor_cells"]
        )
        for field in FIELDS:
            reconstructed = stats(
                [record["descriptors"][field] for record in records.values()]
            )
            checks[f"{target}:{field}"] = (
                reconstructed
                == atlas["targets"][target]["descriptor_summaries"][field]
            )
        for quotient in sorted(records):
            ordered_manifest.append({"target": target, **records[quotient]})

    manifest_digest = hashlib.sha256(compact(ordered_manifest)).hexdigest()
    checks["representative_set_sha256"] = (
        manifest_digest == atlas["representative_set_sha256"]
    )
    checks["total_population"] = (
        sum(len(records) for records in representatives.values())
        == atlas["total_quotient_unique_representatives"]
    )

    failures = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": "partizan.fixed_value_descriptor_atlas.v1.verification",
        "atlas_sha256": declared_atlas_digest,
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
