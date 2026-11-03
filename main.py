"""Titik masuk: hanya membuat dan menjalankan aplikasi.

Pemakaian:
    python main.py          # menu interaktif
    python main.py --demo   # jalankan demo 6 kasus lalu selesai
"""
import sys
from pathlib import Path

from rdr.cli import ConsoleApp


def main() -> None:
    app = ConsoleApp(Path(__file__).resolve().parent / "data")
    app.run(demo_only="--demo" in sys.argv[1:])


if __name__ == "__main__":
    main()
