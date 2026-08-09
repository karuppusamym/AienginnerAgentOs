"""Deterministic PII classification and output protection for governed data paths."""
from __future__ import annotations

import re
from typing import Any

PII_PATTERNS: dict[str, tuple[str, ...]] = {
    "email": ("email", "e_mail", "mail_address"),
    "phone": ("phone", "mobile", "telephone", "tel"),
    "person_name": ("first_name", "last_name", "full_name", "customer_name", "given_name", "surname"),
    "address": ("address", "street", "postal", "zip_code", "postcode"),
    "date_of_birth": ("date_of_birth", "birth_date", "dob"),
    "government_id": ("ssn", "social_security", "national_id", "passport"),
    "payment_card": ("card_number", "credit_card", "debit_card", "pan"),
    "bank_account": ("bank_account", "account_number", "iban", "routing_number"),
}

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SSN = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_PHONE = re.compile(r"^\+?[\d ()-]{7,}$")
_CARD = re.compile(r"^(?:\d[ -]?){13,19}$")


def pii_category(name: str, sample: Any = None) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    for category, markers in PII_PATTERNS.items():
        if any(marker in normalized for marker in markers):
            return category
    if isinstance(sample, str):
        value = sample.strip()
        if _EMAIL.fullmatch(value):
            return "email"
        if _SSN.fullmatch(value):
            return "government_id"
        if _CARD.fullmatch(value.replace(" ", "")):
            return "payment_card"
        if _PHONE.fullmatch(value) and sum(char.isdigit() for char in value) >= 7:
            return "phone"
    return None


def annotate_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated = []
    for column in columns:
        item = dict(column)
        category = pii_category(str(item.get("name") or item.get("source_name") or ""))
        if category:
            item["sensitivity"] = "pii"
            item["pii_category"] = category
            item["masking"] = "partial"
        annotated.append(item)
    return annotated


def mask_pii_value(value: Any, category: str | None) -> Any:
    if value is None or not category:
        return value
    text = str(value)
    if not text:
        return value
    if category == "email":
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "[PII masked]"
    if category in {"government_id", "payment_card", "bank_account"}:
        digits = re.sub(r"\D", "", text)
        return f"****{digits[-4:]}" if len(digits) >= 4 else "[PII masked]"
    if category == "phone":
        digits = re.sub(r"\D", "", text)
        return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "[PII masked]"
    return f"{text[:1]}***" if len(text) > 1 else "[PII masked]"


def protect_rows(columns: list[str], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    categories = {
        column: pii_category(
            column,
            next((row.get(column) for row in rows if row.get(column) not in (None, "")), None),
        )
        for column in columns
    }
    protected = [
        {key: mask_pii_value(value, categories.get(key)) for key, value in row.items()}
        for row in rows
    ]
    return protected, [column for column, category in categories.items() if category]
