from typing import Optional
from supabase import Client


def _get_config(supabase: Client) -> dict:
    rows = supabase.table("system_config").select("key,value").execute().data or []
    return {r["key"]: r["value"] for r in rows}


def _set_config(supabase: Client, key: str, value: str):
    supabase.table("system_config").update({"value": value}).eq("key", key).execute()


def _log(supabase: Client, trigger: str, action: str, before: str, after: str, success: bool):
    supabase.table("healing_log").insert({
        "trigger": trigger,
        "action": action,
        "before_value": before,
        "after_value": after,
        "success": success,
    }).execute()


def heal(supabase: Client, recall=None):  # type: Optional[float]
    config = _get_config(supabase)
    recall_threshold = float(config.get("recall_threshold", 0.70))
    current_k = int(config.get("retrieval_k", 20))

    if recall is not None and recall < recall_threshold:
        new_k = min(current_k + 5, 50)
        if new_k != current_k:
            _set_config(supabase, "retrieval_k", str(new_k))
            _log(
                supabase,
                trigger=f"recall@5={recall:.2%} < threshold={recall_threshold:.2%}",
                action="increase retrieval_k",
                before=str(current_k),
                after=str(new_k),
                success=True,
            )
            print(f"Healer: retrieval_k {current_k} → {new_k}")
