"""
storage.py
=========

Everything that touches disk:

  * Per-board pin JSON at  output/{folder}/{folder}-pins.json
  * Downloaded image files at  output/{folder}/images/{pin_id}.{ext}
  * App state (board selection + book options) at  state.json

Pins are always stored newest-first. Smart download prepends the freshly
fetched pins to the existing list.
"""

from __future__ import annotations

import json
import os
import mimetypes
from urllib.parse import urlparse

import requests


class Storage:
    def __init__(self, output_dir: str, state_path: str):
        self.output_dir = output_dir
        self.state_path = state_path
        os.makedirs(self.output_dir, exist_ok=True)

    # -- paths ------------------------------------------------------------ #
    def board_dir(self, folder: str) -> str:
        return os.path.join(self.output_dir, folder)

    def pins_path(self, folder: str) -> str:
        return os.path.join(self.board_dir(folder), f"{folder}-pins.json")

    def images_dir(self, folder: str) -> str:
        return os.path.join(self.board_dir(folder), "images")

    # -- pin files -------------------------------------------------------- #
    def load_board(self, folder: str) -> dict | None:
        path = self.pins_path(folder)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    def known_pin_ids(self, folder: str) -> set[str]:
        data = self.load_board(folder)
        if not data:
            return set()
        return {str(p.get("id")) for p in data.get("pins", []) if p.get("id")}

    def save_board(self, board: dict, pins: list[dict], fetched_at: str) -> None:
        os.makedirs(self.board_dir(board["folder"]), exist_ok=True)
        payload = {
            "board": board,
            "fetched_at": fetched_at,
            "count": len(pins),
            "pins": pins,
        }
        with open(self.pins_path(board["folder"]), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def merge_new_pins(self, board: dict, new_pins: list[dict],
                       fetched_at: str) -> int:
        """Prepend newly downloaded pins (newest-first) ahead of existing ones.

        Returns the total pin count after merging.
        """
        existing = self.load_board(board["folder"])
        old_pins = existing["pins"] if existing else []
        merged = new_pins + old_pins
        self.save_board(board, merged, fetched_at)
        return len(merged)

    # -- images ----------------------------------------------------------- #
    def download_image(self, folder: str, pin: dict) -> str:
        """Download a pin's image if not already present.

        Returns the image path relative to output_dir (for serving/rendering),
        and records it on the pin as ``image.local``.
        """
        images_dir = self.images_dir(folder)
        os.makedirs(images_dir, exist_ok=True)

        url = pin["image"]["url"]
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        filename = f'{pin["id"]}{ext}'
        abspath = os.path.join(images_dir, filename)
        relpath = os.path.relpath(abspath, self.output_dir).replace(os.sep, "/")

        if not os.path.exists(abspath):
            resp = requests.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(abspath, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
        pin["image"]["local"] = relpath
        return relpath

    # -- discovery -------------------------------------------------------- #
    def list_downloaded_boards(self) -> list[dict]:
        """Scan output/ for boards that already have a pins file."""
        results = []
        if not os.path.isdir(self.output_dir):
            return results
        for folder in sorted(os.listdir(self.output_dir)):
            data = self.load_board(folder)
            if data and data.get("board"):
                b = dict(data["board"])
                b["count"] = data.get("count", len(data.get("pins", [])))
                results.append(b)
        return results

    def load_pins(self, folder: str) -> list[dict]:
        data = self.load_board(folder)
        return data["pins"] if data else []

    # -- app state -------------------------------------------------------- #
    def load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}

    def save_state(self, state: dict) -> None:
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
