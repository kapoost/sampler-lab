"""Dzieli nagranie na fragmenty po transjentach i liczy podgląd fali.

Nie ocenia — proponuje cięcia. Wybór należy do człowieka.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

SR = 22050
MIN_LEN = 0.15      # krótsze niż to jest klikiem, nie fragmentem
MAX_LEN = 6.0       # dłuższe tniemy — pad ma mieścić frazę, nie zwrotkę
PEAKS = 1400        # punktów w podglądzie fali


@dataclass
class Slice:
    idx: int
    start: float
    end: float
    dur: float
    rms_db: float
    peak_db: float


def track_id(path: Path) -> str:
    return hashlib.sha1(str(path).encode()).hexdigest()[:12]


def waveform(path: Path, max_seconds: float | None = None) -> dict:
    y, sr = librosa.load(path, sr=SR, mono=True, duration=max_seconds)
    if y.size == 0:
        return {"peaks": [], "duration": 0.0}
    step = max(1, len(y) // PEAKS)
    trimmed = y[: (len(y) // step) * step].reshape(-1, step)
    peaks = np.abs(trimmed).max(axis=1)
    peaks = peaks / (peaks.max() + 1e-9)
    return {"peaks": [round(float(p), 3) for p in peaks], "duration": round(len(y) / sr, 3)}


def slices(path: Path, max_seconds: float | None = None) -> list[dict]:
    y, sr = librosa.load(path, sr=SR, mono=True, duration=max_seconds)
    if y.size == 0:
        return []
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    total = len(y) / sr
    bounds = list(onsets) + [total]

    out: list[Slice] = []
    for i in range(len(bounds) - 1):
        start = float(bounds[i])
        end = min(float(bounds[i + 1]), start + MAX_LEN)
        if end - start < MIN_LEN:
            continue
        seg = y[int(start * sr): int(end * sr)]
        if seg.size == 0:
            continue
        rms = float(np.sqrt(np.mean(seg**2)))
        pk = float(np.abs(seg).max())
        out.append(Slice(
            idx=len(out),
            start=round(start, 3),
            end=round(end, 3),
            dur=round(end - start, 3),
            rms_db=round(20 * np.log10(rms + 1e-12), 1),
            peak_db=round(20 * np.log10(pk + 1e-12), 1),
        ))
    return [asdict(s) for s in out]


def crossfade_loop(y: np.ndarray, sr: int, fade: float) -> np.ndarray:
    """Wmontowuje ogon w początek, żeby fragment zapętlał się bez szwu.

    Kanały w wierszach. Wynik jest krótszy o długość przenikania — to samo,
    co słychać w odsłuchu, więc eksport zgadza się z tym, co wybrałeś.
    """
    F = min(int(fade * sr), y.shape[1] // 3)
    if F < 8:
        return y
    t = np.linspace(0, 1, F, endpoint=False)
    g_out, g_in = np.cos(t * np.pi / 2), np.sin(t * np.pi / 2)
    out = y[:, F:y.shape[1] - F].copy()
    head = y[:, y.shape[1] - F:] * g_out + y[:, :F] * g_in
    return np.concatenate([head, out], axis=1)


def export(path: Path, start: float, end: float, dest: Path,
           target_sr: int = 44100, fade: float = 0.0) -> Path:
    """Wycina fragment w pełnej jakości (nie z analitycznego 22 kHz) i zapisuje jako WAV 16-bit."""
    y, sr = librosa.load(path, sr=target_sr, mono=False, offset=start, duration=max(0.0, end - start))
    if y.ndim == 1:
        y = y[np.newaxis, :]
    if fade > 0:
        y = crossfade_loop(y, sr, fade)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dest, y.T, sr, subtype="PCM_16")
    return dest


# --- domykanie pętli -------------------------------------------------------

FIT_MATCH = 0.025   # ile sekund porównujemy
FIT_SEARCH = 0.080  # jak daleko szukamy lepszego końca
FIT_SNAP = 0.003    # promień dociągania do przejścia przez zero


def _zero_cross(y: np.ndarray, idx: int, radius: int) -> int:
    """Najbliższe przejście przez zero w górę (z minusa na plus).

    Cięcie w takim punkcie nie daje trzasku, bo obie strony startują od zera
    i z tym samym kierunkiem narastania.
    """
    lo, hi = max(1, idx - radius), min(len(y) - 1, idx + radius)
    best, bd = idx, radius + 1
    for i in range(lo, hi):
        if y[i - 1] <= 0 < y[i]:
            d = abs(i - idx)
            if d < bd:
                best, bd = i, d
    return best


def fit_loop(path: Path, start: float, end: float, sr: int = 44100) -> dict:
    """Przesuwa koniec pętli tak, żeby przechodził w jej początek bez szwu.

    Kryterium: fragment TUŻ PRZED końcem ma wyglądać jak fragment tuż przed
    początkiem. Wtedy przeskok z końca na początek jest dla ucha kontynuacją,
    a nie cięciem. Zwracamy też zgodność, bo nie każdy materiał da się domknąć
    — przy szumie albo mowie nie ma czego dopasować i trzeba to powiedzieć.
    """
    look = FIT_MATCH + 0.005
    off = max(0.0, start - look)
    total = librosa.get_duration(path=str(path))
    dur = min(total - off, (end - off) + FIT_SEARCH + 0.01)
    y, _ = librosa.load(path, sr=sr, mono=True, offset=off, duration=dur)

    N, S, R = int(FIT_MATCH * sr), int(FIT_SEARCH * sr), int(FIT_SNAP * sr)
    i_start = int(round((start - off) * sr))
    i_end = int(round((end - off) * sr))
    if i_start < N or len(y) < i_start + 2 * N or i_end <= i_start + N:
        return {"start": start, "end": end, "score": None,
                "note": "za krótki fragment na dopasowanie"}

    i_start = _zero_cross(y, i_start, R)
    ref = y[i_start - N:i_start]
    ref_n = float(np.linalg.norm(ref))
    if ref_n < 1e-6:
        return {"start": round(off + i_start / sr, 4), "end": end, "score": None,
                "note": "cisza na początku — nie ma czego dopasować"}

    lo = max(i_start + N + 1, i_end - S)
    hi = min(len(y), i_end + S)
    if hi - lo < 2:
        return {"start": round(off + i_start / sr, 4), "end": end, "score": None,
                "note": "brak miejsca na szukanie"}

    # Wszystkie okna długości N kończące się w [lo, hi) naraz.
    win = np.lib.stride_tricks.sliding_window_view(y, N)[lo - N:hi - N]
    norms = np.linalg.norm(win, axis=1)
    ok = norms > 1e-6
    if not ok.any():
        return {"start": round(off + i_start / sr, 4), "end": end, "score": None,
                "note": "cisza w obszarze szukania"}
    scores = np.full(len(win), -1.0)
    scores[ok] = (win[ok] @ ref) / (norms[ok] * ref_n)

    # Przy remisie wybieramy kandydata NAJBLIZSZEGO zadanemu koncowi. Bez tego
    # argmax bierze pierwszego z brzegu i petla skraca sie o promien szukania —
    # na materiale okresowym kazda wielokrotnosc okresu ma te sama zgodnosc.
    best = float(scores.max())
    close = np.flatnonzero(scores >= best - 0.005)
    i_best = lo + int(close[np.argmin(np.abs(close + lo - i_end))])
    i_best = _zero_cross(y, i_best, R)

    return {
        "start": round(off + i_start / sr, 4),
        "end": round(off + i_best / sr, 4),
        "score": round(best, 3),
        "note": None,
    }
