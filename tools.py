"""
tools.py — FitFindr's tools.

Each tool has a clearly defined signature, a single job, and its own failure
handling. Two tools are deterministic (search_listings, estimate_price_fairness)
and two call the Groq LLM (suggest_outfit, create_fit_card). The LLM tools
degrade gracefully: if Groq is unreachable or no key is set, they fall back to a
deterministic response rather than crashing, so the agent stays useful.

Tools:
  search_listings(description, size, max_price)   -> list[dict]
  suggest_outfit(new_item, wardrobe)              -> str
  create_fit_card(outfit, new_item)               -> str
  estimate_price_fairness(item, listings=None)    -> dict   (stretch tool)
"""

import os
import re
import statistics

from dotenv import load_dotenv
from utils.data_loader import load_listings

load_dotenv()  # read GROQ_API_KEY from .env

LLM_MODEL = "llama-3.3-70b-versatile"

# Words we ignore when scoring search relevance — they carry no signal.
_STOPWORDS = {
    "the", "a", "an", "for", "and", "with", "under", "size", "looking",
    "want", "need", "find", "me", "some", "im", "i'm", "that", "this",
    "really", "kind", "of", "in", "to", "my",
}


# ---------------------------------------------------------------------------
# Tool 1: search_listings  (deterministic)
# ---------------------------------------------------------------------------
def search_listings(description, size=None, max_price=None):
    """Search the mock listings dataset and return matching items.

    Args:
        description (str): free-text description, e.g. "vintage graphic tee".
            Tokenized and matched against each listing's title, description,
            style_tags, category, and brand.
        size (str | None): exact size to require, e.g. "M" or "32". None = any.
        max_price (float | None): inclusive price ceiling. None = no ceiling.

    Returns:
        list[dict]: matching listing dicts (each with the original fields plus a
        "relevance" int), sorted by relevance desc then price asc. Returns an
        empty list [] when nothing matches — never raises for "no results".

    Failure mode: no matches -> returns []. The agent is responsible for telling
    the user and (optionally) retrying with loosened constraints.
    """
    listings = load_listings()

    # Tokenize the query into meaningful words.
    tokens = [t for t in re.findall(r"[a-z0-9']+", (description or "").lower())
              if t not in _STOPWORDS and len(t) >= 2]

    matches = []
    for item in listings:
        # Hard filters first.
        if size is not None and str(item.get("size", "")).lower() != str(size).lower():
            continue
        if max_price is not None and item.get("price", 0) > max_price:
            continue

        # Relevance = how many query tokens appear in the item's searchable text.
        haystack = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            " ".join(item.get("style_tags", [])),
            item.get("category", ""),
            item.get("brand", ""),
        ]).lower()
        relevance = sum(1 for t in tokens if t in haystack)

        # If the user gave a description, require at least one token to hit.
        # If the description was empty, every size/price match counts.
        if tokens and relevance == 0:
            continue

        item_copy = dict(item)
        item_copy["relevance"] = relevance
        matches.append(item_copy)

    matches.sort(key=lambda x: (-x["relevance"], x["price"]))
    return matches


# ---------------------------------------------------------------------------
# Groq helper shared by the two LLM tools
# ---------------------------------------------------------------------------
def _chat(system_prompt, user_prompt, temperature):
    """Call Groq and return the message text. Raises on any failure so the
    caller's try/except can fall back."""
    key = os.environ.get("GROQ_API_KEY")  # check first so the deterministic
    if not key:                            # tools/tests need neither a key nor
        raise RuntimeError("GROQ_API_KEY not set")  # the groq package installed
    from groq import Groq  # imported lazily
    client = Groq(api_key=key)
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return completion.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Tool 2: suggest_outfit  (LLM, with deterministic fallback)
# ---------------------------------------------------------------------------
def suggest_outfit(new_item, wardrobe):
    """Suggest one complete outfit pairing a new item with the user's wardrobe.

    Args:
        new_item (dict): a listing dict (as returned by search_listings).
        wardrobe (dict): {"items": [ {type, descriptor, colors, style_tags,
            fit}, ... ]}. May be empty.

    Returns:
        str: a 2-3 sentence styling suggestion. Always a non-empty string.

    Failure modes:
      - Empty wardrobe: returns general styling advice built around the item
        (and says so), rather than crashing.
      - LLM/network/key error: returns a deterministic rule-based suggestion so
        the agent stays useful.
    """
    items = (wardrobe or {}).get("items", [])
    tags = ", ".join(new_item.get("style_tags", [])) or "versatile"
    system = ("You are a sharp, encouraging personal stylist for secondhand "
              "fashion. Be concrete and concise — name specific pieces.")

    try:
        if items:
            wardrobe_desc = "; ".join(
                f"{i.get('descriptor', i.get('type', 'item'))}"
                f" ({', '.join(i.get('colors', []))})" for i in items
            )
            user = (
                f"New find: {new_item['title']} — {new_item['description']} "
                f"(style: {tags}). My wardrobe: {wardrobe_desc}. "
                "Suggest ONE complete outfit that pairs the new find with "
                "specific pieces from my wardrobe. 2-3 sentences, name which of "
                "my pieces to wear, and give one concrete styling tip."
            )
        else:
            user = (
                f"New find: {new_item['title']} — {new_item['description']} "
                f"(style: {tags}). You don't know what's in my wardrobe yet. "
                "Suggest ONE complete outfit built around this find using common "
                "staples. 2-3 sentences, one styling tip, and note that these "
                "are general ideas since you don't know my wardrobe yet."
            )
        return _chat(system, user, temperature=0.7)
    except Exception as exc:
        return _fallback_outfit(new_item, items, reason=str(exc))


