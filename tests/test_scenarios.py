"""Uji skenario berdasarkan 6 kasus demo pada data/demo_cases.json.

Jalankan dari root repo:  python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rdr.attribute import Attribute, AttributeType, Schema, parse_number  # noqa: E402
from rdr.candidate_generator import CandidateGenerator  # noqa: E402
from rdr.cli import simulate_case  # noqa: E402
from rdr.condition import Condition, validate_conjunction  # noqa: E402
from rdr.knowledge_base import KnowledgeBase, RuleRejected  # noqa: E402

DATA = ROOT / "data"


class DemoScenarioTest(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(DATA / "attributes.json")
        with open(DATA / "demo_cases.json", encoding="utf-8") as fh:
            self.demo = json.load(fh)
        self.kb = KnowledgeBase.new(self.demo["default_conclusion"], self.demo["recommendations"])
        self.generator = CandidateGenerator(self.schema)

    def run_up_to(self, n):
        """Menjalankan kasus 1..n berurutan (KB bersifat kumulatif); mengembalikan hasil kasus ke-n."""
        outcome = None
        for entry in self.demo["cases"][:n]:
            outcome = simulate_case(self.kb, self.schema, self.generator, entry)
            self.assertEqual(outcome["system"], entry["expected_system"], f"kasus {entry['id']}")
            self.assertEqual(outcome["status"], entry["expected_status"], f"kasus {entry['id']}")
            expected = entry["expected_rule"]
            if expected:
                rule = outcome["rule"]
                self.assertEqual(rule.id, expected["id"])
                self.assertEqual(rule.conclusion, expected["conclusion"])
                self.assertEqual(outcome["result"].last_evaluated.id, expected["parent"])
                self.assertEqual(outcome["result"].branch, expected["branch"])
        return outcome

    def test_kasus_1_pakar_setuju_kb_tidak_berubah(self):
        before = self.kb.to_dict()
        out = self.run_up_to(1)
        self.assertEqual(out["status"], "agree")
        self.assertEqual(self.kb.to_dict(), before)
        self.assertEqual(len(self.kb.rules), 1)

    def test_kasus_2_r1_bahari_true_child_r0(self):
        self.run_up_to(2)
        r1 = self.kb.rules["R1"]
        self.assertEqual([str(c) for c in r1.conditions], ["jenis_wisata = Bahari"])
        self.assertEqual(self.kb.rules["R0"].true_child, "R1")

    def test_kasus_3_r2_alam_false_child_r1(self):
        self.run_up_to(3)
        self.assertEqual(self.kb.rules["R1"].false_child, "R2")
        self.assertEqual(self.kb.rules["R2"].conclusion, "Malang")

    def test_kasus_4_r3_numerik_dan_and_true_child_r1(self):
        self.run_up_to(4)
        r3 = self.kb.rules["R3"]
        self.assertEqual(len(r3.conditions), 2)
        self.assertIn(Condition("membawa_anak", "=", "Ya"), r3.conditions)
        self.assertIn(Condition("budget", "<", 15000000), r3.conditions)
        self.assertEqual(self.kb.rules["R1"].true_child, "R3")

    def test_kasus_5_r4_bertingkat_false_child_r3(self):
        self.run_up_to(5)
        r4 = self.kb.rules["R4"]
        self.assertEqual(r4.conditions, [Condition("durasi", ">", 5)])
        self.assertEqual(self.kb.rules["R3"].false_child, "R4")
        self.assertEqual(r4.conclusion, "Labuan Bajo")

    def test_kasus_6_identik_kasus_2_ditolak(self):
        out = self.run_up_to(6)
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["candidates"], [])
        self.assertEqual(sorted(self.kb.rules), ["R0", "R1", "R2", "R3", "R4"])  # tidak ada R5

    def test_pohon_akhir(self):
        self.run_up_to(6)
        self.assertEqual(
            {rid: (r.true_child, r.false_child) for rid, r in self.kb.rules.items()},
            {
                "R0": ("R1", None),
                "R1": ("R3", "R2"),
                "R2": (None, None),
                "R3": (None, "R4"),
                "R4": (None, None),
            },
        )

    def test_add_rule_menolak_kondisi_yang_tidak_membedakan(self):
        self.run_up_to(2)
        entry = self.demo["cases"][5]  # identik dengan kasus 2
        case, _ = self.schema.parse_case(entry["case"])
        result = self.kb.infer(case)
        with self.assertRaises(RuleRejected):
            self.kb.add_rule(result, "Bali", [Condition("kota_asal", "=", "Jakarta")], case)


class SchemaAndPendingTest(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(DATA / "attributes.json")
        self.kb = KnowledgeBase.new("Yogyakarta")
        self.raw = {"kota_asal": "Makassar", "budget": "5jt", "durasi": "3 hari",
                    "jenis_wisata": "Budaya", "moda_transportasi": "pesawat", "membawa_anak": "tidak"}

    def test_nilai_baru_diterima_sebagai_pending_tanpa_ubah_schema(self):
        case, pending = self.schema.parse_case(self.raw)
        self.assertEqual(pending, [("kota_asal", "Makassar")])
        attr = self.schema.get("kota_asal")
        self.assertNotIn("Makassar", attr.values)
        self.assertIn("Makassar", attr.pending_values)
        self.assertEqual(self.kb.infer(case).conclusion, "Yogyakarta")  # tetap bisa diproses
        self.assertEqual(case["jenis_wisata"], "Budaya")                 # normalisasi huruf

    def test_pakar_mendaftarkan_nilai_pending(self):
        self.schema.parse_case(self.raw)
        self.schema.register_value("kota_asal", "Makassar")
        attr = self.schema.get("kota_asal")
        self.assertIn("Makassar", attr.values)
        self.assertEqual(attr.pending_values, [])
        _, pending = self.schema.parse_case(self.raw)
        self.assertEqual(pending, [])

    def test_pemetaan_nilai_pending_ke_nilai_resmi(self):
        kb = KnowledgeBase.new("Yogyakarta")
        kb.rules["R0"].cornerstone = {"kota_asal": "Bandoeng"}
        kb.replace_value("kota_asal", "Bandoeng", "Bandung")
        self.assertEqual(kb.rules["R0"].cornerstone["kota_asal"], "Bandung")

    def test_parse_angka(self):
        self.assertEqual(parse_number("Rp3.000.000"), 3000000)
        self.assertEqual(parse_number("3jt"), 3000000)
        self.assertEqual(parse_number("3,5 juta"), 3500000)
        self.assertEqual(parse_number("5 hari"), 5)
        with self.assertRaises(ValueError):
            parse_number("banyak")

    def test_atribut_dinamis_dari_pakar(self):
        self.schema.add_attribute(Attribute("musim", AttributeType.CATEGORICAL, "Musim", ["Kemarau", "Hujan"]))
        with self.assertRaises(ValueError):
            self.schema.add_attribute(Attribute("musim", AttributeType.CATEGORICAL))
        with self.assertRaises(ValueError):
            self.schema.add_attribute(Attribute("Nama Salah", AttributeType.CATEGORICAL))
        raw = dict(self.raw, kota_asal="Bandung", musim="kemarau")
        case, _ = self.schema.parse_case(raw)
        cornerstone = {k: v for k, v in case.items() if k != "musim"}  # kasus lama belum punya 'musim'
        candidates = CandidateGenerator(self.schema).generate(case, cornerstone)
        self.assertEqual(candidates, [Condition("musim", "=", "Kemarau")])
        self.assertFalse(Condition("musim", "=", "Kemarau").evaluate(cornerstone))

    def test_simpan_dan_muat_ulang(self):
        kb = KnowledgeBase.new("Yogyakarta")
        case, _ = self.schema.parse_case(self.raw)
        result = kb.infer(case)
        kb.add_rule(result, "Malang", [Condition("jenis_wisata", "=", "Budaya")], case)
        with tempfile.TemporaryDirectory() as tmp:
            kb.save(Path(tmp) / "kb.json")
            self.schema.save(Path(tmp) / "attributes.json")
            loaded = KnowledgeBase.load(Path(tmp) / "kb.json")
            Schema.load(Path(tmp) / "attributes.json")
        self.assertEqual(loaded.to_dict(), kb.to_dict())
        self.assertEqual(loaded.infer(case).conclusion, "Malang")
        self.assertEqual(loaded.next_id, 2)


class ValidasiKondisiTest(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.load(DATA / "attributes.json")

    def test_batas_bawah_dan_atas_sama_ditolak(self):
        with self.assertRaises(ValueError) as ctx:
            validate_conjunction([Condition("budget", ">=", 3500000), Condition("budget", "<=", 3500000)])
        self.assertIn("'=' ", str(ctx.exception) + " ")

    def test_rentang_valid_dan_kosong(self):
        validate_conjunction([Condition("budget", ">", 3000000), Condition("budget", "<", 5000000)])
        with self.assertRaises(ValueError):
            validate_conjunction([Condition("budget", ">", 5000000), Condition("budget", "<", 3000000)])
        with self.assertRaises(ValueError):
            validate_conjunction([Condition("budget", ">", 3000000), Condition("budget", ">=", 4000000)])

    def test_sama_atau_dengan_kondisi_lain_ditolak(self):
        with self.assertRaises(ValueError):
            validate_conjunction([Condition("budget", "=", 1), Condition("budget", "<", 5)])
        with self.assertRaises(ValueError):
            validate_conjunction([Condition("kota_asal", "=", "Bandung"), Condition("kota_asal", "=", "Bandung")])

    def test_atribut_berbeda_boleh(self):
        validate_conjunction([Condition("membawa_anak", "=", "Ya"), Condition("budget", "<", 15000000)])

    def test_add_rule_menolak_kondisi_degenerate(self):
        kb = KnowledgeBase.new("Yogyakarta")
        case, _ = self.schema.parse_case({"budget": "3,5jt", "durasi": 3})
        result = kb.infer(case)
        with self.assertRaises(RuleRejected):
            kb.add_rule(result, "Danau Toba", [Condition("budget", ">=", 3500000), Condition("budget", "<=", 3500000)], case)
        self.assertEqual(len(kb.rules), 1)
        kb.add_rule(result, "Danau Toba", [Condition("budget", ">", 3000000), Condition("budget", "<", 5000000)], case)
        self.assertEqual(len(kb.rules), 2)

    def test_domain_numerik(self):
        with self.assertRaises(ValueError):
            self.schema.parse_case({"budget": -5})
        with self.assertRaises(ValueError):
            self.schema.parse_case({"durasi": 0})
        with self.assertRaises(ValueError):
            self.schema.parse_case({"durasi": 1000})

    def test_kandidat_numerik_menyertakan_sama_dengan(self):
        case, _ = self.schema.parse_case({"budget": 3500000})
        cands = CandidateGenerator(self.schema).generate(case, None)
        self.assertIn(Condition("budget", "=", 3500000), cands)

    def test_atribut_ya_tidak_menolak_nilai_lain(self):
        attr = self.schema.get("membawa_anak")
        self.assertEqual(attr.parse("ya"), ("Ya", False))
        self.assertEqual(attr.parse("TIDAK"), ("Tidak", False))
        with self.assertRaises(ValueError):
            attr.parse("mungkin")
        with self.assertRaises(ValueError):
            self.schema.parse_case({"membawa_anak": "y"})


if __name__ == "__main__":
    unittest.main()
