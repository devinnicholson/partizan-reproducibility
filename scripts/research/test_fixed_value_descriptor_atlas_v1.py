#!/usr/bin/env python3
"""Unit tests for the frozen structural-descriptor atlas."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("fixed_value_descriptor_atlas_v1.py")
SPEC = importlib.util.spec_from_file_location("descriptor_atlas", MODULE_PATH)
assert SPEC and SPEC.loader
ATLAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ATLAS)


class DescriptorAtlasTests(unittest.TestCase):
    def test_type7_quantiles(self) -> None:
        values = [1, 2, 8, 10]
        self.assertEqual(ATLAS.quantile_type7(values, 0.25), 1.75)
        self.assertEqual(ATLAS.quantile_type7(values, 0.5), 5)
        self.assertEqual(ATLAS.quantile_type7(values, 0.75), 8.5)

    def test_summary_is_deterministic(self) -> None:
        self.assertEqual(
            ATLAS.summarize([3, 1, 3, 2]),
            {
                "minimum": 1,
                "q1": 1.75,
                "median": 2.5,
                "q3": 3,
                "maximum": 3,
                "distinct_values": 3,
            },
        )

    def test_acceptance_boundary(self) -> None:
        event = {
            "target": "0",
            "weakly_connected": True,
            "leakage_collision": False,
            "exact_decision": {"equal": True},
            "quotient": {"quotient_sha256": "q"},
            "measurements": {"graph_arc_count": 4},
            "retention": {"inserted": True},
        }
        self.assertTrue(ATLAS.accepted_heldout(event))
        event["leakage_collision"] = True
        self.assertFalse(ATLAS.accepted_heldout(event))


if __name__ == "__main__":
    unittest.main()