def _fallback_outfit(new_item, items, reason=""):
    """Deterministic styling suggestion used when the LLM is unavailable."""
    title = new_item.get("title", "this piece")
    if items:
        pieces = [i.get("descriptor", i.get("type", "")) for i in items]
        bottoms = next((p for p in pieces if "jean" in p or "pant" in p or "skirt" in p), pieces[0])
        shoes = next((p for p in pieces if "sneaker" in p or "boot" in p or "shoe" in p), None)
        suggestion = f"Pair the {title.lower()} with your {bottoms}"
        if shoes:
            suggestion += f" and {shoes}"
        suggestion += ". Keep the silhouette balanced — if the new piece is boxy, let the rest sit closer to the body. (Offline styling suggestion.)"
        return suggestion
    return (
        f"Build around the {title.lower()}: anchor it with simple staples like "
        "well-fitting jeans and clean sneakers, then add one layer (a jacket or "
        "overshirt) for shape. These are general ideas since no wardrobe was "
        "provided yet. (Offline styling suggestion.)"
    )


# ---------------------------------------------------------------------------
# Tool 3: create_fit_card  (LLM, with guard + deterministic fallback)
# ---------------------------------------------------------------------------
def create_fit_card(outfit, new_item):
    """Generate a short, shareable caption for a complete outfit.

    Args:
        outfit (str): the styling suggestion (from suggest_outfit).
        new_item (dict): the listing dict the outfit is built around.

    Returns:
        str: a casual, social-media-style caption. Varies for different inputs.

    Failure modes:
      - Empty/blank outfit: returns a clear error message string (does NOT call
        the LLM and does NOT crash).
      - LLM/network/key error: returns a deterministic templated caption.
    """
    if not outfit or not outfit.strip():
        return ("[fit card unavailable] No outfit was provided, so there's "
                "nothing to caption. Try generating an outfit suggestion first.")

    title = new_item.get("title", "this piece")
    platform = new_item.get("platform", "")
    price = new_item.get("price")
    system = ("You write short, fun, first-person social captions for thrifted "
              "outfits — the kind someone posts with a mirror pic. Lowercase, "
              "casual, 1-2 sentences, at most one emoji. No hashtag spam.")
    user = (
        f"Item: {title}"
        + (f" (${price:.0f} on {platform})" if price is not None else "")
        + f". The look: {outfit}. Write one caption."
    )
    try:
        return _chat(system, user, temperature=0.95)  # high temp = varied output
    except Exception:
        return _fallback_fit_card(new_item)


def _fallback_fit_card(new_item):
    """Deterministic caption used when the LLM is unavailable. Varies by item."""
    title = new_item.get("title", "this piece").lower()
    platform = new_item.get("platform", "the app")
    price = new_item.get("price")
    deal = f" for ${price:.0f}" if price is not None else ""
    return (f"thrifted this {title} off {platform.lower()}{deal} and it's "
            "already my favorite thing in the rotation 🖤 (offline caption)")


# ---------------------------------------------------------------------------
# Tool 4: estimate_price_fairness  (deterministic stretch tool)
# ---------------------------------------------------------------------------
def estimate_price_fairness(item, listings=None):
    """Judge whether an item's price is fair vs. comparable listings.

    Args:
        item (dict): a listing dict (must have "category" and "price").
        listings (list[dict] | None): the pool to compare against. Defaults to
            the full dataset via load_listings().

    Returns:
        dict: {
          "verdict": "great deal" | "fair" | "slightly high" | "overpriced" | "unknown",
          "item_price": float,
          "median_price": float | None,
          "comparable_count": int,
          "message": str
        }

    Failure mode: fewer than 2 comparable listings -> verdict "unknown" with an
    explanatory message, rather than dividing by zero or guessing.
    """
    if listings is None:
        listings = load_listings()

    category = item.get("category")
    price = item.get("price")
    comps = [l for l in listings
             if l.get("category") == category and l.get("id") != item.get("id")]

    if price is None or len(comps) < 2:
        return {
            "verdict": "unknown",
            "item_price": price,
            "median_price": None,
            "comparable_count": len(comps),
            "message": (f"Not enough comparable {category or 'similar'} listings "
                        "to judge this price."),
        }

    median = statistics.median(l["price"] for l in comps)
    ratio = price / median if median else 1.0
    if ratio <= 0.85:
        verdict = "great deal"
    elif ratio <= 1.10:
        verdict = "fair"
    elif ratio <= 1.30:
        verdict = "slightly high"
    else:
        verdict = "overpriced"

    return {
        "verdict": verdict,
        "item_price": price,
        "median_price": median,
        "comparable_count": len(comps),
        "message": (f"${price:.0f} vs a median of ${median:.0f} across "
                    f"{len(comps)} comparable {category} listings — {verdict}."),
    }
