"""Atribut, tipe atribut, dan Schema.

Nilai kategorikal baru (mis. kota 'Semarang') diterima sebagai nilai
*pending*: kasus tetap diproses, tetapi schema tidak langsung berubah.
Pakar yang memutuskan apakah nilai itu didaftarkan, dipetakan ke nilai
yang sudah ada, atau ditolak.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class AttributeType(Enum):
    CATEGORICAL = "categorical"
    NUMERIC = "numeric"


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def parse_number(raw: Any) -> int | float:
    """Mengubah 'Rp3.000.000', '3jt', '3,5 juta', '5 hari', 7 -> angka."""
    if isinstance(raw, bool):
        raise ValueError("Nilai numerik tidak boleh berupa boolean.")
    if isinstance(raw, (int, float)):
        return _tidy(float(raw))
    text = str(raw).strip().lower()
    for noise in ("rp", "hari", " "):
        text = text.replace(noise, "")
    match = re.fullmatch(r"(\d[\d.,]*)(jt|juta|rb|ribu|k)?", text)
    if not match:
        raise ValueError(f"'{raw}' bukan angka yang valid (contoh: 3000000, 3jt, Rp3.000.000).")
    number, suffix = match.groups()
    try:
        if suffix:
            factor = {"jt": 1e6, "juta": 1e6, "rb": 1e3, "ribu": 1e3, "k": 1e3}[suffix]
            value = float(number.replace(",", ".")) * factor
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", number):
            value = float(number.replace(".", "").replace(",", "."))
        elif re.fullmatch(r"\d{1,3}(,\d{3})+", number):
            value = float(number.replace(",", ""))
        else:
            value = float(number.replace(",", "."))
    except ValueError:
        raise ValueError(f"'{raw}' bukan angka yang valid.") from None
    return _tidy(value)


def _number_text(value: int | float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


@dataclass
class Attribute:
    name: str
    type: AttributeType
    label: str = ""
    values: list[str] = field(default_factory=list)          # nilai resmi (kategorikal)
    pending_values: list[str] = field(default_factory=list)  # nilai sementara
    unit: str = ""
    min_value: float | None = None   # batas domain numerik (opsional)
    max_value: float | None = None
    allow_new_values: bool = True    # False: kategorikal hanya menerima nilai di `values`

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name

    # ---------- parsing ----------
    def parse(self, raw: Any) -> tuple[Any, bool]:
        """Mengembalikan (nilai, is_pending)."""
        if self.type is AttributeType.NUMERIC:
            number = parse_number(raw)
            if self.min_value is not None and number < self.min_value:
                raise ValueError(f"{self.label} minimal {self.format_value(self.min_value)}.")
            if self.max_value is not None and number > self.max_value:
                raise ValueError(f"{self.label} maksimal {self.format_value(self.max_value)}.")
            return number, False
        text = str(raw).strip()
        if not text:
            raise ValueError("Nilai tidak boleh kosong.")
        for known in self.values:                 # normalisasi huruf otomatis
            if known.casefold() == text.casefold():
                return known, False
        for pending in self.pending_values:
            if pending.casefold() == text.casefold():
                return pending, True
        if not self.allow_new_values:
            raise ValueError(f"{self.label} harus salah satu dari: {', '.join(self.values)}.")
        return text, True

    # ---------- tampilan ----------
    def format_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if self.type is AttributeType.NUMERIC:
            if self.unit == "Rp":
                return "Rp" + f"{int(round(value)):,}".replace(",", ".")
            return f"{_number_text(value)} {self.unit}".strip()
        return str(value)

    def is_pending(self, value: Any) -> bool:
        return self.type is AttributeType.CATEGORICAL and any(
            p.casefold() == str(value).casefold() for p in self.pending_values
        )

    # ---------- serialisasi ----------
    def to_dict(self) -> dict:
        data: dict[str, Any] = {"name": self.name, "label": self.label, "type": self.type.value}
        if self.type is AttributeType.CATEGORICAL:
            data["values"] = list(self.values)
            data["pending_values"] = list(self.pending_values)
            if not self.allow_new_values:
                data["allow_new_values"] = False
        if self.type is AttributeType.NUMERIC:
            if self.unit:
                data["unit"] = self.unit
            if self.min_value is not None:
                data["min_value"] = self.min_value
            if self.max_value is not None:
                data["max_value"] = self.max_value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Attribute":
        return cls(
            name=data["name"],
            type=AttributeType(data["type"]),
            label=data.get("label", ""),
            values=list(data.get("values", [])),
            pending_values=list(data.get("pending_values", [])),
            unit=data.get("unit", ""),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            allow_new_values=data.get("allow_new_values", True),
        )


class Schema:
    """Kumpulan atribut. Atribut baru bisa ditambahkan pakar saat runtime."""

    def __init__(self, attributes: list[Attribute] | None = None) -> None:
        self.attributes: list[Attribute] = list(attributes or [])

    # ---------- akses ----------
    def names(self) -> list[str]:
        return [a.name for a in self.attributes]

    def has(self, name: str) -> bool:
        return name in self.names()

    def get(self, name: str) -> Attribute:
        for attr in self.attributes:
            if attr.name == name:
                return attr
        raise KeyError(f"Atribut '{name}' tidak ada di schema.")

    def add_attribute(self, attribute: Attribute) -> None:
        if not NAME_PATTERN.match(attribute.name):
            raise ValueError("Nama atribut harus snake_case (huruf kecil, angka, underscore).")
        if self.has(attribute.name):
            raise ValueError(f"Atribut '{attribute.name}' sudah ada.")
        self.attributes.append(attribute)

    # ---------- parsing kasus ----------
    def parse_value(self, name: str, raw: Any) -> tuple[Any, bool]:
        return self.get(name).parse(raw)

    def parse_case(self, raw: dict[str, Any], track_pending: bool = True) -> tuple[dict, list[tuple[str, Any]]]:
        """Mengubah data mentah menjadi kasus bertipe. Atribut yang tidak
        diisi dianggap tidak diketahui (kondisi atasnya selalu salah)."""
        case: dict[str, Any] = {}
        pending: list[tuple[str, Any]] = []
        for name in raw:
            if not self.has(name):
                raise ValueError(f"Atribut '{name}' tidak ada di schema.")
        for attr in self.attributes:
            if attr.name not in raw:
                continue
            value, is_pending = attr.parse(raw[attr.name])
            case[attr.name] = value
            if is_pending:
                pending.append((attr.name, value))
                if track_pending:
                    self.mark_pending(attr.name, value)
        return case, pending

    # ---------- nilai pending ----------
    def mark_pending(self, name: str, value: str) -> None:
        attr = self.get(name)
        if not any(p.casefold() == str(value).casefold() for p in attr.pending_values):
            attr.pending_values.append(str(value))

    def register_value(self, name: str, value: str) -> None:
        attr = self.get(name)
        if attr.type is not AttributeType.CATEGORICAL:
            raise ValueError("Hanya atribut kategorikal yang punya daftar nilai.")
        if not any(v.casefold() == str(value).casefold() for v in attr.values):
            attr.values.append(str(value))
        self.discard_pending(name, value)

    def discard_pending(self, name: str, value: str) -> None:
        attr = self.get(name)
        attr.pending_values = [p for p in attr.pending_values if p.casefold() != str(value).casefold()]

    def all_pending(self) -> list[tuple[str, str]]:
        return [(a.name, v) for a in self.attributes for v in a.pending_values]

    # ---------- tampilan ----------
    def format_value(self, name: str, value: Any) -> str:
        return self.get(name).format_value(value) if self.has(name) else str(value)

    # ---------- serialisasi ----------
    def to_dict(self) -> dict:
        return {"attributes": [a.to_dict() for a in self.attributes]}

    @classmethod
    def from_dict(cls, data: dict) -> "Schema":
        return cls([Attribute.from_dict(item) for item in data["attributes"]])

    @classmethod
    def load(cls, path: str | Path) -> "Schema":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
