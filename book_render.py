"""
book_render.py
=============

Turns a computed layout (see book_layout.py) into HTML.

There is a single source of truth for the book markup: the preview panel shows
exactly this HTML, the browser Print dialog prints exactly this HTML, and the
"Save as PDF" export rasterises exactly this HTML. Only the surrounding shell
differs (an inline fragment for the live preview vs. a full standalone document
for PDF export).
"""

from __future__ import annotations

import html
import os


def _caption_html(item: dict, options: dict) -> str:
    pin = item["pin"]
    rows = []
    if options.get("show_titles") and pin.get("title"):
        rows.append(f'<div class="cap-title">{html.escape(pin["title"])}</div>')
    if options.get("show_filenames"):
        fname = os.path.basename(pin["image"].get("local") or pin["image"].get("url", ""))
        if fname:
            rows.append(f'<div class="cap-file">{html.escape(fname)}</div>')
    meta = []
    if options.get("show_dates") and pin.get("created_at"):
        meta.append(html.escape(pin["created_at"][:10]))
    if options.get("show_board") and pin.get("board_name"):
        meta.append(html.escape(pin["board_name"]))
    if meta:
        rows.append(f'<div class="cap-meta">{" &middot; ".join(meta)}</div>')
    if not rows:
        return ""
    return f'<figcaption class="caption">{"".join(rows)}</figcaption>'


def _item_html(item: dict, options: dict, image_url) -> str:
    pin = item["pin"]
    src = image_url(pin)
    style = (
        f'left:{item["x"]}px; top:{item["y"]}px; width:{item["w"]}px; '
        f'height:{item["h"]}px;'
    )
    fit = "cover" if options.get("crop") else "contain"
    img_style = f"height:{item['img_h']}px; object-fit:{fit};"
    return (
        f'<figure class="tile" style="{style}">'
        f'<img src="{html.escape(src)}" style="{img_style}" loading="lazy" alt="">'
        f'{_caption_html(item, options)}'
        f"</figure>"
    )


def _page_html(page_items, index, total, layout, options, image_url) -> str:
    tiles = "".join(_item_html(it, options, image_url) for it in page_items)
    footer = ""
    if options.get("page_numbers"):
        footer = f'<div class="page-num">{index + 1} / {total}</div>'
    return (
        f'<section class="book-page" style="width:{layout["page_w"]}px; '
        f'height:{layout["page_h"]}px;">'
        f'<div class="page-inner" style="inset:{layout["margin"]}px;">{tiles}</div>'
        f"{footer}"
        f"</section>"
    )


def _cover_html(options, layout) -> str:
    title = html.escape(options.get("book_title") or "Picture Book")
    subtitle = html.escape(options.get("book_subtitle") or "")
    return (
        f'<section class="book-page cover" style="width:{layout["page_w"]}px; '
        f'height:{layout["page_h"]}px;">'
        f'<div class="cover-inner">'
        f'<h1>{title}</h1>'
        f'{f"<p>{subtitle}</p>" if subtitle else ""}'
        f"</div></section>"
    )


def render_pages(layout: dict, options: dict, image_url) -> str:
    """Render all pages to an HTML fragment.

    ``image_url(pin)`` returns the URL the <img> should point at.
    """
    total = len(layout["pages"]) + (1 if options.get("cover") else 0)
    parts = []
    offset = 0
    if options.get("cover"):
        parts.append(_cover_html(options, layout))
        offset = 1
    for i, page in enumerate(layout["pages"]):
        parts.append(_page_html(page, i + offset, total, layout, options, image_url))
    return "".join(parts)


# The stylesheet shared by preview and print. Injected once into the preview
# document and inlined into the standalone PDF document.
BOOK_CSS = """
.book-page{position:relative;background:#fff;overflow:hidden;
  page-break-after:always;break-after:page;margin:0 auto;}
.book-page:last-child{page-break-after:auto;break-after:auto;}
.page-inner{position:absolute;}
.tile{position:absolute;margin:0;background:#f3f4f6;overflow:hidden;
  border-radius:6px;display:flex;flex-direction:column;}
.tile img{width:100%;display:block;border-radius:6px;}
.caption{padding:3px 2px 0;font-family:ui-sans-serif,system-ui,sans-serif;
  line-height:1.25;}
.cap-title{font-size:11px;font-weight:600;color:#111827;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.cap-file{font-size:10px;color:#6b7280;font-family:ui-monospace,monospace;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.cap-meta{font-size:10px;color:#9ca3af;}
.page-num{position:absolute;bottom:6px;right:10px;font-size:10px;color:#9ca3af;
  font-family:ui-sans-serif,system-ui,sans-serif;}
.cover{display:flex;align-items:center;justify-content:center;}
.cover-inner{text-align:center;font-family:ui-sans-serif,system-ui,sans-serif;}
.cover-inner h1{font-size:42px;font-weight:800;color:#111827;margin:0 0 12px;}
.cover-inner p{font-size:18px;color:#6b7280;margin:0;}
"""


def standalone_document(layout: dict, options: dict, image_url) -> str:
    """A complete HTML document for headless-Chrome PDF export."""
    body = render_pages(layout, options, image_url)
    page_size = options.get("page_size", "a4")
    orientation = options.get("orientation", "portrait")
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
@page {{ size: {page_size} {orientation}; margin: 0; }}
html,body{{margin:0;padding:0;background:#fff;}}
{BOOK_CSS}
.book-page{{margin:0;}}
</style></head>
<body>{body}</body></html>"""
