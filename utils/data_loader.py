"""
data_loader.py — helpers for loading the mock data.

The tools and agent should use these functions rather than reading the JSON
files directly, so there's one place that knows where the data lives and what
shape it has.
"""

import json
import os

# Absolute path to the data/ folder, resolved relative to THIS file so the
# loaders work no matter what directory the app/agent is launched from.
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_LISTINGS_PATH = os.path.join(_DATA_DIR, "listings.json")
_WARDROBE_SCHEMA_PATH = os.path.join(_DATA_DIR, "wardrobe_schema.json")


def load_listings():
    """Return the full list of listing dicts from data/listings.json.

    Each listing has: id, title, description, category, style_tags (list),
    size, condition, price (float), colors (list), brand, platform.
    """
    with open(_LISTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_wardrobe_schema():
    with open(_WARDROBE_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_example_wardrobe():
    """Return a populated example wardrobe: {"items": [ {item}, ... ]}.

    Use this when testing the normal styling path — suggest_outfit can pair a
    new item against these pieces.
    """
    return _load_wardrobe_schema()["example_wardrobe"]


def get_empty_wardrobe():
    """Return an empty wardrobe: {"items": []}.

    Use this to test suggest_outfit's empty-wardrobe failure mode — the agent
    must still return general styling advice instead of crashing.
    """
    return {"items": []}
