"""Deterministic complaint escalation demo rules; not semantic risk scoring."""

import re

PHRASES = [
    "我要投訴",
    "我要投诉",
    "要投訴",
    "要投诉",
    "投訴你",
    "投诉你",
    "投訴佢",
    "向電視",
    "向电视",
    "搵你主管",
    "搵個主管",
    "搵個經理",
    "找你主管",
    "找你們主管",
    "找你们主管",
    "要求主管",
    "主管接聽",
    "主管接听",
    "服務咁差",
    "服务咁差",
    "服務好差",
    "非常不滿",
    "非常不满",
    "非常的不滿",
    "非常的不满",
    "非常不高興",
    "非常不高兴",
    "非常的不高興",
    "非常的不高兴",
]
NEGATION = r"(不會|不会|唔會|不想|唔想|不要|毋須)(再)?投[訴诉]"
LABELS = {"complaint": "Complaint escalation", "supervisor": "Supervisor requested", "dissatisfaction": "Strong dissatisfaction"}


def risk_type(phrase):
    if any(word in phrase for word in ("主管", "經理")):
        return "supervisor"
    if any(word in phrase for word in ("投", "電視", "电视")):
        return "complaint"
    return "dissatisfaction"


def detect_risk(text, kind=None):
    value = re.sub(r"\s+", "", text)
    if re.search(NEGATION, value):
        return None
    term = next(
        (term for term in PHRASES if term in value and (not kind or risk_type(term) == kind)), None
    )
    return (
        {"trigger": term, "risk_type": risk_type(term), "label": LABELS[risk_type(term)]}
        if term
        else None
    )
