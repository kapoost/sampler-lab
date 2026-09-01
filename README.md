# sampler-lab

Narzędzie do przygotowywania materiału na sprzętowy sampler — mierzy nagrania,
tnie je na fragmenty i pozwala wygodnie wybrać te, które trafią na pady.

Powstało pod **Akai MPC Sample**, ale nic w kodzie nie jest do tego modelu
przywiązane: wynikiem jest katalog plików WAV 44,1 kHz / 16 bit, nazwanych
według banku i numeru padu.

## Do czego to jest

Masz kilkaset nagrań i chcesz z nich zrobić kit na sampler. Ręczne
przesłuchiwanie i cięcie w edytorze zajmuje popołudnia. To narzędzie robi
wstępną robotę — mierzy, kroi, filtruje — a wybór estetyczny zostawia tobie.

## Co mierzy

| Cecha | Uwagi |
|---|---|
| BPM | `librosa.beat` |
| stabilność tempa | rozrzut **lokalnego** tempa w czasie — mówi, czy nagranie da się zapętlić |
| tonacja | chromagram + profile Krumhansla-Schmucklera |
| głośność, transjenty | RMS, detekcja onsetów |

Uwaga na tonację: na szumiących, wąskopasmowych nagraniach (płyty 78 obr./min)
pewność wykrycia jest niska i wynik bywa przypadkowy. Kolumna `key_conf`
pokazuje przewagę nad drugą w kolejności — przy wartościach poniżej 0,1
traktuj wynik jak zgadywankę.

Uwaga na stabilność tempa: pierwsza wersja liczyła rozrzut odstępów między
transjentami i **nie działała** — ta wartość jest wysoka nawet dla idealnie
równego materiału, bo transjenty padają na różnych poziomach metrycznych.
Kolumna `ioi_cv` została w bazie wyłącznie do wglądu; decyzje opiera się na
`rubato`, czyli zmienności lokalnego tempa. Próg podziału (`GRID_THRESHOLD`)
wymaga kalibracji na własnym repertuarze.

## Wyszukiwanie: tagi, nie model

Sprawdzaliśmy CLAP (`laion/larger_clap_music_and_speech`) jako wyszukiwanie
tekstem po dźwięku. Na materiale testowym wypadł **2/5 po polsku i 2/5 po
angielsku** — przy czym trafił *inne* dwa zapytania w każdym języku. Pewnie
rozróżnia tylko mowę od muzyki. Skrypt `scripts/clap_probe.py` powtarza ten
pomiar, jeśli chcesz sprawdzić go na swoim materiale.

Dlatego podstawą wyszukiwania są **ręczne tagi** plus zmierzone cechy.

## Uruchomienie

```
uv sync
uv run python src/sampler/analyze.py data/raw
uv run uvicorn src.sampler.server:app --port 8765
```

Interfejs: <http://127.0.0.1:8765>

Materiał wrzuć do `data/raw/`. Skrypt `scripts/fetch_pd_samples.py` pobiera
nagrania z domeny publicznej z archive.org, jeśli chcesz mieć na czym testować.

## Obsługa

| Klawisz | Działanie |
|---|---|
| `↑` `↓` | wiersz |
| `spacja` | odsłuch fragmentu |
| `Enter` | przypisz na pad |
| `A`–`D` | bank |
| `1`–`9` | szybki tag |
| `T` | pole tagów |
| `Esc` | stop |

Zakładka **Szukaj** przegląda otagowane fragmenty ze wszystkich nagrań naraz.
Wiele tagów działa jak koniunkcja.

## Czego tu nie ma

- **Eksportu programu `.xpm`** — format nie został zweryfikowany na prawdziwym
  pliku z urządzenia. Na razie eksportujemy same pliki WAV.
- **Rozdzielenia podsłuchu od wysyłki.** Odsłuch idzie przez przeglądarkę na
  jedno wyjście. Osobne wyjście cue wymaga silnika audio po stronie Pythona.
- **Wyboru zakresu w długich nagraniach** — analizowane są pierwsze 300 sekund.

## Materiał audio

Katalog `data/` jest wyłączony z repozytorium. To narzędzie do pracy z
materiałem, którego masz prawo używać: własnymi nagraniami, nagraniami z
domeny publicznej, licencjonowanymi paczkami sampli.

## Licencja

MIT — patrz [LICENSE](LICENSE).
