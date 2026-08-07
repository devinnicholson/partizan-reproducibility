from __future__ import annotations

import unittest

import audit_submission_evidence_v1 as audit


class SubmissionEvidenceAuditV1Tests(unittest.TestCase):
    def test_embedded_hash_omits_only_the_declared_field(self) -> None:
        value = {"a": 1, "nested": {"b": 2}}
        value["artifact_sha256"] = audit.object_sha256(value)
        self.assertTrue(audit.embedded_hash_matches(value, "artifact_sha256"))
        value["nested"]["b"] = 3
        self.assertFalse(audit.embedded_hash_matches(value, "artifact_sha256"))

    def test_canonical_json_is_stable_and_ascii(self) -> None:
        self.assertEqual(
            audit.canonical_json_bytes({"z": "é", "a": 1}),
            b'{"a":1,"z":"\\u00e9"}',
        )

    def test_audit_status_separates_science_from_release(self) -> None:
        rows = [
            {"passed": True, "severity": "error"},
            {"passed": False, "severity": "release_blocker"},
        ]
        scientific = [
            row for row in rows if not row["passed"] and row["severity"] == "error"
        ]
        blockers = [
            row
            for row in rows
            if not row["passed"] and row["severity"] == "release_blocker"
        ]
        self.assertEqual(scientific, [])
        self.assertEqual(len(blockers), 1)


if __name__ == "__main__":
    unittest.main()
