# Constructive News AI

A daily briefing of what went right in the world, plus a chat that answers questions using only verified, cited news.

Capstone project: multi-agent news pipeline + RAG. Architecture: [docs/architecture.png](docs/architecture.png)

## How it works

| Lane | When | What it does |
|---|---|---|
| A · Ingestion + curation | every 6 hours | Fetcher agents read RSS feeds, extract article text, cluster duplicates, score each story for constructive impact, summarise, chunk and embed. |
| B · Daily briefing | each morning | Builds one personalised briefing per user from the story store. |
| C · On demand | when a user opens the app | Explore and search stories; RAG chat that finds matching stories, then the best passages inside them, and answers with citations. |

## Status

- [x] Project setup, database schema, source registry
- [x] Fetcher agents (RSS + full-text extraction, robots.txt respected)
- [x] Processing + constructive scoring agent (needs a live check with a Gemini key)
- [x] RAG chat (command line and Streamlit)
- [ ] Morning briefing + personalisation
- [ ] Explore, feedback, notifications
- [ ] Evaluation report

## Setup

Requires Python 3.12 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -e .
copy .env.example .env      # then fill in DATABASE_URL and GEMINI_API_KEY
```

### Supabase

1. Create a free project at supabase.com. Keep the database password.
2. Project Settings → Database → Connection string → **Session pooler**. Copy it into `DATABASE_URL` in `.env` and put your password in place of `[YOUR-PASSWORD]`.
3. Create the tables:

```powershell
.\.venv\Scripts\python scripts\init_db.py
```

### Gemini

Create a free API key at aistudio.google.com and put it in `GEMINI_API_KEY` in `.env`.

## Running

```powershell
# Test every feed (no downloads, no database)
.\.venv\Scripts\python -m gooddaynews.ingest.run --check-feeds

# Fetch a few articles and print them (no database)
.\.venv\Scripts\python -m gooddaynews.ingest.run --dry-run --limit 3

# Fetch and save new articles
.\.venv\Scripts\python -m gooddaynews.ingest.run

# Score a few live articles and print the decisions (needs GEMINI_API_KEY, no database)
.\.venv\Scripts\python -m gooddaynews.process.run --preview 2

# Process new articles from the database into stories
.\.venv\Scripts\python -m gooddaynews.process.run

# Chat in the terminal (one question, or interactive with no question)
.\.venv\Scripts\python -m gooddaynews.rag.cli "What conservation news is there from India?"

# Chat in the browser at http://localhost:8501
.\.venv\Scripts\python -m streamlit run streamlit_app.py

# Tests (offline; a fake LLM stands in for Gemini)
.\.venv\Scripts\python -m pytest
```

### How processing works

1. **Triage**: one cheap LLM call screens up to 25 headlines and drops obvious non-candidates (crime, conflict, ads, gossip). When unsure, it keeps the item.
2. **Group**: each candidate is embedded. It joins a story from the last 72 hours if it is similar enough, otherwise it is clustered with other articles about the same event.
3. **Assess**: one LLM call per new story picks the pillar, scores 6 dimensions, and writes the headline, summary, why it matters and key facts. Source credibility, the 7th dimension, comes from `config/sources.yaml`, not the LLM.
4. **Decide**: weighted total from `config/scoring.yaml`. A story is kept only if it is constructive, not opinion, in a known pillar, and at or above the threshold.
5. **Guard**: key facts whose numbers do not appear in the source text are dropped.
6. **Prepare**: kept stories are embedded, and their full text is chunked and embedded for the chat.
7. **Retention**: chunks and full text older than 30 days are deleted.

Rejected stories are stored with `status = 'rejected'` and the reason, for review and evaluation.

### How the chat works

1. **Interpret**: a cheap LLM call rewrites follow-ups into standalone questions and pulls out the intent, keywords, dates ("this week") and any category or country.
2. **Stories**: semantic search plus keyword search over stories, within the filters. A story counts as relevant from similarity 0.62. On real data, answerable questions scored 0.72–0.77 and unanswerable ones 0.52–0.58. If nothing is relevant, the chat refuses without calling the answer model.
3. **Passages**: semantic search over the full-text chunks of the chosen stories only, at most 3 per story.
4. **Rerank**: relevance (fused ranks) 60%, recency 25% (halves every 7 days), constructive score 15%, plus a boost for the user's topics.
5. **Generate**: the answer model sees only numbered sources and must cite every claim, give dates, quote at most once, and use the exact refusal sentence when the sources don't answer.
6. **Cite**: citations that don't match a provided source are removed. The rest link to the stories and their original articles.

Off-topic requests (recipes, poems, homework) get a short scope message. Follow-ups keep context within a session, and the story open on screen always stays in the answer. Settings are in `config/rag.yaml`.

Free-tier notes: `gemini-3.5-flash` allows 20 requests a day, so each task lists several models in `.env` and moves to the next when one is used up. Answers take about 10–40 seconds on the free tier, mostly while the model "thinks"; `GEMINI_ANSWER_THINKING=low` limits that.

## Configuration

| File | Purpose |
|---|---|
| `config/sources.yaml` | Source registry: feeds, fetcher type, country, credibility (1–5). Set `active: false` to pause a source. |
| `config/scoring.yaml` | Weights for the 7 scoring dimensions, keep threshold, diversity limits. Editable without code changes. |
| `config/pillars.yaml` | The 8 pillars and their subcategories. |

## Notes

- The database driver is `pg8000` (pure Python). Windows Smart App Control blocks the compiled `psycopg` driver on the development machine.
- Full article text is stored only for processing and chat grounding. It is never shown to users and is deleted after 30 days.
