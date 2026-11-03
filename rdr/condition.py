from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OPERATORS = ("=", "!=", "<", "<=", ">", ">=")
LOWER_OPS = (">", ">=")
UPPER_OPS = ("<", "<=")


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


@dataclass(frozen=True)
class Condition:
    attribute: str
    operator: str
    value: Any

    def __post_init__(self) -> None:
        if self.operator not in OPERATORS:
            raise ValueError(f"Operator '{self.operator}' tidak dikenal.")

    def evaluate(self, case: dict[str, Any]) -> bool:
        """Atribut yang tidak ada/None pada kasus membuat kondisi bernilai salah."""
        actual = case.get(self.attribute)
        if actual is None:
            return False
        if self.operator == "=":
            return _equal(actual, self.value)
        if self.operator == "!=":
            return not _equal(actual, self.value)
        if isinstance(actual, bool) or isinstance(self.value, bool):
            return False
        try:
            left, right = float(actual), float(self.value)
        except (TypeError, ValueError):
            return False
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[self.operator]

    def describe(self, schema=None) -> str:
        shown = schema.format_value(self.attribute, self.value) if schema is not None else str(self.value)
        return f"{self.attribute} {self.operator} {shown}"

    def __str__(self) -> str:
        return self.describe()

    def to_dict(self) -> dict:
        return {"attribute": self.attribute, "operator": self.operator, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        return cls(data["attribute"], data["operator"], data["value"])


def validate_conjunction(conditions: list[Condition]) -> None:
    """Menolak gabungan kondisi (AND) yang berlebihan atau saling bertentangan.

    Aturan per atribut:
      * kondisi yang sama tidak boleh dipilih dua kali;
      * jika memakai '=', tidak boleh ada kondisi lain pada atribut itu;
      * maksimal satu batas bawah (> / >=) dan satu batas atas (< / <=);
      * rentang harus tidak kosong: batas bawah < batas atas. Batas bawah dan
        atas yang sama (>= X AND <= X) berarti '= X', jadi harus ditulis '='.
    """
    by_attr: dict[str, list[Condition]] = {}
    for cond in conditions:
        group = by_attr.setdefault(cond.attribute, [])
        if cond in group:
            raise ValueError(f"Kondisi '{cond}' dipilih lebih dari sekali.")
        group.append(cond)

    for attr, group in by_attr.items():
        if len(group) == 1:
            continue
        if any(c.operator == "=" for c in group):
            raise ValueError(
                f"Atribut '{attr}' sudah dibatasi dengan '=', kondisi lain pada atribut yang sama "
                "berlebihan atau bertentangan."
            )
        lowers = [c for c in group if c.operator in LOWER_OPS]
        uppers = [c for c in group if c.operator in UPPER_OPS]
        if len(lowers) > 1 or len(uppers) > 1:
            raise ValueError(f"Atribut '{attr}': hanya boleh satu batas bawah dan satu batas atas.")
        if lowers and uppers:
            lo, hi = lowers[0], uppers[0]
            if lo.value == hi.value and lo.operator == ">=" and hi.operator == "<=":
                raise ValueError(
                    f"Atribut '{attr}': batas bawah dan atas sama ({lo.value}); itu berarti "
                    f"'{attr} = {lo.value}'. Gunakan satu kondisi '=' atau ketik rentang sendiri."
                )
            if lo.value >= hi.value:
                raise ValueError(f"Atribut '{attr}': rentang kosong/bertentangan ('{lo}' dan '{hi}').")
