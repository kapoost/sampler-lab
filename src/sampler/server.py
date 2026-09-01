"""Serwer UI do zaznaczania fragmentów.

Przeglądarka jest powierzchnią sterującą, Python liczy cięcia i wycina pliki.
Odsłuch na tym etapie idzie przez przeglądarkę — rozdzielenie cue/wysyłka
wchodzi dopiero, gdy będzie do czego wysyłać (zadanie #7).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import slicer

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
EXPORT = ROOT / "data" / "export"
DB = ROOT / "data" / "derived" / "index.db"
STATIC = Path(__file__).resolve().parent / "static"

# Godzinne audycje analizujemy tylko we fragmencie — inaczej cięcie trwa wieki.
ANALYSIS_CAP = 300.0

app = FastAPI(title="sampler-lab")
_cache: dict[str, dict] = {}

FRAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS frags (
    track_id   TEXT NOT NULL,
    slice_idx  INTEGER NOT NULL,
    start      REAL, end REAL, dur REAL, rms_db REAL,
    tags       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (track_id, slice_idx)
);
"""


def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(FRAGS_SCHEMA)
    return con


def catalog() -> dict[str, Path]:
    return {slicer.track_id(p): p for p in sorted(RAW.iterdir())
            if p.suffix.lower() in {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}}


def measured() -> dict[str, dict]:
    if not DB.exists():
        return {}
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM tracks").fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    return {r["path"]: dict(r) for r in rows}


@app.get("/api/tracks")
def api_tracks():
    meas = measured()
    out = []
    for tid, path in catalog().items():
        m = meas.get(str(path), {})
        out.append({
            "id": tid,
            "name": path.name,
            "duration": m.get("duration"),
            "bpm": m.get("bpm"),
            "rubato": m.get("rubato"),
            "gridded": m.get("gridded"),
            "key_name": m.get("key_name"),
            "key_conf": m.get("key_conf"),
        })
    return sorted(out, key=lambda t: t["name"])


@app.get("/api/track/{tid}")
def api_track(tid: str):
    path = catalog().get(tid)
    if not path:
        raise HTTPException(404, "nie ma takiego nagrania")
    if tid not in _cache:
        _cache[tid] = {
            "wave": slicer.waveform(path, ANALYSIS_CAP),
            "slices": slicer.slices(path, ANALYSIS_CAP),
        }
    c = _cache[tid]
    return {"id": tid, "name": path.name, "capped": ANALYSIS_CAP,
            "wave": c["wave"], "slices": c["slices"]}


@app.get("/audio/{tid}")
def api_audio(tid: str):
    path = catalog().get(tid)
    if not path:
        raise HTTPException(404, "nie ma takiego nagrania")
    return FileResponse(path)


class Frag(BaseModel):
    track_id: str
    slice_idx: int
    start: float
    end: float
    dur: float
    rms_db: float
    tags: list[str]


@app.post("/api/frag")
def api_frag(f: Frag):
    """Zapisuje tagi fragmentu. Pusta lista tagów kasuje wpis."""
    tags = sorted({t.strip().lower() for t in f.tags if t.strip()})
    con = db()
    try:
        if tags:
            con.execute(
                "INSERT INTO frags VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(track_id, slice_idx) DO UPDATE SET tags=excluded.tags",
                (f.track_id, f.slice_idx, f.start, f.end, f.dur, f.rms_db, ",".join(tags)),
            )
        else:
            con.execute("DELETE FROM frags WHERE track_id=? AND slice_idx=?", (f.track_id, f.slice_idx))
        con.commit()
    finally:
        con.close()
    return {"tags": tags}


@app.get("/api/frags")
def api_frags(track_id: str | None = None, tags: str | None = None):
    """Bez track_id — przeszukuje otagowane fragmenty ze WSZYSTKICH nagrań."""
    names = {tid: p.name for tid, p in catalog().items()}
    con = db()
    try:
        if track_id:
            rows = con.execute("SELECT * FROM frags WHERE track_id=?", (track_id,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM frags ORDER BY tags, rms_db DESC").fetchall()
    finally:
        con.close()
    want = [t.strip().lower() for t in (tags or "").split(",") if t.strip()]
    out = []
    for r in rows:
        have = [t for t in r["tags"].split(",") if t]
        if want and not set(want) <= set(have):
            continue
        out.append({**dict(r), "tags": have, "name": names.get(r["track_id"], "?")})
    return out


@app.get("/api/tagcloud")
def api_tagcloud():
    con = db()
    try:
        rows = con.execute("SELECT tags FROM frags").fetchall()
    finally:
        con.close()
    counts: dict[str, int] = {}
    for r in rows:
        for t in r["tags"].split(","):
            if t:
                counts[t] = counts.get(t, 0) + 1
    return sorted(({"tag": k, "n": v} for k, v in counts.items()), key=lambda d: -d["n"])


class ExportItem(BaseModel):
    track_id: str
    start: float
    end: float
    bank: str
    pad: int
    label: str | None = None


class ExportRequest(BaseModel):
    items: list[ExportItem]


@app.post("/api/export")
def api_export(req: ExportRequest):
    cat = catalog()
    written = []
    for it in req.items:
        path = cat.get(it.track_id)
        if not path:
            continue
        stem = (it.label or path.stem)[:40].replace("/", "_").replace(" ", "_")
        dest = EXPORT / f"{it.bank}{it.pad:02d}_{stem}.wav"
        slicer.export(path, it.start, it.end, dest)
        written.append(dest.name)
    return JSONResponse({"written": written, "folder": str(EXPORT)})


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
