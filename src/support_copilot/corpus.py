import hashlib
import json
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

PIPELINE_VERSION = "html-sections-blocks-v1-1600"
CHUNK_TARGET = 1600


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(*parts: str | int) -> str:
    return sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode())


@dataclass(frozen=True)
class Section:
    name: str
    anchor: str
    blocks: tuple[str, ...]


@dataclass(frozen=True)
class Chunk:
    id: str
    ordinal: int
    section: str
    anchor: str
    content: str
    content_sha256: str


def extract_html(html: bytes) -> tuple[str, list[Section]]:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.md-content__inner")
    if article is None or article.find("h1") is None:
        raise ValueError("Expected a FastAPI documentation article with a title")
    for node in article.select(
        ".headerlink, .linenums, .linenos, .md-content__button, script, style"
    ):
        node.decompose()
    title = article.find("h1").get_text(" ", strip=True)
    headings: list[tuple[int, str]] = []
    sections: list[Section] = []
    blocks: list[str] = []
    anchor = ""
    name = title
    tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "li", "table", "dt", "dd", "label"}
    for node in article.find_all(list(tags)):
        if any(
            isinstance(parent, Tag) and parent.name in tags
            for parent in node.parents
            if parent is not article
        ):
            continue
        if node.name.startswith("h") and node.name[1:].isdigit():
            if blocks:
                sections.append(Section(name, anchor, tuple(blocks)))
                blocks = []
            level = int(node.name[1])
            headings = [(depth, text) for depth, text in headings if depth < level]
            headings.append((level, node.get_text(" ", strip=True)))
            name = " > ".join(text for _, text in headings)
            anchor = str(node.get("id", ""))
        elif node.name == "pre":
            code = node.get_text("", strip=False).strip("\n")
            fence = "```"
            while fence in code:
                fence += "`"
            if code.strip():
                blocks.append(f"{fence}\n{code}\n{fence}")
        else:
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append(("- " if node.name == "li" else "") + text)
    if blocks:
        sections.append(Section(name, anchor, tuple(blocks)))
    if not sections:
        raise ValueError("Documentation article contains no usable text")
    return title, sections


def document_content(sections: list[Section]) -> str:
    return "\n\n".join(
        f"# {section.name}\n\n" + "\n\n".join(section.blocks) for section in sections
    )


def make_chunks(document_id: str, sections: list[Section]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        groups: list[str] = []
        current = ""
        for block in section.blocks:
            candidate = f"{current}\n\n{block}" if current else block
            if current and len(candidate) > CHUNK_TARGET:
                groups.append(current)
                current = block
            else:
                current = candidate
        if current:
            groups.append(current)
        for group in groups:
            content = f"# {section.name}\n\n{group}"
            ordinal = len(chunks)
            content_hash = sha256(content.encode())
            chunk_id = stable_id(
                document_id, PIPELINE_VERSION, ordinal, section.anchor, content_hash
            )
            chunks.append(
                Chunk(chunk_id, ordinal, section.name, section.anchor, content, content_hash)
            )
    return chunks
