"""Etap 1: pomiar materiału. BPM, stabilność tempa, tonacja, głośność, transjenty.

Wynik ląduje w sqlite (data/derived/index.db). Nie ocenia — mierzy.
Kluczowy pomiar to `rubato` — rozrzut odstępów między transjentami. Mówi wprost,
czy nagranie da się zapętlić, czy nadaje się tylko na pojedyncze frazy.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import warnings
from pathlib import Path

import librosa
import numpy as np

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "derived" / "index.db"
SR = 22050
# Prog kalibrowany na materiale testowym — patrz scripts/calibrate.md
GRID_THRESHOLD = 0.10

# Profile Krumhansla-Schmucklera — durowy i molowy.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    path        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    duration    REAL,
    bpm         REAL,
    rubato      REAL,   -- zmiennosc LOKALNEGO tempa; nizej = rowniej
    ioi_cv      REAL,   -- zmiennosc odstepow; tylko do wgladu, nie do decyzji
    gridded     INTEGER,-- 1 = da sie zapetlic, 0 = rubato
    key_name    TEXT,
    key_conf    REAL,
    rms_db      REAL,
    onsets      INTEGER,
    analyzed_s  REAL    -- ile sekund faktycznie przeanalizowano
);
"""


def detect_key(y: np.ndarray, sr: int) -> tuple[str, float]:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    if chroma.sum() <= 0:
        return "?", 0.0
    chroma = chroma / chroma.sum()
    scores: list[tuple[float, str]] = []
    for i in range(12):
        for profile, suffix in ((MAJOR, ""), (MINOR, "m")):
            rolled = np.roll(profile, i)
            corr = float(np.corrcoef(chroma, rolled / rolled.sum())[0, 1])
            scores.append((corr, f"{NOTES[i]}{suffix}"))
    scores.sort(reverse=True)
    best, runner = scores[0], scores[1]
    # Pewnosc = przewaga nad druga w kolejnosci. Maly odstep = zgadywanka.
    return best[1], round(max(0.0, best[0] - runner[0]), 4)


def tempo_stability(y: np.ndarray, sr: int) -> tuple[float, float]:
    """Zwraca (zmiennosc_tempa, zmiennosc_odstepow).

    Pierwsza liczba jest wiarygodna: rozrzut LOKALNEGO tempa w czasie. Rowny material
    ma tempo stabilne, rubato — plywajace.

    Druga (wspolczynnik zmiennosci odstepow miedzy transjentami) jest wysoka nawet dla
    idealnie rownego materialu, bo transjenty padaja na roznych poziomach metrycznych
    (osemki, cwiercnuty, synkopy). Zostawiona wylacznie do wgladu — NIE uzywac do decyzji.
    """
    oenv = librosa.onset.onset_strength(y=y, sr=sr)
    local = np.atleast_1d(librosa.feature.tempo(onset_envelope=oenv, sr=sr, aggregate=None))
    tempo_cv = float(np.std(local) / np.mean(local)) if local.size and np.mean(local) > 0 else float("nan")

    onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    ioi_cv = float("nan")
    if len(onset_times) >= 8:
        iois = np.diff(onset_times)
        iois = iois[(iois > 0.05) & (iois < 4.0)]
        if len(iois) >= 6 and iois.mean() > 0:
            ioi_cv = float(iois.std() / iois.mean())
    return tempo_cv, ioi_cv


def analyze(path: Path, max_seconds: float) -> dict | None:
    try:
        y, sr = librosa.load(path, sr=SR, mono=True, duration=max_seconds)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {path.name}: {exc}", file=sys.stderr)
        return None
    if y.size == 0:
        return None

    full = librosa.get_duration(path=str(path))
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    tempo_cv, ioi_cv = tempo_stability(y, sr)
    rub = tempo_cv
    key_name, key_conf = detect_key(y, sr)
    rms = float(librosa.feature.rms(y=y).mean())

    return {
        "path": str(path),
        "name": path.name,
        "duration": round(full, 2),
        "bpm": round(tempo, 1),
        "rubato": None if np.isnan(rub) else round(rub, 3),
        "gridded": None if np.isnan(rub) else int(rub < GRID_THRESHOLD),
        "ioi_cv": None if np.isnan(ioi_cv) else round(ioi_cv, 3),
        "key_name": key_name,
        "key_conf": key_conf,
        "rms_db": round(20 * np.log10(rms + 1e-12), 1),
        "onsets": int(len(onset_times)),
        "analyzed_s": round(len(y) / sr, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Zmierz materiał audio i zapisz do indeksu.")
    ap.add_argument("folder", nargs="?", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--max-seconds", type=float, default=180.0,
                    help="ile sekund z każdego pliku analizować (godzinne audycje inaczej trwają wieki)")
    args = ap.parse_args()

    files = sorted(
        p for p in Path(args.folder).iterdir()
        if p.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a"}
    )
    if not files:
        print(f"Brak plików audio w {args.folder}")
        return 1

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    rows = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name[:70]}")
        rec = analyze(path, args.max_seconds)
        if not rec:
            continue
        con.execute(
            "INSERT OR REPLACE INTO tracks VALUES "
            "(:path,:name,:duration,:bpm,:rubato,:ioi_cv,:gridded,:key_name,:key_conf,:rms_db,:onsets,:analyzed_s)",
            rec,
        )
        rows.append(rec)
    con.commit()

    print(f"\n{'nazwa':<44} {'dl':>7} {'BPM':>6} {'rubato':>7} {'siatka':>7} {'ton':>5} {'pewn':>5} {'dB':>6}")
    print("-" * 96)
    for r in sorted(rows, key=lambda r: (r["rubato"] is None, r["rubato"] or 0)):
        grid = "-" if r["gridded"] is None else ("TAK" if r["gridded"] else "nie")
        rub = "  n/d" if r["rubato"] is None else f"{r['rubato']:.3f}"
        print(f"{r['name'][:43]:<44} {r['duration']:>7.0f} {r['bpm']:>6.1f} {rub:>7} {grid:>7} "
              f"{r['key_name']:>5} {r['key_conf']:>5.2f} {r['rms_db']:>6.1f}")
    print(f"\nZapisano {len(rows)} pozycji do {DB.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
