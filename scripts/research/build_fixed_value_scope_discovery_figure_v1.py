#!/usr/bin/env python3
"""Render the Domineering prefix-discovery figure from validated authorities."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from reportlab.pdfgen import canvas

from fixed_value_scope_protocol_v1 import artifact_sha256


DEFAULT_SOURCE = Path(
    "output/research/fixed-value-scope-v1/validation-v1/"
    "DISCOVERY_CURVES_AUTHORITY_V1.json"
)
DEFAULT_TERMINAL = Path(
    "output/research/fixed-value-scope-v1/validation-v1/"
    "VALIDATION_RESULT_AUTHORITY_V1.json"
)
DEFAULT_OUTPUT = Path(
    "docs/paper/neurips_2026/figures/fig_domineering_discovery_curves.pdf"
)
POLICIES = (
    "uniform_random_without_replacement",
    "neural_equality_only",
    "neural_equality_plus_ruleset_novelty",
)
LABELS = ("Random", "Equality", "Eq. + novelty")
COLORS = ("#94a3b8", "#1d4ed8", "#c2410c")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_authority(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if value.get("artifact_sha256") != artifact_sha256(value):
        raise ValueError(f"authority hash differs: {path}")
    return value


def rgb(value: str) -> tuple[float, float, float]:
    value = value.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def render(curves: dict[str, Any], output: Path) -> None:
    width, height = 504, 180
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(
        str(output), pagesize=(width, height), pageCompression=1, invariant=1
    )
    pdf.setTitle("Domineering discovery across exact-verifier budgets")
    pdf.setAuthor("Partizan")
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    dark = rgb("#0f172a")
    muted = rgb("#475569")
    grid = rgb("#cbd5e1")
    pdf.setFillColorRGB(*dark)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(18, 164, "DOMINEERING: 12 VALUES, 3 ACQUISITION SEEDS")

    budgets = [int(value) for value in curves["prefix_budgets"]]
    rows = {(row["policy_id"], int(row["budget"])): row for row in curves["curve_rows"]}

    # Left panel: cumulative certified ruleset quotients.
    left_x, left_y, left_w, left_h = 42, 40, 270, 94
    pdf.setFillColorRGB(*dark)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(18, 144, "Certified player-preserving quotients")
    for tick in (0, 100, 200, 300, 400):
        y = left_y + left_h * tick / 420
        pdf.setStrokeColorRGB(*grid)
        pdf.setLineWidth(0.35)
        pdf.line(left_x, y, left_x + left_w, y)
        pdf.setFillColorRGB(*muted)
        pdf.setFont("Helvetica", 6.2)
        pdf.drawRightString(left_x - 5, y - 2, str(tick))
    x_values = [left_x + index * left_w / (len(budgets) - 1) for index in range(len(budgets))]
    for x, budget in zip(x_values, budgets):
        pdf.setFillColorRGB(*muted)
        pdf.setFont("Helvetica", 6.2)
        pdf.drawCentredString(x, left_y - 10, f"{budget:,}")
    for policy, label, color in zip(POLICIES, LABELS, COLORS):
        points = [
            (x, left_y + left_h * rows[(policy, budget)]["mean_certified_ruleset_quotients"] / 420)
            for x, budget in zip(x_values, budgets)
        ]
        pdf.setStrokeColorRGB(*rgb(color))
        pdf.setFillColorRGB(*rgb(color))
        pdf.setLineWidth(1.45)
        for first, second in zip(points, points[1:]):
            pdf.line(first[0], first[1], second[0], second[1])
        for x, y in points:
            pdf.circle(x, y, 2.25, fill=1, stroke=0)
    pdf.setFillColorRGB(*muted)
    pdf.setFont("Helvetica", 6.4)
    pdf.drawCentredString(left_x + left_w / 2, 16, "Exact-verifier calls per target-policy-seed")

    # Legend above the left panel.
    legend_x = 102
    legend_y = 127
    for index, (label, color) in enumerate(zip(LABELS, COLORS)):
        x = legend_x + index * 66
        pdf.setStrokeColorRGB(*rgb(color))
        pdf.setLineWidth(1.5)
        pdf.line(x, legend_y, x + 12, legend_y)
        pdf.setFillColorRGB(*rgb(color))
        pdf.circle(x + 6, legend_y, 2, fill=1, stroke=0)
        pdf.setFillColorRGB(*muted)
        pdf.setFont("Helvetica", 6.4)
        pdf.drawString(x + 15, legend_y - 2.2, label)

    # Right panel: paired novelty gain with target-bootstrap intervals.
    right_x, right_y, right_w, right_h = 350, 40, 136, 94
    pdf.setFillColorRGB(*dark)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(337, 144, "Novelty - equality")
    for tick in (0, 2, 4, 6):
        y = right_y + right_h * tick / 7
        pdf.setStrokeColorRGB(*grid)
        pdf.setLineWidth(0.35 if tick else 0.8)
        pdf.line(right_x, y, right_x + right_w, y)
        pdf.setFillColorRGB(*muted)
        pdf.setFont("Helvetica", 6.2)
        pdf.drawRightString(right_x - 5, y - 2, str(tick))
    right_xs = [right_x + index * right_w / (len(budgets) - 1) for index in range(len(budgets))]
    effect_points = []
    for x, budget in zip(right_xs, budgets):
        effect = curves["effects"][str(budget)]["novelty_minus_equality_ruleset_quotients"]
        low, high = effect["bootstrap_interval"]
        estimate = effect["estimate"]
        y = right_y + right_h * estimate / 7
        low_y = right_y + right_h * low / 7
        high_y = right_y + right_h * high / 7
        pdf.setStrokeColorRGB(*rgb("#c2410c"))
        pdf.setLineWidth(0.8)
        pdf.line(x, low_y, x, high_y)
        pdf.line(x - 2.5, low_y, x + 2.5, low_y)
        pdf.line(x - 2.5, high_y, x + 2.5, high_y)
        pdf.setFillColorRGB(*rgb("#c2410c"))
        pdf.circle(x, y, 2.6, fill=1, stroke=0)
        effect_points.append((x, y))
        pdf.setFillColorRGB(*muted)
        pdf.setFont("Helvetica", 5.8)
        pdf.drawCentredString(x, right_y - 10, f"{budget:,}")
    pdf.setStrokeColorRGB(*rgb("#c2410c"))
    pdf.setLineWidth(1.1)
    for first, second in zip(effect_points, effect_points[1:]):
        pdf.line(first[0], first[1], second[0], second[1])
    pdf.setFillColorRGB(*muted)
    pdf.setFont("Helvetica", 6.2)
    pdf.drawCentredString(right_x + right_w / 2, 16, "Calls (95% target bootstrap)")

    pdf.setFillColorRGB(*muted)
    pdf.setFont("Helvetica", 6)
    pdf.drawRightString(486, 164, "Frozen-event secondary analysis")
    pdf.showPage()
    pdf.save()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--terminal", type=Path, default=DEFAULT_TERMINAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    curves = load_authority(args.source)
    terminal = load_authority(args.terminal)
    if curves["status"] != "PASS":
        raise ValueError("discovery-curve authority did not pass")
    if terminal["status"] != "VALIDATION_COMPLETE":
        raise ValueError("terminal validation is incomplete")
    if terminal["discovery_curves_authority_artifact_sha256"] != curves["artifact_sha256"]:
        raise ValueError("terminal authority does not bind curve authority")
    render(curves, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": file_sha256(args.output),
                "source_authority": curves["artifact_sha256"],
                "terminal_authority": terminal["artifact_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
