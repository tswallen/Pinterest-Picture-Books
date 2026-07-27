"""
Pinterest Picture Books
=======================

Eel desktop app entry point. Wires the HTML/JS front end (web/) to the Python
back end (pinterest_client, storage, book_layout, book_render).

Run with:  python main.py
"""

from __future__ import annotations

import base64
import functools
import json
import os
import random
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import eel

from pinterest_client import PinterestClient
from storage import Storage
import book_layout
import book_render

# --------------------------------------------------------------------------- #
# Configuration & singletons
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_config() -> dict:
    with open(os.path.join(ROOT, "config.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


CONFIG = _load_config()
OUTPUT_DIR = os.path.join(ROOT, CONFIG.get("output_dir", "output"))
IMG_PORT = int(CONFIG.get("image_server_port", 8123))

storage = Storage(OUTPUT_DIR, os.path.join(ROOT, "state.json"))
client = PinterestClient(
    base_url=CONFIG.get("base_url", "https://www.pinterest.com"),
    login_url=CONFIG.get("login_url", "https://www.pinterest.com/login"),
    cred_root=os.path.join(ROOT, CONFIG.get("cred_root", "data")),
    login_headless=bool(CONFIG.get("login_headless", False)),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(**kw):
    return {"ok": True, **kw}


def _err(message):
    return {"ok": False, "error": str(message)}


def safe(fn):
    """Wrap an exposed function so exceptions become {ok:False, error:...}
    instead of vanishing into an Eel traceback."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # surfaced to the UI as a toast
            return _err(exc)
    return wrapper


# --------------------------------------------------------------------------- #
# Local static image server (serves output/ so the webview + Chrome can load
# downloaded images and the generated book document by URL).
# --------------------------------------------------------------------------- #
def _start_image_server():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=OUTPUT_DIR)
    handler.log_message = lambda *a, **k: None  # silence request logging

    def serve():
        with ThreadingHTTPServer(("127.0.0.1", IMG_PORT), handler) as httpd:
            httpd.serve_forever()

    threading.Thread(target=serve, daemon=True).start()


def _image_url(pin: dict) -> str:
    local = pin.get("image", {}).get("local")
    if local:
        return f"http://127.0.0.1:{IMG_PORT}/{local}"
    return pin.get("image", {}).get("url", "")


# --------------------------------------------------------------------------- #
# Tab 1 - Login
# --------------------------------------------------------------------------- #
@eel.expose
@safe
def init_app():
    """Called once on page load. Restores any prior session + state."""
    state = storage.load_state()
    username = state.get("username")
    logged_in = False
    if username:
        logged_in = client.resume_session(username)
    return _ok(
        logged_in=logged_in,
        username=client.username,
        downloaded=storage.list_downloaded_boards(),
        state=state,
    )


@eel.expose
@safe
def do_login(email, password):
    username = client.login(email, password)
    state = storage.load_state()
    state["username"] = username
    storage.save_state(state)
    return _ok(username=username)


# --------------------------------------------------------------------------- #
# Tab 2 - Boards
# --------------------------------------------------------------------------- #
@eel.expose
@safe
def get_user_boards():
    if not client.logged_in:
        return _err("Log in first to list your boards, or add a board by URL.")
    return _ok(boards=client.get_boards())


@eel.expose
@safe
def add_board_url(url):
    board = client.resolve_board_url(url)
    return _ok(board=board)


@eel.expose
@safe
def start_download(boards):
    """Kick off a Smart Download for the given boards in a background thread.

    Progress is streamed to the front end via eel.download_progress / done.
    """
    threading.Thread(
        target=_download_worker, args=(boards,), daemon=True
    ).start()
    return _ok()


def _download_worker(boards):
    total_boards = len(boards)
    grand_new = 0
    try:
        for bi, board in enumerate(boards):
            folder = board["folder"]
            known = storage.known_pin_ids(folder)

            eel.download_progress({
                "board": board["name"],
                "board_index": bi + 1,
                "board_total": total_boards,
                "phase": "fetching",
                "new": 0,
            })

            new_pins = client.smart_download(
                board["id"], known,
                progress_cb=lambda n: eel.download_progress({
                    "board": board["name"],
                    "board_index": bi + 1,
                    "board_total": total_boards,
                    "phase": "fetching",
                    "new": n,
                }),
            )

            # Download image files, reporting per-image progress.
            for pi, pin in enumerate(new_pins):
                try:
                    storage.download_image(folder, pin)
                except Exception:
                    pass  # a single bad image should not abort the board
                if pi % 5 == 0 or pi == len(new_pins) - 1:
                    eel.download_progress({
                        "board": board["name"],
                        "board_index": bi + 1,
                        "board_total": total_boards,
                        "phase": "images",
                        "done": pi + 1,
                        "new": len(new_pins),
                    })

            total = storage.merge_new_pins(board, new_pins, _now_iso())
            grand_new += len(new_pins)
            eel.download_progress({
                "board": board["name"],
                "board_index": bi + 1,
                "board_total": total_boards,
                "phase": "board_done",
                "new": len(new_pins),
                "total": total,
            })

        eel.download_done({
            "ok": True,
            "new": grand_new,
            "downloaded": storage.list_downloaded_boards(),
        })
    except Exception as exc:
        eel.download_done({"ok": False, "error": str(exc)})


# --------------------------------------------------------------------------- #
# Tab 3 - Books
# --------------------------------------------------------------------------- #
@eel.expose
@safe
def list_boards_with_data():
    return _ok(downloaded=storage.list_downloaded_boards())


@eel.expose
@safe
def get_book_css():
    return _ok(css=book_render.BOOK_CSS)


def _gather_pins(options) -> list[dict]:
    mode = options.get("source_mode", "shuffle_all")
    downloaded = storage.list_downloaded_boards()
    if mode == "select":
        wanted = set(options.get("selected_folders", []))
        folders = [b["folder"] for b in downloaded if b["folder"] in wanted]
    else:  # shuffle_all -> every downloaded board
        folders = [b["folder"] for b in downloaded]

    pins, seen = [], set()
    for folder in folders:
        for pin in storage.load_pins(folder):
            pid = pin.get("id")
            if pid and pid in seen:
                continue  # dedupe pins that live on multiple boards
            seen.add(pid)
            pins.append(pin)

    order = options.get("order", "newest")
    if order == "shuffle":
        random.shuffle(pins)
    elif order == "oldest":
        pins.sort(key=lambda p: p.get("created_at") or "")
    else:  # newest first
        pins.sort(key=lambda p: p.get("created_at") or "", reverse=True)

    limit = int(options.get("max_images", 0) or 0)
    if limit > 0:
        pins = pins[:limit]
    return pins


@eel.expose
@safe
def build_book(options):
    storage.save_state({**storage.load_state(), "book_options": options})
    pins = _gather_pins(options)
    if not pins:
        return _err("No pins to lay out. Download some boards first.")
    layout = book_layout.compute_layout(pins, options)
    fragment = book_render.render_pages(layout, options, _image_url)
    return _ok(
        html=fragment,
        page_w=layout["page_w"],
        page_h=layout["page_h"],
        page_count=len(layout["pages"]) + (1 if options.get("cover") else 0),
        pin_count=len(pins),
    )


@eel.expose
@safe
def export_pdf(options):
    """Render the current book to a PDF using headless Chrome."""
    pins = _gather_pins(options)
    if not pins:
        return _err("No pins to export.")
    layout = book_layout.compute_layout(pins, options)
    document = book_render.standalone_document(layout, options, _image_url)

    # Write the document where the local server can load it.
    doc_path = os.path.join(OUTPUT_DIR, "_book_preview.html")
    with open(doc_path, "w", encoding="utf-8") as fh:
        fh.write(document)
    doc_url = f"http://127.0.0.1:{IMG_PORT}/_book_preview.html"

    try:
        pdf_bytes = _render_pdf(doc_url, options)
    except Exception as exc:
        first = str(exc).strip().splitlines()[0][:200]
        return _err(
            "PDF export needs headless Chrome and it failed to run "
            f"({first}). You can still use 🖨 Print → “Save as PDF”."
        )
    name = (options.get("book_title") or "picture-book").strip().replace(" ", "-")
    out_path = os.path.join(OUTPUT_DIR, f"{name}.pdf")
    with open(out_path, "wb") as fh:
        fh.write(pdf_bytes)
    return _ok(path=out_path)


def _render_pdf(url, options) -> bytes:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.print_page_options import PrintOptions
    from webdriver_manager.chrome import ChromeDriverManager

    chrome_opts = ChromeOptions()
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=chrome_opts
    )
    try:
        driver.get(url)
        w_mm, h_mm = book_layout.PAGE_SIZES_MM.get(
            options.get("page_size", "a4"), book_layout.PAGE_SIZES_MM["a4"]
        )
        if options.get("orientation", "portrait") == "landscape":
            w_mm, h_mm = h_mm, w_mm

        print_opts = PrintOptions()
        print_opts.page_width = w_mm / 10.0    # PrintOptions expects centimetres
        print_opts.page_height = h_mm / 10.0
        print_opts.margin_top = 0
        print_opts.margin_bottom = 0
        print_opts.margin_left = 0
        print_opts.margin_right = 0
        print_opts.background = True
        print_opts.scale = 1.0
        return base64.b64decode(driver.print_page(print_opts))
    finally:
        driver.quit()


# --------------------------------------------------------------------------- #
# Shared state persistence
# --------------------------------------------------------------------------- #
@eel.expose
@safe
def save_app_state(patch):
    storage.save_state({**storage.load_state(), **patch})
    return _ok()


# --------------------------------------------------------------------------- #
# Boot
# --------------------------------------------------------------------------- #
def main():
    _start_image_server()
    eel.init(os.path.join(ROOT, "web"))
    port = int(CONFIG.get("eel_port", 8000))
    start_kwargs = dict(size=(1360, 900), port=port)
    try:
        eel.start("index.html", **start_kwargs)
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception:
        # Chrome app-mode not available -> fall back to the default browser.
        eel.start("index.html", mode="default", **start_kwargs)


if __name__ == "__main__":
    main()
