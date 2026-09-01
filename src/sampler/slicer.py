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


def export(path: Path, start: float, end: float, dest: Path, target_sr: int = 44100) -> Path:
    """Wycina fragment w pełnej jakości (nie z analitycznego 22 kHz) i zapisuje jako WAV 16-bit."""
    y, sr = librosa.load(path, sr=target_sr, mono=False, offset=start, duration=max(0.0, end - start))
    if y.ndim == 1:
        y = y[np.newaxis, :]
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dest, y.T, sr, subtype="PCM_16")
    return dest
