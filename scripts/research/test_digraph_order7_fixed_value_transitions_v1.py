#!/usr/bin/env python3
"""Prelaunch tests using only registered Stage-0 graphs or synthetic records."""

from __future__ import annotations

import hashlib
import json
import random
import unittest
from pathlib import Path

import digraph_order7_fixed_value_transitions_v1 as generator
import verify_digraph_order7_fixed_value_transitions_v1 as verifier
from digraph_ledger_verifier_v3 import candidate_record


REPO_ROOT = Path(__file__).resolve().parents[2]


class FixedValueTransitionsV1Tests(unittest.TestCase):
    def test_preregistration_hash_is_frozen(self) -> None:
        data = (REPO_ROOT / generator.PREREGISTRATION).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), generator.PREREGISTRATION_SHA256)

    def test_budget_and_seed_schedule(self) -> None:
        self.assertEqual(generator.BASE_SEEDS, verifier.BASE_SEEDS)
        self.assertEqual(generator.BASE_SEEDS[0], 104_729)
        self.assertEqual(generator.BASE_SEEDS[-1], 115_828)
        self.assertEqual(len(generator.TARGETS) * len(generator.BASE_SEEDS) * generator.BUDGET, 73_728)

    def test_rng_derivation_cross_implementation(self) -> None:
        for target in generator.TARGETS:
            for base_seed in generator.BASE_SEEDS:
                for stream in ("proposal", "parent_selection"):
                    self.assertEqual(
                        generator.stable_rng_seed(base_seed=base_seed, target=target, stream_name=stream),
                        verifier.stable_rng_seed(base_seed=base_seed, target=target, stream_name=stream),
                    )

    def test_proposal_kernel_cross_implementation_on_registered_seed(self) -> None:
        seeds = json.loads((REPO_ROOT / generator.STAGE0 / "seed_controls.json").read_text())
        parent = generator.graph_from_record(seeds["seeds"]["0"]["candidate"])
        left = random.Random(312_415_926)
        right = random.Random(312_415_926)
        for _ in range(256):
            proposed = generator.propose(parent, left)
            mode, operator, independent = verifier.independent_proposal(parent, right)
            self.assertEqual((proposed.mode, proposed.operator), (mode, operator))
            self.assertEqual(candidate_record(proposed.candidate), candidate_record(independent))

    def test_transition_partition(self) -> None:
        cases = (
            (("q", "x", "q", "x"), "quotient_self"),
            (("q1", "x", "q2", "x"), "embodiment_only"),
            (("q1", "x", "q2", "y"), "literal_tree_crossing"),
        )
        for inputs, expected in cases:
            self.assertEqual(
                generator.classify_transition(
                    parent_quotient=inputs[0],
                    parent_literal=inputs[1],
                    candidate_quotient=inputs[2],
                    candidate_literal=inputs[3],
                ),
                expected,
            )
            self.assertEqual(verifier.independent_transition_class(*inputs), expected)

    def test_stage0_inputs_and_registered_seed_replay(self) -> None:
        seeds, leakage = generator.verify_stage0(REPO_ROOT)
        self.assertEqual(set(seeds["seeds"]), set(generator.TARGETS))
        self.assertEqual(len(leakage), 1_690)
        for target in generator.TARGETS:
            self.assertIn(seeds["seeds"][target]["candidate_sha256"], leakage)

    def test_summary_projection_cross_implementation(self) -> None:
        def fake_event(index: int, transition_class: str) -> dict:
            target = "0"
            quotient = f"{index + 1:064x}"
            parent = f"{index + 101:064x}"
            literal = f"{index + 201:064x}"
            parent_literal = literal if transition_class == "embodiment_only" else f"{index + 301:064x}"
            return {
                "target": target,
                "base_seed": generator.BASE_SEEDS[0],
                "evaluation_index": index,
                "global_event_index": index,
                "candidate_sha256": f"{index + 401:064x}",
                "exact_decision": {"candidate_root_game_sha256": literal},
                "quotient": {"quotient_sha256": quotient},
                "retention": {"inserted": True},
                "rejection": None,
                "transition": {
                    "class": transition_class,
                    "parent_quotient_sha256": parent,
                    "candidate_quotient_sha256": quotient,
                    "parent_literal_game_sha256": parent_literal,
                    "candidate_literal_game_sha256": literal,
                    "parent_heldout": True,
                    "candidate_heldout": True,
                    "primary": True,
                },
            }

        events = [
            fake_event(0, "embodiment_only"),
            fake_event(1, "literal_tree_crossing"),
            fake_event(2, "embodiment_only"),
            fake_event(3, "literal_tree_crossing"),
        ]
        left = generator.summarize(events)
        right = verifier.recompute_summary(events)
        self.assertEqual(left, right)
        self.assertEqual(left["target_unions"]["0"]["counts"]["heldout_quotient_unique_representatives"], 4)
        self.assertIsNotNone(left["mechanical_exemplars"]["0|embodiment_only"])


if __name__ == "__main__":
    unittest.main()
