-- Run in Supabase SQL Editor
alter table trades
add column if not exists status       text    default 'open',
add column if not exists closed_price float,
add column if not exists pnl          float;
