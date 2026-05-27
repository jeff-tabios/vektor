-- Run in Supabase SQL Editor
alter table trades
add column if not exists ibkr_order_id  int,
add column if not exists ibkr_executed  boolean default false;
