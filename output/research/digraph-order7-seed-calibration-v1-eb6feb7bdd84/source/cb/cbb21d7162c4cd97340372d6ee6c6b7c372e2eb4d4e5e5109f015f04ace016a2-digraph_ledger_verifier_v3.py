#!/usr/bin/env python3
"""Read-only Digraph Placement evidence replay configured for order 7.

The frozen v2 verifier is reused only after its exact source hash and the
order-7 derivation-v3 adapter have been checked.  Candidate, quotient,
descriptor, target, derivation, equality, and sidecar replay logic is
unchanged; the artifact schema binding is advanced to v3.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import digraph_derivation_certificate_v3 as _derivation_v3
import digraph_ledger_verifier_v2 as _v2


BASE_V2_SHA256 = (
    "de830fbecab8a56c1f492f2611897d7a8e98546db7119a316a4a6532b08e1e6d"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


observed = _file_sha256(Path(_v2.__file__).resolve())
if observed != BASE_V2_SHA256:
    raise RuntimeError(
        "frozen ledger verifier v2 source hash mismatch: "
        f"expected {BASE_V2_SHA256}, got {observed}"
    )

_v2.ARTIFACT_SCHEMA = _derivation_v3.ARTIFACT_SCHEMA
_v2.build_graph_artifact = _derivation_v3.build_graph_artifact
_v2.build_derivation_certificate = _derivation_v3.build_derivation_certificate
_v2.canonical_artifact_bytes = _derivation_v3.canonical_artifact_bytes
_v2.game_from_verified_derivation = _derivation_v3.game_from_verified_derivation
_v2.verify_derivation_certificate = _derivation_v3.verify_derivation_certificate

CandidateReplay = _v2.CandidateReplay
LedgerVerificationError = _v2.LedgerVerificationError
TargetReplay = _v2.TargetReplay
candidate_record = _v2.candidate_record
candidate_record_sha256 = _v2.candidate_record_sha256
canonical_json_bytes = _v2.canonical_json_bytes
chain_events = _v2.chain_events
descriptor_record = _v2.descriptor_record
graph_from_candidate_record = _v2.graph_from_candidate_record
object_sha256 = _v2.object_sha256
quotient_record = _v2.quotient_record
verify_candidate_evidence = _v2.verify_candidate_evidence
verify_event_hash_chain = _v2.verify_event_hash_chain
verify_target_artifact = _v2.verify_target_artifact
weakly_connected = _v2.weakly_connected


__all__ = [
    "BASE_V2_SHA256",
    "CandidateReplay",
    "LedgerVerificationError",
    "TargetReplay",
    "candidate_record",
    "candidate_record_sha256",
    "canonical_json_bytes",
    "chain_events",
    "descriptor_record",
    "graph_from_candidate_record",
    "object_sha256",
    "quotient_record",
    "verify_candidate_evidence",
    "verify_event_hash_chain",
    "verify_target_artifact",
    "weakly_connected",
]
