# RUN_NOTES — FitFindr

The code, mock data, planning loop, error handling, and tests are all real and
verified offline (9/9 tests pass; the happy path, the retry-recovery path, and
the no-results error branch were all run). The only content produced **without**
the live LLM is the two LLM-generated example strings in the README — the
**outfit suggestion** and the **fit card** in the "Example interaction" section.
They're labeled representative. Everything else (decision logs, listing, price
check, error message, guard text) is verbatim from a real run.

## Step 1 — Run it with a key

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste a real Groq key
pytest tests/                 # expect all tests to pass
python agent.py               # happy path + no-results branch in the terminal
python app.py                 # open the printed URL
```

## Step 2 — Reconcile the README

- [ ] Run the happy-path query (*"vintage graphic tee under $30, size M"*) in the
      app with **Example wardrobe** selected. Copy the real **outfit suggestion**
      and **fit card** the LLM produces and paste them over the two
      "representative" lines in the README's Example interaction. Then you can
      delete the note that says those two lines are representative.
- [ ] Confirm the decision log, listing line, and price-check string still match
      the README verbatim (they should — those are deterministic).
- [ ] Run `create_fit_card` twice on the same item and confirm the captions
      differ (the spec requires varied output). If they're identical, the LLM
      temperature in `tools.py` (currently 0.95) can go higher.

## Step 3 — Confirm the three failure modes on camera (Milestone 5)

Run each and confirm a graceful response, not a crash:
```bash
python -c "from tools import search_listings; print(search_listings('designer ballgown','XXS',5))"   # -> []
python -c "from tools import search_listings, suggest_outfit; from utils.data_loader import get_empty_wardrobe; r=search_listings('vintage graphic tee',None,50); print(suggest_outfit(r[0], get_empty_wardrobe()))"   # -> general advice
python -c "from tools import search_listings, create_fit_card; r=search_listings('vintage graphic tee',None,50); print(create_fit_card('', r[0]))"   # -> '[fit card unavailable] ...'
```
Screenshot at least one for the demo.

## Step 4 — The two things only you can do

- [ ] **Fork + commits.** Fork the FitFindr starter repo, clone it, copy these
      files in (keep `.env` out of git — it's gitignored), and commit per
      milestone: data + data_loader → planning.md → tools.py → agent.py → app.py
      + tests → README. Your fork URL is the first deliverable.
- [ ] **Demo video (3–5 min).** With `python app.py` running, screen-record:
      a full happy-path interaction (search → price → outfit → fit card) while
      narrating which tool runs and why; point out state passing (the item from
      search flows into the outfit step without re-entry — the decision-log panel
      makes this visible); and at least one triggered failure (the impossible
      query showing the retry attempts and the graceful error message is the
      strongest one). Loom free caps videos at 5 minutes, so keep it tight.

## Note on data realism

The listings and wardrobe are plausible, self-consistent **mock** data (the
project supplies mock data by design — no real marketplace is scraped). The
prices, platforms, and styles are realistic but invented for the exercise.
