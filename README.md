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
- [ ] RAG chat
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

## Configuration

| File | Purpose |
|---|---|
| `config/sources.yaml` | Source registry: feeds, fetcher type, country, credibility (1–5). Set `active: false` to pause a source. |
| `config/scoring.yaml` | Weights for the 7 scoring dimensions, keep threshold, diversity limits. Editable without code changes. |
| `config/pillars.yaml` | The 8 pillars and their subcategories. |

## Notes

- The database driver is `pg8000` (pure Python). Windows Smart App Control blocks the compiled `psycopg` driver on the development machine.
- Full article text is stored only for processing and chat grounding. It is never shown to users and is deleted after 30 days.
