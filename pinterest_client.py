"""
pinterest_client.py
===================

Thin wrapper around the bstoilov/py3-pinterest library.

Responsibilities:
  * Point the library at a configurable host (so it can talk to a local
    Pinterest clone instead of https://www.pinterest.com).
  * Log in (optional) using the library's Selenium cookie-harvesting flow.
  * List the current user's boards.
  * Resolve a board URL into a real board (id + name).
  * "Smart download": fetch pins newest-first and stop as soon as an already
    known pin is reached, so re-runs only pull what was added since last time.
  * Normalise raw Pinterest pin objects into the compact shape the rest of the
    app stores and renders.

All API traffic (boards / board_feed) uses py3-pinterest. Only login() and the
optional PDF export touch a real browser.
"""

from __future__ import annotations

import re
import email.utils
from datetime import datetime, timezone
from urllib.parse import urlparse

import py3pin.Pinterest as _pmod
from py3pin.Pinterest import Pinterest


# --------------------------------------------------------------------------- #
# Host configuration
# --------------------------------------------------------------------------- #
_DEFAULT_HOST = "https://www.pinterest.com"


def configure_host(base_url: str) -> None:
    """Rewrite every ``*_RESOURCE`` constant in py3pin so the library talks to
    ``base_url`` instead of the hard-coded www.pinterest.com host.

    This is what lets the tool target a self-hosted Pinterest clone that
    exposes the same REST resource endpoints.
    """
    base_url = base_url.rstrip("/")
    if base_url == _DEFAULT_HOST:
        return
    for name in dir(_pmod):
        if name.endswith("RESOURCE"):
            value = getattr(_pmod, name)
            if isinstance(value, str) and value.startswith(_DEFAULT_HOST):
                setattr(_pmod, name, value.replace(_DEFAULT_HOST, base_url, 1))


