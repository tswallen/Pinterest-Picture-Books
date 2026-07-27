"""Unit tests for the framework-independent core (no Eel/Selenium needed)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import book_layout
import book_render
import pinterest_client as pc
from storage import Storage


def _pins(n, w=200, h=300):
    return [{
        "id": str(i),
        "created_at": f"2022-01-{(i % 27) + 1:02d}T00:00:00+00:00",
        "title": f"Pin {i}",
        "description": "",
        "link": "",
        "board_name": "Test",
        "image": {"url": f"http://x/{i}.jpg", "width": w, "height": h,
                  "local": f"test/images/{i}.jpg"},
    } for i in range(n)]


def test_layout_paginates_and_fits():
    opts = {"page_size": "a4", "columns": 3, "gutter_mm": 4, "margin_mm": 10}
    layout = book_layout.compute_layout(_pins(40), opts)
    assert len(layout["pages"]) >= 2, "40 portrait pins should need multiple pages"
    content_h = book_layout.page_dimensions_px(opts)["content_h"]
    for page in layout["pages"]:
        for item in page:
            bottom = item["y"] + item["h"]
            assert bottom <= content_h + 1, "item overflows printable height"
    total = sum(len(p) for p in layout["pages"])
    assert total == 40, "every pin must be placed exactly once"


def test_max_per_page_cap():
    opts = {"columns": 3, "max_per_page": 6}
    layout = book_layout.compute_layout(_pins(20), opts)
    assert all(len(p) <= 6 for p in layout["pages"])


def test_columns_positions():
    opts = {"columns": 2, "gutter_mm": 4, "margin_mm": 10}
    layout = book_layout.compute_layout(_pins(4), opts)
    xs = {round(it["x"]) for page in layout["pages"] for it in page}
    assert len(xs) == 2, "two columns should produce two distinct x positions"


def test_render_produces_pages_and_cover():
    opts = {"columns": 3, "cover": True, "book_title": "My Book", "page_numbers": True}
    layout = book_layout.compute_layout(_pins(10), opts)
    html = book_render.render_pages(layout, opts, lambda p: p["image"]["local"])
    assert html.count("book-page") == len(layout["pages"]) + 1  # +cover
    assert "My Book" in html
    doc = book_render.standalone_document(layout, opts, lambda p: p["image"]["local"])
    assert doc.startswith("<!doctype html>") and "@page" in doc


def test_normalize_pin_picks_best_image_and_parses_date():
    raw = {
        "id": 99,
        "created_at": "Sat, 26 Feb 2022 19:41:56 +0000",
        "grid_title": "Hello",
        "board": {"name": "Board A"},
        "images": {
            "236x": {"url": "http://x/236.jpg", "width": 236, "height": 350},
            "orig": {"url": "http://x/orig.jpg", "width": 1200, "height": 1800},
        },
    }
    norm = pc.normalize_pin(raw)
    assert norm["image"]["url"] == "http://x/orig.jpg"
    assert norm["created_at"].startswith("2022-02-26")
    assert norm["title"] == "Hello"

    # A pin with no still image cannot be printed -> dropped.
    assert pc.normalize_pin({"id": 1, "images": {}}) is None


def test_parse_board_url():
    assert pc._parse_board_url("https://host/alice/my-board/") == ("alice", "my-board")
    assert pc._parse_board_url("https://host/") == (None, None)


def test_storage_smart_merge_and_known_ids():
    with tempfile.TemporaryDirectory() as tmp:
        st = Storage(tmp, os.path.join(tmp, "state.json"))
        board = {"id": "b1", "name": "Test", "slug": "test", "folder": "test",
                 "url": "", "pin_count": 0, "privacy": "public"}
        st.save_board(board, _pins(3), "2022-01-01T00:00:00+00:00")
        assert st.known_pin_ids("test") == {"0", "1", "2"}

        new = [{"id": "100", "created_at": "2023-01-01T00:00:00+00:00",
                "image": {"url": "http://x/100.jpg", "width": 1, "height": 1, "local": ""}}]
        total = st.merge_new_pins(board, new, "2023-01-01T00:00:00+00:00")
        assert total == 4
        pins = st.load_pins("test")
        assert pins[0]["id"] == "100", "new pins must be prepended (newest first)"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
