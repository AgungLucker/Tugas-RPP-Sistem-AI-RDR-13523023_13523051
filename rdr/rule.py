from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .condition import Condition


@dataclass
class Rule:
    id: str
    conditions: list[Condition]
    conclusion: str
    cornerstone: dict[str, Any] | None = None   # kasus pemicu aturan ini
    true_child: str | None = None                # dikunjungi jika aturan ini terpenuhi (kanan)
    false_child: str | None = None               # dikunjungi jika aturan ini tidak terpenuhi (kiri)

    def matches(self, case: dict[str, Any]) -> bool:
        """Semua kondisi harus terpenuhi (AND). Tanpa kondisi = aturan default."""
        return all(cond.evaluate(case) for cond in self.conditions)

    def describe(self, schema=None) -> str:
        if not self.conditions:
            return f"{self.id}: DEFAULT -> {self.conclusion}"
        body = " AND ".join(c.describe(schema) for c in self.conditions)
        return f"{self.id}: IF {body} THEN {self.conclusion}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conditions": [c.to_dict() for c in self.conditions],
            "conclusion": self.conclusion,
            "cornerstone": self.cornerstone,
            "true_child": self.true_child,
            "false_child": self.false_child,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        return cls(
            id=data["id"],
            conditions=[Condition.from_dict(c) for c in data.get("conditions", [])],
            conclusion=data["conclusion"],
            cornerstone=data.get("cornerstone"),
            true_child=data.get("true_child"),
            false_child=data.get("false_child"),
        )