# --------------------------------------------------------------------------- #
# Host-aware Pinterest subclass (login page host is configurable)
# --------------------------------------------------------------------------- #
class ClonePinterest(Pinterest):
    """Pinterest subclass whose login() targets a configurable login URL.

    py3-pinterest hard-codes ``https://pinterest.com/login`` inside login().
    For a clone we need to drive the clone's own login page, so we reimplement
    the same Selenium steps against ``login_url``. Everything else is inherited.
    """

    def __init__(self, *args, login_url: str = f"{_DEFAULT_HOST}/login", **kwargs):
        super().__init__(*args, **kwargs)
        self._login_url = login_url

    # Selectors we try when autofilling. Kept broad so a clone whose login
    # form differs slightly from Pinterest's still gets filled in.
    _EMAIL_SELECTORS = (
        "#email", "input[name='email']", "input[type='email']",
        "input[name='username']", "input[id*='email']",
    )
    _PASSWORD_SELECTORS = (
        "#password", "input[name='password']", "input[type='password']",
        "input[id*='password']",
    )
    _SUBMIT_SELECTORS = (
        "button[type='submit']", "input[type='submit']",
        "button[data-test-id='registerFormSubmitButton']",
    )

    def login(self, headless: bool = False, wait_time: int = 180, lang: str = "en"):
        """Open a browser at the clone's login page and capture the session.

        The window is visible by default: we *try* to autofill and submit the
        form, but if the clone's DOM differs we simply wait for the user to
        finish logging in manually. Success is detected by the login form
        disappearing or the page navigating away from the login URL, after
        which every cookie is harvested into the session registry.

        Set ``headless=True`` only when you are confident the autofill
        selectors match (there is no window to complete a manual login in).
        """
        # Imported lazily so the app can run (and download from cache) on
        # machines without Selenium/Chrome installed.
        import time
        from urllib.parse import urlparse as _urlparse
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from webdriver_manager.chrome import ChromeDriverManager

        options = ChromeOptions()
        options.add_experimental_option("prefs", {"intl.accept_languages": lang})
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Keep the window from closing itself and reduce automation banners.
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        def _find(selectors):
            for sel in selectors:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    try:
                        if el.is_displayed():
                            return el
                    except Exception:
                        continue
            return None

        try:
            driver.get(self._login_url)
            time.sleep(1.0)

            # Dismiss a cookie-consent banner if the clone shows one.
            try:
                for btn in driver.find_elements(
                    By.XPATH, "//button[contains(., 'Accept')]"
                ):
                    if btn.is_displayed():
                        btn.click()
                        break
            except Exception:
                pass

            # Best-effort autofill + submit. Any failure just leaves the form
            # for the user to complete by hand in the open window.
            try:
                email_el = _find(self._EMAIL_SELECTORS)
                pw_el = _find(self._PASSWORD_SELECTORS)
                if email_el and self.email:
                    email_el.clear()
                    email_el.send_keys(self.email)
                if pw_el and self.password:
                    pw_el.clear()
                    pw_el.send_keys(self.password)
                    submit = _find(self._SUBMIT_SELECTORS)
                    if submit:
                        submit.click()
                    else:
                        pw_el.send_keys(Keys.RETURN)
            except Exception:
                pass  # user finishes manually

            # Wait for login to complete (autofilled or manual).
            start_path = _urlparse(self._login_url).path.rstrip("/")
            deadline = time.time() + wait_time
            while time.time() < deadline:
                time.sleep(1.0)
                try:
                    cur_path = _urlparse(driver.current_url).path.rstrip("/")
                except Exception:
                    cur_path = start_path
                if cur_path != start_path:
                    break  # navigated away from the login page
                if _find(self._PASSWORD_SELECTORS) is None:
                    break  # login form is gone
            else:
                raise TimeoutError(
                    "Timed out waiting for login to complete. Finish signing in "
                    "in the browser window, then try again."
                )

            time.sleep(1.5)  # let post-login cookies settle
            self.http.cookies.clear()
            for cookie in driver.get_cookies():
                self.http.cookies.set(cookie["name"], cookie["value"])
            self.registry.update_all(self.http.cookies.get_dict())

            # Best-effort: read the logged-in username straight from the page,
            # so the user doesn't have to type it. Never fatal.
            self.discovered_username = self._discover_username(driver, By)
        finally:
            driver.quit()

    def _discover_username(self, driver, By) -> str | None:
        """Try to read the current user's username from the logged-in page."""
        from urllib.parse import urlparse as _urlparse
        import time
        base_root = self._login_url.split("/login")[0].rstrip("/") or self._login_url
        reserved = {"login", "logout", "settings", "pin", "search", "ideas",
                    "today", "news", "resource", "business", "help", ""}
        try:
            driver.get(base_root + "/")
            time.sleep(1.5)
            selectors = (
                "[data-test-id='header-profile'] a",
                "a[data-test-id='user-profile-link']",
                "div[data-test-id='user-menu'] a[href^='/']",
                "header a[href^='/']",
            )
            for sel in selectors:
                for a in driver.find_elements(By.CSS_SELECTOR, sel):
                    href = (a.get_attribute("href") or "").rstrip("/")
                    seg = _urlparse(href).path.strip("/")
                    if seg and "/" not in seg and seg not in reserved:
                        return seg
        except Exception:
            pass
        return None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class PinterestClient:
    """High-level operations used by the Eel backend."""

    def __init__(self, base_url: str, login_url: str, cred_root: str,
                 login_headless: bool = False):
        configure_host(base_url)
        self.base_url = base_url.rstrip("/")
        self.login_url = login_url
        self.cred_root = cred_root
        self.login_headless = login_headless
        self._pin: ClonePinterest | None = None
        self.username: str | None = None

    # -- session ---------------------------------------------------------- #
    def _client(self, email: str = "", password: str = "",
                username: str = "") -> ClonePinterest:
        return ClonePinterest(
            email=email,
            password=password,
            username=username,
            cred_root=self.cred_root,
            login_url=self.login_url,
        )

    def login(self, email: str, password: str, username: str = "") -> dict:
        """Log in via the browser and store the session.

        Returns {"username": <str-or-empty>, "verified": <bool>}. The only thing
        that raises is a genuine login failure (Chrome/driver problem or the
        user never completing the form). Not knowing the username, or the
        optional profile check failing, is *never* fatal -- the cookies are what
        matter, and everything except listing your own boards works without a
        username anyway.
        """
        username = (username or "").strip().lstrip("@")
        pin = self._client(email=email, password=password, username=username)
        try:
            pin.login(headless=self.login_headless)
        except Exception as exc:
            raise RuntimeError(_friendly_login_error(exc)) from exc

        # Resolve the username: use what the user typed, else what we scraped
        # from the logged-in page.
        resolved = username or (getattr(pin, "discovered_username", None) or "")
        pin.username = resolved
        self._pin = pin
        self.username = resolved or None

        # Optional, non-fatal greeting check (also fills in the username if the
        # profile endpoint happens to be available and we still don't have one).
        verified = False
        if resolved:
            try:
                overview = pin.get_user_overview()
                if overview and overview.get("username"):
                    self.username = pin.username = overview["username"]
                    verified = True
            except Exception:
                pass  # cookies are still good; listing may just be limited
        return {"username": self.username or "", "verified": verified}

    def resume_session(self, username: str) -> bool:
        """Reuse cookies persisted in cred_root from a previous login.

        Returns True if a stored session exists. When we know the username we
        verify it against the profile endpoint; otherwise we simply trust the
        stored cookies (verification is best-effort, never a gate).
        """
        username = (username or "").strip()
        pin = self._client(username=username)
        # No cookies persisted -> nothing to resume.
        if not pin.http.cookies.get_dict():
            return False
        if username:
            try:
                overview = pin.get_user_overview()
                if overview and overview.get("username"):
                    self.username = pin.username = overview["username"]
            except Exception:
                pass
        self._pin = pin
        self.username = self.username or (username or None)
        return True

    @property
    def logged_in(self) -> bool:
        return self._pin is not None

    # -- boards ----------------------------------------------------------- #
    def get_boards(self) -> list[dict]:
        """Return all boards for the logged-in user."""
        if not self._pin:
            raise RuntimeError("Not logged in.")
        if not self._pin.username:
            raise RuntimeError(
                "You're signed in, but we couldn't detect your username. Type it "
                "in the Username field on the Login tab (or add boards by URL)."
            )
        boards, seen = [], set()
        self._pin.bookmark_manager.reset_bookmark(
            primary="boards", secondary=self._pin.username
        )
        while True:
            batch = self._pin.boards(page_size=50)
            if not batch:
                break
            for raw in batch:
                b = _normalize_board(raw, self.base_url)
                if b and b["id"] not in seen:
                    seen.add(b["id"])
                    boards.append(b)
        return boards

    def resolve_board_url(self, url: str) -> dict:
        """Resolve a board URL into a real board (id, name, slug, url).

        Works for any public board by listing the owning user's boards and
        matching the slug from the URL.
        """
        username, slug = _parse_board_url(url)
        if not username or not slug:
            raise ValueError("Could not read a username/board from that URL.")

        # A logged-out client is fine for reading public boards.
        pin = self._pin or self._client(username=username)
        pin.bookmark_manager.reset_bookmark(primary="boards", secondary=username)
        while True:
            batch = pin.boards(username=username, page_size=50)
            if not batch:
                break
            for raw in batch:
                b = _normalize_board(raw, self.base_url)
                if b and b["slug"] == slug:
                    return b
        raise ValueError(f"No board matching '{slug}' was found for {username}.")

    # -- pins ------------------------------------------------------------- #
    def smart_download(self, board_id: str, known_ids: set[str],
                       progress_cb=None) -> list[dict]:
        """Fetch pins for a board newest-first, stopping at the first pin we
        already have. Returns the *new* pins (newest first).

        ``known_ids`` is the set of pin ids already stored for this board.
        ``progress_cb(count)`` is called as new pins accumulate.
        """
        pin = self._pin or self._client()
        pin.bookmark_manager.reset_bookmark(primary="board_feed", secondary=board_id)

        new_pins: list[dict] = []
        while True:
            batch = pin.board_feed(board_id=board_id, page_size=100)
            if not batch:
                break
            hit_known = False
            for raw in batch:
                pid = str(raw.get("id", ""))
                if not pid:
                    continue
                if pid in known_ids:
                    # Feed is newest-first; once we reach a known pin every
                    # remaining pin is already stored -> stop.
                    hit_known = True
                    break
                norm = normalize_pin(raw)
                if norm:
                    new_pins.append(norm)
            if progress_cb:
                progress_cb(len(new_pins))
            if hit_known:
                break
        return new_pins


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _friendly_login_error(exc: Exception) -> str:
    """Translate a raw Selenium/WebDriver failure into a one-line hint."""
    text = str(exc)
    low = text.lower()
    if isinstance(exc, TimeoutError) or "timed out waiting for login" in low:
        return str(exc)
    if "chromedriver" in low or "session not created" in low or "chrome" in low:
        if "version" in low or "session not created" in low:
            return ("Chrome/ChromeDriver version mismatch. Update Google Chrome "
                    "(or delete the cached driver) and try again.")
        return ("Couldn't drive Chrome for login. Make sure Google Chrome is "
                "installed. A browser window should open — complete the login "
                "there and it will be captured.")
    if "no such element" in low or "element" in low:
        return ("The clone's login form doesn't match the fields we autofill. "
                "A browser window is open — sign in manually and it will be "
                "captured automatically.")
    # Fall back to a compact first line instead of the full stacktrace.
    return "Login failed: " + text.strip().splitlines()[0][:200]


