"""
agent.py — FitFindr's planning loop and session state.

run_agent(query, wardrobe) parses a natural-language request, then runs a
planning loop that decides which tools to call based on what each one returns.
The agent does NOT call every tool unconditionally: if the search comes back
empty it first retries with loosened constraints, and if it's still empty it
sets an error and returns WITHOUT calling suggest_outfit or create_fit_card.

State lives in one `session` dict. Each tool writes its result there, and later
tools read from it (e.g. selected_item flows into suggest_outfit; the resulting
suggestion flows into create_fit_card). `session["log"]` records the agent's
decisions so the UI and the demo can show the reasoning.
"""

import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    estimate_price_fairness,
)
from utils.data_loader import get_example_wardrobe


# ---------------------------------------------------------------------------
# Query parsing — turn natural language into search parameters.
# Deterministic on purpose so the search/branch decisions are testable.
# ---------------------------------------------------------------------------
def parse_query(query):
    """Extract {description, size, max_price} from a free-text request.

    "vintage graphic tee under $30, size M" ->
        {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}
    """
    text = query or ""

    # max_price: "$30", "under 30", "under $30", "30 dollars".
    max_price = None
    m = re.search(r"(?:under|below|max|<)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    if not m:
        m = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:dollars|bucks)", text, re.I)
    if m:
        max_price = float(m.group(1))

    # size: "size M", "size 32", or a standalone letter size token.
    size = None
    m = re.search(r"size\s*[:\-]?\s*(XXS|XS|S|M|L|XL|XXL|\d{1,2})", text, re.I)
    if m:
        size = m.group(1).upper()

    # description: take the first sentence (the request itself), then strip the
    # filler, the price phrase, and the size phrase, leaving the garment words.
    first_sentence = re.split(r"[.\n]", text, maxsplit=1)[0]
    desc = first_sentence
    # Strip a leading pronoun ("I", "I'm", "I am"), then request verbs.
    desc = re.sub(r"^\s*(?:i'?m|i\s+am|i)\b", " ", desc, flags=re.I)
    desc = re.sub(r"\b(?:looking for|searching for|search for|want|need|find me|find|show me|get me)\b", " ", desc, flags=re.I)
    # Strip the price and size phrases (already captured above).
    desc = re.sub(r"(?:under|below|max|<)\s*\$?\s*\d+(?:\.\d+)?", " ", desc, flags=re.I)
    desc = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", desc)
    desc = re.sub(r"\d+(?:\.\d+)?\s*(?:dollars|bucks)", " ", desc, flags=re.I)
    desc = re.sub(r"size\s*[:\-]?\s*(?:XXS|XS|S|M|L|XL|XXL|\d{1,2})", " ", desc, flags=re.I)
    # Tidy punctuation and any leading article.
    desc = re.sub(r"[,;]", " ", desc)
    desc = re.sub(r"^\s*(?:a|an|some|the)\s+", " ", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip()

    return {"description": desc, "size": size, "max_price": max_price}


def _loosen(params):
    """Yield progressively looser search params for the retry fallback, each
    paired with a human-readable note about what changed."""
    if params.get("size") is not None:
        yield ({**params, "size": None}, "removed the size filter")
    if params.get("max_price") is not None:
        bumped = round(params["max_price"] * 1.5, 2)
        yield ({**params, "size": None, "max_price": bumped},
               f"removed the size filter and raised the budget to ${bumped:.0f}")
    yield ({**params, "size": None, "max_price": None},
           "removed the size and price filters")


def _new_session(query, wardrobe):
    return {
        "query": query,
        "wardrobe": wardrobe,
        "search_params": None,
        "search_results": [],
        "selected_item": None,
        "price_assessment": None,
        "outfit_suggestion": None,
        "fit_card": None,
        "adjustments": [],   # what the retry loosened, if anything
        "error": None,
        "log": [],           # human-readable decision trail
    }


# ---------------------------------------------------------------------------
# The planning loop
# ---------------------------------------------------------------------------
def run_agent(query, wardrobe=None):
    """Run the full FitFindr planning loop and return the session dict."""
    if wardrobe is None:
        wardrobe = get_example_wardrobe()
    session = _new_session(query, wardrobe)
    log = session["log"].append

    # --- Step 1: parse the request -----------------------------------------
    params = parse_query(query)
    session["search_params"] = params
    log(f"Parsed request → description='{params['description']}', "
        f"size={params['size']}, max_price={params['max_price']}.")

    # --- Step 2: search, with retry-on-empty (the planning decision) -------
    results = search_listings(**params)
    log(f"Called search_listings → {len(results)} result(s).")

    if not results:
        # The agent reacts to the empty result instead of marching on: it
        # retries with progressively looser constraints before giving up.
        for loosened, note in _loosen(params):
            if loosened == params:
                continue
            retry = search_listings(**loosened)
            log(f"No matches; retried after I {note} → {len(retry)} result(s).")
            if retry:
                results = retry
                session["search_params"] = loosened
                session["adjustments"].append(note)
                break

    # --- Error branch: still nothing → stop here, do NOT call other tools --
    if not results:
        session["error"] = (
            "I couldn't find any listings matching that, even after loosening "
            "the size and price filters. Try a broader description (e.g. just "
            "'denim jacket'), a higher budget, or a different size."
        )
        log("Still empty after retries → set error and returned early. "
            "suggest_outfit and create_fit_card were NOT called.")
        return session

    # --- Step 3: select the top match into session state -------------------
    session["search_results"] = results
    session["selected_item"] = results[0]
    top = results[0]
    log(f"Selected top match → {top['title']} (${top['price']:.0f}, "
        f"{top['platform']}, {top['condition']}).")
    if session["adjustments"]:
        log("Note: results came from a loosened search "
            f"({'; '.join(session['adjustments'])}).")

    # --- Step 4: price-fairness check (stretch tool) -----------------------
    session["price_assessment"] = estimate_price_fairness(top)
    log(f"Called estimate_price_fairness → {session['price_assessment']['verdict']}.")

    # --- Step 5: suggest an outfit (selected_item + wardrobe flow in) ------
    n_items = len(wardrobe.get("items", []))
    session["outfit_suggestion"] = suggest_outfit(top, wardrobe)
    log(f"Called suggest_outfit with the selected item and "
        f"{n_items} wardrobe piece(s).")

    # --- Step 6: build the shareable fit card (suggestion flows in) --------
    session["fit_card"] = create_fit_card(session["outfit_suggestion"], top)
    log("Called create_fit_card with the outfit suggestion and the item.")

    return session


# ---------------------------------------------------------------------------
# Manual run: a happy path and the no-results branch.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("CASE 1 — happy path")
    s = run_agent("I'm looking for a vintage graphic tee under $30, size M.")
    for line in s["log"]:
        print("  •", line)
    print("\n  selected_item:", s["selected_item"] and s["selected_item"]["title"])
    print("  price:", s["price_assessment"]["message"])
    print("  outfit_suggestion:", s["outfit_suggestion"])
    print("  fit_card:", s["fit_card"])
    print("  error:", s["error"])

    print("\n" + "=" * 70)
    print("CASE 2 — no results (error branch)")
    s2 = run_agent("I want a designer ballgown under $5, size XXS.")
    for line in s2["log"]:
        print("  •", line)
    print("\n  error:", s2["error"])
    print("  fit_card (should be None):", s2["fit_card"])
