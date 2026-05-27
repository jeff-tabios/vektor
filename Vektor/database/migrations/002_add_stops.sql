-- Run in Supabase SQL Editor
alter table trades
add column if not exists stop_loss   float,
add column if not exists take_profit float;
