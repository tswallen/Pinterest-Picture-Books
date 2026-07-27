# 📌 Pinterest Picture Books

Turn Pinterest boards into printable A4 picture books.

A small desktop tool (Python + [Eel](https://github.com/python-eel/Eel) +
Tailwind CSS) that logs into Pinterest through the
[`py3-pinterest`](https://github.com/bstoilov/py3-pinterest) library, downloads
the pins from the boards you choose, and lays them out into a Pinterest-style
masonry that paginates cleanly onto A4 for printing or PDF export.

> Works against real Pinterest **or a self-hosted clone** with the same API
> endpoints — just point `config.json` at your host.

---

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

A desktop window opens with three tabs. Use the **Back / Skip / Next** buttons
at the bottom, or click the numbered tabs directly.

---

## The three tabs

### 1 · Login  *(optional)*
Enter your Pinterest email + password to list **your** boards. Login uses
`py3-pinterest`'s browser-based cookie flow (a headless Chrome window), and the
session is cached in `data/` so you rarely need to log in again.

**Skip** this step if you only want public boards (added by URL in tab 2) or if
you already have downloaded pin data.

### 2 · Boards
- **Add by URL** — paste any board URL; its real name is resolved and added.
- **Board list** — every board with a checkbox. All are selected by default.
- **⚡ Smart Download** — fetches pins and images for the selected boards into
  `output/{board}/`. It's *smart*: it remembers the newest pin already saved and
  only fetches pins added since then, skipping duplicates. Progress (per board,
  per image) is shown in a toast with a progress bar.

Each board is stored as:

```
output/
  {board-name}/
    {board-name}-pins.json     # metadata, newest pin first
    images/{pin_id}.jpg        # highest-resolution image files
```

### 3 · Books
You can open this tab any time — it works from whatever is already in `output/`,
so login/download aren't required if you have data.

- **Left panel** — pick the content (*Shuffle all boards* or *Select from
  boards…*) and the book options: page size, orientation, columns, ordering,
  gutter/margins, image count, crop vs. fit, captions (titles / file names /
  dates / board name), page numbers, and an optional cover page.
- **Right panel** — a live preview of the exact HTML that will be printed.
- **🖨 Print** — opens the browser print dialog (the preview *is* the print
  output, at true A4).
- **⬇ Save PDF** — renders the same pages to a PDF in `output/` via headless
  Chrome.

#### How the layout works
Pinterest's masonry is one endless scroll and can't page-break cleanly. So the
book layout is *computed* rather than styled: fixed-width columns, each pin
dropped into the currently-shortest column (the masonry look, kept *largely*
chronological), starting a fresh page the moment the next pin won't fit within
the printable A4 height. See [`book_layout.py`](book_layout.py).

---

## Pointing at a clone

Edit `config.json`:

```json
{
  "base_url":  "https://your-clone.example",
  "login_url": "https://your-clone.example/login",
  "cred_root": "data",
  "output_dir": "output",
  "image_server_port": 8123,
  "eel_port": 8000
}
```

`base_url` rewrites every `*_RESOURCE` endpoint in `py3-pinterest` at startup,
so all board/pin API calls go to your clone. `login_url` is the page the
Selenium login flow drives (it expects Pinterest-style `#email` / `#password`
fields).

---

## Requirements & notes

- **Python 3.10+**.
- **Chrome / Chromium** is only needed for two things: `pinterest.login()` and
  **Save PDF**. Everything else — adding boards by URL, downloading, building
  and printing books — works without a browser install.
- Tailwind is loaded from the Play CDN (no build step); it needs internet on
  first paint, which is fine since the app is talking to a networked host anyway.
- `output/`, `data/`, and `state.json` are git-ignored (your pins, images, and
  session cookies stay local).

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | Eel entry point, exposed handlers, local image server |
| `pinterest_client.py` | `py3-pinterest` wrapper: login, boards, smart download |
| `storage.py` | JSON + image files on disk, app state, smart-merge |
| `book_layout.py` | masonry → paginated A4 packing algorithm |
| `book_render.py` | layout → HTML (shared by preview, print, PDF) |
| `web/` | Eel front end (`index.html`, `app.js`) |
| `tests/test_core.py` | unit tests for the framework-independent core |

## Tests

```bash
python tests/test_core.py
```
