"""
Driver headshot images — static/img/drivers/<slug>.png, keyed off a slug
derived from full_name rather than a hand-maintained per-driver dict (like
CONSTRUCTOR_LOGOS in draft.py). The driver roster turns over every season
(new drivers, retirements) far more than the 11 constructors do, so a
deterministic name->filename rule is less upkeep than a mapping that needs
a new entry every time someone joins the grid.

Rendered as a CSS background-image (not <img>) wherever it's used — a
missing file just shows an empty placeholder circle instead of a broken-
image icon, so pages don't look broken while photos are still being
collected.
"""

from __future__ import annotations

import re
import unicodedata


def driver_photo_slug(full_name: str) -> str:
    """"Nico Hülkenberg" -> "nico-hulkenberg" (accents stripped, lowercased,
    non-alphanumerics collapsed to single hyphens)."""
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def driver_photo_url(full_name: str) -> str:
    return f"/static/img/drivers/{driver_photo_slug(full_name)}.png"
