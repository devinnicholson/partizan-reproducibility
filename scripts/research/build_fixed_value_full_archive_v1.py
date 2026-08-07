#!/usr/bin/env python3
"""Build a deterministic licensed archive of the canonical evidence trees."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


SCHEMA_VERSION = "partizan.fixed_value_full_evidence_archive.v2"
DEFAULT_EVIDENCE_ROOTS = (
    Path("output/research/digraph-order7-diversity-policy-test-v3-c6d34e38c2b4"),
    Path("output/research/digraph-order7-fixed-value-transitions-v1-00ac040294db"),
    Path("output/research/fixed-value-scope-v1"),
)
NOTICE = """\
LICENSED RELEASE CANDIDATE — DOI PENDING

Copyright (C) 2026 Devin Nicholson.

This archive contains the complete canonical evidence trees for the fixed-value
representation study, including the V3 order-7 held-out run and its
content-addressed sidecars, the historical transition ledger, and the complete
Domineering scope tree. The contents are licensed under GNU GPL-3.0-or-later;
the complete license text and citation metadata are included. This local
release candidate has not yet been deposited or assigned a DOI.
"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_info(name: str, size: int, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = mode
    return info


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    archive.addfile(normalized_info(name, len(data)), io.BytesIO(data))


def add_path(
    archive: tarfile.TarFile, source: Path, archive_name: str
) -> None:
    with source.open("rb") as handle:
        archive.addfile(
            normalized_info(archive_name, source.stat().st_size),
            handle,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--include",
        type=Path,
        action="append",
        help="repository-relative evidence tree; repeat to override defaults",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authority-output", type=Path, required=True)
    parser.add_argument(
        "--license-source", type=Path, default=Path("../partizan/LICENSE")
    )
    parser.add_argument(
        "--citation-source",
        type=Path,
        default=Path("docs/research/FIXED_VALUE_EVIDENCE_CITATION.cff"),
    )
    parser.add_argument("--doi", help="assigned archival DOI, when available")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    requested_roots = args.include or list(DEFAULT_EVIDENCE_ROOTS)
    evidence_roots: list[Path] = []
    for requested in requested_roots:
        root = requested if requested.is_absolute() else repo_root / requested
        root = root.resolve()
        if not root.is_dir() or not root.is_relative_to(repo_root):
            raise FileNotFoundError(root)
        evidence_roots.append(root)

    license_source = args.license_source
    if not license_source.is_absolute():
        license_source = repo_root / license_source
    citation_source = args.citation_source
    if not citation_source.is_absolute():
        citation_source = repo_root / citation_source
    if not license_source.is_file():
        raise FileNotFoundError(license_source)
    if not citation_source.is_file():
        raise FileNotFoundError(citation_source)

    files = sorted(
        {
            path
            for evidence_root in evidence_roots
            for path in evidence_root.rglob("*")
            if path.is_file()
        },
        key=lambda path: path.relative_to(repo_root).as_posix(),
    )
    manifest_files = {}
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        manifest_files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "distribution_status": (
            "licensed_archival_deposit" if args.doi else "licensed_release_candidate"
        ),
        "license": "GPL-3.0-or-later",
        "doi": args.doi,
        "evidence_roots": [
            root.relative_to(repo_root).as_posix() for root in evidence_roots
        ],
        "file_count": len(files),
        "total_uncompressed_bytes": sum(
            entry["bytes"] for entry in manifest_files.values()
        ),
        "files": manifest_files,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    notice_bytes = NOTICE.encode("utf-8")
    license_bytes = license_source.read_bytes()
    citation_bytes = citation_source.read_bytes()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                prefix = "partizan-fixed-value-evidence"
                add_bytes(archive, f"{prefix}/ARCHIVE_NOTICE.txt", notice_bytes)
                add_bytes(archive, f"{prefix}/ARCHIVE_MANIFEST.json", manifest_bytes)
                add_bytes(archive, f"{prefix}/LICENSE", license_bytes)
                add_bytes(archive, f"{prefix}/CITATION.cff", citation_bytes)
                for path in files:
                    relative = path.relative_to(repo_root).as_posix()
                    add_path(archive, path, f"{prefix}/{relative}")
    temporary.replace(args.output)

    authority_payload = {
        "schema_version": SCHEMA_VERSION + ".authority",
        "status": "READY_FOR_DEPOSIT" if not args.doi else "DEPOSITED",
        "archive_path": args.output.name,
        "archive_sha256": file_sha256(args.output),
        "archive_bytes": args.output.stat().st_size,
        "evidence_file_count": len(files),
        "archive_member_count": len(files) + 4,
        "evidence_roots": manifest["evidence_roots"],
        "license": "GPL-3.0-or-later",
        "license_file_sha256": hashlib.sha256(license_bytes).hexdigest(),
        "citation_file_sha256": hashlib.sha256(citation_bytes).hexdigest(),
        "doi": args.doi,
    }
    authority_payload["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            authority_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    args.authority_output.parent.mkdir(parents=True, exist_ok=True)
    args.authority_output.write_text(
        json.dumps(authority_payload, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "archive_sha256": authority_payload["archive_sha256"],
                "authority_sha256": authority_payload["artifact_sha256"],
                "bytes": args.output.stat().st_size,
                "file_count": len(files) + 4,
                "output": str(args.output),
                "status": authority_payload["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
