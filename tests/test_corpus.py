import pytest

from support_copilot.corpus import (
    Section,
    document_content,
    extract_html,
    make_chunks,
    sha256,
)


def test_extract_preserves_headings_code_and_excludes_navigation():
    raw = b"""<nav>Not evidence</nav><article class="md-content__inner">
    <h1>Routing<a class="headerlink">#</a></h1><p>Use a path.</p>
    <h2 id="types">Types</h2><pre><code>@app.get("/items/{item_id}")
def read(item_id: int):
    return {"id": item_id}
</code></pre><h3 id="errors">Errors</h3><p>Invalid integers fail.</p></article>"""
    title, sections = extract_html(raw)
    assert title == "Routing"
    assert [section.name for section in sections] == [
        "Routing",
        "Routing > Types",
        "Routing > Types > Errors",
    ]
    assert sections[1].anchor == "types"
    content = document_content(sections)
    assert '    return {"id": item_id}' in content
    assert "```" in content
    assert "Not evidence" not in content


@pytest.mark.parametrize(
    "raw",
    [b"<html>Gateway error</html>", b'<article class="md-content__inner"><h1>Empty</h1></article>'],
)
def test_unexpected_html_is_rejected(raw):
    with pytest.raises(ValueError):
        extract_html(raw)


def test_chunks_have_stable_ids_metadata_and_content_hashes():
    sections = [
        Section("Title > Types", "types", ("A" * 1000, "B" * 1000)),
        Section("Title > Errors", "errors", ("Invalid input.",)),
    ]
    first = make_chunks("document-one", sections)
    assert first == make_chunks("document-one", sections)
    assert len(first) == 3
    assert len({chunk.id for chunk in first}) == 3
    assert [chunk.ordinal for chunk in first] == [0, 1, 2]
    assert first[0].section == "Title > Types"
    assert first[0].anchor == "types"
    assert all(chunk.content_sha256 == sha256(chunk.content.encode()) for chunk in first)
    assert first[0].id != make_chunks("document-two", sections)[0].id
    assert first[0].id != make_chunks("document-one", [Section("Changed", "types", ("A",))])[0].id


def test_code_block_is_not_split_to_meet_soft_target():
    code = "```\n" + "    print('example')\n" * 150 + "```"
    chunks = make_chunks("doc", [Section("Example", "example", ("Introduction", code, "After"))])
    assert len(chunks) == 3
    assert code in chunks[1].content
