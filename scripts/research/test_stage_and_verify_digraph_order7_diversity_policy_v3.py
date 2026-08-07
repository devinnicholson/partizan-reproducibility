#!/usr/bin/env python3
"""Unit tests for portable V3 authorized-layout staging."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import stage_and_verify_digraph_order7_diversity_policy_v3 as staging


class PortableV3StagingTests(unittest.TestCase):
    def test_safe_relative_rejects_escape(self) -> None:
        for value in ("", "/absolute", "../escape", "a/../../escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                staging.safe_relative(value)

    def test_iter_bindings_finds_nested_bindings(self) -> None:
        value = {
            "a": {"path": "one.json", "sha256": "a" * 64},
            "b": [{"path": "two.json", "sha256": "b" * 64}],
        }
        self.assertEqual(
            list(staging.iter_bindings(value)),
            [(Path("one.json"), "a" * 64), (Path("two.json"), "b" * 64)],
        )

    def test_authority_is_canonical_and_self_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authority.json"
            authority = staging.write_authority(path, {"status": "PASS"})
            raw = path.read_bytes()
            self.assertEqual(raw, staging.canonical_json_bytes(authority) + b"\n")
            supplied = authority.pop("artifact_sha256")
            self.assertEqual(supplied, staging.object_sha256(authority))
            self.assertEqual(json.loads(raw)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
