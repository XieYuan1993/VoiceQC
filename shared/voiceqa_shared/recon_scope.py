"""Fixed transaction scope for trade reconciliation."""

from __future__ import annotations

RECON_ORDER_STATUSES = (
    "\u5df2\u4fee\u6539",  # modified
    "\u5df2\u59d4\u8a17",  # entrusted
    "\u5df2\u904e\u671f",  # expired
    "\u5df2\u64a4\u55ae",  # cancelled
)

_STATUS_ALIASES = {
    "\u5df2\u59d4\u6258": "\u5df2\u59d4\u8a17",
    "\u5df2\u8fc7\u671f": "\u5df2\u904e\u671f",
    "\u5df2\u64a4\u5355": "\u5df2\u64a4\u55ae",
}


def normalize_order_status(value: str | None) -> str:
    status = (value or "").strip()
    return _STATUS_ALIASES.get(status, status)


def recon_action_for_status(value: str | None) -> str | None:
    status = normalize_order_status(value)
    if status not in RECON_ORDER_STATUSES:
        return None
    if status == "\u5df2\u4fee\u6539":
        return "replace"
    if status == "\u5df2\u64a4\u55ae":
        return "cancel"
    return "new"
