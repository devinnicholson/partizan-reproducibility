#!/usr/bin/env python3
"""Smoke and contract tests for the V3 support validation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import digraph_order7_diversity_policy_validation_v3 as builder
import verify_digraph_order7_diversity_policy_validation_v3 as verifier


REPO_ROOT = Path(__file__).resolve().parents[2]


class DiversityPolicyValidationV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.protocol,
            cls.initialization,
            cls.registry,
        ) = builder.frozen_sources(REPO_ROOT)

    def build_smoke(self, parent: Path, name: str) -> Path:
        run_dir = parent / name
        builder.build_run(
            repo_root=REPO_ROOT,
            run_dir=run_dir,
            mode=builder.SMOKE_MODE,
            pair_seeds=[builder.smoke_seed()],
            calls_per_arm_pair=2,
            launch=None,
        )
        return run_dir

    def test_initializations_are_paired_supported_and_quarantined(self) -> None:
        candidates = set(self.registry["candidate_sha256"])
        quotients = set(self.registry["quotient_sha256"])
        for split, count in (("validation", 4), ("test", 12)):
            for target in builder.TARGETS:
                rows = self.initialization["initializations"][split][target]
                self.assertEqual(len(rows), count)
                for row in rows:
                    self.assertGreaterEqual(
                        row[
                            "weakly_connected_nonprior_candidate_neighbor_count"
                        ],
                        32,
                    )
                    self.assertIn(row["candidate_sha256"], candidates)
                    self.assertIn(row["quotient_sha256"], quotients)
                    self.assertTrue(row["shared_across_arms"])
                    self.assertFalse(row["counts_as_discovery"])
                    self.assertFalse(row["selected_using_semantic_outcome"])

    def test_validation_and_test_assignments_are_disjoint(self) -> None:
        validation = {
            row["initialization_id"]
            for rows in self.initialization["initializations"]["validation"].values()
            for row in rows
        }
        test = {
            row["initialization_id"]
            for rows in self.initialization["initializations"]["test"].values()
            for row in rows
        }
        self.assertTrue(validation.isdisjoint(test))
        self.assertEqual(len(validation), 12)
        self.assertEqual(len(test), 36)

    def test_official_validation_requires_launch_before_directory(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="partizan-v3-validation-launch-"
        ) as tmp:
            run_dir = Path(tmp) / "official"
            with self.assertRaisesRegex(ValueError, "requires a launch"):
                builder.build_run(
                    repo_root=REPO_ROOT,
                    run_dir=run_dir,
                    mode=builder.OFFICIAL_MODE,
                    pair_seeds=self.protocol["splits"]["validation"][
                        "pair_seeds"
                    ],
                    calls_per_arm_pair=128,
                    launch=None,
                )
            self.assertFalse(run_dir.exists())

    def test_smoke_is_deterministic_and_independently_replays(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="partizan-v3-validation-smoke-"
        ) as tmp:
            root = Path(tmp)
            first = self.build_smoke(root, "smoke-first")
            second = self.build_smoke(root, "smoke-second")
            for relative in (
                "manifest.json",
                "prior_split_registry.json",
                "initialization_manifest.json",
                "validation_stream_metrics.json",
                "validation_projection.json",
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
            self.assertEqual(
                completion["status"],
                "SMOKE_PASS_NOT_EVIDENCE",
            )
            self.assertTrue(completion["independent_replay_pass"])
            self.assertEqual(completion["corruption_family_count"], 30)
            self.assertFalse(completion["test_authorization_allowed"])

    def test_smoke_first_pools_escape_stage0_deadlock(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="partizan-v3-validation-support-"
        ) as tmp:
            run_dir = self.build_smoke(Path(tmp), "smoke-support")
            projection = json.loads(
                (run_dir / "validation_projection.json").read_bytes()
            )
            self.assertTrue(
                projection["checks"]["first_pool_tier_zero_for_every_stream"]
            )


if __name__ == "__main__":
    unittest.main()
