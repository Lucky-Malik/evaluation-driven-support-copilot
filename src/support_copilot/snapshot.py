import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

from support_copilot.corpus import extract_html, sha256
from support_copilot.events import emit

SOURCE_PATHS = (
    "tutorial/path-params/",
    "tutorial/query-params/",
    "tutorial/body/",
    "tutorial/dependencies/",
    "tutorial/handling-errors/",
    "tutorial/security/first-steps/",
)
SOURCE_URLS = tuple(f"https://fastapi.tiangolo.com/{path}" for path in SOURCE_PATHS)
LICENSE_URL = "https://raw.githubusercontent.com/fastapi/fastapi/master/LICENSE"
MAX_DOWNLOAD_BYTES = 3_000_000


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str
    title: str
    file: str = Field(pattern=r"^page-[0-9]+\.html$")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: int = Field(default=1, ge=1, le=1)
    snapshot_id: str
    snapshot_hash: str
    captured_at: datetime
    upstream_version: str = "unversioned official website; captured bytes are pinned"
    attribution: str = "FastAPI documentation, copyright Sebastián Ramírez; MIT license"
    license_url: str = LICENSE_URL
    license_sha256: str
    pages: list[Page]


def fingerprint(pages: list[Page], license_hash: str) -> str:
    data = {"pages": [page.model_dump() for page in pages], "license_sha256": license_hash}
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode())


def download(client: httpx.Client, url: str) -> bytes:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        parts: list[bytes] = []
        size = 0
        for part in response.iter_bytes():
            size += len(part)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError("Documentation download exceeds the 3 MB per-file limit")
            parts.append(part)
    return b"".join(parts)


def fetch_snapshot(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=output) as temporary:
        folder = Path(temporary)
        pages: list[Page] = []
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for index, url in enumerate(SOURCE_URLS):
                raw = download(client, url)
                title, _ = extract_html(raw)
                filename = f"page-{index}.html"
                (folder / filename).write_bytes(raw)
                pages.append(
                    Page(source_url=url, title=title, file=filename, raw_sha256=sha256(raw))
                )
                emit("page_downloaded", source_url=url, bytes=len(raw))
            license_bytes = download(client, LICENSE_URL)
        if (
            b"MIT License" not in license_bytes
            or b"Permission is hereby granted" not in license_bytes
        ):
            raise ValueError("Expected the upstream MIT license")
        (folder / "LICENSE").write_bytes(license_bytes)
        digest = fingerprint(pages, sha256(license_bytes))
        manifest = Manifest(
            snapshot_id=f"fastapi-{digest[:16]}",
            snapshot_hash=digest,
            captured_at=datetime.now(UTC),
            license_sha256=sha256(license_bytes),
            pages=pages,
        )
        (folder / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
        destination = output / manifest.snapshot_id
        if destination.exists():
            load_snapshot(destination)
        else:
            folder.rename(destination)
        emit("snapshot_saved", snapshot_id=manifest.snapshot_id, documents=len(pages))
        return destination


def load_snapshot(folder: Path) -> tuple[Manifest, list[bytes]]:
    manifest = Manifest.model_validate_json((folder / "manifest.json").read_bytes())
    if tuple(page.source_url for page in manifest.pages) != SOURCE_URLS:
        raise ValueError("Snapshot must contain exactly the six selected official pages in order")
    if len({page.file for page in manifest.pages}) != len(manifest.pages):
        raise ValueError("Snapshot page filenames must be unique")
    if manifest.license_url != LICENSE_URL or manifest.captured_at.utcoffset() is None:
        raise ValueError("Invalid license source or timezone-free capture timestamp")
    if sha256((folder / "LICENSE").read_bytes()) != manifest.license_sha256:
        raise ValueError("Snapshot license checksum mismatch")
    digest = fingerprint(manifest.pages, manifest.license_sha256)
    if digest != manifest.snapshot_hash or manifest.snapshot_id != f"fastapi-{digest[:16]}":
        raise ValueError("Snapshot identity does not match its manifest")
    pages = []
    for page in manifest.pages:
        raw = (folder / page.file).read_bytes()
        if sha256(raw) != page.raw_sha256:
            raise ValueError(f"Snapshot checksum mismatch: {page.file}")
        pages.append(raw)
    return manifest, pages
