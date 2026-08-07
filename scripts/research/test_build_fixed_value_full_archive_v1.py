#!/usr/bin/env python3
"""Regression tests for the deterministic full-evidence archive builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("build_fixed_value_full_archive_v1.py")


class FullEvidenceArchiveTests(unittest.TestCase):
    def test_small_archive_is_deterministic_and_licensed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "a.json").write_text('{"a":1}\n', encoding="utf-8")
            (evidence / "b.txt").write_text("evidence\n", encoding="utf-8")
            license_path = root / "LICENSE"
            license_path.write_text("test license\n", encoding="utf-8")
            citation = root / "CITATION.cff"
            citation.write_text("cff-version: 1.2.0\n", encoding="utf-8")

            outputs = []
            for index in range(2):
                archive = root / f"archive-{index}.tar.gz"
                authority = root / f"authority-{index}.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repo-root",
                        str(root),
                        "--include",
                        "evidence",
                        "--output",
                        str(archive),
                        "--authority-output",
                        str(authority),
                        "--license-source",
                        str(license_path),
                        "--citation-source",
                        str(citation),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append((archive.read_bytes(), json.loads(authority.read_bytes())))

            self.assertEqual(outputs[0][0], outputs[1][0])
            self.assertEqual(outputs[0][1]["archive_sha256"], outputs[1][1]["archive_sha256"])
            self.assertEqual(
                hashlib.sha256(outputs[0][0]).hexdigest(),
                outputs[0][1]["archive_sha256"],
            )
            self.assertEqual(outputs[0][1]["license"], "GPL-3.0-or-later")
            self.assertEqual(outputs[0][1]["status"], "READY_FOR_DEPOSIT")

            archive_path = root / "archive-0.tar.gz"
            with tarfile.open(archive_path, "r:gz") as archive:
                names = set(archive.getnames())
            self.assertIn("partizan-fixed-value-evidence/LICENSE", names)
            self.assertIn("partizan-fixed-value-evidence/CITATION.cff", names)
            self.assertIn(
                "partizan-fixed-value-evidence/evidence/a.json", names
            )


if __name__ == "__main__":
    unittest.main()
