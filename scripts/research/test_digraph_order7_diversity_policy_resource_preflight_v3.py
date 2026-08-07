#!/usr/bin/env python3
"""Tests for the semantic-free V3 resource preflight."""

from __future__ import annotations

from pathlib import Path
import unittest

from digraph_derivation_certificate_v3 import object_sha256
import digraph_order7_diversity_policy_resource_preflight_v3 as preflight


REPO_ROOT = Path(__file__).resolve().parents[2]


class DiversityPolicyResourcePreflightV3Tests(unittest.TestCase):
    def test_report_is_deterministic_self_hashed_and_within_caps(self) -> None:
        first = preflight.build_report(REPO_ROOT)
        second = preflight.build_report(REPO_ROOT)
        self.assertEqual(first, second)
        payload = dict(first)
        supplied = payload.pop("report_sha256")
        self.assertEqual(supplied, object_sha256(payload))
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["projection"]["status"], "PASS")
        self.assertFalse(first["semantic_test_evaluation_performed"])
        self.assertEqual(
            first["method"]["new_exact_verifier_calls_performed"],
            0,
        )
        self.assertFalse(
            first["method"]["test_seeds_or_test_initializations_executed"]
        )

    def test_projection_binds_equal_v2_and_v3_test_event_budgets(self) -> None:
        report = preflight.build_report(REPO_ROOT)
        inputs = report["inputs"]
        self.assertEqual(inputs["total_test_events"], 221184)
        self.assertEqual(
            inputs["total_test_events"],
            inputs["v2_test_events"],
        )
        self.assertTrue(
            report["projection"]["checks"][
                "same_event_budget_as_completed_v2_test"
            ]
        )


if __name__ == "__main__":
    unittest.main()
