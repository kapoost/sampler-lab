"""Pobiera materiał z domeny publicznej z archive.org (kolekcja 78rpm) na potrzeby testów.

Tylko biblioteka standardowa — ma działać zanim zainstalujemy cokolwiek do venv.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH = "https://archive.org/advancedsearch.php"
METADATA = "https://archive.org/metadata/"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw"
UA = {"User-Agent": "sampler-lab/0.1 (personal research)"}
AUDIO_EXT = (".mp3", ".flac", ".ogg")


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def find_items(query: str, rows: int) -> list[str]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "fl[]": "identifier",
            "rows": rows,
            "page": 1,
            "output": "json",
        }
    )
    data = get_json(f"{SEARCH}?{params}")
    return [d["identifier"] for d in data["response"]["docs"]]


def pick_file(identifier: str) -> tuple[str, int] | None:
    """Najmniejszy plik audio w itemie — wystarczy do testów, a szybko się ściąga."""
    meta = get_json(f"{METADATA}{identifier}")
    candidates = [
        (f["name"], int(f.get("size", 0)))
        for f in meta.get("files", [])
        if f["name"].lower().endswith(AUDIO_EXT) and int(f.get("size", 0)) > 0
    ]
    return min(candidates, key=lambda c: c[1]) if candidates else None


def download(identifier: str, name: str) -> Path | None:
    url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(name)}"
    dest = OUT / f"{identifier}__{name.replace('/', '_')}"
    if dest.exists():
        print(f"  = {dest.name} (jest)")
        return dest
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
            fh.write(r.read())
    except Exception as exc:  # noqa: BLE001 - chcemy lecieć dalej mimo pojedynczych błędów
        print(f"  ! {identifier}: {exc}")
        return None
    print(f"  + {dest.name} ({dest.stat().st_size // 1024} KB)")
    return dest


def main() -> int:
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    OUT.mkdir(parents=True, exist_ok=True)

    # Dwa źródła o różnym charakterze: muzyka 78 obr./min i nagrania terenowe.
    queries = {
        "78rpm": 'collection:(georgeblood) AND mediatype:(audio)',
        "field": 'collection:(fieldrecordings) AND mediatype:(audio)',
    }

    total = 0
    for label, query in queries.items():
        print(f"\n[{label}] {query}")
        try:
            ids = find_items(query, rows)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! wyszukiwanie nie powiodło się: {exc}")
            continue
        print(f"  znaleziono {len(ids)} pozycji")
        for identifier in ids:
            try:
                picked = pick_file(identifier)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {identifier}: {exc}")
                continue
            if not picked:
                continue
            if download(identifier, picked[0]):
                total += 1

    print(f"\nPobrano {total} plików do {OUT}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
