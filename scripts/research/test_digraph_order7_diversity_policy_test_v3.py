#!/usr/bin/env python3
"""Smoke, determinism, and gate tests for the V3 held-out test."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import digraph_order7_diversity_policy_test_v3 as builder
import verify_digraph_order7_diversity_policy_test_v3 as verifier


REPO_ROOT = Path(__file__).resolve().parents[2]


class DiversityPolicyTestV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.protocol,
            cls.initialization,
            cls.validation_completion,
            cls.registry,
        ) = builder.frozen_sources(REPO_ROOT)

    def build_smoke(self, parent: Path, name: str, calls: int = 2) -> Path:
        run_dir = parent / name
        builder.build_run(
            repo_root=REPO_ROOT,
            run_dir=run_dir,
            mode=builder.SMOKE_MODE,
            pair_seeds=[builder.smoke_seed()],
            calls_per_arm_pair=calls,
            launch=None,
        )
        return run_dir

    def test_official_test_requires_one_time_launch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="partizan-v3-test-launch-") as tmp:
            run_dir = Path(tmp) / "official"
            with self.assertRaisesRegex(ValueError, "requires a one-time launch"):
                builder.build_run(
                    repo_root=REPO_ROOT,
                    run_dir=run_dir,
                    mode=builder.OFFICIAL_MODE,
                    pair_seeds=self.protocol["splits"]["test"]["pair_seeds"],
                    calls_per_arm_pair=2048,
                    launch=None,
                )
            self.assertFalse(run_dir.exists())

    def test_smoke_is_deterministic_and_independently_replays(self) -> None:
        with tempfile.TemporaryDirectory(prefix="partizan-v3-test-smoke-") as tmp:
            root = Path(tmp)
            first = self.build_smoke(root, "first")
            second = self.build_smoke(root, "second")
            for relative in (
                "manifest.json",
                "prior_split_registry.json",
                "initialization_manifest.json",
                "stream_metrics.json",
                "preliminary_report.json",
                "GENERATION_COMPLETE.json",
                "pairs/00/proposal_decisions.jsonl",
                "pairs/00/events.jsonl",
                "pairs/00/stream_metrics.json",
            ):
                self.assertEqual(
                    (first / relative).read_bytes(),
                    (second / relative).read_bytes(),
                    relative,
                )
            completion = verifier.replay(first, REPO_ROOT)
            self.assertEqual(completion["status"], "SMOKE_PASS_NOT_EVIDENCE")
            self.assertTrue(completion["independent_replay_pass"])
            self.assertEqual(completion["corruption_family_count"], 30)
            self.assertTrue(completion["strict_zero_denominator_rule"])
            inference = json.loads(
                (first / "independent_inference.json").read_bytes()
            )
            self.assertEqual(
                inference["quotient_noninferiority_to_equality"][
                    "zero_denominator_rule"
                ],
                "fail",
            )

    def test_smoke_uses_supported_test_initialization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="partizan-v3-test-support-") as tmp:
            run_dir = self.build_smoke(Path(tmp), "support", calls=1)
            first_event = json.loads(
                (run_dir / "pairs/00/events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(first_event["structural_filter"]["tier_index"], 0)
            for target in builder.TARGETS:
                row = self.initialization["initializations"]["test"][target][0]
                self.assertGreaterEqual(
                    row["weakly_connected_nonprior_candidate_neighbor_count"],
                    32,
                )

    def test_zero_denominator_fails_instead_of_becoming_one(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["primary_analysis"]["interval"]["resamples"] = 16
        protocol["primary_analysis"]["sign_flip"]["maximum_assignments"] = 64
        streams = []
        for target in builder.TARGETS:
            for arm in builder.ARMS:
                streams.append(
                    {
                        "target": target,
                        "pair_seed": 1,
                        "arm": arm,
                        "quotient_unique_discoveries": 0,
                        "literal_game_unique_discoveries": (
                            1 if arm == builder.ARMS[2] else 0
                        ),
                        "descriptor_cells": [],
                        "transition_class_counts": {},
                    }
                )
        inference = verifier.independent_inference(streams, protocol)
        gate = verifier.independent_gate(streams, inference, protocol)
        quotient = inference["quotient_noninferiority_to_equality"]
        self.assertFalse(quotient["ratio_defined"])
        self.assertIsNone(quotient["ratio_point_estimate"])
        self.assertEqual(quotient["bootstrap_undefined_denominator_count"], 16)
        self.assertFalse(gate["checks"]["quotient_noninferiority_point"])
        self.assertFalse(gate["checks"]["quotient_noninferiority_interval"])
        self.assertFalse(
            gate["checks"][
                "nonzero_quotient_and_literal_support_every_arm_and_target"
            ]
        )
        self.assertFalse(
            gate["all_scientific_checks_pass_before_independent_replay"]
        )


if __name__ == "__main__":
    unittest.main()
