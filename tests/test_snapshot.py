import json

import httpx
import pytest

from support_copilot.snapshot import download, fetch_snapshot, load_snapshot


def test_snapshot_loads_and_tampering_is_rejected(snapshot):
    manifest, pages = load_snapshot(snapshot)
    assert len(pages) == len(manifest.pages) == 6
    (snapshot / "page-0.html").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_snapshot(snapshot)


def test_manifest_identity_cannot_be_renamed(snapshot):
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["snapshot_id"] = "invented-version"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        load_snapshot(snapshot)


def test_source_allowlist_is_enforced(snapshot):
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["pages"][0]["source_url"] = "https://example.com/unrelated"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="six selected official pages"):
        load_snapshot(snapshot)


def test_download_rejects_http_error_and_excessive_size():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            download(client, "https://example.com")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 3_000_001))
    ) as client:
        with pytest.raises(ValueError, match="3 MB"):
            download(client, "https://example.com")


def test_failed_fetch_leaves_no_partial_snapshot(tmp_path, monkeypatch):
    def fail(client, url):
        raise httpx.ConnectError("Synthetic failure")

    monkeypatch.setattr("support_copilot.snapshot.download", fail)
    with pytest.raises(httpx.ConnectError):
        fetch_snapshot(tmp_path)
    assert list(tmp_path.iterdir()) == []
