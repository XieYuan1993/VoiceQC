"""Starter evaluator configuration shared by seeding and project creation."""

from __future__ import annotations

DEFAULT_EVAL_CRITERIA = [
    {
        "key": "identity_verification",
        "name": "Client identity verified",
        "description": (
            "The broker must verify the caller's identity before accepting any order: "
            "full name plus account number (or at least an account suffix). Recognising "
            "the caller's voice alone does NOT count. Pass only if an explicit identity "
            "check happens before the first order is accepted."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 1,
    },
    {
        "key": "order_readback",
        "name": "Order read back and confirmed",
        "description": (
            "Before submitting each order the broker must read back the complete details "
            "- stock name or code, buy/sell side, quantity, and price (or market order) - "
            "and obtain the client's explicit confirmation. Pass only if every order in "
            "the call was read back and confirmed."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 2,
    },
    {
        "key": "no_unauthorized_advice",
        "name": "No unauthorised investment advice",
        "description": (
            "The broker must not give unsolicited investment advice, price predictions, "
            "or buy/sell recommendations. Factual information (current price, order "
            "status, product features) is allowed. Fail if the broker volunteers "
            "recommendations or predictions."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "critical",
        "weight": 2.0,
        "sort_order": 3,
    },
    {
        "key": "risk_disclosure",
        "name": "Risk disclosure where required",
        "description": (
            "If the client asks for an opinion, or the order involves derivatives or "
            "leveraged products, the broker must give an appropriate risk warning. For "
            "plain equity orders where no advice is sought, this criterion passes by default."
        ),
        "category": "compliance",
        "score_type": "pass_fail",
        "severity": "warning",
        "weight": 1.0,
        "sort_order": 4,
    },
    {
        "key": "professional_conduct",
        "name": "Professional conduct",
        "description": (
            "The broker is courteous and professional throughout: a proper greeting "
            "identifying the firm, polite tone, no over-familiarity that compromises "
            "professionalism, and a proper closing. Score 1 (poor) to 5 (exemplary)."
        ),
        "category": "quality",
        "score_type": "scale_1_5",
        "severity": "info",
        "weight": 1.0,
        "sort_order": 5,
    },
]

DEFAULT_EXTRACTION_FIELDS = [
    {
        "key": "stock_code",
        "label": "Stock code",
        "field_type": "string",
        "scope": "trade",
        "is_system": True,
        "sort_order": 1,
    },
    {
        "key": "stock_name",
        "label": "Stock name",
        "field_type": "string",
        "scope": "trade",
        "is_system": True,
        "sort_order": 2,
    },
    {
        "key": "side",
        "label": "Side",
        "field_type": "enum",
        "enum_options": ["buy", "sell", "amend", "cancel", "unknown"],
        "scope": "trade",
        "is_system": True,
        "sort_order": 3,
    },
    {
        "key": "quantity",
        "label": "Quantity",
        "field_type": "number",
        "scope": "trade",
        "is_system": True,
        "sort_order": 4,
    },
    {
        "key": "price",
        "label": "Price",
        "field_type": "number",
        "scope": "trade",
        "is_system": True,
        "sort_order": 5,
    },
    {
        "key": "price_type",
        "label": "Price type",
        "field_type": "enum",
        "enum_options": ["market", "limit", "unknown"],
        "scope": "trade",
        "is_system": True,
        "sort_order": 6,
    },
    {
        "key": "client_name",
        "label": "Client name",
        "field_type": "string",
        "scope": "trade",
        "is_system": True,
        "sort_order": 7,
    },
    {
        "key": "client_account",
        "label": "Client account",
        "field_type": "string",
        "scope": "trade",
        "is_system": True,
        "sort_order": 8,
    },
    {
        "key": "call_purpose",
        "label": "Call purpose",
        "field_type": "enum",
        "enum_options": ["place_order", "amend_or_cancel", "inquiry", "complaint", "other"],
        "scope": "call",
        "is_system": False,
        "sort_order": 10,
        "description": "The caller's primary purpose.",
    },
    {
        "key": "complaint_mentioned",
        "label": "Complaint mentioned",
        "field_type": "boolean",
        "scope": "call",
        "is_system": False,
        "sort_order": 11,
        "description": "True if the client expresses dissatisfaction or complains.",
    },
]
