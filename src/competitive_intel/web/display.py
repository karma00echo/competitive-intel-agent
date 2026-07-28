"""Human-readable fact values for API and HTML presentation."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class FactDisplayFormatter:
    PERIODS = {"MONTH": "月", "YEAR": "年", "DAY": "天"}
    UNITS = {"USER": "用户", "WORKSPACE": "工作区", "ORGANIZATION": "组织"}

    def format(
        self,
        category: str,
        value: Any,
        *,
        fact_key: str = "",
        value_text: str | None = None,
    ) -> str:
        data = decode_json(value)
        if category == "PRICE" and isinstance(data, dict):
            return self._price(data)
        if category == "PLAN" and isinstance(data, dict):
            name = data.get("plan_name") or data.get("name") or self._label(fact_key)
            details = data.get("description") or data.get("availability")
            return f"{name}：{details}" if details else str(name)
        if category == "FEATURE" and isinstance(data, dict):
            name = data.get("feature_name") or data.get("name") or self._label(fact_key)
            detail = data.get("description") or data.get("status")
            return f"{name}：{detail}" if detail else str(name)
        if category == "POSITIONING" and isinstance(data, dict):
            return str(
                data.get("positioning")
                or data.get("description")
                or data.get("value")
                or self._compact(data)
            )
        if category == "PRODUCT_UPDATE" and isinstance(data, dict):
            title = data.get("title") or data.get("update_name") or self._label(fact_key)
            date = data.get("date") or data.get("published_at")
            return f"{title}（{date}）" if date else str(title)
        if value_text:
            return value_text
        if isinstance(data, dict):
            return self._compact(data)
        if isinstance(data, list):
            return "、".join(str(item) for item in data)
        return str(data if data is not None else "未公开")

    def format_change(
        self, category: str, fact_key: str, old_value: Any, new_value: Any
    ) -> tuple[str, str]:
        return (
            self.format(category, old_value, fact_key=fact_key),
            self.format(category, new_value, fact_key=fact_key),
        )

    def _price(self, data: dict[str, Any]) -> str:
        plan = data.get("plan_name") or data.get("name") or "公开价格"
        amount = data.get("amount")
        currency = data.get("currency") or ""
        if amount is None:
            return f"{plan}：未发现公开金额"
        amount_text = self._number(amount)
        period = self.PERIODS.get(str(data.get("billing_period", "")).upper())
        unit = self.UNITS.get(str(data.get("billing_unit", "")).upper())
        suffix = ""
        if unit:
            suffix += f" / {unit}"
        if period:
            suffix += f" / {period}"
        commitment = str(data.get("billing_commitment", "")).upper()
        commitment_text = "，按年计费" if commitment == "ANNUAL_BILLING" else ""
        return f"{plan}：{amount_text} {currency}{suffix}{commitment_text}".strip()

    @staticmethod
    def _number(value: Any) -> str:
        try:
            number = Decimal(str(value))
            return format(number.normalize(), "f")
        except Exception:
            return str(value)

    @staticmethod
    def _label(fact_key: str) -> str:
        return fact_key.rsplit(".", 1)[-1].replace("_", " ") or "未命名"

    @staticmethod
    def _compact(data: dict[str, Any]) -> str:
        return "；".join(f"{key}：{value}" for key, value in data.items())
