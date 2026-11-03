"""Antarmuka konsol (ConsoleApp) untuk sistem RDR rekomendasi daerah pariwisata."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .attribute import Attribute, AttributeType, Schema, parse_number
from .candidate_generator import CandidateGenerator
from .condition import Condition
from .knowledge_base import (
    DEFAULT_RECOMMENDATIONS,
    InferenceResult,
    KnowledgeBase,
    RuleRejected,
)

EXPR_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*(<=|>=|!=|=|<|>)\s*(.+?)\s*$")

BANNER = """=====================================================
 RDR - Rekomendasi Daerah Pariwisata Indonesia
====================================================="""

MENU = """
--- MENU ---
1. Konsultasi kasus baru
2. Jalankan demo 6 kasus (simulasi, KB asli tidak diubah)
3. Lihat Knowledge Base (pohon aturan)
4. Lihat atribut
5. Tambah atribut baru
6. Tinjau nilai pending
7. Reset Knowledge Base
0. Simpan & keluar"""


# ----------------------------------------------------------------------
# Simulasi satu kasus demo (dipakai CLI demo dan tes otomatis)
# ----------------------------------------------------------------------
def simulate_case(
    kb: KnowledgeBase, schema: Schema, generator: CandidateGenerator, entry: dict[str, Any]
) -> dict[str, Any]:
    """Menjalankan satu entri demo_cases.json dengan pakar tersimulasi.

    Hasil: dict berisi status ('agree' | 'rule_added' | 'rejected'), kesimpulan
    sistem, hasil inferensi, kandidat kondisi, aturan baru (jika ada), dan alasan.
    """
    case, _ = schema.parse_case(entry["case"])
    result = kb.infer(case)
    outcome: dict[str, Any] = {
        "id": entry["id"], "case": case, "system": result.conclusion,
        "result": result, "candidates": [], "rule": None, "reason": "",
    }
    if entry.get("expert_agrees"):
        outcome["status"] = "agree"
        return outcome

    candidates = generator.generate(case, result.last_satisfied.cornerstone)
    outcome["candidates"] = candidates
    if not candidates:
        outcome["status"] = "rejected"
        outcome["reason"] = (
            f"tidak ada kondisi pembeda terhadap cornerstone case {result.last_satisfied.id}"
        )
        return outcome

    chosen: list[Condition] = []
    for raw in entry.get("expert_conditions", []):
        value, _ = schema.parse_value(raw["attribute"], raw["value"])
        cond = Condition(raw["attribute"], raw["operator"], value)
        if cond not in candidates:
            raise ValueError(f"Kondisi pakar '{cond}' bukan kandidat yang dihasilkan sistem.")
        chosen.append(cond)
    try:
        outcome["rule"] = kb.add_rule(result, entry["expert_conclusion"], chosen, case)
        outcome["status"] = "rule_added"
    except RuleRejected as exc:
        outcome["status"] = "rejected"
        outcome["reason"] = str(exc)
    return outcome


class ConsoleApp:
    def __init__(
        self,
        data_dir: str | Path,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._in = input_fn
        self._out = output_fn
        self.schema = Schema.load(self.data_dir / "attributes.json")
        kb_path = self.data_dir / "kb.json"
        self.kb = KnowledgeBase.load(kb_path) if kb_path.exists() else KnowledgeBase.new("Yogyakarta")
        self.generator = CandidateGenerator(self.schema)

    # ------------------------------------------------------------------
    # util I/O
    # ------------------------------------------------------------------
    def say(self, text: str = "") -> None:
        self._out(text)

    def ask(self, prompt: str) -> str:
        return self._in(prompt).strip()

    def ask_yes_no(self, prompt: str) -> bool:
        while True:
            answer = self.ask(f"{prompt} (y/n): ").lower()
            if answer in ("y", "ya", "yes"):
                return True
            if answer in ("n", "t", "tidak", "no"):
                return False
            self.say("  Jawab dengan y atau n.")

    def save(self) -> None:
        self.schema.save(self.data_dir / "attributes.json")
        self.kb.save(self.data_dir / "kb.json")

    def format_case(self, case: dict[str, Any]) -> list[str]:
        return [
            f"  {a.label}: {self.schema.format_value(a.name, case.get(a.name))}"
            for a in self.schema.attributes
            if a.name in case
        ]

    # ------------------------------------------------------------------
    # loop utama
    # ------------------------------------------------------------------
    def run(self, demo_only: bool = False) -> None:
        self.say(BANNER)
        if demo_only:
            self.run_demo()
            return
        handlers = {
            "1": self.consult,
            "2": self.run_demo,
            "3": self.show_kb,
            "4": self.show_attributes,
            "5": self.add_attribute,
            "6": self.review_pending,
            "7": self.reset_kb,
        }
        try:
            while True:
                self.say(MENU)
                choice = self.ask("Pilih menu: ")
                if choice == "0":
                    break
                handler = handlers.get(choice)
                if handler is None:
                    self.say("Menu tidak dikenal.")
                    continue
                handler()
        except (EOFError, KeyboardInterrupt):
            self.say()
        self.save()
        self.say("Knowledge Base dan atribut tersimpan. Sampai jumpa!")

    # ------------------------------------------------------------------
    # 1. konsultasi
    # ------------------------------------------------------------------
    def consult(self) -> None:
        self.say("\n== Konsultasi kasus baru ==")
        case: dict[str, Any] = {}
        for attr in self.schema.attributes:
            while True:
                text = self.ask(f"{attr.label} {self._hint(attr)}: ")
                try:
                    value, is_pending = attr.parse(text)
                except ValueError as exc:
                    self.say(f"  ! {exc}")
                    continue
                break
            if is_pending:
                self.schema.mark_pending(attr.name, value)
                self.say(
                    f"  [!] '{value}' belum terdaftar pada '{attr.name}'. Diterima sementara "
                    "(pending); schema tidak diubah sampai pakar memutuskan."
                )
            case[attr.name] = value
        self.process_case(case)

    def _hint(self, attr: Attribute) -> str:
        if attr.type is AttributeType.CATEGORICAL:
            if not attr.values:
                return "[teks]"
            suffix = " / nilai baru" if attr.allow_new_values else ""
            return f"[{', '.join(attr.values)}{suffix}]"
        if attr.type is AttributeType.NUMERIC:
            return "[angka, mis. 3jt atau 3.000.000]" if attr.unit == "Rp" else f"[angka, {attr.unit}]".replace(", ]", "]")
        return ""

    def process_case(self, case: dict[str, Any]) -> None:
        result = self.kb.infer(case)
        self.say("\nData kasus:")
        for line in self.format_case(case):
            self.say(line)
        self.say(f"Jalur inferensi : {result.path_text()}")
        self.say(f"Rekomendasi     : {result.conclusion}  (aturan {result.last_satisfied.id})")
        if self.ask_yes_no("Apakah pakar setuju dengan rekomendasi ini?"):
            self.say("Pakar setuju. Knowledge Base tidak berubah.")
            return
        self.acquire_knowledge(case, result)

    # ------------------------------------------------------------------
    # akuisisi pengetahuan
    # ------------------------------------------------------------------
    def acquire_knowledge(self, case: dict[str, Any], result: InferenceResult) -> None:
        conclusion = self.choose_conclusion(result.conclusion)
        if conclusion is None:
            self.say("Dibatalkan. Knowledge Base tidak berubah.")
            return

        wrong = result.last_satisfied
        candidates = self.generator.generate(case, wrong.cornerstone)
        if not candidates:
            self.say(
                f"Ditolak: tidak ada kondisi pembeda antara kasus ini dan cornerstone case {wrong.id}. "
                "Kasus identik tidak bisa diberi kesimpulan berbeda."
            )
            return

        self.say(f"\nKondisi pembeda (kasus baru vs cornerstone {wrong.id}):")
        for i, cond in enumerate(candidates, 1):
            self.say(f"  {i}. {cond.describe(self.schema)}")
        self.say("Anda juga bisa mengetik kondisi sendiri, mis. 'budget > 3jt', 'budget < 5jt',")
        self.say("atau rentang 'budget > 3jt; budget < 5jt' (pisahkan dengan ';').")

        while True:
            raw = self.ask("Pilih nomor (mis. 1,3 = AND) atau ketik kondisi sendiri, kosong = batal: ")
            if not raw:
                self.say("Dibatalkan. Knowledge Base tidak berubah.")
                return
            try:
                conditions = self._pick(raw, candidates)
            except ValueError as exc:
                self.say(f"  ! {exc}")
                continue
            if not self._confirm_pending(conditions):
                self.say("  Nilai pending harus didaftarkan agar bisa dipakai pada aturan. Pilih ulang.")
                continue
            try:
                rule = self.kb.add_rule(result, conclusion, conditions, case)
            except RuleRejected as exc:
                self.say(f"  ! {exc}")
                continue
            break

        self.save()
        parent = result.last_evaluated.id
        self.say(f"\nAturan baru ditambahkan: {rule.describe(self.schema)}")
        self.say(f"Posisi: {result.branch}-child dari {parent}. Kasus ini disimpan sebagai cornerstone {rule.id}.")

    def choose_conclusion(self, system_conclusion: str) -> str | None:
        self.say("\nRekomendasi yang tersedia:")
        for i, name in enumerate(self.kb.recommendations, 1):
            self.say(f"  {i}. {name}")
        while True:
            raw = self.ask("Rekomendasi yang benar (nomor atau nama baru, kosong = batal): ")
            if not raw:
                return None
            name = raw
            if raw.isdigit():
                index = int(raw)
                if not 1 <= index <= len(self.kb.recommendations):
                    self.say("  ! Nomor di luar daftar.")
                    continue
                name = self.kb.recommendations[index - 1]
            if name.casefold() == system_conclusion.casefold():
                self.say("  ! Sama dengan rekomendasi sistem. Pilih yang berbeda.")
                continue
            if not any(known.casefold() == name.casefold() for known in self.kb.recommendations):
                if not self.ask_yes_no(f"  '{name}' belum ada di daftar rekomendasi. Tambahkan sebagai rekomendasi baru"):
                    continue
            return name

    def _pick(self, raw: str, candidates: list[Condition]) -> list[Condition]:
        """Mengurai pilihan pakar: nomor kandidat dan/atau ekspresi kondisi sendiri."""
        if ";" in raw:
            tokens = raw.split(";")
        elif re.fullmatch(r"[\d\s,]+", raw):
            tokens = raw.split(",")
        else:
            tokens = [raw]
        chosen: list[Condition] = []
        for token in (t.strip() for t in tokens):
            if not token:
                continue
            if token.isdigit():
                if not 1 <= int(token) <= len(candidates):
                    raise ValueError(f"Nomor '{token}' di luar daftar kandidat.")
                cond = candidates[int(token) - 1]
            else:
                cond = self._parse_custom(token)
            chosen.append(cond)
        if not chosen:
            raise ValueError("Tidak ada kondisi yang dipilih.")
        return chosen

    def _parse_custom(self, token: str) -> Condition:
        match = EXPR_PATTERN.match(token)
        if not match:
            raise ValueError(f"'{token}' bukan nomor kandidat atau ekspresi (contoh: budget < 5jt).")
        name, op, raw_value = match.groups()
        name = name.lower()
        if not self.schema.has(name):
            raise ValueError(f"Atribut '{name}' tidak ada. Atribut: {', '.join(self.schema.names())}.")
        attr = self.schema.get(name)
        if op in ("<", "<=", ">", ">=") and attr.type is not AttributeType.NUMERIC:
            raise ValueError(f"Operator '{op}' hanya untuk atribut numerik; '{name}' bertipe {attr.type.value}.")
        value, is_pending = attr.parse(raw_value)
        if is_pending:
            self.schema.mark_pending(name, value)
        return Condition(name, op, value)

    def _confirm_pending(self, conditions: list[Condition]) -> bool:
        for cond in conditions:
            attr = self.schema.get(cond.attribute)
            if attr.is_pending(cond.value):
                if not self.ask_yes_no(
                    f"Nilai '{cond.value}' pada '{attr.name}' belum terdaftar. Daftarkan sebagai nilai resmi?"
                ):
                    return False
                self.schema.register_value(attr.name, cond.value)
                self.say(f"  Nilai '{cond.value}' didaftarkan ke '{attr.name}'.")
        return True

    # ------------------------------------------------------------------
    # 2. demo
    # ------------------------------------------------------------------
    def run_demo(self) -> None:
        path = self.data_dir / "demo_cases.json"
        with open(path, encoding="utf-8") as fh:
            demo = json.load(fh)
        kb = KnowledgeBase.new(demo["default_conclusion"], demo["recommendations"])
        schema = Schema.from_dict(self.schema.to_dict())
        generator = CandidateGenerator(schema)

        self.say("\n== Demo 6 kasus (KB simulasi, KB asli tidak diubah) ==")
        for entry in demo["cases"]:
            self.say(f"\n--- Kasus {entry['id']}: {entry['description']} ---")
            out = simulate_case(kb, schema, generator, entry)
            for line in self.format_case(out["case"]):
                self.say(line)
            result: InferenceResult = out["result"]
            self.say(f"Jalur inferensi : {result.path_text()}")
            self.say(f"Sistem          : {out['system']}")
            if out["status"] == "agree":
                self.say("Pakar           : y (setuju) -> KB tidak berubah")
            elif out["status"] == "rule_added":
                rule = out["rule"]
                self.say(f"Pakar           : n -> {rule.conclusion}")
                self.say(f"Aturan baru     : {rule.describe(schema)}")
                self.say(f"Posisi          : {result.branch}-child dari {result.last_evaluated.id}")
            else:
                self.say(f"Pakar           : n -> {entry['expert_conclusion']}")
                self.say(f"DITOLAK         : {out['reason']}")
        self.say("\nPohon aturan akhir demo:")
        for line in kb.tree_lines(schema):
            self.say("  " + line)

    # ------------------------------------------------------------------
    # 3-4. tampilan
    # ------------------------------------------------------------------
    def show_kb(self) -> None:
        self.say(f"\n== Knowledge Base ({len(self.kb.rules)} aturan) ==")
        for line in self.kb.tree_lines(self.schema):
            self.say(line)
        self.say(f"\nDaftar rekomendasi: {', '.join(self.kb.recommendations)}")

    def show_attributes(self) -> None:
        self.say("\n== Atribut ==")
        for attr in self.schema.attributes:
            extra = ""
            if attr.type is AttributeType.CATEGORICAL:
                extra = f" | nilai: {', '.join(attr.values) or '-'}"
                if attr.pending_values:
                    extra += f" | pending: {', '.join(attr.pending_values)}"
            elif attr.type is AttributeType.NUMERIC and attr.unit:
                extra = f" | satuan: {attr.unit}"
            self.say(f"  {attr.name} ({attr.label}) : {attr.type.value}{extra}")

    # ------------------------------------------------------------------
    # 5. atribut dinamis
    # ------------------------------------------------------------------
    def add_attribute(self) -> None:
        self.say("\n== Tambah atribut baru ==")
        name = self.ask("Nama atribut (snake_case, kosong = batal): ")
        if not name:
            return
        label = self.ask("Label tampilan (kosong = sama dengan nama): ")
        choice = self.ask("Tipe: 1) kategorikal  2) numerik : ")
        types = {"1": AttributeType.CATEGORICAL, "2": AttributeType.NUMERIC}
        if choice not in types:
            self.say("Tipe tidak valid. Dibatalkan.")
            return
        attr_type = types[choice]
        values: list[str] = []
        unit = ""
        allow_new = True
        if attr_type is AttributeType.CATEGORICAL:
            raw = self.ask("Nilai awal (pisahkan koma, boleh kosong): ")
            values = [v.strip() for v in raw.split(",") if v.strip()]
            if values:
                allow_new = self.ask_yes_no("Izinkan nilai baru di luar daftar ini")
        elif attr_type is AttributeType.NUMERIC:
            unit = self.ask("Satuan (boleh kosong): ")
        min_value = max_value = None
        if attr_type is AttributeType.NUMERIC:
            try:
                raw_min = self.ask("Batas bawah domain (kosong = tanpa batas): ")
                raw_max = self.ask("Batas atas domain (kosong = tanpa batas): ")
                min_value = parse_number(raw_min) if raw_min else None
                max_value = parse_number(raw_max) if raw_max else None
            except ValueError as exc:
                self.say(f"  ! {exc}")
                return
            if min_value is not None and max_value is not None and min_value > max_value:
                self.say("  ! Batas bawah lebih besar dari batas atas. Dibatalkan.")
                return
        try:
            self.schema.add_attribute(
                Attribute(name, attr_type, label, values, [], unit, min_value, max_value, allow_new)
            )
        except ValueError as exc:
            self.say(f"  ! {exc}")
            return
        self.save()
        self.say(
            f"Atribut '{name}' ditambahkan. Aturan lama tidak berubah; kasus lama dianggap "
            "tidak punya nilai untuk atribut ini."
        )

    # ------------------------------------------------------------------
    # 6. tinjau nilai pending
    # ------------------------------------------------------------------
    def review_pending(self) -> None:
        pending = self.schema.all_pending()
        if not pending:
            self.say("\nTidak ada nilai pending.")
            return
        self.say(f"\n== Tinjau {len(pending)} nilai pending ==")
        for name, value in pending:
            attr = self.schema.get(name)
            self.say(f"\nAtribut '{name}', nilai baru: '{value}'")
            self.say("  1) Daftarkan sebagai nilai resmi")
            self.say("  2) Petakan ke nilai yang sudah ada (mis. koreksi ejaan)")
            self.say("  3) Tolak / hapus")
            self.say("  (kosong = tunda)")
            choice = self.ask("Pilihan: ")
            if choice == "1":
                self.schema.register_value(name, value)
                self.say(f"  '{value}' didaftarkan.")
            elif choice == "2":
                if not attr.values:
                    self.say("  Belum ada nilai resmi untuk dipetakan.")
                    continue
                for i, known in enumerate(attr.values, 1):
                    self.say(f"    {i}. {known}")
                pick = self.ask("  Petakan ke nomor: ")
                if pick.isdigit() and 1 <= int(pick) <= len(attr.values):
                    target = attr.values[int(pick) - 1]
                    self.kb.replace_value(name, value, target)
                    self.schema.discard_pending(name, value)
                    self.say(f"  '{value}' dipetakan ke '{target}'.")
                else:
                    self.say("  Pilihan tidak valid. Ditunda.")
            elif choice == "3":
                self.schema.discard_pending(name, value)
                self.say(f"  '{value}' ditolak.")
            else:
                self.say("  Ditunda.")
        self.save()

    # ------------------------------------------------------------------
    # 7. reset
    # ------------------------------------------------------------------
    def reset_kb(self) -> None:
        if not self.ask_yes_no("Reset KB ke aturan default saja? Semua aturan akan hilang"):
            return
        self.kb = KnowledgeBase.new(self.kb.default_conclusion, DEFAULT_RECOMMENDATIONS)
        self.save()
        self.say("Knowledge Base direset.")
