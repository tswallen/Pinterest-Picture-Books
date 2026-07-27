"""
book_layout.py
==============

The "clever algorithm" that turns a flat, chronological list of pins into
discrete, printable A4 pages.

Pinterest's masonry is one endless column-balanced scroll; a book needs fixed
pages. So instead of relying on CSS masonry (which cannot page-break cleanly)
we *compute* an absolute-positioned layout:

  * Fixed number of columns of equal width.
  * Each pin is placed into whichever column is currently shortest -- this is
    what produces the staggered masonry look while keeping pins *largely* in
    chronological order (we only ever look at the next pin in sequence).
  * As soon as the shortest column can no longer fit the next pin within the
    page's printable height, the page is finalised and a fresh page begins.

Everything is measured in CSS pixels at 96 DPI so the numbers map 1:1 onto what
a browser prints.
"""

from __future__ import annotations

# Physical page sizes in millimetres (width, height) in portrait orientation.
PAGE_SIZES_MM = {
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
    "a5": (148.0, 210.0),
}

_MM_TO_PX = 96.0 / 25.4  # CSS reference pixel is 1/96 inch


def _mm(value: float) -> float:
    return value * _MM_TO_PX


def _caption_height_px(options: dict) -> float:
    """Vertical room reserved under each image for its caption lines."""
    lines = 0
    if options.get("show_titles"):
        lines += 1
    if options.get("show_filenames"):
        lines += 1
    if options.get("show_dates") or options.get("show_board"):
        lines += 1
    if lines == 0:
        return 0.0
    # ~15px per line of caption text + a little breathing room.
    return lines * 15.0 + 6.0


def page_dimensions_px(options: dict) -> dict:
    """Return page + printable content box dimensions in pixels."""
    w_mm, h_mm = PAGE_SIZES_MM.get(options.get("page_size", "a4"), PAGE_SIZES_MM["a4"])
    if options.get("orientation", "portrait") == "landscape":
        w_mm, h_mm = h_mm, w_mm
    margin = float(options.get("margin_mm", 10))
    return {
        "page_w": _mm(w_mm),
        "page_h": _mm(h_mm),
        "margin": _mm(margin),
        "content_w": _mm(w_mm) - 2 * _mm(margin),
        "content_h": _mm(h_mm) - 2 * _mm(margin),
    }


def compute_layout(pins: list[dict], options: dict) -> dict:
    """Compute page-by-page placement for ``pins``.

    Returns a dict with:
        page_w, page_h, margin  -- pixel geometry for rendering
        pages                   -- list of pages, each a list of placed items
    Each placed item: {pin, x, y, w, img_h, cap_h, h}
    """
    dims = page_dimensions_px(options)
    content_w, content_h = dims["content_w"], dims["content_h"]

    columns = max(1, int(options.get("columns", 3)))
    gutter = _mm(float(options.get("gutter_mm", 4)))
    max_per_page = int(options.get("max_per_page", 0)) or None
    cap_h = _caption_height_px(options)

    col_w = (content_w - gutter * (columns - 1)) / columns

    pages: list[list[dict]] = []
    heights = [0.0] * columns          # current filled height per column
    current: list[dict] = []

    def start_new_page():
        nonlocal current, heights
        if current:
            pages.append(current)
        current = []
        heights = [0.0] * columns

    for pin in pins:
        iw = pin["image"].get("width") or 1
        ih = pin["image"].get("height") or 1
        img_h = col_w * (ih / iw)

        # An image taller than a whole page is scaled down to fit.
        max_img_h = content_h - cap_h
        if img_h > max_img_h:
            img_h = max_img_h
        item_h = img_h + cap_h

        col = min(range(columns), key=lambda c: heights[c])
        top = heights[col]
        need = top + item_h + (gutter if top > 0 else 0)

        page_full = need > content_h or (
            max_per_page is not None and len(current) >= max_per_page
        )
        if page_full and current:
            start_new_page()
            col, top = 0, 0.0

        x = col * (col_w + gutter)
        y = heights[col] + (gutter if heights[col] > 0 else 0)
        current.append({
            "pin": pin,
            "x": round(x, 2),
            "y": round(y, 2),
            "w": round(col_w, 2),
            "img_h": round(img_h, 2),
            "cap_h": round(cap_h, 2),
            "h": round(item_h, 2),
        })
        heights[col] = y + item_h

    if current:
        pages.append(current)

    return {
        "page_w": round(dims["page_w"], 2),
        "page_h": round(dims["page_h"], 2),
        "margin": round(dims["margin"], 2),
        "columns": columns,
        "pages": pages,
    }
