# csni-migrate

Extract the archive of **noul-ierusalim.ro** (old custom-PHP site) into local
Markdown (one file per message) plus the audio recordings, ready to migrate to the
new WordPress/Divi site.

This page covers running a **Romanian** extraction yourself, for two scenarios:

1. [The entire archive](#1-romanian--entire-archive) (1955–present)
2. [Year to date](#2-romanian--year-to-date) (just the current year)

> The English/French archives are separate — see `scripts/csni_extract_intl.py`.

## Prerequisites

- **Python 3** — standard library only, no packages to install.
- Run the commands **from the repository root** (the folder containing this README).
  The scripts anchor all their paths (`cache/`, `out/`, `logs/`) to the repo root, so
  output always lands in the right place.

## 1. Romanian — entire archive

Crawls every year from 1955 to the present: text first, then audio.

```bash
# text + audio (the full deal)
python3 scripts/csni_extract.py --all

# text only (skip the ~840 mp3 downloads — much faster)
python3 scripts/csni_extract.py --all --no-audio
```

## 2. Romanian — year to date

Extract only the **current** year. The archive id (`k`) for a year is looked up from
the site's index automatically:

```bash
YEAR=$(date +%Y)
K=$(PYTHONPATH=scripts python3 -c "import csni_extract as c; print(dict(c.year_map())[$YEAR])")
python3 scripts/csni_extract.py --k "$K" --year "$YEAR"            # text + audio
# add --no-audio for text only
```

To target a **specific** year instead of the current one, set `YEAR` to it (e.g.
`YEAR=2024`), or pass `--k`/`--year` directly if you already know the id.

## Where the output lands

| Path | Contents |
|------|----------|
| `out/markdown/ro/<year>/YYYY-MM-DD--slug.md` | one Markdown file per message |
| `out/audio/ro/<year>/yy.mm.dd-ro.mp3` | recordings (git-ignored; recent years only) |
| `cache/` | raw source HTML, one file per fetched page (the offline safety net) |
| `logs/CRAWL_DONE.txt` | written when a `--all` run finishes (counts of docs/audio) |
| `logs/failures.log` | any pages that failed, one per line (only if there were failures) |

## Good to know

- **Idempotent & resumable.** Already-fetched message pages and existing mp3s are
  skipped, so a re-run only does the missing work. If a run is interrupted, just run
  the same command again — downloads are atomic (`.part` → rename), so nothing is
  left half-written.
- **New posts are always picked up.** The listing pages (`arhiva.html` and the per-year
  index) are re-fetched live on every run, never served from a stale cache — so running
  the year-to-date command again grabs any messages posted since last time. (Only the
  individual message pages, which never change, are cached permanently.)
- **Failures don't stop the crawl.** A page that fails is logged to `logs/failures.log`
  and skipped; re-running retries only those (the cache resumes automatically).
- **Politeness.** The crawler waits briefly between live requests, so a full audio
  crawl takes a while — the `--no-audio` text pass is much quicker.
