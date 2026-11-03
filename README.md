# Sistem Rekomendasi Daerah Pariwisata (RDR)

Aplikasi CLI Python yang memberikan rekomendasi destinasi berdasarkan preferensi
wisatawan. Sistem memakai Ripple-Down Rules (RDR): pengetahuan awalnya memberi
rekomendasi **Yogyakarta**, lalu koreksi pakar disimpan sebagai aturan pengecualian
bercabang true/false.

## Menjalankan aplikasi

```powershell
python main.py
```

Menu aplikasi dapat:

1. Meminta rekomendasi dan menerima umpan balik pakar. Untuk koreksi, pilih
   kondisi pembeda yang diusulkan generator kandidat.
2. Menampilkan pohon aturan yang sudah dipelajari.
3. Menambahkan atribut categorical atau numeric ke skema.
4. Menjalankan enam kasus demo spesifikasi dalam KB sementara.

Aturan dan contoh pelatihan disimpan di `data/kb.json`; definisi atribut disimpan
di `data/attributes.json`. Atribut awal meliputi kota asal, budget, durasi
liburan, jenis wisata, moda transportasi, dan apakah wisatawan membawa anak.
Input budget menerima angka biasa atau format Rupiah seperti `Rp3.000.000`.

## Menjalankan pengujian

```powershell
python -m unittest discover -s tests -v
```

Demo menguji jalur rekomendasi Yogyakarta, Raja Ampat, Malang, Bali, dan Labuan
Bajo. Kasus terakhir mengulang input kasus 2 dengan jawaban pakar berbeda, dan
harus ditolak karena tidak memiliki kondisi pembeda.
