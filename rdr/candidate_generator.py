"""Pembangkit kandidat kondisi pembeda antara kasus baru dan cornerstone case."""
from __future__ import annotations

from typing import Any

from .attribute import AttributeType, Schema
from .condition import Condition


class CandidateGenerator:
    def __init__(self, schema: Schema) -> None:
        self.schema = schema

    def generate(self, case: dict[str, Any], cornerstone: dict[str, Any] | None) -> list[Condition]:
        """Kondisi yang benar untuk `case` dan (bila mungkin) salah untuk `cornerstone`.

        Tanpa cornerstone (aturan default), semua atribut kasus menjadi kandidat.
        Jika kasus identik dengan cornerstone, hasilnya kosong (tidak ada pembeda).
        """
        candidates: list[Condition] = []
        for attr in self.schema.attributes:
            if attr.name not in case or case[attr.name] is None:
                continue
            new = case[attr.name]
            old = cornerstone.get(attr.name) if cornerstone is not None else None
            if cornerstone is not None and old == new:
                continue

            if attr.type is AttributeType.CATEGORICAL:
                candidates.append(Condition(attr.name, "=", new))
            elif old is None:
                candidates.append(Condition(attr.name, ">=", new))
                candidates.append(Condition(attr.name, "<=", new))
                candidates.append(Condition(attr.name, "=", new))
            elif new < old:
                candidates.append(Condition(attr.name, "<", old))
                candidates.append(Condition(attr.name, "<=", new))
                candidates.append(Condition(attr.name, "=", new))
            else:
                candidates.append(Condition(attr.name, ">", old))
                candidates.append(Condition(attr.name, ">=", new))
                candidates.append(Condition(attr.name, "=", new))

        return [c for c in candidates if c.evaluate(case) and not (cornerstone and c.evaluate(cornerstone))]
