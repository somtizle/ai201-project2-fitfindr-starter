"""
test_tools.py — pytest tests for FitFindr's tools and planning loop.

These cover the deterministic behavior and every failure mode that doesn't
require the live LLM:
  - search_listings: results, empty, price filter, size filter
  - estimate_price_fairness: a verdict and the not-enough-comparables case
  - create_fit_card: the empty-outfit guard (returns before any LLM call)
  - parse_query: pulls description / size / max_price out of free text
  - run_agent: the no-results error branch stops before the LLM tools

Run from the repo root:  pytest tests/
"""

from tools import (
    search_listings,
    create_fit_card,
    estimate_price_fairness,
)
from agent import run_agent, parse_query
from utils.data_loader import load_listings


# --- search_listings -------------------------------------------------------
def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []          # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    results = search_listings("tee", size="M", max_price=None)
    assert all(item["size"] == "M" for item in results)


# --- estimate_price_fairness ----------------------------------------------
def test_price_fairness_verdict():
    listings = {x["id"]: x for x in load_listings()}
    result = estimate_price_fairness(listings["L004"])   # cheap $15 tee
    assert result["verdict"] in {"great deal", "fair", "slightly high", "overpriced"}
    assert result["item_price"] == 15.0
    assert result["comparable_count"] >= 2


def test_price_fairness_no_comparables():
    lonely = {"id": "ZZZ", "category": "spacesuit", "price": 999.0}
    result = estimate_price_fairness(lonely)
    assert result["verdict"] == "unknown"
    assert result["median_price"] is None


# --- create_fit_card empty-outfit guard (no LLM call) ---------------------
def test_fit_card_empty_outfit_guard():
    item = load_listings()[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert "fit card unavailable" in card.lower()   # graceful, not an exception


# --- parse_query -----------------------------------------------------------
def test_parse_query_full():
    params = parse_query("I'm looking for a vintage graphic tee under $30, size M.")
    assert params["description"] == "vintage graphic tee"
    assert params["size"] == "M"
    assert params["max_price"] == 30.0


# --- run_agent no-results branch (must NOT reach the LLM tools) -----------
def test_agent_no_results_branch():
    session = run_agent("I want a designer ballgown under $5, size XXS.")
    assert session["error"] is not None
    assert session["fit_card"] is None
    assert session["outfit_suggestion"] is None
    assert session["selected_item"] is None
