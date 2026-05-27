-- Run this in Supabase SQL Editor once after schema.sql
create or replace function match_chunks(
    query_embedding vector(384),
    match_count     int default 5
)
returns table (
    id         bigint,
    text       text,
    source     text,
    asset      text,
    similarity float
)
language sql stable as $$
    select
        id,
        text,
        source,
        asset,
        1 - (embedding <=> query_embedding) as similarity
    from chunks
    where embedding is not null
    order by embedding <=> query_embedding
    limit match_count;
$$;
