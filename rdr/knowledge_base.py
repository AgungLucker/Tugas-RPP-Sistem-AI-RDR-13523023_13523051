from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .condition import Condition, validate_conjunction
from .rule import Rule

DEFAULT_RECOMMENDATIONS = ["Yogyakarta", "Bali", "Malang", "Raja Ampat", "Labuan Bajo"]


class RuleRejected(Exception):
    """Aturan baru tidak valid (mis. tidak ada kondisi pembeda)."""


@dataclass
class InferenceResult:
    conclusion: str
    path: list[tuple[str, bool]]      # (id aturan, terpenuhi?)
    last_satisfied: Rule              # aturan yang memberi kesimpulan
    last_evaluated: Rule              # aturan terakhir yang diuji (titik penempelan)
    last_evaluated_satisfied: bool

    @property
    def branch(self) -> str:
        """Cabang tempat aturan baru ditempel pada last_evaluated."""
        return "true" if self.last_evaluated_satisfied else "false"

    def path_text(self) -> str:
        return " -> ".join(f"{rid}({'true' if ok else 'false'})" for rid, ok in self.path)


class KnowledgeBase:
    def __init__(self, default_conclusion: str, recommendations: list[str] | None = None) -> None:
        self.default_conclusion = default_conclusion
        self.recommendations: list[str] = list(recommendations or DEFAULT_RECOMMENDATIONS)
        if default_conclusion not in self.recommendations:
            self.recommendations.insert(0, default_conclusion)
        self.root_id = "R0"
        self.rules: dict[str, Rule] = {"R0": Rule("R0", [], default_conclusion)}
        self.next_id = 1

    @classmethod
    def new(cls, default_conclusion: str, recommendations: list[str] | None = None) -> "KnowledgeBase":
        return cls(default_conclusion, recommendations)

    # ---------- inferensi ----------
    def infer(self, case: dict[str, Any]) -> InferenceResult:
        current: Rule | None = self.rules[self.root_id]
        path: list[tuple[str, bool]] = []
        last_satisfied = self.rules[self.root_id]
        last_evaluated, last_ok = current, True
        while current is not None:
            ok = current.matches(case)
            path.append((current.id, ok))
            last_evaluated, last_ok = current, ok
            if ok:
                last_satisfied = current
                child_id = current.true_child
            else:
                child_id = current.false_child
            current = self.rules.get(child_id) if child_id else None
        return InferenceResult(last_satisfied.conclusion, path, last_satisfied, last_evaluated, last_ok)

    # ---------- akuisisi pengetahuan ----------
    def add_rule(
        self,
        result: InferenceResult,
        conclusion: str,
        conditions: list[Condition],
        case: dict[str, Any],
    ) -> Rule:
        conclusion = conclusion.strip()
        if not conclusion:
            raise RuleRejected("Kesimpulan baru tidak boleh kosong.")
        if conclusion.casefold() == result.conclusion.casefold():
            raise RuleRejected("Kesimpulan pakar sama dengan kesimpulan sistem; tidak perlu aturan baru.")
        if not conditions:
            raise RuleRejected("Aturan baru membutuhkan minimal satu kondisi.")
        try:
            validate_conjunction(conditions)
        except ValueError as exc:
            raise RuleRejected(str(exc)) from None
        for cond in conditions:
            if not cond.evaluate(case):
                raise RuleRejected(f"Kondisi '{cond}' tidak terpenuhi oleh kasus baru.")

        for known in self.recommendations:            # samakan penulisan dengan yang sudah ada
            if known.casefold() == conclusion.casefold():
                conclusion = known
                break

        new_rule = Rule(f"R{self.next_id}", list(conditions), conclusion, cornerstone=dict(case))

        cornerstone = result.last_satisfied.cornerstone
        if cornerstone is not None and new_rule.matches(cornerstone):
            raise RuleRejected(
                f"Ditolak: tidak ada kondisi pembeda terhadap cornerstone case {result.last_satisfied.id}."
            )

        self.next_id += 1
        self.rules[new_rule.id] = new_rule
        parent = result.last_evaluated
        if result.last_evaluated_satisfied:
            parent.true_child = new_rule.id
        else:
            parent.false_child = new_rule.id
        if conclusion not in self.recommendations:
            self.recommendations.append(conclusion)
        return new_rule

    # ---------- pemetaan nilai ----------
    def replace_value(self, attribute: str, old: str, new: str) -> None:
        """Dipakai saat pakar memetakan nilai pending ke nilai resmi."""
        for rule in self.rules.values():
            rule.conditions = [
                Condition(c.attribute, c.operator, new)
                if c.attribute == attribute and isinstance(c.value, str) and c.value.casefold() == old.casefold()
                else c
                for c in rule.conditions
            ]
            cs = rule.cornerstone
            if cs and isinstance(cs.get(attribute), str) and cs[attribute].casefold() == old.casefold():
                cs[attribute] = new

    # ---------- tampilan ----------
    def tree_lines(self, schema=None) -> list[str]:
        lines: list[str] = []

        def walk(rule_id: str, depth: int, label: str) -> None:
            rule = self.rules[rule_id]
            lines.append("    " * depth + label + rule.describe(schema))
            if rule.true_child:
                walk(rule.true_child, depth + 1, "[true]  ")
            if rule.false_child:
                walk(rule.false_child, depth + 1, "[false] ")

        walk(self.root_id, 0, "")
        return lines

    # ---------- serialisasi ----------
    def to_dict(self) -> dict:
        return {
            "default_conclusion": self.default_conclusion,
            "recommendations": list(self.recommendations),
            "root_id": self.root_id,
            "next_id": self.next_id,
            "rules": [r.to_dict() for r in self.rules.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeBase":
        kb = cls(data["default_conclusion"], data.get("recommendations"))
        rules = [Rule.from_dict(item) for item in data.get("rules", [])]
        if rules:
            kb.rules = {r.id: r for r in rules}
        kb.root_id = data.get("root_id", "R0")
        numbers = [int(m.group(1)) for rid in kb.rules if (m := re.fullmatch(r"R(\d+)", rid))]
        kb.next_id = data.get("next_id", (max(numbers) + 1) if numbers else 1)
        return kb

    @classmethod
    def load(cls, path: str | Path) -> "KnowledgeBase":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
