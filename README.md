# FitFindr — a multi-tool thrifting agent

FitFindr takes one natural-language request ("vintage graphic tee under $30,
size M") and runs a small agent that searches secondhand listings, checks
whether the price is fair, styles the top match against your wardrobe, and
writes a shareable caption. The agent decides which tools to call based on what
each one returns — if the search comes back empty it retries with looser
filters, and if it's still empty it explains why and stops instead of styling
an item that doesn't exist.

## Setup and run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your free Groq key (same as Project 1)
python app.py                 # open the URL it prints (usually http://localhost:7860)
```

Other entry points: `python agent.py` runs a happy-path and a no-results case
in the terminal; `pytest tests/` runs the tool/loop tests.

## Tool inventory

The documented inputs and returns match the function signatures in `tools.py`.

### `search_listings(description, size=None, max_price=None)` → `list[dict]`
- **description** (`str`) — free-text query, tokenized and matched against each
  listing's title, description, style_tags, category, and brand.
- **size** (`str | None`) — exact size to require, e.g. `"M"` or `"32"`; `None` = any.
- **max_price** (`float | None`) — inclusive price ceiling; `None` = no ceiling.
- **Returns** — list of matching listing dicts (original fields plus an integer
  `relevance`), sorted by relevance desc then price asc; `[]` if nothing matches.
- **Purpose** — find candidate items from the mock dataset.

### `suggest_outfit(new_item, wardrobe)` → `str`
- **new_item** (`dict`) — a listing dict (normally the top search result).
- **wardrobe** (`dict`) — `{"items": [ {type, descriptor, colors, style_tags, fit}, … ]}`; may be empty.
- **Returns** — a 2–3 sentence styling suggestion (always non-empty).
- **Purpose** — pair the new item with the user's existing pieces. Calls the LLM.

### `create_fit_card(outfit, new_item)` → `str`
- **outfit** (`str`) — the styling suggestion from `suggest_outfit`.
- **new_item** (`dict`) — the listing the outfit is built around.
- **Returns** — a short, casual, shareable caption (varies per input).
- **Purpose** — turn the outfit into something you'd actually post. Calls the LLM.

### `estimate_price_fairness(item, listings=None)` → `dict`  *(stretch tool)*
- **item** (`dict`) — a listing dict (needs `category` and `price`).
- **listings** (`list[dict] | None`) — comparison pool; defaults to the full dataset.
- **Returns** — `{"verdict", "item_price", "median_price", "comparable_count", "message"}`; verdict ∈ *great deal / fair / slightly high / overpriced / unknown*.
- **Purpose** — judge price against comparable listings in the same category.

## How the planning loop works

`run_agent(query, wardrobe)` in `agent.py` is the loop. It does not call the
tools in a fixed sequence — it branches on what each step returns:

1. **Parse** the query into `{description, size, max_price}` (`parse_query`).
2. **Search** with those params.
3. **If the search is empty, retry** with progressively looser filters: first
   drop the size filter, then drop size and raise the budget by 50%, then drop
   both filters. The first non-empty retry wins and the adjustment is recorded.
4. **If it's still empty, stop**: set `session["error"]` to a specific,
   actionable message and return early. `suggest_outfit` and `create_fit_card`
   are not called.
5. Otherwise, set `selected_item = results[0]` and continue:
   **price check** → **suggest outfit** → **create fit card**.

So an impossible query exits after step 4 having only searched; a query that
needs loosening searches several times and tells the user what changed; a normal
query runs all four tools. Each decision is appended to `session["log"]`, which
the UI shows in a "What the agent did" panel.

## State management

Everything for one request lives in a single `session` dict. Each tool writes
its result there and later tools read from it, so the user never re-enters
anything:

- `parse_query` writes `search_params`.
- the search writes `search_results` and `selected_item`.
- `selected_item` is then **passed into both** `estimate_price_fairness` and
  `suggest_outfit` (→ `price_assessment`, `outfit_suggestion`).
- `outfit_suggestion` is **passed straight into** `create_fit_card` (→ `fit_card`).
- `adjustments`, `error`, and `log` capture the control flow for display.

You can see the hand-off directly: in `agent.py`'s `__main__`, the same
`selected_item` dict set at step 5 is the object passed into `suggest_outfit`,
and the exact string in `outfit_suggestion` is what goes into `create_fit_card`.

## Error handling (with concrete results from testing)

Each tool owns its failure mode; none crash the agent.

- **`search_listings` — no matches.** `search_listings("designer ballgown",
  "XXS", 5)` returns `[]` (verified in tests). In the full agent, the impossible
  query retries three times then returns this exact message: *"I couldn't find
  any listings matching that, even after loosening the size and price filters.
  Try a broader description (e.g. just 'denim jacket'), a higher budget, or a
  different size."* — and `fit_card` stays `None`.
- **`search_listings` — retry recovers.** For *"vintage graphic tee size XXL
  under $30"* the first search returns 0; the agent drops the size filter, finds
  7 matches, selects the top one (Vintage Champion Spellout Tee), and notes
  *"results came from a loosened search (removed the size filter)."*
- **`suggest_outfit` — empty wardrobe.** With `get_empty_wardrobe()` the tool
  still returns a complete suggestion built around the item from staples and
  flags it as general advice, rather than raising.
- **`create_fit_card` — empty outfit.** `create_fit_card("", item)` returns
  *"[fit card unavailable] No outfit was provided, so there's nothing to caption.
  Try generating an outfit suggestion first."* — no exception (verified in tests).
- **`estimate_price_fairness` — no comparables.** An item in a one-off category
  returns `verdict: "unknown"` with `median_price: None` (verified in tests).
- **LLM unavailable (both LLM tools).** If Groq is unreachable or no key is set,
  `suggest_outfit` and `create_fit_card` fall back to deterministic responses
  (a rule-based pairing and a templated caption) so the agent still produces a
  useful result instead of erroring.

## Example interaction

Request: *"I'm looking for a vintage graphic tee under $30, size M."*
(wardrobe = the example wardrobe: baggy wide-leg jeans, chunky platform
sneakers, oversized denim jacket, black beanie)

**Decision log (actual output):**
```
• Parsed request → description='vintage graphic tee', size=M, max_price=30.0.
• Called search_listings → 3 result(s).
• Selected top match → Faded Band Tee ($22, Depop, Good).
• Called estimate_price_fairness → fair.
• Called suggest_outfit with the selected item and 4 wardrobe piece(s).
• Called create_fit_card with the outfit suggestion and the item.
```
**Listing found:** Faded Band Tee — $22, Depop, Good condition, size M.
**Price check (actual):** "$22 vs a median of $22 across 4 comparable tee listings — fair. Vintage faded graphic band tee with cracked screen print. Soft, broken-in cotton with a relaxed boxy fit."
**Outfit suggestion:** "Pair the faded band tee with your baggy wide-leg jeans and chunky platform sneakers. Keep the silhouette balanced — if the new piece is boxy, let the rest sit closer to the body. (Offline styling suggestion.)"
**Fit card (LLM, representative):** "thrifted this faded band tee off depop for $22 and it's already my favorite thing in the rotation 🖤 (offline caption)"

> The outfit suggestion and fit card are produced by Groq's
> `llama-3.3-70b-versatile`, so the exact wording varies per run; the examples
> above are representative. Everything else here (the log, the listing, the
> price-check string) is verbatim from a real run. With no API key, those two
> lines fall back to a deterministic suggestion/caption instead.

## Spec reflection

**One way the spec helped.** Writing the Planning Loop section in `planning.md`
as numbered branches — "if results is empty, retry; if still empty, set error
and return early before the LLM tools" — meant the implementation was almost a
transcription. Because the early-return rule was written down, it was obvious in
testing that the no-results case must leave `fit_card = None`, which became a
direct assertion in `tests/test_tools.py`.

**One way the implementation diverged.** The spec originally had query parsing
as a vague "extract the search terms" step. In practice the wardrobe description
("I mostly wear baggy jeans…") and the search request live in the same sentence,
so I split the design: `parse_query` deterministically pulls only
`description / size / max_price` from the request, and the wardrobe comes from
the user's saved profile (the app's wardrobe selector), not the sentence. That
kept the search/branch logic testable without an LLM and avoided conflating the
two kinds of information.

## AI usage

**Instance 1 — `search_listings`.** I gave Claude the Tool 1 spec block (the
three parameters, the sorted-list return with a `relevance` field, and the
"return `[]`, never raise" failure mode) and asked it to implement filtering on
top of `load_listings()`. Its first version matched on whole-string containment,
which missed multi-word queries; I changed it to tokenize the description and
score by token overlap, and added the rule that a non-empty description must
match at least one token so size/price-only noise doesn't leak in. I verified
with the three search tests before moving on.

**Instance 2 — the planning loop.** I gave Claude the Planning Loop section and
the architecture diagram and asked it to implement `run_agent`. The draft called
all tools in sequence and only checked for empty results at the end. I rewrote
it to branch immediately after the search, added the `_loosen` retry generator,
and moved the error return ahead of the LLM tools so they can't be called with
empty input. I confirmed the branch with `test_agent_no_results_branch`
(`error` set, `fit_card`/`outfit_suggestion`/`selected_item` all `None`).
