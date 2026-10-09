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
- [x] Morning briefing + personalisation (demo email sign-in; password sign-in still to do)
- [x] Explore, search, story pages, feedback, notifications (email via SMTP, or a local outbox)
- [x] Evaluation report ([docs/evaluation_report.md](docs/evaluation_report.md))

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

# Build briefings for users whose briefing time has passed (or one user now)
.\.venv\Scripts\python -m gooddaynews.briefing.run
.\.venv\Scripts\python -m gooddaynews.briefing.run --user demo@example.com

# The whole pipeline in one go: fetch -> process -> briefings (schedule this every few hours)
.\.venv\Scripts\python scripts\daily.py

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

### How the morning briefing works

1. **Candidates**: published stories from the last 24 hours. If there are too few for the chosen length, the window widens to 48 and then 72 hours, and the briefing says so.
2. **Rank**: constructive score, boosted when the story's pillar matches the user's topics (+35%), its country matches their geography (+25%), and by their likes and dislikes on that pillar.
3. **Diversify**: at most 2 stories per pillar and 3 per country (`config/scoring.yaml`). If that leaves the briefing short, the best skipped stories fill it.
4. **Trim**: Quick 3, Standard 7, Deep 12 stories (`config/briefing.yaml`).
5. **Close**: one cheap LLM call writes "Something to think about today" using only the stories' own content. If it fails, the briefing still appears without it.
6. **Cache**: saved per user per day. If today's briefing can't be built, the most recent earlier one is shown with a note.

Topics from onboarding map to pillars in `config/briefing.yaml`; for example, "AI" maps to Innovation and Science.

The web app has three pages: Today's Briefing (the landing page), Ask AI, and My preferences. "Ask AI" on a story opens the chat about that story. Sign-in is a demo by email only (`demo@example.com` is the test profile); real password sign-in comes before launch.

### Feedback, Explore and notifications

- **Story actions** (every card): 👍 / 👎, Save, Share (headline, one-line summary, source and a link back to the app, never the article), and More: hide or follow the topic, follow the source. Each action is stored as a row in `feedback`; the latest row per item is its current state. Hidden topics are left out of briefings and Explore; followed topics and sources are boosted.
- **Explore**: browse by category, geography and date, sorted by newest, most constructive, most liked or "For you". Search mixes keywords (all words must match) with meaning, ignoring words like "good" and "news" that describe every story here, and understands "today", "this week" and "this month". It makes no AI calls apart from one embedding, and falls back to keywords if that fails. The **Saved** tab lists saved stories.
- **Story page** at `/story?id=…`: key facts, all sources, why the story was included, related stories and Ask AI. Viewing it records a `read` event.
- **Notifications**: the hourly `gooddaynews.briefing.run` sends one email per user per day, once their briefing time has passed, on the days they chose (daily, weekdays or weekends). Each send is logged in `notifications`, so it's never sent twice, and failures are retried up to 3 times. Without `SMTP_*` settings in `.env`, emails are written to `data/outbox/` instead, so nothing is sent during development. Streamlit can't do phone push notifications, so email stands in for them.

Not yet tracked: clicks on "Read the original", because Streamlit opens external links directly without telling the app.

### Evaluation

Results: [docs/evaluation_report.md](docs/evaluation_report.md). In short: 29/30 questions passed. Accuracy,
citation correctness, recency and unanswerable handling scored 100% on the automatic checks and the judge, with one
date slip found by a manual check. Story scoring agrees with hand labels 75% of the time.

- `eval/questions.yaml`: 30 questions with expected outcomes (answer, refuse, off-topic, or a false premise to reject), the stories each answer must cite, required facts, countries and dates.
- `python -m gooddaynews.evaluation.run`: asks every question in a fresh conversation with the date fixed, and saves each result as it goes (`--resume` continues after a quota stop). It checks the outcome, the cited stories, required facts, countries, dates and any number missing from the sources. A judge model grades accuracy and citations, and never grades an answer written by its own model.
- `python -m gooddaynews.evaluation.report <run.jsonl> [baseline.jsonl]`: writes the report, adds the keep/reject (`eval/classification_labels.yaml`) and duplicate (`eval/dedupe_labels.yaml`) checks, and includes the hand-written `eval/findings.md`.
- Raw results stay local (`eval/results/` is git-ignored) because they contain source passages.

Free-tier notes: embeddings are capped at 1,000 texts a day, which limits daily processing volume. `gemini-3.5-flash` allows 20 requests a day, so each task lists several models in `.env` and moves to the next when one is used up. Answers take about 10–40 seconds on the free tier, mostly while the model "thinks"; `GEMINI_ANSWER_THINKING=low` limits that. Embeddings have a per-minute token limit, so requests are split to about 12,000 tokens and paced to stay under 25,000 a minute (`EMBED_BATCH_TOKENS`, `EMBED_TOKENS_PER_MINUTE`).

## Configuration

| File | Purpose |
|---|---|
| `config/sources.yaml` | Source registry: feeds, fetcher type, country, credibility (1–5). Set `active: false` to pause a source. |
| `config/scoring.yaml` | Weights for the 7 scoring dimensions, keep threshold, diversity limits. Editable without code changes. |
| `config/pillars.yaml` | The 8 pillars and their subcategories. |

## Notes

- The database driver is `pg8000` (pure Python). Windows Smart App Control blocks the compiled `psycopg` driver on the development machine.
- Full article text is stored only for processing and chat grounding. It is never shown to users and is deleted after 30 days.
