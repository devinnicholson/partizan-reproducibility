#!/usr/bin/env python3
"""Build a frozen structural-descriptor atlas from the order-7 held-out ledger.

The population is quotient-unique: for each target, the first accepted
held-out event for every graph quotient is retained.  This matches the union
population reported by the preregistered experiment and prevents rediscovery
across streams from changing the descriptor distributions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "partizan.fixed_value_descriptor_atlas.v1"
TARGET_ORDER = ("0", "*", "{0|1}")
TARGET_LABELS = {"0": "0", "*": "*", "{0|1}": "1/2"}
DESCRIPTORS = (
    ("graph_arc_count", "Directed arcs"),
    ("blue_vertex_count", "Blue vertices"),
    ("red_vertex_count", "Red vertices"),
    ("distinct_game_tree_node_count", "Literal-game nodes"),
    ("distinct_game_tree_edge_count", "Literal-game edges"),
    ("game_birthday", "Game birthday"),
    ("root_dominated_option_count", "Dominated root options"),
    ("root_reversible_option_count", "Reversible root options"),
    ("root_simplification_count", "Root simplifications"),
)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        .encode("utf-8")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quantile_type7(sorted_values: list[int], probability: float) -> int | float:
    """Return the R type-7/sample-linear quantile, with exact integer cleanup."""
    if not sorted_values:
        raise ValueError("quantile requires at least one value")
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    value = sorted_values[lower] + weight * (
        sorted_values[upper] - sorted_values[lower]
    )
    rounded = round(value, 6)
    return int(rounded) if float(rounded).is_integer() else rounded


def summarize(values: Iterable[int]) -> dict[str, int | float]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty descriptor")
    return {
        "minimum": ordered[0],
        "q1": quantile_type7(ordered, 0.25),
        "median": quantile_type7(ordered, 0.5),
        "q3": quantile_type7(ordered, 0.75),
        "maximum": ordered[-1],
        "distinct_values": len(set(ordered)),
    }


def accepted_heldout(event: dict[str, Any]) -> bool:
    decision = event.get("exact_decision") or {}
    retention = event.get("retention") or {}
    return bool(
        event.get("target") in TARGET_ORDER
        and event.get("weakly_connected") is True
        and event.get("leakage_collision") is False
        and decision.get("equal") is True
        and event.get("quotient")
        and event.get("measurements")
        and retention.get("inserted") is True
    )


def load_representatives(
    events_path: Path,
) -> tuple[dict[str, dict[str, dict[str, Any]]], int, str]:
    representatives: dict[str, dict[str, dict[str, Any]]] = {
        target: {} for target in TARGET_ORDER
    }
    event_count = 0
    ledger_digest = hashlib.sha256()

    with events_path.open("rb") as handle:
        for expected_index, raw_line in enumerate(handle):
            ledger_digest.update(raw_line)
            event = json.loads(raw_line)
            event_count += 1
            if event.get("global_event_index") != expected_index:
                raise ValueError(
                    "non-contiguous global_event_index at line "
                    f"{expected_index + 1}"
                )
            if not accepted_heldout(event):
                continue

            target = event["target"]
            quotient_sha = event["quotient"]["quotient_sha256"]
            measurements = event["measurements"]
            missing = [key for key, _ in DESCRIPTORS if key not in measurements]
            if missing:
                raise ValueError(
                    f"event {expected_index} lacks descriptors: {', '.join(missing)}"
                )

            representatives[target].setdefault(
                quotient_sha,
                {
                    "candidate_sha256": event["candidate_sha256"],
                    "descriptor_cell": measurements["descriptor_cell"],
                    "descriptors": {
                        key: measurements[key] for key, _ in DESCRIPTORS
                    },
                    "first_global_event_index": expected_index,
                    "literal_game_sha256": event["exact_decision"][
                        "candidate_root_game_sha256"
                    ],
                    "quotient_sha256": quotient_sha,
                },
            )

    return representatives, event_count, ledger_digest.hexdigest()


def representative_set_sha256(
    representatives: dict[str, dict[str, dict[str, Any]]],
) -> str:
    ordered = []
    for target in TARGET_ORDER:
        for quotient_sha in sorted(representatives[target]):
            ordered.append(
                {
                    "target": target,
                    **representatives[target][quotient_sha],
                }
            )
    return hashlib.sha256(canonical_bytes(ordered)).hexdigest()


def build_atlas(run_dir: Path) -> dict[str, Any]:
    events_path = run_dir / "events.jsonl"
    summary_path = run_dir / "summary.json"
    verification_path = run_dir / "independent_verification.json"
    run_complete_path = run_dir / "RUN_COMPLETE.json"

    for path in (events_path, summary_path, verification_path, run_complete_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    independent_verification = json.loads(
        verification_path.read_text(encoding="utf-8")
    )
    run_complete = json.loads(run_complete_path.read_text(encoding="utf-8"))
    representatives, event_count, events_sha = load_representatives(events_path)

    if event_count != summary["event_count"]:
        raise ValueError(
            f"ledger has {event_count} events; summary reports {summary['event_count']}"
        )

    targets: dict[str, Any] = {}
    total_representatives = 0
    for target in TARGET_ORDER:
        records = list(representatives[target].values())
        observed_count = len(records)
        expected_count = summary["target_unions"][target]["counts"][
            "heldout_quotient_unique_representatives"
        ]
        if observed_count != expected_count:
            raise ValueError(
                f"target {target}: reconstructed {observed_count} quotient-unique "
                f"representatives; summary reports {expected_count}"
            )
        total_representatives += observed_count
        cells = {
            " | ".join(record["descriptor_cell"])
            for record in records
        }
        targets[target] = {
            "display_label": TARGET_LABELS[target],
            "quotient_unique_representatives": observed_count,
            "literal_games": summary["target_unions"][target]["counts"][
                "heldout_literal_game_digests"
            ],
            "occupied_descriptor_cells": len(cells),
            "descriptor_summaries": {
                key: summarize(record["descriptors"][key] for record in records)
                for key, _ in DESCRIPTORS
            },
        }

    atlas = {
        "schema_version": SCHEMA_VERSION,
        "analysis_status": "descriptive_secondary_analysis",
        "claim_boundary": (
            "Observed structural variation among quotient-unique held-out exact "
            "matches; no fiber-size, prevalence, aesthetic, or human-preference "
            "claim."
        ),
        "population_rule": (
            "For each target, retain the first accepted held-out event for every "
            "distinct graph-quotient SHA-256."
        ),
        "quantile_definition": (
            "Sample quantiles use linear interpolation at (n-1)p (type 7)."
        ),
        "source": {
            "run_directory": run_dir.name,
            "events_path": "events.jsonl",
            "events_sha256": events_sha,
            "summary_sha256": sha256_file(summary_path),
            "summary_declared_sha256": summary["summary_sha256"],
            "independent_verification_sha256": sha256_file(verification_path),
            "run_complete_sha256": sha256_file(run_complete_path),
            "event_count": event_count,
            "independent_replay_pass": bool(
                independent_verification.get("overall_pass")
                or independent_verification.get("verification_pass")
                or independent_verification.get("status") == "PASS"
            ),
            "run_complete_status": run_complete.get("status"),
        },
        "descriptor_definitions": [
            {"key": key, "label": label} for key, label in DESCRIPTORS
        ],
        "total_quotient_unique_representatives": total_representatives,
        "representative_set_sha256": representative_set_sha256(representatives),
        "targets": targets,
    }
    atlas["atlas_sha256"] = hashlib.sha256(canonical_bytes(atlas)).hexdigest()
    return atlas


def markdown_report(atlas: dict[str, Any]) -> str:
    rows = []
    for target in TARGET_ORDER:
        data = atlas["targets"][target]
        descriptors = data["descriptor_summaries"]

        def span(key: str) -> str:
            values = descriptors[key]
            return (
                f"{values['minimum']}–{values['median']}–{values['maximum']}"
            )

        rows.append(
            "| {label} | {n:,} | {arcs} | {nodes} | {birthday} | {simp} | "
            "{cells} |".format(
                label=data["display_label"],
                n=data["quotient_unique_representatives"],
                arcs=span("graph_arc_count"),
                nodes=span("distinct_game_tree_node_count"),
                birthday=span("game_birthday"),
                simp=span("root_simplification_count"),
                cells=data["occupied_descriptor_cells"],
            )
        )

    return "\n".join(
        [
            "# Fixed-Value Structural Descriptor Atlas v1",
            "",
            "This is a descriptive secondary analysis of the frozen held-out "
            "experiment. Each target population contains the first accepted "
            "held-out representative of every distinct graph quotient.",
            "",
            "| Target | Quotients | Arcs min–median–max | Literal nodes "
            "min–median–max | Birthday min–median–max | Root simplifications "
            "min–median–max | Occupied cells |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Population: {atlas['total_quotient_unique_representatives']:,} "
            "quotient-unique certified representatives.",
            "",
            f"Representative-set SHA-256: "
            f"`{atlas['representative_set_sha256']}`",
            "",
            f"Atlas SHA-256: `{atlas['atlas_sha256']}`",
            "",
            "Claim boundary: " + atlas["claim_boundary"],
            "",
        ]
    )


def tex_number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", "{,}")
    return f"{value:g}"


def figure_tex(atlas: dict[str, Any]) -> str:
    panels = (
        ("graph_arc_count", "directed arcs"),
        ("distinct_game_tree_node_count", "literal nodes"),
        ("game_birthday", "birthday"),
        ("root_simplification_count", "root simplifications"),
    )
    colors = {"0": "blue", "*": "amber", "{0|1}": "green"}
    target_y = {"0": 1.30, "*": 0.72, "{0|1}": 0.14}
    lines = [
        r"\documentclass[tikz,border=3pt]{standalone}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{lmodern}",
        r"\usepackage{xcolor}",
        r"\usetikzlibrary{calc}",
        r"\definecolor{ink}{HTML}{17212B}",
        r"\definecolor{muted}{HTML}{66717B}",
        r"\definecolor{grid}{HTML}{D7DEE4}",
        r"\definecolor{blue}{HTML}{2F6B8A}",
        r"\definecolor{amber}{HTML}{C76B13}",
        r"\definecolor{green}{HTML}{177A58}",
        r"\begin{document}",
        r"\begin{tikzpicture}[font=\sffamily,x=1cm,y=1cm]",
        rf"% atlas_sha256={atlas['atlas_sha256']}",
    ]
    panel_width = 2.33
    gap = 0.34
    for panel_index, (key, label) in enumerate(panels):
        x0 = panel_index * (panel_width + gap)
        all_summaries = [
            atlas["targets"][target]["descriptor_summaries"][key]
            for target in TARGET_ORDER
        ]
        global_min = min(values["minimum"] for values in all_summaries)
        global_max = max(values["maximum"] for values in all_summaries)
        span = max(1.0, float(global_max - global_min))
        lines.extend(
            [
                rf"\node[anchor=west,font=\bfseries\fontsize{{7.2}}{{8.2}}\selectfont,"
                rf"text=ink] at ({x0:.3f},1.91) {{{label}}};",
                rf"\draw[grid,line width=.45pt] ({x0:.3f},0) rectangle "
                rf"({x0 + panel_width:.3f},1.68);",
            ]
        )
        for target in TARGET_ORDER:
            summary = atlas["targets"][target]["descriptor_summaries"][key]

            def x_position(value: int | float) -> float:
                return x0 + 0.16 + (float(value) - global_min) / span * (
                    panel_width - 0.32
                )

            y = target_y[target]
            color = colors[target]
            lines.extend(
                [
                    rf"\draw[{color}!55,line width=.7pt] "
                    rf"({x_position(summary['minimum']):.3f},{y:.3f}) -- "
                    rf"({x_position(summary['maximum']):.3f},{y:.3f});",
                    rf"\draw[{color},line width=3.2pt,line cap=round] "
                    rf"({x_position(summary['q1']):.3f},{y:.3f}) -- "
                    rf"({x_position(summary['q3']):.3f},{y:.3f});",
                    rf"\fill[{color}] "
                    rf"({x_position(summary['median']):.3f},{y:.3f}) circle (1.25pt);",
                ]
            )
        lines.extend(
            [
                rf"\node[anchor=north west,font=\fontsize{{5.6}}{{6.3}}\selectfont,"
                rf"text=muted] at ({x0:.3f},-.04) "
                rf"{{{tex_number(global_min)}}};",
                rf"\node[anchor=north east,font=\fontsize{{5.6}}{{6.3}}\selectfont,"
                rf"text=muted] at ({x0 + panel_width:.3f},-.04) "
                rf"{{{tex_number(global_max)}}};",
            ]
        )
    for target in TARGET_ORDER:
        y = target_y[target]
        color = colors[target]
        label = atlas["targets"][target]["display_label"]
        n = atlas["targets"][target]["quotient_unique_representatives"]
        lines.append(
            rf"\node[anchor=east,font=\bfseries\fontsize{{6.5}}{{7.4}}\selectfont,"
            rf"text={color}] at (-.12,{y:.3f}) {{$\,{label}$}};"
        )
        lines.append(
            rf"\node[anchor=west,font=\fontsize{{5.5}}{{6.2}}\selectfont,text=muted] "
            rf"at (10.82,{y:.3f}) {{$n={n:,}$}};"
        )
    lines.extend(
        [
            r"\draw[muted!55,line width=.6pt] (7.05,-.48) -- (7.62,-.48);",
            r"\draw[ink,line width=3.2pt,line cap=round] (7.20,-.48) -- (7.47,-.48);",
            r"\fill[ink] (7.335,-.48) circle (1.25pt);",
            r"\node[anchor=west,font=\fontsize{5.7}{6.4}\selectfont,text=muted] "
            r"at (7.72,-.48) {range / IQR / median};",
            r"\end{tikzpicture}",
            r"\end{document}",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--figure-tex", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    atlas = build_atlas(args.run_dir)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(atlas, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(markdown_report(atlas), encoding="utf-8")
    if args.figure_tex:
        args.figure_tex.parent.mkdir(parents=True, exist_ok=True)
        args.figure_tex.write_text(figure_tex(atlas), encoding="utf-8")
    print(
        json.dumps(
            {
                "atlas_sha256": atlas["atlas_sha256"],
                "output_json": str(args.output_json),
                "representatives": atlas["total_quotient_unique_representatives"],
                "status": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
