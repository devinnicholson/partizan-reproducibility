#!/usr/bin/env python3
"""Order-7 extension of the frozen Digraph Placement derivation schema.

V3 deliberately changes only two schema identifiers and the admitted maximum
graph order.  The builder and strict replay implementation remain the frozen
v2 functions, whose source hash is checked before the globals they consult are
configured for v3.  This avoids maintaining a second, subtly divergent move
semantics while keeping v2 artifacts byte- and schema-incompatible with v3.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import digraph_derivation_certificate_v2 as _v2


ARTIFACT_SCHEMA = "partizan.digraph_placement_artifact.v3"
DERIVATION_SCHEMA = "partizan.digraph_placement_derivation_certificate.v3"
MAX_ORDER = 7
BASE_V2_SHA256 = (
    "06f4d8c0e28cf9390a041dd7ae711eb7af2849db7ce2be2dfe424152bf96d1cd"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configure_frozen_base() -> None:
    source = Path(_v2.__file__).resolve()
    observed = _file_sha256(source)
    if observed != BASE_V2_SHA256:
        raise RuntimeError(
            "frozen derivation v2 source hash mismatch: "
            f"expected {BASE_V2_SHA256}, got {observed}"
        )
    _v2.ARTIFACT_SCHEMA = ARTIFACT_SCHEMA
    _v2.DERIVATION_SCHEMA = DERIVATION_SCHEMA
    _v2.MAX_ORDER = MAX_ORDER


_configure_frozen_base()

RULESET = _v2.RULESET
DerivationVerificationError = _v2.DerivationVerificationError
canonical_json_bytes = _v2.canonical_json_bytes
object_sha256 = _v2.object_sha256
bytes_sha256 = _v2.bytes_sha256
validate_graph = _v2.validate_graph
build_graph_artifact = _v2.build_graph_artifact
canonical_artifact_bytes = _v2.canonical_artifact_bytes
build_derivation_certificate = _v2.build_derivation_certificate
verify_derivation_certificate = _v2.verify_derivation_certificate
game_from_verified_derivation = _v2.game_from_verified_derivation
validate_content_addressed_relpath = _v2.validate_content_addressed_relpath


def schema_contract() -> dict[str, Any]:
    """Return the exact, hashable difference between derivation v2 and v3."""

    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "derivation_schema": DERIVATION_SCHEMA,
        "maximum_order": MAX_ORDER,
        "base_v2_sha256": BASE_V2_SHA256,
        "semantic_changes_from_v2": ["maximum_order_6_to_7"],
        "ruleset": RULESET,
    }


__all__ = [
    "ARTIFACT_SCHEMA",
    "BASE_V2_SHA256",
    "DERIVATION_SCHEMA",
    "DerivationVerificationError",
    "MAX_ORDER",
    "RULESET",
    "build_derivation_certificate",
    "build_graph_artifact",
    "bytes_sha256",
    "canonical_artifact_bytes",
    "canonical_json_bytes",
    "game_from_verified_derivation",
    "object_sha256",
    "schema_contract",
    "validate_content_addressed_relpath",
    "validate_graph",
    "verify_derivation_certificate",
]

