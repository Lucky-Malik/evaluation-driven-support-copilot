from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from support_copilot.corpus import document_content, extract_html
from support_copilot.snapshot import load_snapshot

SNAPSHOT = Path(__file__).resolve().parents[1] / "data/snapshots/fastapi-d4f83a093dd1b2ab"


@pytest.mark.parametrize(
    "index, expected",
    [
        (0, "item_id: int"),
        (1, "short: bool"),
        (2, "class Item(BaseModel)"),
        (3, "Depends"),
        (4, "HTTPException"),
        (5, "OAuth2PasswordBearer"),
    ],
)
def test_real_saved_page_retains_code_examples(index: int, expected: str) -> None:
    manifest, pages = load_snapshot(SNAPSHOT)
    title, sections = extract_html(pages[index])
    assert title == manifest.pages[index].title
    assert expected in document_content(sections)
    article = BeautifulSoup(pages[index], "html.parser").select_one("article.md-content__inner")
    originals = [node.get_text("", strip=False).strip("\n") for node in article.find_all("pre")]
    extracted = [
        block for section in sections for block in section.blocks if block.startswith("```")
    ]
    assert len(originals) == len(extracted)
    assert all(original in block for original, block in zip(originals, extracted, strict=True))
