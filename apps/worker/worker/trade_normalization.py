"""Normalize LLM trade output and recover explicit evidence safely."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

SecurityCandidate = tuple[str, str | None]
MAX_SECURITY_CANDIDATES = 100

_CODE_KEYS = (
    "stock_code",
    "security_code",
    "securityCode",
    "instrument_code",
    "instrumentCode",
    "symbol",
    "ticker",
    "code",
)
_NAME_KEYS = (
    "stock_name_raw",
    "stock_name",
    "security_name",
    "securityName",
    "instrument_name",
    "instrumentName",
    "name",
)
_MARKET_TERMS = ("market", "mkt", "市價", "市价", "市價盤", "市价盘")
_LIMIT_TERMS = ("limit", "限價", "限价")


def normalize_stock_code(value: Any) -> str | None:
    if value is None:
        return None
    raw = unicodedata.normalize("NFKC", str(value)).strip().upper()
    if not raw:
        return None
    compact = re.sub(r"\s+", "", raw)
    hk_match = re.fullmatch(r"(?:HK|HKG|SEHK)[:.-]?(\d{1,5})(?:\.HK)?", compact)
    if hk_match:
        return str(int(hk_match.group(1)))
    if compact.isdigit():
        return str(int(compact))
    ticker = re.sub(r"[^A-Z0-9.-]", "", compact)
    return ticker or None


def _first_value(source: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", normalized)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def infer_price_type(value: Any, evidence: Any = None) -> str:
    folded = unicodedata.normalize("NFKC", str(value or "")).casefold()
    evidence_folded = unicodedata.normalize("NFKC", str(evidence or "")).casefold()
    combined = f"{folded} {evidence_folded}"
    if any(term in combined for term in _MARKET_TERMS):
        return "market"
    if any(term in combined for term in _LIMIT_TERMS):
        return "limit"
    return folded if folded in {"market", "limit", "unknown"} else "unknown"


def recover_stock_code(
    evidence: Any,
    candidates: Iterable[SecurityCandidate],
    *,
    quantity: Any = None,
    price: Any = None,
) -> str | None:
    """Return one candidate explicitly present in evidence, otherwise None.

    Candidate restriction prevents arbitrary transcript numbers from becoming
    securities. Quantity/price values are excluded to avoid treating "2000
    shares" as stock 2000.
    """
    text = unicodedata.normalize("NFKC", str(evidence or ""))
    if not text.strip():
        return None
    folded = _fold(text)
    numeric_tokens = {
        str(int(token))
        for token in re.findall(r"(?<![\d.])\d{1,5}(?![\d.])", text)
    }
    excluded: set[str] = set()
    for value in (quantity, price):
        number = _number(value)
        if number is not None and number.is_integer() and number >= 0:
            excluded.add(str(int(number)))

    matches: set[str] = set()
    for raw_code, raw_name in candidates:
        code = normalize_stock_code(raw_code)
        if not code:
            continue
        if code.isdigit():
            code_match = code in numeric_tokens and code not in excluded
            if code_match and len(code) < 3:
                code_match = bool(
                    re.search(
                        rf"(?:HK|HKG|SEHK|STOCK|股票|股份)\s*[:#.-]?\s*0*{re.escape(code)}(?!\d)",
                        text,
                        flags=re.IGNORECASE,
                    )
                )
        else:
            code_match = bool(
                re.search(
                    rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])",
                    text.upper(),
                )
            )
        name = _fold(raw_name)
        name_match = bool(name and len(name) >= 2 and name in folded)
        if code_match or name_match:
            matches.add(code)
    return next(iter(matches)) if len(matches) == 1 else None


def normalize_trade_item(
    raw: Mapping[str, Any],
    candidates: Iterable[SecurityCandidate] = (),
) -> dict[str, Any]:
    """Map common provider aliases to the canonical trade schema."""
    item = dict(raw)
    nested = next(
        (
            value
            for key in ("stock", "security", "instrument")
            if isinstance((value := item.get(key)), Mapping)
        ),
        {},
    )
    code_value = _first_value(item, _CODE_KEYS) or _first_value(nested, _CODE_KEYS)
    name_value = _first_value(item, _NAME_KEYS) or _first_value(nested, _NAME_KEYS)
    scalar_stock = item.get("stock")
    if code_value is None and scalar_stock is not None and not isinstance(scalar_stock, Mapping):
        normalized_scalar = normalize_stock_code(scalar_stock)
        if normalized_scalar and (
            normalized_scalar.isdigit() or re.search(r"[A-Z]", normalized_scalar)
        ):
            code_value = scalar_stock
        elif name_value is None:
            name_value = scalar_stock

    evidence = _first_value(item, ("evidence_quote", "evidence", "quote", "source_text"))
    quantity = _first_value(item, ("quantity", "qty", "shares", "order_quantity"))
    price = _first_value(item, ("price", "limit_price", "order_price"))
    code = normalize_stock_code(code_value)
    if code is None:
        code = recover_stock_code(evidence, candidates, quantity=quantity, price=price)

    item["stock_code"] = code
    item["stock_name_raw"] = str(name_value).strip() if name_value is not None else None
    item["quantity"] = quantity
    item["price"] = price
    item["price_type"] = infer_price_type(
        _first_value(item, ("price_type", "priceType", "order_type", "orderType")),
        evidence,
    )
    client_name = _first_value(
        item, ("client_name_raw", "client_name", "clientName", "customer_name")
    )
    client_account = _first_value(
        item,
        ("client_account_raw", "client_account", "clientAccount", "account", "account_number"),
    )
    if client_name is not None or "client_name_raw" in item:
        item["client_name_raw"] = client_name
    if client_account is not None or "client_account_raw" in item:
        item["client_account_raw"] = client_account
    item["time_in_call_ms"] = _first_value(
        item, ("time_in_call_ms", "time_ms", "timestamp_ms", "approx_ms")
    )
    item["evidence_quote"] = str(evidence).strip() if evidence is not None else None
    return item