def _slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-") or "board"


def _parse_board_url(url: str):
    """Return (username, board_slug) from a Pinterest board URL."""
    path = urlparse(url.strip()).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def _normalize_board(raw: dict, base_url: str) -> dict | None:
    bid = str(raw.get("id", ""))
    name = raw.get("name")
    if not bid or not name:
        return None
    url = raw.get("url", "")
    slug = url.strip("/").split("/")[-1] if url else _slugify(name)
    full_url = f"{base_url}{url}" if url.startswith("/") else url
    return {
        "id": bid,
        "name": name,
        "slug": slug,
        "folder": _slugify(name),
        "url": full_url,
        "pin_count": raw.get("pin_count", 0),
        "privacy": raw.get("privacy", "public"),
    }


def _parse_created(value: str) -> str | None:
    """Parse Pinterest's RFC-2822 created_at into an ISO-8601 UTC string."""
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.strptime(
                value, "%a, %d %b %Y %H:%M:%S %z"
            ).astimezone(timezone.utc).isoformat()
        except Exception:
            return None


def _best_image(images: dict) -> dict | None:
    """Pick the highest-resolution image variant from a pin's images dict."""
    if not isinstance(images, dict):
        return None
    best, best_w = None, -1
    for key, variant in images.items():
        if not isinstance(variant, dict) or not variant.get("url"):
            continue
        # "orig" is the full-resolution source; treat it as the largest.
        w = 10 ** 9 if key == "orig" else int(variant.get("width") or 0)
        if w > best_w:
            best_w, best = w, variant
    if not best:
        return None
    return {
        "url": best["url"],
        "width": int(best.get("width") or 0),
        "height": int(best.get("height") or 0),
    }


def normalize_pin(raw: dict) -> dict | None:
    """Reduce a raw Pinterest pin to the fields the app stores.

    Returns None for pins with no usable still image (e.g. some story/video
    pins), which cannot appear in a printed book.
    """
    img = _best_image(raw.get("images", {}))
    if not img:
        return None
    board = raw.get("board", {}) or {}
    return {
        "id": str(raw.get("id", "")),
        "created_at": _parse_created(raw.get("created_at", "")),
        "title": (raw.get("grid_title") or raw.get("title")
                  or (raw.get("rich_summary") or {}).get("display_name") or "").strip(),
        "description": (raw.get("description") or "").strip(),
        "link": raw.get("link") or "",
        "board_name": board.get("name", ""),
        "image": {
            "url": img["url"],
            "width": img["width"],
            "height": img["height"],
            "local": "",  # filled in once the file is downloaded
        },
    }
