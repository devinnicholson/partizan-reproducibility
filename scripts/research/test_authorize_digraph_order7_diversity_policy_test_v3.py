#!/usr/bin/env python3
"""Tests for the one-time V3 test authorizer."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import authorize_digraph_order7_diversity_policy_test_v3 as authorizer
from digraph_derivation_certificate_v3 import object_sha256
import digraph_order7_diversity_policy_test_v3 as test_builder


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_FIELDS = (
    "protocol",
    "test_design",
    "sources",
    "initialization_manifest",
    "validation_completion",
    "prior_registry",
    "model_package",
    "model_verification",
    "resource_preflight",
    "commands",
    "resource_limits",
    "authorization_nonce",
)


def reauthorize(launch: dict) -> None:
    launch["authorization_sha256"] = object_sha256(
        {field: launch[field] for field in AUTHORIZATION_FIELDS}
    )
    launch["output_directory"] = (
        "output/research/digraph-order7-diversity-policy-test-v3-"
        + launch["authorization_sha256"][:12]
    )
    payload = dict(launch)
    payload.pop("launch_sha256", None)
    launch["launch_sha256"] = object_sha256(payload)


class DiversityPolicyTestAuthorizerV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            dir=REPO_ROOT,
            prefix=".smoke-v3-test-authorizer-",
        )
        self.launch_path = Path(self.temp.name) / "AUTHORIZED_ONCE.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, nonce: str = "8" * 64) -> dict:
        return authorizer.build_launch(
            repo_root=REPO_ROOT,
            launch_path=self.launch_path,
            authorization_nonce=nonce,
        )

    def test_launch_replays_exact_test_design_and_dependencies(self) -> None:
        launch = self.build()
        protocol = authorizer.load_json_object(
            REPO_ROOT / test_builder.PROTOCOL_PATH
        )
        test_builder.verify_launch(
            repo_root=REPO_ROOT,
            launch=launch,
            protocol=protocol,
        )
        self.assertEqual(launch["status"], "AUTHORIZED_ONCE")
        self.assertEqual(launch["test_design"]["calls_per_arm_pair"], 2048)
        self.assertEqual(len(launch["test_design"]["pair_seeds"]), 12)
        self.assertEqual(
            launch["test_design"]["initialization_indices"],
            list(range(12)),
        )
        self.assertFalse(launch["test_data_generated"])
        self.assertFalse(launch["paper_evidence"])

    def test_launch_is_write_once(self) -> None:
        authorizer.authorize(
            repo_root=REPO_ROOT,
            launch_path=self.launch_path,
            authorization_nonce="a" * 64,
        )
        with self.assertRaises(FileExistsError):
            authorizer.authorize(
                repo_root=REPO_ROOT,
                launch_path=self.launch_path,
                authorization_nonce="a" * 64,
            )

    def test_invalid_nonce_creates_no_launch(self) -> None:
        with self.assertRaisesRegex(
            authorizer.AuthorizationError,
            "64 lowercase hexadecimal",
        ):
            self.build("invalid")
        self.assertFalse(self.launch_path.exists())

    def test_rehashed_prior_registry_mutation_is_rejected(self) -> None:
        launch = self.build()
        changed = copy.deepcopy(launch)
        changed["prior_registry"]["sha256"] = "0" * 64
        reauthorize(changed)
        protocol = authorizer.load_json_object(
            REPO_ROOT / test_builder.PROTOCOL_PATH
        )
        with self.assertRaisesRegex(ValueError, "prior_registry.*changed"):
            test_builder.verify_launch(
                repo_root=REPO_ROOT,
                launch=changed,
                protocol=protocol,
            )

    def test_rehashed_source_mutation_is_rejected(self) -> None:
        launch = self.build()
        changed = copy.deepcopy(launch)
        changed["sources"][-1]["sha256"] = "0" * 64
        reauthorize(changed)
        protocol = authorizer.load_json_object(
            REPO_ROOT / test_builder.PROTOCOL_PATH
        )
        with self.assertRaisesRegex(ValueError, "source.*changed"):
            test_builder.verify_launch(
                repo_root=REPO_ROOT,
                launch=changed,
                protocol=protocol,
            )


if __name__ == "__main__":
    unittest.main()
