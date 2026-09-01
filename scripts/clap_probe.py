"""Zadanie #5: czy CLAP w ogóle rozumie ten materiał — i czy rozumie po polsku.

Test ma twardą podstawę: nazwy plików mówią, co w nich jest (Whistling Mose,
Czardas, calypso, audycje radiowe AM/FM). Zapytania są tak dobrane, żeby
poprawna odpowiedź była z góry znana. To ocena trafień, nie wrażeń.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import librosa
import numpy as np
import torch
from transformers import ClapModel, ClapProcessor

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MODEL = "laion/larger_clap_music_and_speech"
SR = 48_000          # CLAP oczekuje 48 kHz
WIN = 10.0           # okno w sekundach
PER_FILE = 5         # ile okien z każdego pliku, rozłożonych równomiernie

# (zapytanie polskie, zapytanie angielskie, oczekiwane trafienie w nazwie pliku)
PROBES = [
    ("gwizdanie, solo",                    "solo whistling",                      "whistling"),
    ("skrzypce, szybki taniec ludowy",     "fast violin folk dance",              "czardas"),
    ("muzyka karaibska, calypso",          "caribbean calypso music",             "calypso"),
    ("mężczyzna mówi przez radio",         "a man talking on talk radio",         "KABC"),
    ("kobiecy śpiew z orkiestrą",          "woman singing with orchestra",        "wayward|telephone|smile"),
]


def windows(path: Path) -> list[tuple[float, np.ndarray]]:
    total = librosa.get_duration(path=str(path))
    if total < WIN:
        return []
    starts = np.linspace(0, max(0.0, total - WIN), PER_FILE)
    out = []
    for s in starts:
        y, _ = librosa.load(path, sr=SR, mono=True, offset=float(s), duration=WIN)
        if y.size:
            out.append((float(s), y))
    return out


def main() -> int:
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"model: {MODEL}   urządzenie: {device}")
    model = ClapModel.from_pretrained(MODEL).to(device).eval()
    proc = ClapProcessor.from_pretrained(MODEL)

    files = sorted(p for p in RAW.iterdir() if p.suffix.lower() in {".mp3", ".ogg", ".wav", ".flac"})
    labels: list[str] = []
    embs: list[np.ndarray] = []

    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name[:64]}", flush=True)
        for start, y in windows(path):
            inp = proc(audio=y, sampling_rate=SR, return_tensors="pt").to(device)
            with torch.no_grad():
                e = model.get_audio_features(**inp).pooler_output[0].cpu().numpy()
            embs.append(e / (np.linalg.norm(e) + 1e-9))
            labels.append(f"{path.name[:46]:<46} @{int(start//60)}:{int(start%60):02d}")

    A = np.stack(embs)
    print(f"\nzaindeksowano {len(labels)} okien po {WIN:.0f} s\n")

    hits = {"pl": 0, "en": 0}
    for pl, en, expect in PROBES:
        print(f"OCZEKIWANE: /{expect}/")
        for lang, query in (("pl", pl), ("en", en)):
            inp = proc(text=[query], return_tensors="pt", padding=True).to(device)
            with torch.no_grad():
                t = model.get_text_features(**inp).pooler_output[0].cpu().numpy()
            t = t / (np.linalg.norm(t) + 1e-9)
            order = np.argsort(-(A @ t))[:3]
            top = labels[order[0]]
            import re
            ok = bool(re.search(expect, top, re.I))
            hits[lang] += ok
            print(f"  [{lang}] {query!r:<42} {'TRAFIONE' if ok else 'pudło   '}")
            for r, idx in enumerate(order, 1):
                print(f"        {r}. {labels[idx]}  {float(A[idx] @ t):+.3f}")
        print()

    n = len(PROBES)
    print(f"WYNIK: polski {hits['pl']}/{n}, angielski {hits['en']}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
