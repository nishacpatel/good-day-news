-- Constructive News AI: database schema (Supabase Postgres + pgvector)
-- Safe to re-run: every statement uses IF NOT EXISTS.
-- Embedding size must match EMBED_DIM in .env (768 for gemini-embedding-001 at reduced size).

create extension if not exists vector;

-- ---------- Source registry (PRD 13) ----------
create table if not exists sources (
    id            serial primary key,
    name          text not null,
    domain        text not null unique,
    feed_url      text not null,
    fetcher       text not null check (fetcher in ('news', 'science', 'official')),
    country       text,
    credibility   smallint not null check (credibility between 1 and 5),
    is_primary    boolean not null default false,
    active        boolean not null default true,
    last_checked  timestamptz,
    last_error    text
);

-- ---------- Stories: one row per real-world event (PRD 15) ----------
create table if not exists stories (
    id                  bigserial primary key,
    status              text not null default 'published' check (status in ('published', 'rejected')),
    headline            text not null,
    summary             text,
    why_it_matters      text,
    key_facts           jsonb not null default '[]',
    pillar              text,
    subcategory         text,
    country             text,
    place               text,
    entities            jsonb not null default '[]',
    published_at        timestamptz,
    score               numeric(4, 2),
    score_breakdown     jsonb not null default '{}',
    verification_level  text,
    why_included        text,
    source_count        int not null default 1,
    embedding           vector(768),
    tsv                 tsvector generated always as (
                            to_tsvector('english', coalesce(headline, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(why_it_matters, ''))
                        ) stored,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists stories_published_idx on stories (status, published_at desc);
create index if not exists stories_pillar_idx on stories (pillar);
create index if not exists stories_tsv_idx on stories using gin (tsv);
create index if not exists stories_embedding_idx on stories using hnsw (embedding vector_cosine_ops);

-- ---------- Raw articles (internal only, never shown to users) ----------
create table if not exists articles (
    id             bigserial primary key,
    source_id      int not null references sources(id),
    url            text not null unique,
    title          text not null,
    feed_summary   text,
    body           text,                -- full text, deleted after the retention window
    published_at   timestamptz,
    fetched_at     timestamptz not null default now(),
    status         text not null default 'new' check (status in ('new', 'processed', 'rejected', 'error')),
    status_reason  text,
    story_id       bigint references stories(id) on delete set null
);
create index if not exists articles_status_idx on articles (status);
create index if not exists articles_story_idx on articles (story_id);

-- ---------- Chunk index: full-text passages for kept stories (30-day retention) ----------
create table if not exists chunks (
    id           bigserial primary key,
    story_id     bigint not null references stories(id) on delete cascade,
    article_id   bigint not null references articles(id) on delete cascade,
    chunk_index  int not null,
    content      text not null,
    embedding    vector(768),
    tsv          tsvector generated always as (to_tsvector('english', content)) stored,
    created_at   timestamptz not null default now(),
    unique (article_id, chunk_index)
);
create index if not exists chunks_story_idx on chunks (story_id);
create index if not exists chunks_tsv_idx on chunks using gin (tsv);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);

-- ---------- Users, preferences, feedback (PRD 18, 24) ----------
create table if not exists user_profiles (
    id              uuid primary key default gen_random_uuid(),
    email           text not null unique,
    display_name    text,
    topics          text[] not null default '{}',
    geography       text[] not null default '{}',
    briefing_length text not null default 'standard' check (briefing_length in ('quick', 'standard', 'deep')),
    notify_time     time not null default '06:00',
    timezone        text not null default 'Asia/Kolkata',
    notify_enabled  boolean not null default true,
    created_at      timestamptz not null default now()
);

create table if not exists feedback (
    id          bigserial primary key,
    user_id     uuid not null references user_profiles(id) on delete cascade,
    story_id    bigint references stories(id) on delete cascade,
    action      text not null check (action in ('like', 'dislike', 'save', 'unsave', 'share', 'hide_topic', 'follow_topic', 'follow_source', 'open_source', 'read')),
    value       text,
    created_at  timestamptz not null default now()
);
create index if not exists feedback_user_idx on feedback (user_id, created_at desc);
-- Toggle actions (unlike, unhide_topic, ...) so the latest row per item is the current state.
alter table feedback drop constraint if exists feedback_action_check;
alter table feedback add constraint feedback_action_check check (action in (
    'like', 'unlike', 'dislike', 'undislike', 'save', 'unsave', 'share',
    'hide_topic', 'unhide_topic', 'follow_topic', 'unfollow_topic', 'follow_source', 'unfollow_source',
    'open_source', 'read'));

alter table user_profiles add column if not exists frequency text not null default 'daily';
alter table user_profiles drop constraint if exists user_profiles_frequency_check;
alter table user_profiles add constraint user_profiles_frequency_check check (frequency in ('daily', 'weekdays', 'weekends'));

-- ---------- Notifications sent (PRD 21): at most one per user, day and channel ----------
create table if not exists notifications (
    id         bigserial primary key,
    user_id    uuid not null references user_profiles(id) on delete cascade,
    for_date   date not null,
    channel    text not null,
    status     text not null check (status in ('sent', 'failed')),
    subject    text,
    error      text,
    attempts   int not null default 1,
    sent_at    timestamptz not null default now(),
    unique (user_id, for_date, channel)
);

create table if not exists briefings (
    id          bigserial primary key,
    user_id     uuid not null references user_profiles(id) on delete cascade,
    for_date    date not null,
    story_ids   bigint[] not null,
    intro       text,
    thought     text,
    created_at  timestamptz not null default now(),
    unique (user_id, for_date)
);
alter table briefings add column if not exists window_hours int not null default 24;

-- ---------- Run log (orchestrator) ----------
create table if not exists run_log (
    id           bigserial primary key,
    stage        text not null,
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    counts       jsonb not null default '{}',
    errors       jsonb not null default '[]'
);
