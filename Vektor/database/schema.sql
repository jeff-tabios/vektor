-- enable pgvector
create extension if not exists vector;

-- ── core data ──────────────────────────────────────────

-- news and market data chunks
create table chunks (
    id          bigserial primary key,
    text        text not null,
    embedding   vector(384),
    source      text,
    source_url  text,
    asset       text,        -- 'BTC', 'ETH', 'general'
    created_at  timestamp default now()
);

-- full text search column for hybrid search
alter table chunks
add column tsv tsvector
generated always as (to_tsvector('english', text)) stored;

-- HNSW index for vector search
create index on chunks
using hnsw (embedding vector_cosine_ops)
with (m = 16, ef_construction = 64);

-- GIN index for keyword search
create index on chunks using gin(tsv);

-- ── eval system ────────────────────────────────────────

-- eval questions (timeless + rolling)
create table eval_questions (
    id                  bigserial primary key,
    query               text not null,
    expected_chunk_id   bigint references chunks(id) on delete set null,
    question_type       text default 'rolling',  -- 'timeless' or 'rolling'
    expires_at          timestamp,               -- null for timeless
    created_at          timestamp default now()
);

-- ── metrics ────────────────────────────────────────────

-- ingestion run results
create table ingestion_runs (
    id                          bigserial primary key,
    chunks_added                int,
    chunks_deleted              int,
    eval_questions_generated    int,
    recall_at_5                 float,
    duration_ms                 float,
    created_at                  timestamp default now()
);

-- per trade eval results
create table trade_evals (
    id              bigserial primary key,
    query           text,
    decision        text,        -- BUY / SELL / HOLD
    faithfulness    float,
    retrieval_ms    float,
    rerank_ms       float,
    llm_ms          float,
    total_ms        float,
    created_at      timestamp default now()
);

-- ── system config ──────────────────────────────────────

create table system_config (
    key         text primary key,
    value       text,
    updated_at  timestamp default now()
);

-- default config values
insert into system_config values
    ('retrieval_k',               '20',      now()),
    ('rerank_k',                  '5',       now()),
    ('recall_threshold',          '0.70',    now()),
    ('faithfulness_threshold',    '0.75',    now()),
    ('p95_latency_threshold',     '3000',    now()),
    ('prompt_template',           'default', now()),
    ('chunk_size_tokens',         '500',     now()),
    ('chunk_overlap_tokens',      '50',      now());

-- ── self healing log ───────────────────────────────────

create table healing_log (
    id              bigserial primary key,
    trigger         text,
    action          text,
    before_value    text,
    after_value     text,
    success         boolean,
    created_at      timestamp default now()
);

-- ── trades ─────────────────────────────────────────────

create table trades (
    id              bigserial primary key,
    asset           text,        -- 'BTC', 'ETH'
    decision        text,        -- 'BUY', 'SELL', 'HOLD'
    reasoning       text,
    confidence      float,
    persona         text,        -- 'taleb', 'saliba'
    paper_trade     boolean default true,
    price_at_trade  float,
    created_at      timestamp default now()
);

-- ── cleanup functions ──────────────────────────────────

create or replace function delete_stale_chunks()
returns void as $$
    delete from chunks
    where created_at < now() - interval '7 days';
$$ language sql;

create or replace function delete_expired_evals()
returns void as $$
    delete from eval_questions
    where expires_at < now()
    and question_type = 'rolling';
$$ language sql;
